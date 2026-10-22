"""Step 6: score everything per industry and write the files the website reads into _site/."""
import os
import re
import shutil
from datetime import datetime, timezone

import items as itemlib
import scoring
import stages
from common import (SIMPLE_RESOLUTIONS, bill_label, bill_url, load_json, save_json)

OUT = "_site"
WATCH_BILLS = 60
WATCH_REGS = 20


def first_sentences(text, limit=320):
    text = (text or "").strip()
    if not text:
        return ""
    # CRS summaries open with the bill's short title in bold, then "This bill ..."
    m = re.search(r"\b(This (bill|joint resolution|concurrent resolution|act)\b.*)", text)
    if m:
        text = m.group(1)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    return (cut[:end + 1] if end > 120 else cut.rstrip() + "…")


def bill_out(it, rel, hits, pr):
    b, e, a = it["bill"], it["enrich"], it.get("ai") or {}
    return {
        "kind": "bill", "key": it["key"],
        "label": bill_label(b["type"], b["number"]),
        "url": bill_url(b["congress"], b["type"], b["number"]),
        "chamber": b.get("origin_chamber"),
        "title": b.get("title"),
        "headline": a.get("headline"),
        "what": a.get("what_it_does") or first_sentences(e.get("summary")),
        "impact_text": a.get("business_impact"),
        "impact": a.get("impact"),
        "stage": it["stage"], "stage_label": it["stage_label"], "step": stages.STEP.get(it["stage"], 0),
        "latest_date": b.get("latest_action_date"), "latest_action": b.get("latest_action"),
        "days": it["days"], "cosponsors": e.get("cosponsors"), "bipartisan": it["bipartisan"],
        "policy_area": e.get("policy_area"), "sponsor": e.get("sponsor"),
        "matched": hits, "position": it.get("position"),
        "relevance": rel, "momentum": it["momentum"], "priority": pr,
    }


def reg_out(it, rel, hits, pr):
    r, a = it["reg"], it.get("ai") or {}
    return {
        "kind": "reg", "key": it["key"],
        "label": "Proposed rule" if r.get("type") == "Proposed Rule" else "Final rule",
        "url": r.get("url"), "agency": ", ".join(r.get("agencies") or [])[:120],
        "title": r.get("title"), "headline": a.get("headline"),
        "what": a.get("what_it_does") or first_sentences(r.get("abstract")),
        "impact_text": a.get("business_impact"), "impact": a.get("impact"),
        "published": r.get("published"), "comments_close": r.get("comments_close_on"),
        "effective": r.get("effective_on"), "significant": r.get("significant"),
        "days": it["days"], "matched": hits, "position": it.get("position"),
        "relevance": rel, "momentum": it["momentum"], "priority": pr,
    }


def main():
    bills = load_json("data/bills.json", {})
    state = load_json("data/state.json", {})
    regs = load_json("data/regs.json", {})
    senators = load_json("data/senators.json", {})
    positions = {k: v for k, v in load_json("config/chamber_positions.json", {}).items() if not k.startswith("_")}
    site = load_json("config/site.json", {})
    enrich = itemlib.load_enrichment()
    ai = itemlib.load_ai()

    bill_list = list(itemlib.bill_items(bills, enrich, ai, positions))
    reg_list = list(itemlib.reg_items(regs, ai, positions))

    os.makedirs(f"{OUT}/data/watch", exist_ok=True)
    counts = {}
    for ind in scoring.INDUSTRIES:
        slug = ind["slug"]
        picked_bills, picked_regs = [], []
        for it in bill_list:
            rel, hits, pr = itemlib.score_for(it, slug)
            if itemlib.is_candidate(it, rel):
                picked_bills.append(bill_out(it, rel, hits, pr))
        for it in reg_list:
            rel, hits, pr = itemlib.score_for(it, slug)
            if itemlib.is_candidate(it, rel):
                picked_regs.append(reg_out(it, rel, hits, pr))
        picked_bills.sort(key=lambda x: -x["priority"])
        picked_regs.sort(key=lambda x: -x["priority"])
        watch = picked_bills[:WATCH_BILLS] + picked_regs[:WATCH_REGS]
        watch.sort(key=lambda x: -x["priority"])
        save_json(f"{OUT}/data/watch/{slug}.json", watch, compact=True)
        counts[slug] = len(watch)

    # Compact index of every bill for the search tab
    index = []
    for key, b in bills.items():
        e = enrich.get(key) or {}
        label = e.get("stage_label") or stages.from_text(b.get("latest_action"))["label"]
        index.append([b.get("congress"), b.get("type"), b.get("number"), b.get("title"),
                      b.get("origin_chamber"), b.get("latest_action_date"),
                      (b.get("latest_action") or "")[:200], label])
    save_json(f"{OUT}/data/index.json", index, compact=True)

    eligible = sum(1 for b in bills.values() if b.get("type") not in SIMPLE_RESOLUTIONS)
    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_sync": state.get("last_run"),
        "total_bills": len(bills),
        "analyzed": len(enrich), "analyzable": eligible,
        "regs": len(regs), "ai_summaries": len(ai),
        "industries": [{"slug": i["slug"], "name": i["name"], "count": counts.get(i["slug"], 0)}
                       for i in scoring.INDUSTRIES],
        "senators": {k: v for k, v in senators.items() if not k.startswith("_")},
        "site": site,
    }
    save_json(f"{OUT}/data/meta.json", meta, compact=True)
    shutil.copy("index.html", f"{OUT}/index.html")
    print(f"Site built. Watch list sizes: {counts}")


if __name__ == "__main__":
    main()
