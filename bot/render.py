"""render(result) -> Telegram message text.

Turns {"comps", "ranked", "stats"} into the target message from IVAN.md.
Copes with null fields and Telegram's 4096-character limit (trims whole blocks,
never cuts mid-line).
"""
from __future__ import annotations

from schemas import MARKETPLACE_LABELS

MAX_LEN = 4096
MEDALS = ["🥇", "🥈", "🥉", "🏷️", "🏷️"]


def _yen(n) -> str:
    return f"¥{n:,}" if isinstance(n, int) else "¥?"


def _yenk(n) -> str:
    return f"¥{round(n / 1000)}k" if isinstance(n, (int, float)) else "¥?"


def _label(marketplace) -> str:
    return MARKETPLACE_LABELS.get(marketplace, str(marketplace))


def _comps_line(comps: list) -> str:
    # 0-1 sold items -> median_jpy is null (brains/README); skip those marketplaces.
    return " · ".join(
        f"{_label(c.get('marketplace'))} {_yenk(c.get('median_jpy'))}"
        for c in comps
        if isinstance(c.get("median_jpy"), int)
    )


def _pct_under(price, ref) -> str | None:
    if not (isinstance(price, int) and isinstance(ref, int) and ref):
        return None
    pct = round((1 - price / ref) * 100)
    return f"{pct}% under" if pct >= 0 else f"{-pct}% over"


def _used_median(comps: list) -> int | None:
    """Sold-count-weighted median across Japanese marketplaces (eBay excludes fees/shipping)."""
    jp = [c for c in comps if isinstance(c.get("median_jpy"), int) and c.get("marketplace") != "ebay"] or \
         [c for c in comps if isinstance(c.get("median_jpy"), int)]
    n = sum(c.get("n_sold") or 1 for c in jp)
    return round(sum(c["median_jpy"] * (c.get("n_sold") or 1) for c in jp) / n) if jp else None


def _price_check(comps: list, retail: dict | None) -> str | None:
    lines = []
    new = (retail or {}).get("price_jpy")
    if isinstance(new, int):
        src = f" ({retail['source']})" if retail.get("source") else ""
        lines.append(f"🆕 New: {_yen(new)}{src}")
    comps_line = _comps_line(comps)
    if comps_line:
        lines.append(f"♻️ Used, recently sold (median): {comps_line}")
    used = _used_median(comps)
    if isinstance(new, int) and used:
        lines.append(f"→ used sells for ~{round(used / new * 100)}% of the new price")
    return ("📊 Price check\n" + "\n".join(lines)) if lines else None


def _deal_block(i: int, item: dict) -> str:
    listing = item.get("listing") or {}
    verdict = item.get("verdict") or {}
    medal = MEDALS[min(i, len(MEDALS) - 1)]
    lines = [
        f"{medal} {_yen(listing.get('price_jpy'))}, {_label(listing.get('marketplace'))}"
        f" · deal score {verdict.get('deal_score', '?')}"
    ]
    vs = [f"{p} sold median ({_yenk(verdict.get('sold_median_jpy'))})"
          for p in [_pct_under(listing.get("price_jpy"), verdict.get("sold_median_jpy"))] if p]
    vs += [f"{p} new" for p in [_pct_under(listing.get("price_jpy"), verdict.get("new_price_jpy"))] if p]
    if vs:
        lines.append("💴 " + " · ".join(vs))
    if verdict.get("pros"):
        lines.append("✅ " + ", ".join(verdict["pros"]))
    if verdict.get("cons"):
        lines.append("⚠️ " + ", ".join(verdict["cons"]))
    offer = verdict.get("suggested_offer_jpy")
    suffix = " (draft message ready)" if item.get("draft_message") else ""
    lines.append(f"💬 Suggested offer: {_yen(offer)}{suffix}")
    if listing.get("url"):
        lines.append("🔗 " + listing["url"])
    return "\n".join(lines)


def _skip_line(item: dict) -> str:
    listing = item.get("listing") or {}
    reason = item.get("reason") or "flagged by scam check"
    return f"🚩 Skipped: {_yen(listing.get('price_jpy'))}, {_label(listing.get('marketplace'))}. {reason}"


def render(result: dict) -> str:
    stats = result.get("stats") or {}
    ranked = result.get("ranked") or {}
    comps = result.get("comps") or []
    top = ranked.get("top") or []
    skipped = ranked.get("skipped") or []

    header = f"🔎 {stats.get('query') or 'search'}"
    if stats.get("budget_jpy"):
        header += f", budget {_yenk(stats['budget_jpy'])}"

    blocks = [
        header,
        f"Searched {stats.get('marketplaces', 0)} marketplaces · {stats.get('listings', 0)} listings"
        f" · {stats.get('sold', 0)} sold prices · {stats.get('rejected', 0)} rejected",
    ]
    price_check = _price_check(comps, result.get("retail"))
    if price_check:
        blocks.append(price_check)
    blocks.extend(_deal_block(i, item) for i, item in enumerate(top))
    blocks.extend(_skip_line(item) for item in skipped)
    if not top:
        blocks.append("No deals found. Try a higher budget or a different item.")

    out = ""
    for block in blocks:
        candidate = f"{out}\n\n{block}" if out else block
        if len(candidate) > MAX_LEN - 30:
            out += "\n\n…(trimmed to fit Telegram)"
            break
        out = candidate
    return out


def render_sell(result: dict) -> str:
    lines = [f"💰 Suggested asking price: {_yen(result.get('asking_price_jpy'))}"]
    price_check = _price_check(result.get("comps") or [], result.get("retail"))
    if price_check:
        lines.append(price_check)
    if result.get("draft_listing"):
        lines.append("📝 Draft listing:\n\n" + result["draft_listing"])
    text = "\n\n".join(lines)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"