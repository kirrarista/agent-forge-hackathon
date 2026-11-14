"""Telegram handlers: /buy, /sell, and the Approve / Send offer / Skip buttons."""
from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import orchestrator
from bot import render

UNDER_RE = re.compile(r"\s+under\s+[¥￥]?\s*(\d+(?:[.,]\d+)?)\s*(k?)\s*$", re.IGNORECASE)

USAGE = "Usage: /buy Sony A7III under ¥90k  ·  /sell my RTX 3080"


def parse_buy(text: str) -> tuple[str, int | None]:
    """'Sony A7III under ¥90k' -> ('Sony A7III', 90000). No 'under' -> budget None.

    Accepts ¥90k, 90k, ¥90,000 and 90000 (also ￥ and decimal k like 90.5k).
    """
    m = UNDER_RE.search(text)
    if not m:
        return text.strip(), None
    amount = float(m.group(1).replace(",", ""))
    budget = int(amount * 1000) if m.group(2).lower() == "k" else int(amount)
    return text[: m.start()].strip(), budget


async def start(update, context):
    await update.message.reply_text(
        "Lowball — deals from Japanese marketplaces.\n\n"
        + USAGE
        + "\n\nNothing is sent to a seller until you tap Approve."
    )


async def buy(update, context):
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(USAGE)
        return
    query, budget = parse_buy(text)
    msg = await update.message.reply_text(f"🔎 Searching {query}…")
    try:
        result = await orchestrator.run_buy(query, budget)
    except Exception as exc:
        await msg.edit_text(f"⚠️ Search failed: {exc}")
        return
    run_id = orchestrator.new_run(result)
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Approve #1", callback_data=f"approve:{run_id}"),
            InlineKeyboardButton("💬 Send offer", callback_data=f"offer:{run_id}"),
            InlineKeyboardButton("❌ Skip", callback_data=f"skip:{run_id}"),
        ]]
    )
    await msg.edit_text(
        render.render(result), reply_markup=keyboard, disable_web_page_preview=True
    )


async def sell(update, context):
    item = " ".join(context.args).strip()
    if not item:
        await update.message.reply_text("Usage: /sell my RTX 3080")
        return
    msg = await update.message.reply_text(f"🔎 Pricing {item}…")
    try:
        result = await orchestrator.run_sell(item)
    except Exception as exc:
        await msg.edit_text(f"⚠️ Pricing failed: {exc}")
        return
    await msg.edit_text(render.render_sell(result), disable_web_page_preview=True)


async def on_button(update, context):
    query = update.callback_query
    await query.answer()
    action, _, run_id = (query.data or "").partition(":")
    run = orchestrator.get_run(run_id)
    if run is None:
        await query.message.reply_text("That search expired — run /buy again.")
        return
    top = (run["result"].get("ranked") or {}).get("top") or []
    first = top[0] if top else {}

    if action == "approve":
        if orchestrator.approve(run_id):
            offer = (first.get("verdict") or {}).get("suggested_offer_jpy")
            price = f" at ¥{offer:,}" if isinstance(offer, int) else ""
            await query.message.reply_text(
                f"✅ Approved #1{price}. Tap 💬 Send offer for the draft — "
                "nothing is sent to the seller automatically."
            )
        else:
            await query.message.reply_text("Already handled.")
    elif action == "offer":
        draft = first.get("draft_message")
        if draft:
            await query.message.reply_text(
                "💬 Draft for #1 — copy & send on the marketplace:\n\n" + draft
            )
        else:
            await query.message.reply_text("No draft available for this search.")
    elif action == "skip":
        orchestrator.skip(run_id)
        await query.message.reply_text("❌ Skipped.")