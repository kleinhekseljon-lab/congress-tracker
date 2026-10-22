"""Turn bills and rules into scored items. Shared by the AI step and the site build."""
import glob
import os

import scoring
import stages
from common import SIMPLE_RESOLUTIONS, load_json


def load_enrichment():
    out = {}
    for path in glob.glob("data/enrich/*.json"):
        out[os.path.basename(path)[:-5]] = load_json(path, {})
    return out


def load_ai():
    out = {}
    for path in glob.glob("data/ai/*.json"):
        out[os.path.basename(path)[:-5]] = load_json(path, {})
    return out


def bill_items(bills, enrich, ai=None, positions=None):
    ai, positions = ai or {}, positions or {}
    for key, b in bills.items():
        if b.get("type") in SIMPLE_RESOLUTIONS:
            continue
        e = enrich.get(key) or {}
        if e.get("stage") is not None:
            stage, label = e["stage"], e.get("stage_label")
        else:
            st = stages.from_text(b.get("latest_action"))
            stage, label = st["stage"], st["label"]
        days = scoring.days_since(b.get("latest_action_date"))
        bip = scoring.is_bipartisan(e.get("parties"))
        mom = scoring.bill_momentum(stage, e.get("cosponsors", 0), bip, days)
        a = ai.get(key)
        doc = {
            "subjects": [s.lower() for s in e.get("subjects", [])],
            "title": (b.get("title") or "").lower(),
            "summary": (e.get("summary") or "").lower(),
            "policy_area": e.get("policy_area"),
        }
        yield {
            "kind": "bill", "key": key, "bill": b, "enrich": e, "ai": a, "doc": doc,
            "stage": stage, "stage_label": label, "days": days, "bipartisan": bip,
            "momentum": mom, "position": positions.get(key),
        }


def reg_items(regs, ai=None, positions=None):
    ai, positions = ai or {}, positions or {}
    for doc_no, r in regs.items():
        if scoring.is_noise_reg(r.get("title")):
            continue
        doc = {
            # A rule's abstract is its official description, so it counts as much as bill subjects
            "subjects": [(r.get("abstract") or "").lower()],
            "title": (r.get("title") or "").lower(),
            "summary": "",
            "policy_area": None,
            "agencies": set(r.get("agency_slugs") or []),
        }
        yield {
            "kind": "reg", "key": doc_no, "reg": r, "ai": ai.get(f"fr-{doc_no}"), "doc": doc,
            "momentum": scoring.reg_momentum(r), "position": positions.get(doc_no),
            "days": scoring.days_since(r.get("published")),
        }


def score_for(item, slug, use_ai=True):
    rel, hits = scoring.relevance(slug, item["doc"], item.get("ai") if use_ai else None)
    return rel, hits, scoring.priority(rel, item["momentum"], bool(item.get("position")))


def is_candidate(item, rel):
    if item.get("position"):
        return True
    if rel < 30:
        return False
    if item["kind"] == "bill":
        return item["momentum"] >= 35
    return item["momentum"] >= 45
