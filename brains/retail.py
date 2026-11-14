"""New / retail price for an item: one Tavily search on Japanese price-comparison and retailer sites,
then the model (or a regex fallback) pulls out the current new price. Costs 1 Tavily credit per query,
cached per process. Never raises; returns None when nothing reliable is found.

    await retail_price("Sony A7III") -> {"price_jpy": 198000, "kind": "lowest new price",
                                         "source": "kakaku.com", "url": "https://kakaku.com/..."}
"""
from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from . import llm

log = logging.getLogger("brains.retail")

DOMAINS = ["kakaku.com", "yodobashi.com", "biccamera.com", "amazon.co.jp", "store.sony.jp", "apple.com"]
_cache: dict[str, dict | None] = {}


class RetailAI(BaseModel):
    price_jpy: int | None = Field(description="Current price of the item bought NEW in Japan, in yen incl. tax. "
                                              "null if the snippets don't clearly show it")
    kind: str = Field(description='"lowest new price" (price comparison) or "retail price" (maker / store list price)')
    url: str | None = Field(description="URL of the result the price came from")


SYSTEM = """You read web search snippets and find the current NEW (unused) price in Japan of a specific product.
Use only prices that clearly belong to that exact model as a new item (kakaku.com 最安価格 / 価格.com lowest
price, or a maker / big retailer list price). Ignore used (中古) prices, accessories, bundles with lenses
unless the query asks for them, monthly payments and points. If unsure, return null."""

_KAKAKU = re.compile(r"最安価格[^¥￥\d]{0,12}[¥￥]\s*([\d,]{4,9})")
_YEN = re.compile(r"[¥￥]\s*([\d,]{4,9})")


def _regex_price(results: list[dict]) -> dict | None:
    for r in results:
        text = f"{r.get('title', '')} {r.get('content', '')}"
        m = _KAKAKU.search(text) or (_YEN.search(text) if "kakaku.com" in r.get("url", "") else None)
        if m:
            return {"price_jpy": int(m.group(1).replace(",", "")), "kind": "lowest new price", "url": r.get("url")}
    return None


async def retail_price(query: str) -> dict | None:
    key = query.strip().lower()
    if key in _cache:
        return _cache[key]
    out = None
    try:
        if not os.getenv("TAVILY_API_KEY") or os.getenv("BRAINS_RETAIL", "1") == "0":
            return None
        from tavily import AsyncTavilyClient

        res = await AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"]).search(
            query=f"{query} 新品 価格 最安値", include_domains=DOMAINS, max_results=6, search_depth="basic")
        results = [{"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:600]}
                   for r in res.get("results", [])]
        if not results:
            return None
        ai = await llm.structured(SYSTEM, json.dumps({"product": query, "results": results}, ensure_ascii=False),
                                  RetailAI)
        if ai and ai.price_jpy and 500 <= ai.price_jpy <= 5_000_000:
            out = {"price_jpy": ai.price_jpy, "kind": ai.kind, "url": ai.url}
        elif not llm.enabled():
            out = _regex_price(results)
        if out:
            out["source"] = urlparse(out.get("url") or "").netloc.removeprefix("www.") or None
    except Exception as e:
        log.warning("retail price lookup failed: %s", e)
        out = None
    finally:
        _cache[key] = out
    return out
