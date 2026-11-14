"""Price history: raw SoldItems → Comps per marketplace. Pure Python, no network."""
from __future__ import annotations

import re
import statistics

MARKETPLACE_ORDER = ["mercari", "yahoo_auctions", "jimoty", "ebay"]
JP_MARKETPLACES = ("mercari", "yahoo_auctions", "jimoty")

# Sold items that would drag the median around: broken units, parts, accessories-only.
JUNK_TITLE = re.compile(
    r"ジャンク|部品取り|部品|故障|難あり|for\s*parts|not\s*working|broken|as[\s-]*is|"
    r"箱のみ|空箱|box\s*only|ケースのみ|バッテリーのみ|充電器のみ|説明書のみ|manual\s*only",
    re.IGNORECASE,
)


def _price(item: dict) -> int | None:
    p = item.get("price_jpy")
    return int(p) if isinstance(p, (int, float)) and p > 0 else None


def trim(prices: list[int]) -> list[int]:
    """Drop prices far from the median (accessories at ¥2k, bundles at ¥400k)."""
    if len(prices) < 4:
        return sorted(prices)
    med = statistics.median(prices)
    kept = [p for p in prices if 0.4 * med <= p <= 2.5 * med]
    if len(kept) >= 4:  # second pass with Tukey fences on what's left
        q1, _, q3 = statistics.quantiles(kept, n=4, method="inclusive")
        iqr = q3 - q1
        kept = [p for p in kept if q1 - 1.5 * iqr <= p <= q3 + 1.5 * iqr]
    return sorted(kept)


def stats(marketplace: str, items: list[dict]) -> dict:
    usable = [(i, _price(i)) for i in items if _price(i) and not JUNK_TITLE.search(i.get("title") or "")]
    kept_prices = trim([p for _, p in usable])
    kept_set = set(kept_prices)
    sample = [i.get("url") for i, p in usable if p in kept_set and i.get("url")][:3]
    out = {"marketplace": marketplace, "median_jpy": None, "p25_jpy": None, "p75_jpy": None,
           "n_sold": len(kept_prices), "sample_urls": sample}
    if len(kept_prices) >= 2:
        q1, med, q3 = statistics.quantiles(kept_prices, n=4, method="inclusive")
        out.update(median_jpy=int(round(med)), p25_jpy=int(round(q1)), p75_jpy=int(round(q3)))
    return out


def comps(sold: list[dict]) -> list[dict]:
    """One Comps per marketplace that appears in `sold`, in a stable order."""
    by_mp: dict[str, list[dict]] = {}
    for item in sold or []:
        by_mp.setdefault(item.get("marketplace") or "unknown", []).append(item)
    order = [m for m in MARKETPLACE_ORDER if m in by_mp] + sorted(set(by_mp) - set(MARKETPLACE_ORDER))
    return [stats(m, by_mp[m]) for m in order]


def reference(comps_list: list[dict], marketplace: str | None) -> dict | None:
    """The Comps to judge a listing against: its own marketplace if it has numbers, else the
    Japanese marketplace with the most sold items, else anything with numbers (eBay last, since
    its prices exclude shipping and fees)."""
    usable = [c for c in comps_list or [] if c.get("median_jpy")]
    for c in usable:
        if c["marketplace"] == marketplace and marketplace != "ebay":  # buyer is in Japan: eBay vs JP prices
            return c
    jp = sorted((c for c in usable if c["marketplace"] in JP_MARKETPLACES), key=lambda c: -c["n_sold"])
    if jp:
        return jp[0]
    return max(usable, key=lambda c: c["n_sold"], default=None)


def pooled(comps_list: list[dict]) -> dict | None:
    """Weighted blend of the Japanese marketplaces (for sell mode and the 'overall' line)."""
    usable = [c for c in comps_list or [] if c.get("median_jpy") and c["marketplace"] in JP_MARKETPLACES]
    if not usable:
        usable = [c for c in comps_list or [] if c.get("median_jpy")]
    if not usable:
        return None
    n = sum(c["n_sold"] for c in usable) or 1
    w = lambda k: int(round(sum(c[k] * c["n_sold"] for c in usable) / n))  # noqa: E731
    return {"marketplace": "all", "median_jpy": w("median_jpy"), "p25_jpy": w("p25_jpy"),
            "p75_jpy": w("p75_jpy"), "n_sold": sum(c["n_sold"] for c in usable),
            "sample_urls": [u for c in usable for u in c["sample_urls"]][:3]}
