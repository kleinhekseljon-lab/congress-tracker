"""
Step 1: keep data/bills.json in sync with every bill in the current Congress.
First run pulls everything; later runs pull only bills updated since the last run.
"""
import os
import time
from datetime import datetime, timezone

from common import API_KEY, AuthError, RateLimited, bill_key, congress, load_json, save_json

CONGRESS = os.environ.get("CONGRESS", "119")
BILLS_FILE = "data/bills.json"
STATE_FILE = "data/state.json"
PAGE_SIZE = 250


def main():
    if not API_KEY:
        raise SystemExit("CONGRESS_API_KEY is empty. Check Settings > Secrets and variables > Actions.")
    print(f"API key loaded ({len(API_KEY)} characters)")
    bills = load_json(BILLS_FILE, {})
    state = load_json(STATE_FILE, {})
    run_started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {"sort": "updateDate desc", "limit": PAGE_SIZE}
    if state.get("last_run"):
        params["fromDateTime"] = state["last_run"]
        print(f"Incremental pull since {state['last_run']}")
    else:
        print(f"First run: full pull of Congress {CONGRESS}")

    offset, changed, complete = 0, 0, True
    while True:
        try:
            page = congress(f"bill/{CONGRESS}", offset=offset, **params)
        except AuthError as e:
            raise SystemExit(f"Congress.gov rejected the API key ({e}). Update the CONGRESS_API_KEY secret.")
        except RateLimited:
            print("Hit the Congress.gov rate limit; will finish next run.")
            complete = False
            break
        if page is None:
            print("A page failed after retries; will finish next run.")
            complete = False
            break
        batch = page.get("bills", [])
        for b in batch:
            latest = b.get("latestAction") or {}
            bills[bill_key(b["congress"], b["type"], b["number"])] = {
                "congress": b.get("congress"),
                "type": b.get("type"),
                "number": b.get("number"),
                "title": b.get("title"),
                "origin_chamber": b.get("originChamber"),
                "introduced_date": b.get("introducedDate"),
                "latest_action_date": latest.get("actionDate"),
                "latest_action": latest.get("text"),
                "update_date": b.get("updateDate"),
            }
            changed += 1
        print(f"Offset {offset}: {len(batch)} bills")
        if not batch or not (page.get("pagination") or {}).get("next"):
            break
        offset += PAGE_SIZE
        time.sleep(0.5)

    save_json(BILLS_FILE, bills)
    if complete:
        state["last_run"] = run_started
    state["total_bills"] = len(bills)
    save_json(STATE_FILE, state)
    print(f"Done. {changed} bills added/updated. {len(bills)} total.")


if __name__ == "__main__":
    main()
