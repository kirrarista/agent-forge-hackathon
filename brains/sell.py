"""Sell mode: asking price from Comps plus a draft listing."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from . import llm
from .comps import pooled


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


async def sell_advice(item: str, comps: list[dict]) -> dict:
    ref = pooled(comps)
    by_mp = {c["marketplace"]: c["median_jpy"] for c in comps or [] if c.get("median_jpy")}
    if ref:
        quick, patient = ref["median_jpy"], ref["p75_jpy"] or ref["median_jpy"]
        asking = _round500((quick + patient) / 2)
        best_mp = max(by_mp, key=by_mp.get) if by_mp else None
    else:
        quick = patient = asking = None
        best_mp = None

    draft = await llm.structured(SYSTEM, json.dumps({"item": item, "sold_prices": ref,
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
    }
