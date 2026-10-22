"""
Step 3: add the detail a CEO needs to each bill: policy area, official subjects,
the Congressional Research Service summary, how far it has moved, and cosponsor parties.

Congress.gov allows 5,000 calls per hour, so each run spends a fixed budget and picks up
where the last run stopped. Bills that are moving get done first. The first full backfill
takes about a day of hourly runs; after that each run only touches bills that changed.
"""
import html
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import stages
from common import (AuthError, RateLimited, SIMPLE_RESOLUTIONS, congress, load_json, save_json)

BUDGET = int(os.environ.get("ENRICH_CALL_BUDGET", "3800"))
TIME_LIMIT = int(os.environ.get("ENRICH_TIME_LIMIT_SEC", "2100"))
WORKERS = 4
ENRICH_DIR = "data/enrich"
VERSION = 1

_lock = threading.Lock()
_calls = 0
_stop = threading.Event()
_auth_error = []


class BudgetSpent(Exception):
    pass


def call(path, **params):
    global _calls
    with _lock:
        if _stop.is_set() or _calls >= BUDGET:
            _stop.set()
            raise BudgetSpent()
        _calls += 1
    return congress(path, **params)


TAG_RX = re.compile(r"<[^>]+>")


def clean_summary(text, limit=2500):
    text = html.unescape(TAG_RX.sub(" ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def enrich(key, b):
    base = f"bill/{b['congress']}/{b['type'].lower()}/{b['number']}"
    d = call(base)
    if not d or "bill" not in d:
        return None
    bill = d["bill"]
    sponsors = bill.get("sponsors") or [{}]
    out = {
        "v": VERSION,
        "update_date": b.get("update_date"),
        "policy_area": (bill.get("policyArea") or {}).get("name"),
        "cosponsors": (bill.get("cosponsors") or {}).get("count", 0) or 0,
        "sponsor": sponsors[0].get("fullName"),
        "sponsor_party": sponsors[0].get("party"),
        "laws": [f"{l.get('type', 'Law')} {l.get('number', '')}".strip() for l in bill.get("laws") or []],
        "subjects": [],
        "summary": None,
    }

    if bill.get("subjects"):
        s = call(base + "/subjects", limit=250) or {}
        subj = s.get("subjects") or {}
        out["subjects"] = [x.get("name") for x in subj.get("legislativeSubjects") or [] if x.get("name")]
        if not out["policy_area"]:
            out["policy_area"] = (subj.get("policyArea") or {}).get("name")

    if bill.get("summaries"):
        sm = (call(base + "/summaries") or {}).get("summaries") or []
        if sm:
            latest = max(sm, key=lambda x: (x.get("actionDate") or "", x.get("updateDate") or ""))
            out["summary"] = clean_summary(latest.get("text"))
            out["summary_version"] = latest.get("actionDesc")

    st = stages.from_text(b.get("latest_action"))
    actions_count = (bill.get("actions") or {}).get("count", 0) or 0
    if st["stage"] > 0 or actions_count > 3 or out["laws"]:
        acts = (call(base + "/actions", limit=250) or {}).get("actions") or []
        if acts:
            st = stages.from_actions(acts)
    if out["laws"]:
        st["stage"], st["label"] = 100, stages.LABELS[100]
    out.update({"stage": st["stage"], "stage_label": st["label"], "chambers_passed": st.get("chambers", [])})

    if out["cosponsors"] > 0 and (st["stage"] >= 30 or out["cosponsors"] >= 5):
        cs = (call(base + "/cosponsors", limit=250) or {}).get("cosponsors") or []
        parties = {}
        for c in cs:
            p = c.get("party") or "?"
            parties[p] = parties.get(p, 0) + 1
        sp = out["sponsor_party"]
        if sp:
            parties[sp] = parties.get(sp, 0) + 1
        out["parties"] = parties
    return out


def worker(item):
    key, b = item
    try:
        result = enrich(key, b)
    except BudgetSpent:
        return key, None
    except RateLimited:
        print("Hit the Congress.gov rate limit; stopping this run.")
        _stop.set()
        return key, None
    except AuthError as e:
        _auth_error.append(str(e))
        _stop.set()
        return key, None
    return key, result


def main():
    bills = load_json("data/bills.json", {})
    todo = []
    for key, b in bills.items():
        if b.get("type") in SIMPLE_RESOLUTIONS:
            continue  # commemorative and procedural resolutions; not member-relevant
        existing = load_json(os.path.join(ENRICH_DIR, f"{key}.json"), None)
        if existing and existing.get("v") == VERSION and existing.get("update_date") == b.get("update_date"):
            continue
        prio = stages.from_text(b.get("latest_action"))["stage"]
        todo.append((prio, b.get("latest_action_date") or "", key))
    todo.sort(reverse=True)
    eligible = sum(1 for b in bills.values() if b.get("type") not in SIMPLE_RESOLUTIONS)
    print(f"{len(todo)} of {eligible} bills need analysis. Budget this run: {BUDGET} calls.")

    started, done = time.time(), 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for i in range(0, len(todo), WORKERS * 10):
            if _stop.is_set() or time.time() - started > TIME_LIMIT:
                break
            chunk = [(k, bills[k]) for _, _, k in todo[i:i + WORKERS * 10]]
            for key, result in pool.map(worker, chunk):
                if result:
                    save_json(os.path.join(ENRICH_DIR, f"{key}.json"), result, compact=True)
                    done += 1
            print(f"  analyzed {done} so far ({_calls} calls)")

    if _auth_error:
        raise SystemExit(f"Congress.gov rejected the API key: {_auth_error[0]}")
    print(f"Done. Analyzed {done} bills using {_calls} calls. {max(0, len(todo) - done)} left for later runs.")


if __name__ == "__main__":
    main()
