#!/usr/bin/env python3
"""
PIN Setup Script
Run this ONCE locally to hash your chosen PIN and store it in Supabase.

Usage:
  pip install bcrypt supabase
  SUPABASE_URL=https://xxx.supabase.co SUPABASE_SERVICE_KEY=xxx python setup_pin.py

You will be prompted to enter your PIN interactively (it won't echo to the terminal).
"""

import os
import sys
import json
import getpass
import bcrypt
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("\n── iPad Dashboard PIN Setup ──")
print("Choose a PIN that you and your partner will enter on the dashboard.")
print("It can be any length (digits or letters).\n")

pin = getpass.getpass("Enter your PIN: ")
confirm = getpass.getpass("Confirm PIN:   ")

if pin != confirm:
    print("ERROR: PINs do not match.")
    sys.exit(1)

if len(pin) < 4:
    print("ERROR: PIN must be at least 4 characters.")
    sys.exit(1)

print("\nHashing PIN…")
hashed = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()

sb.table("dashboard_settings").upsert(
    {"key": "pin_hash", "value": json.dumps(hashed)},
    on_conflict="key"
).execute()

print("✅ PIN saved to Supabase. You can now deploy the dashboard.")
print("\nIMPORTANT: Never share or commit your PIN or the hash.")
