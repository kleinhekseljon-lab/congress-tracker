"""Step 4: recent final and proposed rules from the agencies that hit small and mid-size companies.
Source: Federal Register API (free, no key)."""
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

from common import http_json, load_json, save_json

FR_BASE = os.environ.get("FR_API_BASE", "https://www.federalregister.gov/api/v1").rstrip("/")
OUT = "data/regs.json"
LOOKBACK_DAYS = 120
KEEP_DAYS = 200
FIELDS = ["title", "type", "abstract", "document_number", "html_url", "publication_date", "agencies",
          "comments_close_on", "effective_on", "significant"]


def agencies():
    cfg = load_json("config/industries.json", {})
    slugs = set(cfg.get("universal", {}).get("agencies", []))
    for i in cfg.get("industries", []):
        slugs |= set(i.get("agencies", []))
    return sorted(slugs)


def main():
    regs = load_json(OUT, {})
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    added = 0
    for slug in agencies():
        params = [("per_page", "100"), ("order", "newest"), ("conditions[type][]", "RULE"),
                  ("conditions[type][]", "PRORULE"), ("conditions[agencies][]", slug),
                  ("conditions[publication_date][gte]", since)] + [("fields[]", f) for f in FIELDS]
        url = f"{FR_BASE}/documents.json?{urllib.parse.urlencode(params)}"
        for _ in range(2):  # up to 200 documents per agency
            try:
                data = http_json(url)
            except Exception as e:
                print(f"{slug}: {e}")
                data = None
            if not data:
                print(f"{slug}: no data (agency name may have changed); skipping")
                break
            for r in data.get("results", []):
                doc = r.get("document_number")
                if not doc:
                    continue
                regs[doc] = {
                    "title": r.get("title"),
                    "type": r.get("type"),
                    "abstract": (r.get("abstract") or "")[:1500],
                    "url": r.get("html_url"),
                    "published": r.get("publication_date"),
                    "comments_close_on": r.get("comments_close_on"),
                    "effective_on": r.get("effective_on"),
                    "significant": bool(r.get("significant")),
                    "agencies": [a.get("name") for a in r.get("agencies") or [] if a.get("name")],
                    "agency_slugs": [a.get("slug") for a in r.get("agencies") or [] if a.get("slug")],
                }
                added += 1
            url = data.get("next_page_url")
            if not url:
                break
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).date().isoformat()
    regs = {k: v for k, v in regs.items() if (v.get("published") or "") >= cutoff}
    save_json(OUT, regs)
    print(f"Done. {added} rules fetched; {len(regs)} on file.")


if __name__ == "__main__":
    main()
