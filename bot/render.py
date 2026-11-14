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
    if pct == 0:
        return "at"
    return f"{pct}% under" if pct > 0 else f"{-pct}% over"


def _used_median(comps: list) -> int | None:
    """Sold-count-weighted median across Japanese marketplaces (eBay excludes fees/shipping)."""
    jp = [c for c in comps if isinstance(c.get("median_jpy"), int) and c.get("marketplace") != "ebay"] or \
         [c for c in comps if isinstance(c.get("median_jpy"), int)]
    n = sum(c.get("n_sold") or 1 for c in jp)
    return round(sum(c["median_jpy"] * (c.get("n_sold") or 1) for c in jp) / n) if jp else None


def _price_check(comps: list, retail: dict | None, selling: bool = False) -> str | None:
    lines = []
    new = (retail or {}).get("price_jpy")
    if isinstance(new, int):
        src = f" ({retail['source']})" if retail.get("source") else ""
        lines.append(f"🆕 New: {_yen(new)}{src}")
    comps_line = _comps_line(comps)
    if comps_line:
        lines.append(f"♻️ Used, recently sold (median): {comps_line}")
    used = _used_median(comps)
    if selling:  # the sell message explains its own basis
        if isinstance(new, int) and used and used < new * 0.9:
            lines.append(f"→ used sells for ~{round(used / new * 100)}% of the new price")
    elif isinstance(new, int) and used:
        if used >= new * 0.9:
            lines.append("→ too little sold data (above the new price); deals judged against the new price")
        else:
            lines.append(f"→ used sells for ~{round(used / new * 100)}% of the new price")
    elif isinstance(new, int):
        lines.append("→ no sold data; deals judged against the new price")
    return ("📊 Price check\n" + "\n".join(lines)) if lines else None


def _deal_block(i: int, item: dict) -> str:
    listing = item.get("listing") or {}
    verdict = item.get("verdict") or {}
    medal = MEDALS[min(i, len(MEDALS) - 1)]
    lines = [
        f"{medal} {_yen(listing.get('price_jpy'))}, {_label(listing.get('marketplace'))}"
        f" · deal score {verdict.get('deal_score', '?')}"
    ]
    price = verdict.get("landed_price_jpy") or listing.get("price_jpy")
    ref_name = "fair used price" if verdict.get("fair_price_capped") else "sold median"
    vs = [f"{p} {ref_name} ({_yenk(verdict.get('sold_median_jpy'))})"
          for p in [_pct_under(price, verdict.get("sold_median_jpy"))] if p]
    vs += [f"{p} new" for p in [_pct_under(price, verdict.get("new_price_jpy"))] if p]
    if vs and price != listing.get("price_jpy"):
        vs[0] = f"{_yen(price)} delivered: " + vs[0]
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
    asking = result.get("asking_price_jpy")
    head = f"💰 Suggested asking price: {_yen(asking)}" if isinstance(asking, int) else \
        "💰 Couldn't find enough prices to suggest one"
    if isinstance(result.get("quick_sale_jpy"), int) and isinstance(result.get("patient_jpy"), int):
        head += f"\n⚡ Quick sale {_yen(result['quick_sale_jpy'])} · 🐢 Patient {_yen(result['patient_jpy'])}"
    if result.get("basis"):
        head += f"\n📐 Based on {result['basis']}"
    lines = [head]
    price_check = _price_check(result.get("comps") or [], result.get("retail"), selling=True)
    if price_check:
        lines.append(price_check)
    if result.get("draft_listing"):
        lines.append("📝 Draft listing:\n\n" + result["draft_listing"])
    text = "\n\n".join(lines)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"