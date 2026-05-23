-- ============================================================
-- iPad Dashboard — Supabase Schema
-- Run this in your Supabase SQL Editor
-- ============================================================

-- Calendar Events
CREATE TABLE IF NOT EXISTS calendar_events (
  id            TEXT PRIMARY KEY,          -- iCloud UID
  title         TEXT NOT NULL,
  calendar_name TEXT NOT NULL,
  calendar_color TEXT DEFAULT '#4A90D9',
  start_time    TIMESTAMPTZ NOT NULL,
  end_time      TIMESTAMPTZ,
  all_day       BOOLEAN DEFAULT FALSE,
  location      TEXT,
  notes         TEXT,
  synced_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Reminder Lists
CREATE TABLE IF NOT EXISTS reminder_lists (
  id            TEXT PRIMARY KEY,          -- iCloud list UID
  name          TEXT NOT NULL UNIQUE,
  color         TEXT DEFAULT '#FF9500',
  visible       BOOLEAN DEFAULT TRUE,      -- user toggle on dashboard
  synced_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Reminders / Todos
CREATE TABLE IF NOT EXISTS reminders (
  id            TEXT PRIMARY KEY,          -- iCloud reminder UID
  list_id       TEXT REFERENCES reminder_lists(id) ON DELETE CASCADE,
  list_name     TEXT NOT NULL,
  title         TEXT NOT NULL,
  notes         TEXT,
  due_date      TIMESTAMPTZ,
  completed     BOOLEAN DEFAULT FALSE,
  completed_at  TIMESTAMPTZ,
  priority      INTEGER DEFAULT 0,        -- 0=none, 1=high, 5=medium, 9=low
  synced_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Dashboard Settings (key/value store for future expandability)
CREATE TABLE IF NOT EXISTS dashboard_settings (
  key           TEXT PRIMARY KEY,
  value         JSONB NOT NULL,
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default settings
INSERT INTO dashboard_settings (key, value) VALUES
  ('weather_location', '"Albuquerque, NM"'),
  ('weather_units', '"imperial"'),
  ('refresh_interval_minutes', '30'),
  ('last_synced', 'null')
ON CONFLICT (key) DO NOTHING;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_events_start    ON calendar_events(start_time);
CREATE INDEX IF NOT EXISTS idx_reminders_list  ON reminders(list_id);
CREATE INDEX IF NOT EXISTS idx_reminders_due   ON reminders(due_date);
CREATE INDEX IF NOT EXISTS idx_reminders_done  ON reminders(completed);

-- ============================================================
-- Row Level Security — allow public read/write (anon key)
-- since anyone with the URL can interact
-- ============================================================
ALTER TABLE calendar_events    ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminder_lists     ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminders          ENABLE ROW LEVEL SECURITY;
ALTER TABLE dashboard_settings ENABLE ROW LEVEL SECURITY;

-- Public read on everything
CREATE POLICY "public_read_events"    ON calendar_events    FOR SELECT USING (true);
CREATE POLICY "public_read_lists"     ON reminder_lists     FOR SELECT USING (true);
CREATE POLICY "public_read_reminders" ON reminders          FOR SELECT USING (true);
CREATE POLICY "public_read_settings"  ON dashboard_settings FOR SELECT USING (true);

-- Public can update reminders (check/uncheck) and list visibility
CREATE POLICY "public_update_reminders" ON reminders
  FOR UPDATE USING (true) WITH CHECK (true);

CREATE POLICY "public_update_lists" ON reminder_lists
  FOR UPDATE USING (true) WITH CHECK (true);

CREATE POLICY "public_update_settings" ON dashboard_settings
  FOR UPDATE USING (true) WITH CHECK (true);

-- Only service role (sync script) can insert/delete
CREATE POLICY "service_insert_events"    ON calendar_events    FOR INSERT WITH CHECK (true);
CREATE POLICY "service_delete_events"    ON calendar_events    FOR DELETE USING (true);
CREATE POLICY "service_insert_lists"     ON reminder_lists     FOR INSERT WITH CHECK (true);
CREATE POLICY "service_insert_reminders" ON reminders          FOR INSERT WITH CHECK (true);
CREATE POLICY "service_delete_reminders" ON reminders          FOR DELETE USING (true);
CREATE POLICY "service_upsert_settings"  ON dashboard_settings FOR INSERT WITH CHECK (true);
