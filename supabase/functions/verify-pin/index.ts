// supabase/functions/verify-pin/index.ts
// Deployed as a Supabase Edge Function.
// Receives { pin: "1234" }, checks it against the stored bcrypt hash,
// returns { valid: true, token: "..." } or { valid: false }.
//
// Deploy with:
//   supabase functions deploy verify-pin --no-verify-jwt

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import * as bcrypt from "https://deno.land/x/bcrypt@v0.4.1/mod.ts";

const SUPABASE_URL        = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

// Simple signed token: base64(payload + HMAC). Not JWT — keeps deps minimal.
// The dashboard stores this in sessionStorage and sends it with write requests.
const TOKEN_SECRET = Deno.env.get("PIN_TOKEN_SECRET") ?? "change-me-in-env";
const TOKEN_TTL_MS = 12 * 60 * 60 * 1000; // 12 hours

async function makeToken(): Promise<string> {
  const payload = JSON.stringify({ exp: Date.now() + TOKEN_TTL_MS });
  const encoded = btoa(payload);
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(TOKEN_SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(encoded));
  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(sig)));
  return `${encoded}.${sigB64}`;
}

export async function verifyToken(token: string): Promise<boolean> {
  try {
    const [encoded, sigB64] = token.split(".");
    const key = await crypto.subtle.importKey(
      "raw", new TextEncoder().encode(TOKEN_SECRET),
      { name: "HMAC", hash: "SHA-256" }, false, ["verify"]
    );
    const sig = Uint8Array.from(atob(sigB64), c => c.charCodeAt(0));
    const valid = await crypto.subtle.verify("HMAC", key, sig, new TextEncoder().encode(encoded));
    if (!valid) return false;
    const { exp } = JSON.parse(atob(encoded));
    return Date.now() < exp;
  } catch { return false; }
}

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type, authorization",
};

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { pin, token } = await req.json();

    // If a token is provided, just validate it (used for session checks)
    if (token) {
      const valid = await verifyToken(token);
      return new Response(JSON.stringify({ valid }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    // Otherwise verify the PIN
    if (!pin) {
      return new Response(JSON.stringify({ valid: false, error: "No PIN provided" }), {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);
    const { data } = await sb
      .from("dashboard_settings")
      .select("value")
      .eq("key", "pin_hash")
      .single();

    if (!data) {
      return new Response(JSON.stringify({ valid: false, error: "PIN not configured" }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    const hash = JSON.parse(data.value);
    if (hash === "CHANGE_ME") {
      // PIN not set up yet — reject
      return new Response(JSON.stringify({ valid: false, error: "PIN not set. Run setup script." }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    const valid = await bcrypt.compare(pin, hash);
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
    return new Response(JSON.stringify({ valid: false, error: String(e) }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" }
    });
  }
});
