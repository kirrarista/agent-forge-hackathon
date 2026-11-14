"""Sell mode: asking price from Comps plus a draft listing."""
from __future__ import annotations

import json
import statistics

from pydantic import BaseModel, Field

from . import llm, scam
from .comps import pooled, trim


class ListingDraft(BaseModel):
    title_ja: str = Field(description="Mercari-style Japanese title, max 40 chars")
    description_ja: str = Field(description="Japanese listing description, 4-8 short lines, polite, honest")
    summary_en: str = Field(description="One-line English gloss of the listing")


SYSTEM = """You write second-hand listings for Japanese marketplaces (Mercari / Yahoo Auctions).
Given an item and recent sold prices, write a short honest Japanese listing: title (max 40 chars),
description with condition placeholders in 【】 the seller should fill in (e.g. 【傷の有無】),
what's included, smoke-free home / shipping lines typical on Mercari. No emoji."""


def _round500(x: float) -> int:
    return int(round(x / 500) * 500)


async def sell_advice(item: str, comps: list[dict], retail: dict | None = None,
                      listings: list[dict] | None = None) -> dict:
    """Asking price, best evidence first:
       1. recent sold prices (pooled Japanese marketplaces, >= 3 sold)
       2. what the same item is listed for right now (undercut the median ask a little so it sells)
       3. a rough share of the new price
    Never above 85% of the new price."""
    ref = pooled(comps)
    by_mp = {c["marketplace"]: c["median_jpy"] for c in comps or [] if c.get("median_jpy")}
    best_mp = max(by_mp, key=by_mp.get) if by_mp else None
    new_price = (retail or {}).get("price_jpy")
    asks = sorted(l["price_jpy"] for l in listings or []
                  if isinstance(l.get("price_jpy"), int) and l["price_jpy"] > 0 and not scam.is_sold(l))
    if len(asks) >= 4:  # drop accessories / bundles the same way comps does
        asks = trim(asks)
    if new_price:  # junk/accessory listings far below new, or bundles far above
        asks = [a for a in asks if new_price * 0.2 <= a <= new_price * 1.1] or asks

    quick = patient = None
    if ref and ref.get("n_sold", 0) >= 3:
        quick, patient = ref["median_jpy"], ref["p75_jpy"] or ref["median_jpy"]
        basis = f"{ref['n_sold']} recent sales (median ¥{ref['median_jpy']:,})"
    elif len(asks) >= 2:
        med_ask = statistics.median(asks)
        quick, patient = med_ask * 0.9, med_ask * 0.97  # asks are above what things sell for
        basis = f"{len(asks)} current listings (median ask ¥{int(med_ask):,}, lowest ¥{asks[0]:,})"
    elif ref:
        quick, patient = ref["median_jpy"], ref["p75_jpy"] or ref["median_jpy"]
        basis = f"only {ref['n_sold']} recent sale(s) (¥{ref['median_jpy']:,})"
    elif new_price:
        quick, patient = new_price * 0.6, new_price * 0.7
        basis = f"rough estimate from the new price (¥{new_price:,}); no used prices found"
    else:
        basis = "no price data found; check similar listings by hand"
    asking = _round500((quick + patient) / 2) if quick else None
    if new_price and asking and asking > new_price * 0.85:  # nobody buys used at (almost) the new price
        asking = _round500(new_price * 0.85)
        quick, patient = min(quick, asking * 0.95), min(patient, asking)

    draft = await llm.structured(SYSTEM, json.dumps({"item": item, "sold_prices": ref, "new_price_in_japan": retail, "price_basis": basis,
                                                     "asking_price_jpy": asking}, ensure_ascii=False), ListingDraft)
    if draft:
        text = f"{draft.title_ja}\n\n{draft.description_ja}\n\n({draft.summary_en})"
    else:
        text = (f"{item}\n\nご覧いただきありがとうございます。\n【状態】\n【付属品】\n"
                f"中古品のため、神経質な方はご遠慮ください。\n喫煙者・ペットなし。迅速に発送いたします。\n\n"
                f"({item}, used. Fill in condition and accessories. Non-smoking home, ships fast.)")
    return {
        "asking_price_jpy": asking,
        "quick_sale_jpy": _round500(quick) if quick else None,
        "patient_jpy": _round500(patient) if patient else None,
        "best_marketplace": best_mp,  # where it sells for the most (eBay excludes fees/shipping)
        "median_by_marketplace": by_mp,
        "draft_listing": text,
        "retail": retail,  # new price in Japan (brains.retail_price), or None
        "basis": basis,    # one line: what the asking price is based on
        "n_active_listings": len(asks),
    }
