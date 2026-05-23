# iPad Dashboard

A clean, live personal dashboard for iPad — powered by Supabase and hosted on GitHub Pages.
Pulls Apple Calendar events and Reminders via iCloud CalDAV, synced to Supabase every 30 minutes
by a GitHub Action. Completions made on the dashboard sync back to iCloud (and your partner's
iCloud) within 5 minutes.

---

## Architecture

```
iCloud (you)      ──┐
                    ├──► GitHub Action (sync.py, every 30 min) ──► Supabase DB
iCloud (partner)  ──┘                                                  │
                                                           dashboard.html (GitHub Pages)
                                                           reads via anon key + Realtime
                                                                       │
                    ┌──────────────────────────────────────────────────┘
                    ▼
          GitHub Action (sync.py writeback mode, every 5 min)
          reads completion_queue → writes back to iCloud (both accounts)
```

---

## File Reference

| File | Purpose |
|------|---------|
| `dashboard.html` | iPad dashboard UI — PIN gate + calendar, reminders, weather |
| `sync.py` | Bidirectional sync: pull iCloud → Supabase, push completions → iCloud |
| `requirements.txt` | Python dependencies |
| `supabase_schema.sql` | Base schema — run first |
| `supabase_schema_v2.sql` | Adds completion queue + PIN storage — run second |
| `supabase/functions/verify-pin/index.ts` | Edge Function: validates PIN, issues session token |
| `setup_pin.py` | One-time local script: hashes your PIN and stores it in Supabase |
| `.github/workflows/sync.yml` | Two GitHub Action jobs: full sync (30 min) + write-back (5 min) |
| `README.md` | This file |

---

## Setup (one-time, ~30 minutes)

### Step 1 — Create your GitHub repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `ipad-dashboard`
3. Set to **Public** (required for free GitHub Pages)
4. Upload all files from this folder, preserving the directory structure:
   ```
   dashboard.html
   sync.py
   requirements.txt
   supabase_schema.sql
   supabase_schema_v2.sql
   setup_pin.py
   .github/workflows/sync.yml
   supabase/functions/verify-pin/index.ts
   ```

### Step 2 — Enable GitHub Pages

1. Repo → **Settings → Pages**
2. Source: **GitHub Actions**
3. Dashboard will be at: `https://YOUR_USERNAME.github.io/ipad-dashboard/dashboard.html`

### Step 3 — Set up Supabase tables

