"""Rules + one model call per listing → Verdict. Rule-based risk always wins over the model."""
from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel, Field

from . import llm, scam
from .comps import reference

# Filled by evaluate(), read by rank() for skip reasons and draft messages (same process).
FLAGS: dict[str, list[dict]] = {}
REFS: dict[str, dict | None] = {}


class VerdictAI(BaseModel):
    pros: list[str] = Field(description="1-3 short concrete pros, max 70 chars each, English")
    cons: list[str] = Field(description="0-3 short concrete cons, max 70 chars each, English")
    deal_score: int = Field(description="0-100; 50 = priced at the sold median, 100 = far under median from a "
                                        "trusted seller in good condition")


SYSTEM = """You judge second-hand marketplace listings in Japan for a buyer who wants a good deal.
You get one listing (page text may be Japanese and include site navigation noise), recent sold prices
for the same item, and red flags our rules already found. Write pros and cons a buyer would care about:
condition details, accessories/box included, shutter count / usage, seller reputation, price vs sold
prices. Be concrete and short (max 70 chars each, English, no emoji). Do not repeat the price itself in
every line. A price under the sold median is a pro, never a con (too-cheap scam pricing is already
in the rule flags). Do not invent facts that are not in the text; if photos or details are unknown, leave it out. The rule flags are correct: include the
serious ones as cons. deal_score: 50 means priced at the sold median, 100 means well under the median
from a trusted seller in good condition; stay within 10 points of the rule_score you are given."""


def _yen(n) -> str:
    return f"¥{n:,}" if isinstance(n, int) else "?"


def rule_score(listing: dict, ref: dict | None, flags: list[dict], risk: str) -> int:
    if risk == "scam":
        return 0
    price, med = listing.get("price_jpy"), (ref or {}).get("median_jpy")
    score = 50.0
    if price and med:
        score = 50 + (1 - price / med) * 100  # 25% under median → 75, 50% under → 100
    for f in flags:
        score -= {"sketchy": 15, "info": 4, "deal": 0}.get(f["level"], 0)
    s = listing.get("seller") or {}
    if (s.get("review_count") or 0) >= 50 and (s.get("rating") or 0) >= 4.7:
        score += 5
    return int(max(1, min(100, round(score))))


def suggested_offer(listing: dict, ref: dict | None, flags: list[dict]) -> int | None:
    """Lowball: start at p25 of sold prices, never above asking, steeper with cons, ¥500 steps."""
    price = listing.get("price_jpy")
    if not price:
        return None
    p25 = (ref or {}).get("p25_jpy")
    offer = min(p25, price * 0.95) if p25 else price * 0.88
    if p25 and price <= p25:  # already cheap: just shave a little
        offer = price * 0.93
    cons = sum(1 for f in flags if f["level"] in ("sketchy", "deal")) + 0.5 * sum(1 for f in flags if f["level"] == "info")
    offer *= 1 - 0.04 * cons
    offer = max(offer, price * 0.7)  # below 70% of asking just gets you blocked
    return int(offer // 500 * 500) or 500


def template_pros_cons(listing: dict, ref: dict | None, flags: list[dict]) -> tuple[list[str], list[str]]:
    pros, cons = [], []
    price, med = listing.get("price_jpy"), (ref or {}).get("median_jpy")
    if price and med and price < med:
        pros.append(f"{round((1 - price / med) * 100)}% under the recent sold median ({_yen(med)})")
    elif price and med:
        cons.append(f"{round((price / med - 1) * 100)}% over the recent sold median ({_yen(med)})")
    s = listing.get("seller") or {}
    if (s.get("review_count") or 0) >= 20:
        rating = f" ({s['rating']:.1f}★)" if s.get("rating") else ""
        pros.append(f"seller has {s['review_count']} reviews{rating}")
    if listing.get("condition"):
        pros.append(f"condition: {listing['condition']}")
    for f in flags:
        cons.append(f["en"] + (", check carefully" if f["level"] == "deal" else ""))
    return pros[:3] or ["listed within budget"], cons[:3]


async def evaluate_one(listing: dict, comps_list: list[dict], all_listings: list[dict]) -> dict:
    ref = reference(comps_list, listing.get("marketplace"))
    flags = scam.check(listing, ref, all_listings)
    risk = scam.risk(flags)
    base = rule_score(listing, ref, flags, risk)
    pros, cons = template_pros_cons(listing, ref, flags)
    score = base

    if risk != "scam":  # don't spend model calls on listings we're skipping anyway
        payload = {
            "listing": {k: listing.get(k) for k in ("marketplace", "title", "price_jpy", "condition", "seller")}
            | {"description": scam.clean(listing.get("description"))[:2000]},
            "sold_prices": ref,
            "rule_flags": [f["en"] for f in flags],
            "rule_score": base,
        }
        ai = await llm.structured(SYSTEM, json.dumps(payload, ensure_ascii=False), VerdictAI)
        if ai:
            pros = [p.strip()[:90] for p in ai.pros if p.strip()][:3] or pros
            # rule flags always make it into cons, then the model's own
            rule_cons = [c for c in cons if any(c.startswith(f["en"]) for f in flags)]
            extra = [c.strip()[:90] for c in ai.cons if c.strip()]
            cons = (rule_cons + [c for c in extra if c not in rule_cons])[:3]
            score = max(1, min(100, max(base - 10, min(base + 10, ai.deal_score))))

    lid = listing.get("id")
    FLAGS[lid], REFS[lid] = flags, ref
    return {
        "listing_id": lid,
        "risk": risk,
        "deal_score": score,
        "pros": pros,
        "cons": cons,
        "suggested_offer_jpy": None if risk == "scam" else suggested_offer(listing, ref, flags),
    }


async def evaluate(listings: list[dict], comps: list[dict]) -> list[dict]:
    return list(await asyncio.gather(*(evaluate_one(l, comps, listings) for l in listings or [])))
