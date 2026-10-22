"""
Step 5 (optional): plain-English 'what it means for your business' summaries from Claude.
Runs only if the ANTHROPIC_API_KEY secret exists. Summarizes the bills and rules most likely
to matter, caches each one, and only re-summarizes when the bill changes.
"""
import json
import os
import re

import items as itemlib
import scoring
from common import AuthError, RateLimited, http_json, load_json, save_json

KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
BASE = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
MODEL = os.environ.get("AI_MODEL", "claude-haiku-5-5")
MAX_PER_RUN = int(os.environ.get("AI_MAX_PER_RUN", "60"))

SYSTEM = (
    "You brief owners and CEOs of U.S. companies with 25 to 500 employees and $1M to $100M in revenue "
    "on federal bills and regulations. Write plainly and concretely for a busy executive. Stay neutral: "
    "describe effects, do not argue for or against. Never invent dollar figures or facts that are not in "
    "the source; when an effect depends on facts you do not have, say what it depends on. "
    "Respond with a single JSON object and nothing else."
)


def prompt_for(item):
    slugs = ", ".join(i["slug"] for i in scoring.INDUSTRIES)
    if item["kind"] == "bill":
        b, e = item["bill"], item["enrich"]
        src = (f"Bill: {b.get('title')}\nStatus: {item['stage_label']}\n"
               f"Policy area: {e.get('policy_area') or 'unknown'}\n"
               f"Subjects: {', '.join(e.get('subjects', [])[:25]) or 'none listed'}\n"
               f"Official summary: {e.get('summary') or 'none yet; work from the title only and say so'}")
    else:
        r = item["reg"]
        src = (f"{r.get('type')} from {', '.join(r.get('agencies') or [])}: {r.get('title')}\n"
               f"Abstract: {r.get('abstract') or 'none'}\n"
               f"Comments close: {r.get('comments_close_on') or 'n/a'}  Effective: {r.get('effective_on') or 'n/a'}")
    return f"""{src}

Return JSON with exactly these keys:
"headline": what it does, at most 12 words, plain English, no bill number.
"what_it_does": 1 to 2 sentences.
"business_impact": 1 to 2 sentences on what would change for a company of this size (costs, taxes, hiring, compliance, or opportunities). If it would not meaningfully affect such companies, say that.
"impact": one of "cost", "relief", "mixed", "compliance", "opportunity", "minimal".
"industries": list drawn only from [{slugs}, all_employers]; empty if none.
"relevant_to_business": true or false."""


def parse(text):
    text = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def main():
    if not KEY:
        print("No ANTHROPIC_API_KEY secret set; skipping AI summaries. The site will use official summaries.")
        return
    bills = load_json("data/bills.json", {})
    regs = load_json("data/regs.json", {})
    positions = load_json("config/chamber_positions.json", {})
    enrich = itemlib.load_enrichment()
    ai = itemlib.load_ai()

    ranked = []
    all_items = list(itemlib.bill_items(bills, enrich, None, positions)) + \
        list(itemlib.reg_items(regs, None, positions))
    for it in all_items:
        best = 0
        for ind in scoring.INDUSTRIES:
            rel, _, pr = itemlib.score_for(it, ind["slug"], use_ai=False)
            if itemlib.is_candidate(it, rel):
                best = max(best, pr)
        if not best:
            continue
        cache_key = it["key"] if it["kind"] == "bill" else f"fr-{it['key']}"
        version = it["bill"].get("update_date") if it["kind"] == "bill" else it["reg"].get("published")
        cached = ai.get(cache_key)
        if cached and cached.get("update_date") == version:
            continue
        ranked.append((best, cache_key, version, it))
    ranked.sort(key=lambda x: -x[0])
    print(f"{len(ranked)} items need a fresh summary; doing up to {MAX_PER_RUN} this run with {MODEL}.")

    done = 0
    for _, cache_key, version, it in ranked[:MAX_PER_RUN]:
        body = {"model": MODEL, "max_tokens": 700, "system": SYSTEM,
                "messages": [{"role": "user", "content": prompt_for(it)}]}
        try:
            resp = http_json(f"{BASE}/v1/messages", data=body, timeout=90,
                             headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"})
        except AuthError as e:
            print(f"Anthropic rejected the key: {e}")
            return
        except RateLimited:
            print("Anthropic rate limit hit; finishing next run.")
            break
        if not resp:
            continue
        text = "".join(c.get("text", "") for c in resp.get("content", []) if c.get("type") == "text")
        out = parse(text)
        if not out:
            print(f"  could not parse summary for {cache_key}")
            continue
        out.update({"update_date": version, "model": MODEL})
        save_json(f"data/ai/{cache_key}.json", out, compact=True)
        done += 1
    print(f"Done. {done} summaries written.")


if __name__ == "__main__":
    main()
