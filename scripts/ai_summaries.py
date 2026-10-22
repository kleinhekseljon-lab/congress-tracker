"""
Step 5: plain-English 'what it means for your business' summaries.

Default: GitHub Models, which is free and uses the token GitHub Actions already has.
No account, card, or secret needed. The free tier allows roughly 150 summaries a day,
so each hourly run does a few, most important first, and caches them.

Optional: add an ANTHROPIC_API_KEY secret to use Claude instead (paid, no daily cap).
"""
import json
import os
import re

import items as itemlib
import scoring
from common import AuthError, RateLimited, http_json, load_json, save_json

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_BASE = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_MODELS_URL = os.environ.get("GITHUB_MODELS_URL", "https://models.github.ai/inference/chat/completions")

if ANTHROPIC_KEY:
    PROVIDER, MODEL, DEFAULT_MAX = "anthropic", os.environ.get("AI_MODEL") or "claude-haiku-5-5", 60
else:
    PROVIDER, MODEL, DEFAULT_MAX = "github", os.environ.get("AI_MODEL") or "openai/gpt-4.1-mini", 6
MAX_PER_RUN = int(os.environ.get("AI_MAX_PER_RUN") or DEFAULT_MAX)

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


def ask(prompt):
    """Send one prompt; return the reply text or None."""
    if PROVIDER == "anthropic":
        body = {"model": MODEL, "max_tokens": 700, "system": SYSTEM,
                "messages": [{"role": "user", "content": prompt}]}
        resp = http_json(f"{ANTHROPIC_BASE}/v1/messages", data=body, timeout=90,
                         headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"})
        if not resp:
            return None
        return "".join(c.get("text", "") for c in resp.get("content", []) if c.get("type") == "text")
    body = {"model": MODEL, "max_tokens": 700, "temperature": 0.2,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    resp = http_json(GITHUB_MODELS_URL, data=body, timeout=90,
                     headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"})
    if not resp:
        return None
    choices = resp.get("choices") or [{}]
    return (choices[0].get("message") or {}).get("content")


def main():
    if not ANTHROPIC_KEY and not GITHUB_TOKEN:
        print("No AI access configured; skipping. The site will use official summaries.")
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
    print(f"{len(ranked)} items need a fresh summary; doing up to {MAX_PER_RUN} this run "
          f"with {MODEL} via {'Anthropic' if PROVIDER == 'anthropic' else 'GitHub Models (free)'}.")

    done = 0
    for _, cache_key, version, it in ranked[:MAX_PER_RUN]:
        try:
            text = ask(prompt_for(it))
        except AuthError as e:
            print(f"AI access was refused: {e}")
            if PROVIDER == "github":
                print("Check that the workflow has 'models: read' under permissions.")
            return
        except RateLimited:
            print("Hit today's free limit; the next runs will pick up where this left off.")
            break
        if not text:
            print(f"  no response for {cache_key} (if every item fails, the model name may have changed)")
            continue
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
