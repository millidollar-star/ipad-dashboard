#!/usr/bin/env python3
"""
iCloud → Supabase Sync Script
Pulls Apple Calendar events and Reminders via CalDAV/CardDAV
and upserts them into Supabase.

Required environment variables (set as GitHub Actions secrets):
  ICLOUD_USERNAME   — your Apple ID email
  ICLOUD_PASSWORD   — app-specific password (NOT your Apple ID password)
                      Generate at: appleid.apple.com → Sign-In & Security → App-Specific Passwords
  SUPABASE_URL      — your Supabase project URL
  SUPABASE_SERVICE_KEY — your Supabase service role key (not anon key)

Dependencies: pip install caldav supabase python-dateutil
"""

import os
import sys
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

import caldav
from caldav.elements import dav, cdav
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

ICLOUD_USERNAME    = os.environ["ICLOUD_USERNAME"]
ICLOUD_PASSWORD    = os.environ["ICLOUD_PASSWORD"]
SUPABASE_URL       = os.environ["SUPABASE_URL"]
SUPABASE_KEY       = os.environ["SUPABASE_SERVICE_KEY"]

CALDAV_URL         = "https://caldav.icloud.com"
SYNC_WINDOW_DAYS   = 14   # fetch events ± 14 days from today

# ── Supabase client ───────────────────────────────────────────────────────────

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────

def to_utc_str(dt) -> str | None:
    """Convert a datetime (or date) to ISO UTC string for Supabase."""
    if dt is None:
        return None
    if hasattr(dt, "date") and not hasattr(dt, "hour"):
        # it's a date not datetime
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def calendar_color(cal) -> str:
    """Try to get a calendar's color; fall back to a nice default."""
    try:
        props = cal.get_properties([dav.DisplayName(), cdav.CalendarColor()])
        color = props.get("{http://apple.com/ns/ical/}calendar-color", "#4A90D9")
        if color and len(color) == 9:   # #RRGGBBAA → drop alpha
            color = color[:7]
        return color or "#4A90D9"
    except Exception:
        return "#4A90D9"

# ── Calendar sync ─────────────────────────────────────────────────────────────

def sync_calendars(client: caldav.DAVClient):
    log.info("Fetching calendars…")
    principal = client.principal()
    calendars = principal.calendars()
    log.info(f"Found {len(calendars)} calendar(s)")

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=1)
    window_end   = now + timedelta(days=SYNC_WINDOW_DAYS)

    all_events = []

    for cal in calendars:
        try:
            name = cal.name or "Unnamed"
            color = calendar_color(cal)
            log.info(f"  Syncing calendar: {name}")

            events = cal.date_search(
                start=window_start,
                end=window_end,
                expand=True   # expand recurring events
            )

            for event in events:
                try:
                    vevent = event.vobject_instance.vevent
                    uid = str(vevent.uid.value)

                    dtstart = vevent.dtstart.value
                    dtend   = getattr(vevent, "dtend", None)
                    dtend   = dtend.value if dtend else None

                    all_day = not hasattr(dtstart, "hour")

                    all_events.append({
                        "id":             uid,
                        "title":          str(vevent.summary.value) if hasattr(vevent, "summary") else "(No title)",
                        "calendar_name":  name,
                        "calendar_color": color,
                        "start_time":     to_utc_str(dtstart),
                        "end_time":       to_utc_str(dtend),
                        "all_day":        all_day,
                        "location":       str(vevent.location.value) if hasattr(vevent, "location") else None,
                        "notes":          str(vevent.description.value) if hasattr(vevent, "description") else None,
                        "synced_at":      now.isoformat(),
                    })
                except Exception as e:
                    log.warning(f"    Skipping event: {e}")

        except Exception as e:
            log.warning(f"  Could not sync calendar '{cal.name}': {e}")

    if all_events:
        log.info(f"Upserting {len(all_events)} event(s) to Supabase…")
        # Delete old events outside window first
        supabase.table("calendar_events")\
            .delete()\
            .lt("start_time", window_start.isoformat())\
            .execute()
        # Upsert current batch
        supabase.table("calendar_events").upsert(all_events, on_conflict="id").execute()
    else:
        log.info("No events found in sync window.")

