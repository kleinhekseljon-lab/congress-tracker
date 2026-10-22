"""
Pull every bill in the current Congress from the Congress.gov API.
First run: full pull. Every run after: only bills updated since the last run.
Output: data/bills.json (all bills) and data/state.json (last run timestamp).
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from urllib.error import HTTPError

API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()
CONGRESS = os.environ.get("CONGRESS", "119")
BASE = f"https://api.congress.gov/v3/bill/{CONGRESS}"
DATA_DIR = "data"
BILLS_FILE = os.path.join(DATA_DIR, "bills.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
PAGE_SIZE = 250  # API max


def load(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def fetch(params):
    params = {**params, "api_key": API_KEY, "format": "json", "limit": PAGE_SIZE}
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "congress-tracker/1.0 (+https://github.com)",
        "Accept": "application/json",
    })
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if 400 <= e.code < 500 and e.code != 429:
                # Bad key or bad request: retrying won't help, so stop with the real reason
                raise SystemExit(f"Congress.gov rejected the request (HTTP {e.code}): {body}")
            wait = (2 ** attempt) * 5
            print(f"HTTP {e.code}. Retrying in {wait}s")
            time.sleep(wait)
        except Exception as e:
            wait = (2 ** attempt) * 5
            print(f"Request failed ({e}). Retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError("Congress.gov API failed after 5 attempts")


def main():
    if not API_KEY:
        raise SystemExit("CONGRESS_API_KEY is empty. Check Settings > Secrets and variables > Actions.")
    print(f"API key loaded ({len(API_KEY)} characters)")
    os.makedirs(DATA_DIR, exist_ok=True)
    bills = load(BILLS_FILE, {})
    state = load(STATE_FILE, {})
    run_started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {"sort": "updateDate desc"}
    if state.get("last_run"):
        params["fromDateTime"] = state["last_run"]
        print(f"Incremental pull since {state['last_run']}")
    else:
        print(f"First run: full pull of Congress {CONGRESS}")

    offset, changed = 0, 0
    while True:
        page = fetch({**params, "offset": offset})
        batch = page.get("bills", [])
        for b in batch:
            key = f"{b['congress']}-{b['type']}-{b['number']}".lower()
            latest = b.get("latestAction") or {}
            bills[key] = {
                "congress": b.get("congress"),
                "type": b.get("type"),
                "number": b.get("number"),
                "title": b.get("title"),
                "origin_chamber": b.get("originChamber"),
                "latest_action_date": latest.get("actionDate"),
                "latest_action": latest.get("text"),
                "update_date": b.get("updateDate"),
                "api_url": b.get("url"),
            }
