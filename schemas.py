"""Lowball shared contract — identical in IVAN.md / JULIUS.md / KIRIL.md.

Change only if all three agree, then update all three plan docs.
Python 3.11+, async everywhere. All prices are integers in yen.
Any field a scout can't find is null, never missing. Brains must cope with null.
"""
from __future__ import annotations

from typing import Literal, TypedDict

Marketplace = Literal["mercari", "yahoo_auctions", "jimoty", "ebay"]
MARKETPLACES: tuple[str, ...] = ("mercari", "yahoo_auctions", "jimoty", "ebay")

MARKETPLACE_LABELS: dict[str, str] = {
    "mercari": "Mercari",
    "yahoo_auctions": "Yahoo Auctions",
    "jimoty": "Jimoty",
    "ebay": "eBay",
}


class Seller(TypedDict):
    name: str | None
    rating: float | None        # 0..5
    review_count: int | None
    account_age: str | int | None  # raw string as scraped ("2023年5月", "Mar 2014"); numeric = months


class Listing(TypedDict):
    id: str                     # "<marketplace>:<site's own id or a hash of the url>"
    marketplace: Marketplace
    url: str
    title: str
    price_jpy: int
    condition: str | None
    seller: Seller
    description: str | None
    image_urls: list[str]


class SoldItem(TypedDict):
    marketplace: Marketplace
    title: str
    price_jpy: int
    url: str


class Comps(TypedDict):
    marketplace: Marketplace
    median_jpy: int
    p25_jpy: int
    p75_jpy: int
    n_sold: int
    sample_urls: list[str]


Risk = Literal["ok", "sketchy", "scam"]


class Verdict(TypedDict):
    listing_id: str
    risk: Risk
    deal_score: int             # 0..100
    pros: list[str]
    cons: list[str]
    suggested_offer_jpy: int | None


class RankedTop(TypedDict):
    listing: Listing
    verdict: Verdict
    draft_message: str


class RankedSkipped(TypedDict):
    listing: Listing
    verdict: Verdict
    reason: str


class Ranked(TypedDict):
    top: list[RankedTop]
    skipped: list[RankedSkipped]


class Stats(TypedDict):
    query: str
    budget_jpy: int | None
    marketplaces: int           # marketplaces searched
    listings: int               # listings found
    sold: int                   # sold prices found
    rejected: int               # len(ranked.skipped)


class BuyResult(TypedDict):
    comps: list[Comps]
    ranked: Ranked
    stats: Stats


class SellResult(TypedDict):
    asking_price_jpy: int
    draft_listing: str
    comps: list[Comps]