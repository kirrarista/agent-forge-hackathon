"""Per-marketplace configuration. Adding a marketplace = adding one Site here."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Site:
    key: str                       # value used in Listing.marketplace
    domains: tuple[str, ...]       # Tavily include_domains
    item_re: str                   # matches a single-listing URL; group(1) is the site's item id
    currency: str = "JPY"          # "JPY" or "USD"
    sold_markers: tuple[str, ...] = ()       # text that means the item is already sold/ended
    sold_search_url: str | None = None       # results page of sold/completed items, {q} = query
    query_suffix: str = ""                   # appended to the user's query for Tavily search
    extra_skip_ctx: tuple[str, ...] = field(default_factory=tuple)

    def item_id(self, url: str) -> str | None:
        m = re.search(self.item_re, url)
        return m.group(1) if m else None

    def sold_url(self, query: str) -> str | None:
        return self.sold_search_url.format(q=quote_plus(query)) if self.sold_search_url else None


SITES: dict[str, Site] = {
    "mercari": Site(
        key="mercari",
        domains=("jp.mercari.com",),
        item_re=r"jp\.mercari\.com/(?:en/)?(?:item|shops/product)/([A-Za-z0-9]+)",
        sold_markers=("売り切れました", "売り切れ", "SOLD OUT", "この商品は売り切れ"),
        sold_search_url="https://jp.mercari.com/search?keyword={q}&status=sold_out",
    ),
    "yahoo_auctions": Site(
        key="yahoo_auctions",
        domains=("auctions.yahoo.co.jp", "page.auctions.yahoo.co.jp"),
        item_re=r"auctions\.yahoo\.co\.jp/jp/auction/([a-z]?\d{6,})",
        sold_markers=("このオークションは終了しています", "オークションは終了", "落札者"),
        sold_search_url="https://auctions.yahoo.co.jp/closedsearch/closedsearch?p={q}&va={q}&b=1&n=100",
    ),
    "jimoty": Site(
        key="jimoty",
        domains=("jmty.jp",),
        item_re=r"jmty\.jp/[a-z_]+/sale-[a-z_]+/article-([a-z0-9]+)",
        sold_markers=("取引中", "受付終了", "掲載終了"),
        query_suffix=" 売ります",
    ),
    "ebay": Site(
        key="ebay",
        domains=("ebay.com",),
        item_re=r"ebay\.com/itm/(?:[^/?#]+/)?(\d{9,})",
        currency="USD",
        sold_markers=("This listing sold", "This listing was ended", "Sold on"),
        sold_search_url="https://www.ebay.com/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1&_ipg=120",
    ),
}

MARKETPLACES: list[str] = list(SITES)
