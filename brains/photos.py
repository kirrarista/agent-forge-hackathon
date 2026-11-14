"""Pick real product photos out of a listing's image_urls (scouts' page extract also returns icons,
logos, banners and thumbnails). Used by the reused-photos rule and by the bot's photo album."""
from __future__ import annotations

import re

_JUNK = re.compile(r"\.svg|\.gif|logo|icon|banner|sprite|badge|avatar|profile|/common/|/templa/|blank|spacer|"
                   r"placeholder|emoji|/flag|btn|button|loading|pixel|1x1|na_170x170", re.I)
# CDN resizers that wrap the original (Yahoo auc-pctr) are duplicates of a full-size photo
_RESIZED = re.compile(r"auc-pctr\.c\.yimg\.jp|[?&](?:w|h)=\d{2,3}\b", re.I)
_PRODUCT_HOST = re.compile(r"static\.mercdn\.net/(?:item|c!)|auctions\.c\.yimg\.jp/images\.auctions\.yahoo\.co\.jp/image|"
                           r"i\.ebayimg\.com/images|jmty\.jp/.*(?:article|photo)|img\.jmty\.jp", re.I)


def product_photos(listing: dict) -> list[str]:
    """Product photo URLs, best first: ones containing the listing's own id, then known product-photo
    hosts, then anything else that doesn't look like site chrome. Page order is kept within each group."""
    urls = [u for u in dict.fromkeys(listing.get("image_urls") or [])
            if isinstance(u, str) and u.startswith("http") and not _JUNK.search(u) and not _RESIZED.search(u)]
    site_id = (listing.get("id") or "").split(":", 1)[-1]

    def rank(u: str) -> int:
        if site_id and len(site_id) > 5 and site_id in u:
            return 0
        return 1 if _PRODUCT_HOST.search(u) else 2

    return sorted(urls, key=rank)
