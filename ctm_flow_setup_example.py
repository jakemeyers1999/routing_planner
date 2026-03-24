#!/usr/bin/env python3
"""
CTM Routing Flow Provisioning Script
Generated: 3/24/2026, 7:40:20 AM
Tool: CTM Routing Planner

This script provisions the routing flow in a live CTM account via the REST API.
Resources are created in dependency order so that IDs are available for cross-linking.

BEFORE RUNNING:
  1. Fill in ACCOUNT_ID, API_KEY, and API_SECRET below
  2. Install dependencies:  pip install requests
  3. Run:  python3 ctm_flow_setup.py
"""

import requests
import json
import sys
from base64 import b64encode

# ── CONFIGURE BEFORE RUNNING ──────────────────────────────────────────────────
ACCOUNT_ID = "YOUR_ACCOUNT_ID"   # CTM Account ID (numeric)
API_KEY    = "YOUR_API_KEY"       # CTM API Key    (Settings → API)
API_SECRET = "YOUR_API_SECRET"    # CTM API Secret (Settings → API)
# ─────────────────────────────────────────────────────────────────────────────

BASE  = f"https://api.calltrackingmetrics.com/api/v1/accounts/{ACCOUNT_ID}"
HEADS = {
    "Authorization": "Basic " + b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode(),
    "Content-Type": "application/json"
}

def post(path, data=None):
    r = requests.post(BASE + path, headers=HEADS, json=data or {})
    if not r.ok:
        print(f"  ✗ POST {path} failed [{r.status_code}]: {r.text[:300]}")
        r.raise_for_status()
    return r.json()

def patch(path, data):
    r = requests.patch(BASE + path, headers=HEADS, json=data)
    if not r.ok:
        print(f"  ✗ PATCH {path} failed [{r.status_code}]: {r.text[:300]}")
        r.raise_for_status()
    return r.json()

def put(path, data):
    r = requests.put(BASE + path, headers=HEADS, json=data)
    if not r.ok:
        print(f"  ✗ PUT {path} failed [{r.status_code}]: {r.text[:300]}")
        r.raise_for_status()
    return r.json()

# Stores CTM resource IDs keyed by diagram node ID
node_ids = {}

print("=" * 60)
print("CTM Routing Flow Provisioning")
print("=" * 60)


# ── Step 1: Tracking Number 1 (TrackingNumber) ─────────────────────────
print("\nStep 1: Purchasing Tracking Number — Tracking Number 1")
print(f"  Area code: XXX | Type: tollfree | Campaign: ")
# Search for available toll-free number then purchase
search = requests.get(f"{BASE}/numbers/search.json?country=US&searchby=tollfree&per_page=10", headers=HEADS).json()
if not search.get("numbers"):
    print("  ✗ No toll-free numbers available"); sys.exit(1)
toll_number = search["numbers"][0]
print(f"  Using toll-free: {toll_number}")
r = post("/numbers", {"phone_number": toll_number, "test": False})
node_ids["n1"] = r["id"]
print(f'  ✓ Tracking Number purchased: {r.get("number","?")}  ID: {node_ids["n1"]}')

# Update tracking number settings
post(f'/numbers/{node_ids["n1"]}/update_number', {
    "name": "Tracking Number 1",
    
    "sms_enabled": False
})
# Set dial route → Queue 1 (Queue)
put(f'/numbers/{node_ids["n1"]}/dial_routes', {
    "virtual_phone_number.dial_route": "call_queue",
    "virtual_phone_number.call_queue_id": node_ids.get("n2", 0)
})
print(f'  ✓ Dial route set to Queue 1')


# ── Step 2: Queue 1 (Queue) ────────────────────────────────────────────
print("\nStep 2: Creating Call Queue — Queue 1")
r = post("/call_queues", {
    "name": "Queue 1",
    "ring_to": "round_robin",
    "timeout": 20,
    "max_queue_wait": 120,
    "description": "After-Hours Route: External Number"
})
node_ids["n2"] = r["call_queue"]["id"]
print(f'  ✓ Queue created: ID {node_ids["n2"]}')

# Set queue no-answer route
patch(f'/queues/{node_ids["n2"]}', {
    "default_action_type": "Hangup",
    "default_action_id": node_ids.get("n3", 0)
})
print("  ✓ No-answer route configured")

# ── Step 3: End Action 1 (EndAction) ───────────────────────────────────
print("\nStep 3.1: Webhook End Action — End Action 1")
# Webhook URL: abc.com
# Auth type: none
# Body template: 
# Configure this as a Trigger in CTM pointing to the webhook above
# or wire it directly in the routing node's End Actions in the CTM UI

print("\n" + "=" * 60)
print("✅ Provisioning complete!")
print("=" * 60)
print("\nCreated resource IDs:")
for k, v in node_ids.items():
    print(f"  {k}: {v}")
print("\nNext steps:")
print("  1. Log into CTM and verify each resource was created correctly")
print("  2. Assign tracking numbers to your campaigns / sources")
print("  3. Test incoming calls through the full flow")
