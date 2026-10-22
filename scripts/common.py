"""Shared helpers: HTTP with retries, Congress.gov calls, JSON files, bill keys."""
import json
import os
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

API_KEY = os.environ.get("CONGRESS_API_KEY", "").strip()
API_BASE = os.environ.get("CONGRESS_API_BASE", "https://api.congress.gov/v3").rstrip("/")
UA = "congress-tracker/2.0 (+https://github.com)"


class RateLimited(Exception):
    pass


class AuthError(Exception):
    pass


def http_json(url, headers=None, data=None, timeout=60, retries=4):
    """GET (or POST when data is given) and return parsed JSON.
    429 raises RateLimited, 401/403 raise AuthError, other 4xx return None,
    5xx and network errors retry with backoff, then return None."""
    hdrs = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    err = ""
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=hdrs, data=body, method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:400]
            if e.code == 429:
                raise RateLimited(text)
            if e.code in (401, 403):
                raise AuthError(f"HTTP {e.code}: {text}")
            if 400 <= e.code < 500:
                return None
            err = f"HTTP {e.code}"
        except Exception as e:  # network hiccup, timeout, bad JSON
            err = str(e)
        wait = 3 * (2 ** attempt)
        print(f"  {err}; retrying in {wait}s")
        time.sleep(wait)
    return None


def congress(path, **params):
    params = {**params, "api_key": API_KEY, "format": "json"}
    return http_json(f"{API_BASE}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}")


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj, compact=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(obj, f, indent=1, sort_keys=True)


def bill_key(congress_num, bill_type, number):
    return f"{congress_num}-{bill_type}-{number}".lower()


TYPE_INFO = {
    "HR": ("H.R.", "house-bill"), "S": ("S.", "senate-bill"),
    "HRES": ("H.Res.", "house-resolution"), "SRES": ("S.Res.", "senate-resolution"),
    "HJRES": ("H.J.Res.", "house-joint-resolution"), "SJRES": ("S.J.Res.", "senate-joint-resolution"),
    "HCONRES": ("H.Con.Res.", "house-concurrent-resolution"),
    "SCONRES": ("S.Con.Res.", "senate-concurrent-resolution"),
}
SIMPLE_RESOLUTIONS = {"HRES", "SRES"}


def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def bill_label(bill_type, number):
    return f"{TYPE_INFO.get(bill_type, (bill_type, ''))[0]} {number}"


def bill_url(congress_num, bill_type, number):
    slug = TYPE_INFO.get(bill_type, ("", ""))[1]
    if not slug:
        return "https://www.congress.gov/"
    return f"https://www.congress.gov/bill/{ordinal(congress_num)}-congress/{slug}/{number}"
