"""Step 2 (weekly): current U.S. senators by state, for the 'tell your senators' links."""
import os
from datetime import datetime, timedelta, timezone

from common import AuthError, RateLimited, congress, load_json, save_json

OUT = "data/senators.json"
STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
          "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
          "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
          "WI", "WY"]


def main():
    existing = load_json(OUT, {})
    fetched = existing.get("_fetched")
    if fetched and datetime.now(timezone.utc) - datetime.fromisoformat(fetched) < timedelta(days=7) \
            and not os.environ.get("FORCE_MEMBERS"):
        print("Senator list is less than a week old; skipping.")
        return
    out = {}
    try:
        for st in STATES:
            data = congress(f"member/{st}", currentMember="true", limit=250) or {}
            senators = []
            for m in data.get("members", []):
                terms = (m.get("terms") or {}).get("item", []) or []
                if m.get("district") is None and any(t.get("chamber") == "Senate" for t in terms):
                    name = m.get("name", "")
                    if ", " in name:
                        last, first = name.split(", ", 1)
                        name = f"{first} {last}"
                    detail = (congress(f"member/{m['bioguideId']}") or {}).get("member", {})
                    senators.append({
                        "name": name,
                        "party": (m.get("partyName") or "?")[:1],
                        "url": detail.get("officialWebsiteUrl") or f"https://www.senate.gov/states/{st}/intro.htm",
                    })
            out[st] = senators
            print(f"{st}: {len(senators)} senators")
    except (AuthError, RateLimited) as e:
        print(f"Stopped early: {e}")
        return
    out["_fetched"] = datetime.now(timezone.utc).isoformat()
    save_json(OUT, out)


if __name__ == "__main__":
    main()
