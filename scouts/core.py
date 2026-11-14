"""Scout pipeline: Tavily search → Tavily extract → Puppeteer in Daytona if that fails.

Public API (shared contract):
    await search(query, budget_jpy, marketplaces)  -> list[Listing]
    await sold_prices(query, marketplaces)         -> list[SoldItem]
Plus LAST_RUN, a dict of counts for the Telegram header line."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from . import daytona_fetch, parse
from .sites import MARKETPLACES, SITES, Site

log = logging.getLogger("scouts")

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo_data"
MAX_RESULTS = int(os.getenv("SCOUTS_MAX_RESULTS", "20"))
SEARCH_DEPTH = os.getenv("SCOUTS_SEARCH_DEPTH", "advanced")

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Counts from the most recent search()/sold_prices() call, for "Searched 4 marketplaces · 63 listings ·
# 41 sold prices · 11 rejected".
LAST_RUN: dict = {"marketplaces": 0, "listings": 0, "sold": 0, "rejected": 0, "rejections": [], "errors": {}}

_extract_cache: dict[str, dict] = {}
_client = None


def _tavily():
    global _client
    if _client is None:
        from tavily import AsyncTavilyClient
        _client = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    return _client


def _demo_mode() -> bool:
    return os.getenv("DEMO_MODE") == "1"


def _sites(marketplaces: list[str] | None) -> list[Site]:
    keys = marketplaces or MARKETPLACES
    unknown = [k for k in keys if k not in SITES]
    if unknown:
        log.warning("unknown marketplaces ignored: %s", unknown)
    return [SITES[k] for k in keys if k in SITES]


# ---------- fetching ----------

async def _tavily_search(site: Site, query: str) -> list[dict]:
    res = await _tavily().search(
        query=query + site.query_suffix,
        include_domains=list(site.domains),
        max_results=MAX_RESULTS,
        search_depth=SEARCH_DEPTH,
    )
    return res.get("results", [])


async def _extract(urls: list[str]) -> dict[str, dict]:
    """url → {"text", "images"} for every url Tavily could read. Cached per process."""
    todo = [u for u in dict.fromkeys(urls) if u not in _extract_cache]
    for i in range(0, len(todo), 20):  # Tavily extract takes up to 20 urls per call
        batch = todo[i:i + 20]
        try:
            res = await _tavily().extract(urls=batch, extract_depth="advanced",
                                          include_images=True, format="markdown")
        except Exception as e:  # one bad batch shouldn't sink the run
            log.warning("tavily extract failed: %s", e)
            continue
        for r in res.get("results", []):
            _extract_cache[r["url"]] = {"text": r.get("raw_content") or "", "images": r.get("images") or []}
    return {u: _extract_cache[u] for u in urls if u in _extract_cache}


async def _puppeteer(url: str, item_pattern: str | None = None) -> dict | None:
    if not daytona_fetch.enabled():
        return None
    try:
        page = await daytona_fetch.fetch(url, item_pattern)
    except Exception as e:
        log.warning("daytona fetch failed for %s: %s", url, e)
        return None
    if not page.get("ok"):
        log.warning("puppeteer failed for %s: %s", url, page.get("error"))
        return None
    return page


# ---------- listings ----------

async def _site_listings(site: Site, query: str, budget_jpy: int | None,
                         rejections: list, sold_out: list) -> list[dict]:
    hits = await _tavily_search(site, query)
    hits = [h for h in hits if site.item_id(h.get("url", ""))]
    seen, uniq = set(), []
    for h in hits:
        iid = site.item_id(h["url"])
        if iid not in seen:
            seen.add(iid)
            uniq.append(h)
    # Drop obvious non-matches by title before spending extract credits on them.
    candidates = []
    for h in uniq:
        why = parse.reject_reason(query, parse.clean_title(h.get("title")))
        if why:
            rejections.append({"url": h["url"], "reason": why})
        else:
            candidates.append(h)

    pages = await _extract([h["url"] for h in candidates])

    async def build(h: dict) -> dict:
        url, page = h["url"], pages.get(h["url"])
        text, images = (page or {}).get("text", ""), (page or {}).get("images", [])
        if not page or parse.find_price(text, site.currency) is None:
            pp = await _puppeteer(url)
            if pp:
                text, images = pp.get("text", ""), pp.get("images", [])
        if parse.find_price(text, site.currency) is None:
            text = "\n".join(filter(None, [text, h.get("content", "")]))  # last resort: search snippet
        listing = parse.to_listing(site=site, url=url, title=h.get("title"), text=text, image_urls=images)
        listing["_sold"] = parse.is_sold(text, site)
        return listing

    built = await asyncio.gather(*(build(h) for h in candidates))
    out = []
    for lst in built:
        sold = lst.pop("_sold")
        if sold:
            if lst["price_jpy"]:
                sold_out.append(parse.to_sold(site=site, url=lst["url"], title=lst["title"],
                                              price_jpy=lst["price_jpy"]))
            rejections.append({"url": lst["url"], "reason": "already sold"})
        elif lst["price_jpy"] is None:
            rejections.append({"url": lst["url"], "reason": "no price found"})
        elif budget_jpy and lst["price_jpy"] > budget_jpy:
            rejections.append({"url": lst["url"], "reason": f"over budget (¥{lst['price_jpy']:,})"})
        else:
            out.append(lst)
    return out


# Sold items spotted while searching for live listings, reused by sold_prices(): query key → url → SoldItem.
_sold_seen: dict[str, dict[str, dict]] = {}
# search() runs in flight per query, so a sold_prices() started at the same time (the orchestrator
# gathers both) can wait for it and still pick up those sold items.
_inflight: dict[str, asyncio.Task] = {}


def _qkey(query: str) -> str:
    return parse._norm(query)


async def search(query: str, budget_jpy: int | None = None,
                 marketplaces: list[str] | None = None) -> list[dict]:
    """Live listings for `query` under `budget_jpy` across `marketplaces` (default: all)."""
    sites = _sites(marketplaces)
    if _demo_mode():
        listings = _load_demo("listings", sites)
        if budget_jpy:
            listings = [l for l in listings if (l.get("price_jpy") or 0) <= budget_jpy]
        LAST_RUN.update(marketplaces=len(sites), listings=len(listings), rejected=0, rejections=[], errors={})
        return listings

    # Registered before the first await, so a sold_prices() gathered alongside always sees it.
    key = _qkey(query)
    task = asyncio.ensure_future(_search(query, budget_jpy, sites))
    _inflight[key] = task
    try:
        return await task
    finally:
        if _inflight.get(key) is task:
            del _inflight[key]


async def _search(query: str, budget_jpy: int | None, sites: list[Site]) -> list[dict]:
    rejections: list = []
    sold_out: list = []
    results = await asyncio.gather(
        *(_site_listings(s, query, budget_jpy, rejections, sold_out) for s in sites),
        return_exceptions=True)
    listings, errors = [], {}
    for site, r in zip(sites, results):
        if isinstance(r, Exception):
            log.warning("%s failed: %r", site.key, r)
            errors[site.key] = repr(r)[:200]
        else:
            listings.extend(r)
    seen = _sold_seen.setdefault(_qkey(query), {})
    for s in sold_out:
        seen[s["url"]] = s
    LAST_RUN.update(marketplaces=len(sites), listings=len(listings), rejected=len(rejections),
                    rejections=rejections, errors=errors)
    return listings


# ---------- sold prices ----------

async def _site_sold(site: Site, query: str) -> list[dict]:
    sold: list[dict] = []
    url = site.sold_url(query)
    if url:
        page = (await _extract([url])).get(url)
        found = parse.sold_from_results_page(page["text"], site) if page else []
        if len(found) < 5:
            pp = await _puppeteer(url, site.item_re)
            if pp:
                for it in pp.get("items", []):
                    price = parse.find_price(it.get("text", ""), site.currency)
                    if price:
                        found.append(parse.to_sold(site=site, url=it["url"], title=it.get("title"),
                                                   price_jpy=price))
        sold.extend(found)
    # Sold-out items search() came across (wait for a search of the same query still running).
    inflight = _inflight.get(_qkey(query))
    if inflight is not None:
        await asyncio.wait([inflight])  # its errors are search()'s to report
    sold.extend(s for s in _sold_seen.get(_qkey(query), {}).values() if s["marketplace"] == site.key)
    # Keep only the item asked for (drop accessories / other models), dedupe by url.
    out, seen = [], set()
    for s in sold:
        if s["url"] in seen or parse.reject_reason(query, s["title"]):
            continue
        seen.add(s["url"])
        out.append(s)
    return out


async def sold_prices(query: str, marketplaces: list[str] | None = None) -> list[dict]:
    """Recently sold items for `query` per marketplace. Brains turns these into Comps."""
    sites = _sites(marketplaces)
    if _demo_mode():
        sold = _load_demo("sold", sites)
        LAST_RUN["sold"] = len(sold)
        return sold
    results = await asyncio.gather(*(_site_sold(s, query) for s in sites), return_exceptions=True)
    sold = []
    for site, r in zip(sites, results):
        if isinstance(r, Exception):
            log.warning("%s sold prices failed: %r", site.key, r)
            LAST_RUN.setdefault("errors", {})[f"{site.key}_sold"] = repr(r)[:200]
        else:
            sold.extend(r)
    LAST_RUN["sold"] = len(sold)
    return sold


# ---------- demo data ----------

def _load_demo(kind: str, sites: list[Site]) -> list[dict]:
    path = DEMO_DIR / f"{kind}.json"
    if not path.exists():
        log.warning("DEMO_MODE=1 but %s is missing", path)
        return []
    keys = {s.key for s in sites}
    return [x for x in json.loads(path.read_text()) if x.get("marketplace") in keys]


def _write(name: str, data) -> None:
    (DEMO_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def save_demo(query: str, budget_jpy: int | None, marketplaces: list[str] | None = None,
                    sell_item: str | None = None) -> dict:
    """Run a real search and save everything the offline demo needs:
      demo_data/listings.json, sold.json   raw scout output (brains' `python -m brains` reads these)
      demo_data/buy.json, sell.json        BuyResult / SellResult that orchestrator DEMO_MODE=1 serves
    """
    import brains  # Kiril's; imported here so scouts works on its own without it

    listings, sold = await asyncio.gather(search(query, budget_jpy, marketplaces),
                                          sold_prices(query, marketplaces))
    stats_scouts = {k: v for k, v in LAST_RUN.items() if k != "rejections"}
    comps = brains.comps(sold)
    verdicts = await brains.evaluate(listings, comps)
    ranked = await brains.rank(listings, verdicts)
    advice = await brains.sell_advice(sell_item or query, comps)

    stats = {"query": query, "budget_jpy": budget_jpy,
             "marketplaces": stats_scouts["marketplaces"], "listings": len(listings), "sold": len(sold),
             "rejected": stats_scouts["rejected"] + len(ranked.get("skipped") or [])}
    DEMO_DIR.mkdir(exist_ok=True)
    _write("listings.json", listings)
    _write("sold.json", sold)
    _write("buy.json", {"comps": comps, "ranked": ranked, "stats": stats})
    _write("sell.json", {**advice, "comps": comps})
    meta = {**stats, "top": len(ranked.get("top") or []), "errors": stats_scouts.get("errors", {})}
    _write("meta.json", meta)
    return meta