# ── Reminders sync ────────────────────────────────────────────────────────────

REMINDER_CALDAV_URL = "https://caldav.icloud.com"

def priority_label(priority: int) -> int:
    """Normalize vCal priority (1-9) where 1=highest."""
    return priority if priority else 0

def sync_reminders(client: caldav.DAVClient):
    log.info("Fetching reminder lists (VTODO calendars)…")
    principal = client.principal()
    calendars = principal.calendars()
    now = datetime.now(timezone.utc)

    lists_upserted = []
    todos_upserted = []
    todo_ids_seen  = []

    for cal in calendars:
        try:
            # Only process reminder lists (they contain VTODOs)
            todos = cal.todos(include_completed=False)
            if todos is None:
                continue

            list_id   = str(cal.url).strip("/").split("/")[-1]
            list_name = cal.name or "Reminders"
            list_color = calendar_color(cal)

            lists_upserted.append({
                "id":        list_id,
                "name":      list_name,
                "color":     list_color,
                "synced_at": now.isoformat(),
            })

            for todo in todos:
                try:
                    vtodo = todo.vobject_instance.vtodo
                    uid   = str(vtodo.uid.value)

                    due = None
                    if hasattr(vtodo, "due"):
                        due = to_utc_str(vtodo.due.value)

                    completed    = hasattr(vtodo, "completed")
                    completed_at = to_utc_str(vtodo.completed.value) if completed else None

                    priority = int(vtodo.priority.value) if hasattr(vtodo, "priority") else 0

                    todos_upserted.append({
                        "id":           uid,
                        "list_id":      list_id,
                        "list_name":    list_name,
                        "title":        str(vtodo.summary.value) if hasattr(vtodo, "summary") else "(No title)",
                        "notes":        str(vtodo.description.value) if hasattr(vtodo, "description") else None,
                        "due_date":     due,
                        "completed":    completed,
                        "completed_at": completed_at,
                        "priority":     priority,
                        "synced_at":    now.isoformat(),
                    })
                    todo_ids_seen.append(uid)

                except Exception as e:
                    log.warning(f"    Skipping todo: {e}")

        except Exception as e:
            log.debug(f"  Calendar '{cal.name}' has no todos or errored: {e}")

    if lists_upserted:
        log.info(f"Upserting {len(lists_upserted)} reminder list(s)…")
        supabase.table("reminder_lists").upsert(
            lists_upserted, on_conflict="id", ignore_duplicates=False
        ).execute()

    if todos_upserted:
        log.info(f"Upserting {len(todos_upserted)} reminder(s)…")
        supabase.table("reminders").upsert(todos_upserted, on_conflict="id").execute()

    log.info("Reminder sync complete.")

# ── Timestamp ─────────────────────────────────────────────────────────────────

def update_last_synced():
    now = datetime.now(timezone.utc).isoformat()
    supabase.table("dashboard_settings").upsert(
        {"key": "last_synced", "value": json.dumps(now)},
        on_conflict="key"
    ).execute()
    log.info(f"last_synced updated → {now}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Connecting to iCloud CalDAV…")
    try:
        client = caldav.DAVClient(
            url=CALDAV_URL,
            username=ICLOUD_USERNAME,
            password=ICLOUD_PASSWORD,
        )
        # Test connection
        client.principal()
        log.info("Connected successfully.")
    except Exception as e:
        log.error(f"Failed to connect to iCloud: {e}")
        log.error("Make sure you are using an App-Specific Password from appleid.apple.com")
        sys.exit(1)

    sync_calendars(client)
    sync_reminders(client)
    update_last_synced()
    log.info("✅ Sync complete.")

if __name__ == "__main__":
    main()
