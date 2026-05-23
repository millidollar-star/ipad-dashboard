-- ============================================================
-- iPad Dashboard — Schema Additions (run after supabase_schema.sql)
-- Adds: PIN security, completion write-back queue, partner iCloud
-- ============================================================

-- Write-back queue: completions pending sync to iCloud
-- The 5-min GitHub Action reads this and writes to iCloud, then clears rows
CREATE TABLE IF NOT EXISTS completion_queue (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reminder_id   TEXT NOT NULL,          -- iCloud UID of the reminder
  list_id       TEXT NOT NULL,
  completed     BOOLEAN NOT NULL,       -- true = mark done, false = unmark
  icloud_account TEXT NOT NULL,         -- 'owner' or 'partner'
  queued_at     TIMESTAMPTZ DEFAULT NOW(),
  processed_at  TIMESTAMPTZ            -- set by sync script when done
);

-- Index for the sync script to efficiently fetch unprocessed rows
CREATE INDEX IF NOT EXISTS idx_queue_unprocessed
  ON completion_queue(processed_at)
  WHERE processed_at IS NULL;

-- Seed PIN in dashboard_settings (change '0000' to your real PIN after setup)
INSERT INTO dashboard_settings (key, value) VALUES
  ('pin_hash', '"CHANGE_ME"'),         -- store a bcrypt hash, not the raw PIN
  ('partner_icloud_enabled', 'true')
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- RLS for completion_queue
-- Anyone can INSERT (dashboard posts completions)
-- Only service role can UPDATE (sync script marks processed)
-- ============================================================
ALTER TABLE completion_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_insert_queue" ON completion_queue
  FOR INSERT WITH CHECK (true);

CREATE POLICY "public_read_queue" ON completion_queue
  FOR SELECT USING (true);

CREATE POLICY "service_update_queue" ON completion_queue
  FOR UPDATE USING (true) WITH CHECK (true);

CREATE POLICY "service_delete_queue" ON completion_queue
  FOR DELETE USING (true);