1. Log in to [supabase.com](https://supabase.com) and open your project
2. Go to **SQL Editor**
3. Run `supabase_schema.sql` first (click Run)
4. Run `supabase_schema_v2.sql` second
5. Confirm tables exist: `calendar_events`, `reminder_lists`, `reminders`,
   `dashboard_settings`, `completion_queue`

> **Important**: Also add an `icloud_account` column to the `reminders` table if it
> doesn't exist (the v2 schema expects it):
> ```sql
> ALTER TABLE reminders ADD COLUMN IF NOT EXISTS icloud_account TEXT DEFAULT 'owner';
> ```

### Step 4 — Get your Supabase keys

1. Supabase → **Settings → API**
2. Copy **Project URL** → goes in `dashboard.html` and GitHub Secrets
3. Copy **`anon` public key** → goes in `dashboard.html` only
4. Copy **`service_role` secret key** → GitHub Secrets only (never put this in the HTML)

### Step 5 — Update dashboard.html

Find this block near the bottom of `dashboard.html` and fill in your values:

```js
const SUPABASE_URL   = "https://YOUR_PROJECT.supabase.co";
const SUPABASE_ANON  = "YOUR_ANON_KEY";
const VERIFY_PIN_URL = "https://YOUR_PROJECT.supabase.co/functions/v1/verify-pin";
```

Commit and push the change.

### Step 6 — Deploy the PIN verification Edge Function

Install the Supabase CLI if you haven't:
```bash
brew install supabase/tap/supabase   # macOS
```

Link your project and deploy:
```bash
supabase login
supabase link --project-ref YOUR_PROJECT_REF
supabase functions deploy verify-pin --no-verify-jwt
```

Set the required secret for the Edge Function:
```bash
# Generate a random secret (any long random string)
supabase secrets set PIN_TOKEN_SECRET="your-long-random-secret-here"
```

> Your `YOUR_PROJECT_REF` is the part of your Supabase URL before `.supabase.co`
> (e.g. if URL is `https://abcdef.supabase.co`, ref is `abcdef`)

### Step 7 — Set your PIN

Run this once on your local Mac. It hashes your PIN and stores it securely in Supabase
(the raw PIN is never saved anywhere):

```bash
pip install bcrypt supabase
SUPABASE_URL=https://YOUR_PROJECT.supabase.co \
SUPABASE_SERVICE_KEY=your-service-role-key \
python setup_pin.py
```

You'll be prompted to type and confirm your PIN interactively.

### Step 8 — Create Apple App-Specific Passwords

> **Never use your real Apple ID password.** Create App-Specific Passwords instead.

**For your account:**
1. Go to [appleid.apple.com](https://appleid.apple.com)
2. Sign-In & Security → **App-Specific Passwords → +**
3. Name it `ipad-dashboard-owner`
4. Copy and save the password

**For your partner's account:**
1. Your partner logs into [appleid.apple.com](https://appleid.apple.com) on their device
2. Creates an App-Specific Password named `ipad-dashboard-partner`
3. Shares the password with you (just for setup — you add it to GitHub Secrets)

### Step 9 — Add GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

Add all six:

| Secret Name | Value |
|-------------|-------|
| `ICLOUD_USERNAME` | Your Apple ID email |
| `ICLOUD_PASSWORD` | Your App-Specific Password |
| `PARTNER_ICLOUD_USERNAME` | Partner's Apple ID email |
| `PARTNER_ICLOUD_PASSWORD` | Partner's App-Specific Password |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Your Supabase **service_role** key |

### Step 10 — Trigger first sync

1. Repo → **Actions → iCloud ↔ Supabase Sync**
2. Click **Run workflow → Run workflow** (leave mode as `full`)
3. Watch the logs — look for "Done." after ~1–2 minutes
4. Verify data in Supabase → **Table Editor**

### Step 11 — Open on your iPad

1. Open Safari on iPad
2. Navigate to your GitHub Pages URL
3. **Share → Add to Home Screen** to install as a full-screen app
4. Enter your PIN — you're in
5. Share the URL + PIN with your partner

---

## How the PIN works

- The PIN is **never stored in plain text** — only a bcrypt hash lives in Supabase
- When you enter the PIN, it's sent to a Supabase Edge Function which verifies the hash
- If correct, the Edge Function returns a **signed session token** (valid 12 hours)
- That token is stored in `sessionStorage` — refreshing the page doesn't log you out,
  but closing Safari does (by design)
- To manually lock: Settings → **Lock dashboard**
- To change your PIN: re-run `setup_pin.py` with a new PIN

---

## How two-way sync works

```
You check off a reminder on dashboard
        │
        ├─► Supabase `reminders` updated immediately (UI reflects instantly)
        └─► Row inserted into `completion_queue`
                    │
                    ▼ (within ~5 minutes)
        GitHub Action reads queue, connects to iCloud via CalDAV
        Marks VTODO as COMPLETED in the correct account (owner or partner)
        iPhone Reminders app syncs with iCloud → shows as done ✓
        Row in completion_queue marked as processed
```

Partner reminders are prefixed with `[Partner]` in the dashboard so you can tell
whose list is whose. When your partner checks something off on their iPhone, it
appears as completed in the dashboard after the next 30-minute full sync.

---

## Sync schedule summary

| Action | Frequency | GitHub Action job |
|--------|-----------|-------------------|
| Pull iCloud → Supabase | Every 30 min + on push | `full-sync` |
| Push completions → iCloud | Every 5 min | `writeback` |
| Redeploy dashboard | On push to `main` | `deploy` |

---

## Customization

### Change your PIN
```bash
python setup_pin.py
# Enter your new PIN when prompted
```

### Change weather location
Tap **⚙ Settings** on the dashboard → update location → Save.

### Show/hide reminder lists
Tap the colored chips in the Reminders tile header, or manage defaults in ⚙ Settings.

### Add a new widget
1. Add a `<div class="tile">` block in the `.tiles` grid in `dashboard.html`
2. Write a `fetchXxx()` function and call it from `refreshAll()`
3. Add a Supabase table if needed (add to `supabase_schema.sql` for reference)
4. Commit and push — GitHub Actions redeploys automatically

---

## Troubleshooting

**PIN screen says "Connection error"**
→ Check that `VERIFY_PIN_URL` in `dashboard.html` matches your actual Edge Function URL
→ Verify the Edge Function deployed: Supabase Dashboard → Edge Functions

**PIN screen says "PIN not set"**
→ Run `setup_pin.py` — the PIN hash hasn't been written to Supabase yet

**Sync fails: "Failed to connect to iCloud"**
→ Confirm you used an App-Specific Password (not your Apple ID password)
→ Ensure 2FA is enabled on the Apple ID (required for App-Specific Passwords)

**Completions not appearing on iPhone**
→ The write-back Action runs every 5 min — wait up to 5 minutes
→ Check Actions tab for errors in the `writeback` job
→ Make sure `completion_queue` table exists (run `supabase_schema_v2.sql`)

**Partner reminders not showing**
→ Confirm `PARTNER_ICLOUD_USERNAME` and `PARTNER_ICLOUD_PASSWORD` secrets are set
→ Run the full-sync Action manually and check logs for partner errors

**Dashboard not updating**
→ Pull down to refresh in Safari, or tap the ↻ button
→ Supabase Realtime handles instant updates — check your Supabase project isn't paused
   (free tier projects pause after 1 week of inactivity)
