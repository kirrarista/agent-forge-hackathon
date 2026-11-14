"""Product photos for Telegram: download the first working photo of each top deal ourselves (marketplace
CDNs often refuse Telegram's fetcher) and send them as an album. Every failure is swallowed: a missing
photo must never break the deal message."""
from __future__ import annotations

import asyncio
import logging

import httpx
from telegram import InputMediaPhoto

from brains.photos import product_photos

log = logging.getLogger("bot.photos")

MEDALS = ["🥇", "🥈", "🥉", "🏷️", "🏷️"]
LABELS = {"mercari": "Mercari", "yahoo_auctions": "Yahoo Auctions", "jimoty": "Jimoty", "ebay": "eBay"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
MAX_BYTES = 9_500_000  # Telegram photo upload limit is 10 MB


async def _download(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        r = await client.get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if not ctype.startswith("image/") or "svg" in ctype or "gif" in ctype:
            return None
        if not 3_000 < len(r.content) < MAX_BYTES:  # tiny = icon/placeholder
            return None
        return r.content
    except Exception:
        return None


async def first_photo(client: httpx.AsyncClient, listing: dict) -> bytes | None:
    for url in product_photos(listing)[:3]:
        if data := await _download(client, url):
            return data
    return None


def caption(i: int, listing: dict) -> str:
    price = listing.get("price_jpy")
    price_txt = f"¥{price:,}" if isinstance(price, int) else "¥?"
    return f"{MEDALS[min(i, len(MEDALS) - 1)]} {price_txt} · {LABELS.get(listing.get('marketplace'), listing.get('marketplace'))}"


async def send_top_photos(bot, chat_id: int, top: list[dict]) -> None:
    """Album of the top deals' photos, captioned with medal, price and marketplace."""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers={"User-Agent": UA}) as client:
            photos = await asyncio.gather(*(first_photo(client, t.get("listing") or {}) for t in top[:5]))
        media = [InputMediaPhoto(data, caption=caption(i, t.get("listing") or {}))
                 for i, (t, data) in enumerate(zip(top, photos)) if data]
        if len(media) >= 2:
            await bot.send_media_group(chat_id, media)
        elif media:
            await bot.send_photo(chat_id, media[0].media, caption=media[0].caption)
    except Exception as e:
        log.warning("photo album failed: %s", e)


async def send_with_photo(bot, chat_id: int, listing: dict, text: str) -> bool:
    """Send `text` as the caption of the listing's photo. False if no photo (caller sends plain text)."""
    if len(text) > 1024:  # Telegram caption limit
        return False
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers={"User-Agent": UA}) as client:
            data = await first_photo(client, listing)
        if not data:
            return False
        await bot.send_photo(chat_id, data, caption=text)
        return True
    except Exception as e:
        log.warning("photo send failed: %s", e)
        return False
