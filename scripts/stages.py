"""Work out how far a bill has gotten from its action text."""
import re

LABELS = {
    0: "Introduced", 30: "In committee", 45: "Out of committee", 65: "Passed one chamber",
    80: "Passed both chambers", 85: "Vetoed", 90: "On the President's desk", 100: "Became law",
}
# Position on the 5-step track shown on the site
STEP = {0: 0, 30: 1, 45: 1, 65: 2, 80: 3, 85: 3, 90: 3, 100: 4}

PASSED_IN = re.compile(r"passed/agreed to in (house|senate)")
PASSED_X = re.compile(r"\bpassed (house|senate)\b")


def classify(text, source=""):
    """Return (score, chambers_passed) for one action."""
    t = (text or "").lower()
    src = (source or "").lower()
    chambers = set()
    if "became public law" in t or "signed by president" in t:
        return 100, chambers
    if "presented to president" in t:
        return 90, chambers
    if "vetoed" in t or "veto message" in t:
        return 85, chambers
    for rx in (PASSED_IN, PASSED_X):
        m = rx.search(t)
        if m:
            chambers.add(m.group(1))
    if "received in the senate" in t:
        chambers.add("house")
    if "received in the house" in t:
        chambers.add("senate")
    floor_pass = ("on passage passed" in t) or (
        "suspend the rules and pass" in t and "agreed to" in t and "failed" not in t)
    if floor_pass:
        chambers.add("senate" if "senate" in src else "house")
    if "resolving differences" in t or "conference report" in t:
        return 80, chambers
    if len(chambers) == 2:
        return 80, chambers
    if chambers:
        return 65, chambers
    if ("reported by" in t or "ordered to be reported" in t or "reported to senate" in t
            or ("placed on" in t and "calendar" in t)):
        return 45, chambers
    if ("referred to" not in t) and any(k in t for k in (
            "markup", "mark-up", "hearings held", "committee consideration", "subcommittee consideration")):
        return 30, chambers
    return 0, chambers


def label_for(score, chambers=()):
    if score == 65 and len(chambers) == 1:
        return f"Passed {next(iter(chambers)).title()}"
    return LABELS.get(score, "Introduced")


def from_text(text):
    score, ch = classify(text)
    return {"stage": score, "label": label_for(score, ch), "chambers": sorted(ch)}


def from_actions(actions):
    best, best_date, chambers = 0, None, set()
    for a in actions or []:
        src = (a.get("sourceSystem") or {}).get("name", "")
        typ = a.get("type", "")
        score, ch = classify(a.get("text"), src)
        if typ == "BecameLaw":
            score = 100
        chambers |= ch
        if score > best or (score == best and (a.get("actionDate") or "") > (best_date or "")):
            best, best_date = max(best, score), a.get("actionDate")
    if len(chambers) == 2 and best < 80:
        best = 80
    return {"stage": best, "label": label_for(best, chambers), "chambers": sorted(chambers), "stage_date": best_date}
