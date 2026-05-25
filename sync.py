#!/usr/bin/env python3
"""
iCloud → Supabase Sync Script (v2 — bidirectional)
Handles:
  1. Pull iCloud Calendar + Reminders → Supabase (owner + partner accounts)
  2. Push completion changes from dashboard → back to iCloud (write-back queue)

Environment variables (GitHub Secrets):
  ICLOUD_USERNAME         — owner Apple ID email
  ICLOUD_PASSWORD         — owner App-Specific Password
  PARTNER_ICLOUD_USERNAME — partner Apple ID email
  PARTNER_ICLOUD_PASSWORD — partner App-Specific Password
  SUPABASE_URL            — Supabase project URL
  SUPABASE_SERVICE_KEY    — Supabase service role key

Run modes (set via SYNC_MODE env var, defaults to 'full'):
  full      — pull iCloud → Supabase  (every 30 min action)
  writeback — push completions to iCloud (every 5 min action)
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta

import caldav
from caldav.elements import dav, cdav
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SYNC_MODE    = os.environ.get("SYNC_MODE", "full")
OWNER_USER   = os.environ["ICLOUD_USERNAME"]
OWNER_PASS   = os.environ["ICLOUD_PASSWORD"]
PARTNER_USER = os.environ.get("PARTNER_ICLOUD_USERNAME", "")
PARTNER_PASS = os.environ.get("PARTNER_ICLOUD_PASSWORD", "")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
CALDAV_URL      = "https://caldav.icloud.com"
REMINDERS_URL   = "https://reminders.icloud.com"   # separate iCloud endpoint for Reminders
SYNC_WINDOW_DAYS = 14

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def to_utc_str(dt):
    if dt is None:
        return None
    if hasattr(dt, "date") and not hasattr(dt, "hour"):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def calendar_color(cal):
    try:
        props = cal.get_properties([dav.DisplayName(), cdav.CalendarColor()])
        color = props.get("{http://apple.com/ns/ical/}calendar-color", "#4A90D9")
        if color and len(color) == 9:
            color = color[:7]
        return color or "#4A90D9"
    except Exception:
        return "#4A90D9"

def connect(username, password, label=""):
    log.info(f"Connecting to iCloud CalDAV ({label or username})...")
    client = caldav.DAVClient(url=CALDAV_URL, username=username, password=password)
    client.principal()
    log.info("  Connected.")
    return client

def connect_reminders(username, password, label=""):
    """Connect to the separate iCloud Reminders CalDAV endpoint."""
    log.info(f"Connecting to iCloud Reminders ({label or username})...")
    client = caldav.DAVClient(url=REMINDERS_URL, username=username, password=password)
    client.principal()
    log.info("  Connected to Reminders.")
    return client

def sync_calendars(client, account_label):
    log.info(f"[{account_label}] Syncing calendars...")
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=1)
    window_end = now + timedelta(days=SYNC_WINDOW_DAYS)
    all_events = []

    for cal in client.principal().calendars():
        try:
            name = cal.name or "Unnamed"
            color = calendar_color(cal)
            events = cal.date_search(start=window_start, end=window_end, expand=True)
            for event in events:
                try:
                    ve = event.vobject_instance.vevent
                    uid = str(ve.uid.value)
                    dtstart = ve.dtstart.value
                    dtend = getattr(ve, "dtend", None)
                    dtend = dtend.value if dtend else None
                    all_day = not hasattr(dtstart, "hour")
                    all_events.append({
                        "id": uid,
                        "title": str(ve.summary.value) if hasattr(ve, "summary") else "(No title)",
                        "calendar_name": name,
                        "calendar_color": color,
                        "start_time": to_utc_str(dtstart),
                        "end_time": to_utc_str(dtend),
                        "all_day": all_day,
                        "location": str(ve.location.value) if hasattr(ve, "location") else None,
                        "notes": str(ve.description.value) if hasattr(ve, "description") else None,
                        "synced_at": now.isoformat(),
                    })
                except Exception as e:
                    log.warning(f"  Skipping event: {e}")
        except Exception as e:
            log.debug(f"  Calendar '{cal.name}' error: {e}")

    if all_events:
        sb.table("calendar_events").delete().lt("start_time", window_start.isoformat()).execute()
        sb.table("calendar_events").upsert(all_events, on_conflict="id").execute()
        log.info(f"[{account_label}] Upserted {len(all_events)} event(s).")

def sync_reminders(client, account_label):
    log.info(f"[{account_label}] Syncing reminders...")
    now = datetime.now(timezone.utc)
    lists_batch = []
    todos_batch = []

    all_cals = client.principal().calendars()
    log.info(f"[{account_label}] Found {len(all_cals)} calendar(s) on reminders endpoint")

    for cal in all_cals:
        try:
            log.info(f"[{account_label}]   Checking: '{cal.name}'")
            todos = cal.todos(include_completed=False)
            if not todos:
                log.info(f"[{account_label}]     → No todos")
                continue
            list_id = str(cal.url).strip("/").split("/")[-1]
            list_name = cal.name or "Reminders"
            if account_label == "partner":
                list_name = f"[Partner] {list_name}"

            log.info(f"[{account_label}]     → {len(todos)} todo(s) found")
            lists_batch.append({
                "id": list_id,
                "name": list_name,
                "color": calendar_color(cal),
                "synced_at": now.isoformat(),
            })

            for todo in todos:
                try:
                    vt = todo.vobject_instance.vtodo
                    uid = str(vt.uid.value)
                    due = to_utc_str(vt.due.value) if hasattr(vt, "due") else None
                    completed = hasattr(vt, "completed")
                    completed_at = to_utc_str(vt.completed.value) if completed else None
                    priority = int(vt.priority.value) if hasattr(vt, "priority") else 0
                    todos_batch.append({
                        "id": uid,
                        "list_id": list_id,
                        "list_name": list_name,
                        "title": str(vt.summary.value) if hasattr(vt, "summary") else "(No title)",
                        "notes": str(vt.description.value) if hasattr(vt, "description") else None,
                        "due_date": due,
                        "completed": completed,
                        "completed_at": completed_at,
                        "priority": priority,
                        "icloud_account": account_label,
                        "synced_at": now.isoformat(),
                    })
                except Exception as e:
                    log.warning(f"  Skipping todo: {e}")
        except Exception as e:
            log.debug(f"  Calendar '{cal.name}' no todos: {e}")

    if lists_batch:
        sb.table("reminder_lists").upsert(lists_batch, on_conflict="id").execute()
    if todos_batch:
        sb.table("reminders").upsert(todos_batch, on_conflict="id").execute()
    log.info(f"[{account_label}] {len(todos_batch)} reminder(s) synced.")

def process_write_back_queue():
    log.info("Processing write-back queue...")
    result = sb.table("completion_queue").select("*").is_("processed_at", "null").order("queued_at").execute()
    rows = result.data or []
    if not rows:
        log.info("No pending completions.")
        return

    log.info(f"Found {len(rows)} pending completion(s).")
    clients = {}

    def get_client(account):
        if account not in clients:
            if account == "owner":
                clients[account] = connect(OWNER_USER, OWNER_PASS, "owner")
            elif account == "partner" and PARTNER_USER:
                clients[account] = connect(PARTNER_USER, PARTNER_PASS, "partner")
        return clients.get(account)

    now = datetime.now(timezone.utc)

    for row in rows:
        reminder_id = row["reminder_id"]
        account_label = row["icloud_account"]
        completed = row["completed"]
        queue_id = row["id"]
        try:
            client = get_client(account_label)
            if not client:
                log.warning(f"  No credentials for account '{account_label}', skipping.")
                continue

            found = False
            for cal in client.principal().calendars():
                try:
                    todos = cal.todos(include_completed=True)
                    for todo in (todos or []):
                        try:
                            vt = todo.vobject_instance.vtodo
                            if str(vt.uid.value) != reminder_id:
                                continue
                            found = True
                            if completed:
                                if not hasattr(vt, "completed"):
                                    vt.add("completed").value = now
                                else:
                                    vt.completed.value = now
                                if hasattr(vt, "status"):
                                    vt.status.value = "COMPLETED"
                            else:
                                if hasattr(vt, "completed"):
                                    del vt.completed
                                if hasattr(vt, "status"):
                                    vt.status.value = "NEEDS-ACTION"
                            todo.save()
                            log.info(f"  {'Completed' if completed else 'Uncompleted'} {reminder_id[:8]}... ({account_label})")
                            break
                        except Exception as e:
                            log.warning(f"    Todo parse error: {e}")
                    if found:
                        break
                except Exception as e:
                    log.debug(f"  Calendar search error: {e}")

            if not found:
                log.warning(f"  Reminder {reminder_id[:8]}... not found in iCloud ({account_label})")

        except Exception as e:
            log.error(f"  Write-back failed for {reminder_id}: {e}")

        sb.table("completion_queue").update({"processed_at": now.isoformat()}).eq("id", queue_id).execute()

    log.info("Write-back queue processed.")

def update_last_synced():
    now = datetime.now(timezone.utc).isoformat()
    sb.table("dashboard_settings").upsert({"key": "last_synced", "value": json.dumps(now)}, on_conflict="key").execute()

def main():
    if SYNC_MODE == "writeback":
        process_write_back_queue()
    else:
        # Calendars — standard CalDAV endpoint
        owner_client = connect(OWNER_USER, OWNER_PASS, "owner")
        sync_calendars(owner_client, "owner")

        # Reminders — separate iCloud endpoint
        try:
            owner_reminders_client = connect_reminders(OWNER_USER, OWNER_PASS, "owner")
            sync_reminders(owner_reminders_client, "owner")
        except Exception as e:
            log.error(f"Owner reminders sync failed: {e}")

        if PARTNER_USER:
            try:
                partner_reminders_client = connect_reminders(PARTNER_USER, PARTNER_PASS, "partner")
                sync_reminders(partner_reminders_client, "partner")
            except Exception as e:
                log.error(f"Partner reminders sync failed: {e}")

        process_write_back_queue()
        update_last_synced()
    log.info("Done.")

if __name__ == "__main__":
    main()
