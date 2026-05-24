// supabase/functions/verify-pin/index.ts
// Uses only built-in Deno/Web Crypto APIs — no external bcrypt dependency.
// PIN is stored as a SHA-256 hex hash in dashboard_settings.
//
// Deploy with:
//   supabase functions deploy verify-pin --no-verify-jwt

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL         = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const TOKEN_SECRET         = Deno.env.get("PIN_TOKEN_SECRET") ?? "change-me-in-env";
const TOKEN_TTL_MS         = 12 * 60 * 60 * 1000; // 12 hours

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type, authorization",
};

// SHA-256 hex hash of a string
async function sha256(text: string): Promise<string> {
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text)
  );
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}

// HMAC-signed token
async function makeToken(): Promise<string> {
  const payload = JSON.stringify({ exp: Date.now() + TOKEN_TTL_MS });
  const encoded = btoa(payload);
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(TOKEN_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign(
    "HMAC", key, new TextEncoder().encode(encoded)
  );
  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(sig)));
  return `${encoded}.${sigB64}`;
}

async function verifyToken(token: string): Promise<boolean> {
  try {
    const [encoded, sigB64] = token.split(".");
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(TOKEN_SECRET),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );
    const sig = Uint8Array.from(atob(sigB64), c => c.charCodeAt(0));
    const valid = await crypto.subtle.verify(
      "HMAC", key, sig, new TextEncoder().encode(encoded)
    );
    if (!valid) return false;
    const { exp } = JSON.parse(atob(encoded));
    return Date.now() < exp;
  } catch {
    return false;
  }
}

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const body = await req.json();
    const { pin, token } = body;

    // Session token validation
    if (token) {
      const valid = await verifyToken(token);
      return new Response(JSON.stringify({ valid }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    if (!pin) {
      return new Response(JSON.stringify({ valid: false, error: "No PIN provided" }), {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    // Look up stored hash
    const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
    const { data, error } = await sb
      .from("dashboard_settings")
      .select("value")
      .eq("key", "pin_hash")
      .single();

    if (error || !data) {
      console.error("Failed to fetch pin_hash:", error);
      return new Response(JSON.stringify({ valid: false, error: "PIN not configured" }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    const storedHash = JSON.parse(data.value);

    if (storedHash === "CHANGE_ME") {
      return new Response(JSON.stringify({ valid: false, error: "PIN not set. Run setup_pin.py." }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    // Compare SHA-256 hash of entered PIN
    const enteredHash = await sha256(pin);
    const valid = enteredHash === storedHash;

    if (!valid) {
      return new Response(JSON.stringify({ valid: false }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    const newToken = await makeToken();
    return new Response(JSON.stringify({ valid: true, token: newToken }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" }
    });

  } catch (e) {
    console.error("verify-pin error:", e);
    return new Response(JSON.stringify({ valid: false, error: String(e) }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" }
    });
  }
});
