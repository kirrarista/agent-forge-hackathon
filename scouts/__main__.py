"""Scouts CLI.

  python -m scouts check  "Sony A7III"                      # the T+0 Tavily check: does it find listing pages?
  python -m scouts search "Sony A7III" --budget 90000 -m mercari,yahoo_auctions
  python -m scouts sold   "Sony A7III" -m yahoo_auctions,ebay
  python -m scouts save   "Sony A7III" --budget 90000       # writes demo_data/ for offline demos
  python -m scouts snapshot                                 # build the Daytona Chromium snapshot (once)
  python -m scouts fetch  <url>                             # test Puppeteer-in-Daytona on one page
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from . import core, daytona_fetch, parse
from .sites import MARKETPLACES, SITES


def _dump(x) -> None:
    print(json.dumps(x, ensure_ascii=False, indent=2))


async def _check(query: str, markets: list[str]) -> None:
    """For each marketplace: how many search hits are single-listing pages, and can extract read them?"""
    for key in markets:
        site = SITES[key]
        print(f"\n=== {key} ({', '.join(site.domains)}) ===")
        try:
            hits = await core._tavily_search(site, query)
        except Exception as e:
            print(f"  search failed: {e!r}")
            continue
        items = [h for h in hits if site.item_id(h.get("url", ""))]
        print(f"  search: {len(hits)} results, {len(items)} are listing pages")
        for h in hits[:6]:
            print(f"    {'LISTING' if site.item_id(h['url']) else 'other  '}  {h['url']}")
        if not items:
            print("  → no listing pages: this marketplace needs Puppeteer (python -m scouts fetch <search url>)")
            continue
        url = items[0]["url"]
        page = (await core._extract([url])).get(url)
        if not page:
            print(f"  extract: FAILED on {url} → Puppeteer fallback needed")
            continue
        lst = parse.to_listing(site=site, url=url, title=items[0].get("title"), text=page["text"],
                               image_urls=page["images"])
        print(f"  extract: {len(page['text'])} chars, {len(page['images'])} images")
        print(f"    title={lst['title']!r} price_jpy={lst['price_jpy']} condition={lst['condition']!r}")
        print(f"    seller={lst['seller']} sold={parse.is_sold(page['text'], site)}")
        verdict = "Tavily works" if lst["price_jpy"] else "price not in extract → Puppeteer fallback needed"
        print(f"  → {verdict}")


async def _main(a: argparse.Namespace) -> None:
    markets = a.markets.split(",") if a.markets else MARKETPLACES
    try:
        if a.cmd == "check":
            await _check(a.query, markets)
        elif a.cmd == "search":
            res = await core.search(a.query, a.budget, markets)
            _dump(res)
            print(f"\n{len(res)} listings · stats {json.dumps({k: v for k, v in core.LAST_RUN.items() if k != 'rejections'}, ensure_ascii=False)}", file=sys.stderr)
            for r in core.LAST_RUN["rejections"]:
                print(f"  rejected: {r['reason']:<24} {r['url']}", file=sys.stderr)
        elif a.cmd == "sold":
            res = await core.sold_prices(a.query, markets)
            _dump(res)
            print(f"\n{len(res)} sold items", file=sys.stderr)
        elif a.cmd == "save":
            _dump(await core.save_demo(a.query, a.budget, markets))
        elif a.cmd == "snapshot":
            await daytona_fetch.build_snapshot()
        elif a.cmd == "fetch":
            page = await daytona_fetch.fetch(a.query, a.item_pattern)
            page["text"] = (page.get("text") or "")[:1500]
            _dump(page)
    finally:
        await daytona_fetch.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m scouts", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["check", "search", "sold", "save", "snapshot", "fetch"])
    p.add_argument("query", nargs="?", default="", help="item to search for, or a URL for `fetch`")
    p.add_argument("--budget", type=int, default=None, help="max price in yen")
    p.add_argument("-m", "--markets", default=None, help=f"comma-separated, default all: {','.join(MARKETPLACES)}")
    p.add_argument("--item-pattern", default=None, help="fetch: regex of item links to collect")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(name)s: %(message)s")
    if a.cmd not in ("snapshot",) and not a.query:
        p.error("query is required")
    asyncio.run(_main(a))


if __name__ == "__main__":
    main()
