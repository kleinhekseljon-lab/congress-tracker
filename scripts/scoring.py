"""Relevance (does this matter to my kind of company?) and momentum (is it actually moving?)."""
import re
from datetime import date, datetime, timezone

from common import load_json

CONFIG = load_json("config/industries.json", {})


def _rx(words):
    return [(w, re.compile(r"\b" + re.escape(w.lower()))) for w in words]


UNIVERSAL = CONFIG.get("universal", {})
UNI_RX = _rx(UNIVERSAL.get("keywords", []))
INDUSTRIES = CONFIG.get("industries", [])
IND_RX = {i["slug"]: _rx(i.get("keywords", [])) for i in INDUSTRIES}
IND_PA = {i["slug"]: set(i.get("policy_areas", [])) for i in INDUSTRIES}
IND_AG = {i["slug"]: set(i.get("agencies", [])) for i in INDUSTRIES}
UNI_PA = set(UNIVERSAL.get("policy_areas", []))
UNI_AG = set(UNIVERSAL.get("agencies", []))

TODAY = datetime.now(timezone.utc).date()


def days_since(d):
    try:
        return (TODAY - date.fromisoformat(d[:10])).days
    except (TypeError, ValueError):
        return None


def days_until(d):
    n = days_since(d)
    return None if n is None else -n


def _match(rx_list, fields, weights, cap):
    """fields: list of (text_or_list, weight). Each keyword counts once, at its best field."""
    score, hits = 0, []
    for word, rx in rx_list:
        best = 0
        for value, w in zip(fields, weights):
            items = value if isinstance(value, list) else [value]
            if any(rx.search(x) for x in items if x):
                best = max(best, w)
        if best:
            score += best
            hits.append(word)
    return min(score, cap), hits


def relevance(slug, doc, ai=None):
    """doc: {'subjects': [..lower], 'title': lower, 'summary': lower, 'policy_area': str, 'agencies': set}"""
    fields = [doc.get("subjects", []), doc.get("title", ""), doc.get("summary", "")]
    ind, ind_hits = _match(IND_RX.get(slug, []), fields, (25, 20, 10), 70)
    uni, uni_hits = _match(UNI_RX, fields, (15, 12, 6), 45)
    score = ind + uni
    pa = doc.get("policy_area")
    if pa in IND_PA.get(slug, set()):
        score += 15
    elif pa in UNI_PA:
        score += 8
    ags = doc.get("agencies") or set()
    if ags & IND_AG.get(slug, set()):
        score += 20
    elif ags & UNI_AG:
        score += 15
    if ai:
        if ai.get("relevant_to_business") is False:
            return 0, []
        inds = set(ai.get("industries") or [])
        if slug in inds:
            score += 30
        elif "all_employers" in inds:
            score += 20
    return min(score, 100), (ind_hits + uni_hits)[:4]


def is_bipartisan(parties):
    if not parties:
        return False
    r, d = parties.get("R", 0), parties.get("D", 0) + parties.get("I", 0)
    total = sum(parties.values())
    return min(r, d) >= 1 and min(r, d) >= max(1, 0.15 * total)


BASE = {0: 5, 30: 30, 45: 45, 65: 65, 80: 80, 85: 55, 90: 90, 100: 75}


def bill_momentum(stage, cosponsors, bipartisan, days):
    m = BASE.get(stage, 5) + min(12, (cosponsors or 0) // 4) + (10 if bipartisan else 0)
    if days is not None:
        if days <= 14:
            m += 12
        elif days <= 45:
            m += 6
        elif days > 365 and stage < 100:
            m -= 15
        if stage == 100 and days > 365:
            m -= 40
    return max(0, min(100, m))


NOISE = ("airworthiness directive", "safety zone", "special local regulation", "drawbridge operation",
         "air plan approval", "approval and promulgation", "establishment of class", "amendment of class",
         "modification of class", "revocation of class", "anchorage", "regulated navigation area",
         "security zone", "standard instrument approach")


def is_noise_reg(title):
    t = (title or "").lower()
    return any(n in t for n in NOISE)


def reg_momentum(reg):
    close = days_until(reg.get("comments_close_on"))
    eff = days_until(reg.get("effective_on"))
    if reg.get("type") == "Proposed Rule":
        if close is not None and close >= 0:
            m = 75 + (10 if close <= 21 else 0)
        else:
            m = 35
    else:
        if eff is not None and eff >= -30:
            m = 80
        else:
            m = 45
    if reg.get("significant"):
        m += 10
    return min(100, m)


def priority(relevance_score, momentum_score, has_position):
    return round(0.55 * relevance_score + 0.45 * momentum_score + (15 if has_position else 0), 1)
