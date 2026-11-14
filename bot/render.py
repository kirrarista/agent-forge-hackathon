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
    return " · ".join(
        f"{_label(c.get('marketplace'))} {_yenk(c.get('median_jpy'))}" for c in comps
    )


def _deal_block(i: int, item: dict) -> str:
    listing = item.get("listing") or {}
    verdict = item.get("verdict") or {}
    medal = MEDALS[min(i, len(MEDALS) - 1)]
    lines = [
        f"{medal} {_yen(listing.get('price_jpy'))}, {_label(listing.get('marketplace'))}"
        f" · deal score {verdict.get('deal_score', '?')}"
    ]
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
    if comps:
        blocks.append("📊 Recent sold prices (median)\n" + _comps_line(comps))
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
    comps = result.get("comps") or []
    if comps:
        lines.append("📊 Recent sold prices (median): " + _comps_line(comps))
    if result.get("draft_listing"):
        lines.append("📝 Draft listing:\n\n" + result["draft_listing"])
    text = "\n\n".join(lines)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"