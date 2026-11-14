"""Ranking: top 3-5 non-scam listings with a draft seller message; scams go to skipped."""
from __future__ import annotations

from . import scam
from .evaluate import FLAGS, REFS

TOP_N = 5
MAX_SKIPPED = 5

_JA_CON = {"junk": "ジャンク扱いとのことですので", "vague": "詳細が分からない点もありますので",
           "seller_unknown": "", "no_photos": "写真で状態が確認できないため"}
_EN_CON = {"junk": "it's sold as-is", "vague": "the description is light on details",
           "no_photos": "I can't check the condition from photos"}


def draft_message(listing: dict, verdict: dict) -> str:
    """Polite Japanese offer with an English gloss underneath (for the demo)."""
    offer = verdict.get("suggested_offer_jpy")
    if not offer:
        return ""
    ref = REFS.get(listing.get("id")) or {}
    flags = FLAGS.get(listing.get("id"), [])
    con = next((f["rule"] for f in flags if f["rule"] in _EN_CON), None)
    med = ref.get("median_jpy")
    if con:
        ja_reason, en_reason = _JA_CON[con], _EN_CON[con]
    elif med:
        around = int(round((ref.get("p25_jpy") or med) / 1000) * 1000)
        ja_reason = f"最近の取引相場（¥{around:,}前後）を参考にさせていただき"
        en_reason = f"recent sales have been around ¥{around:,}"
    else:
        ja_reason, en_reason = "予算の都合上", "it's at the top of my budget"
    ja = (f"はじめまして。こちらの商品に興味があります。{ja_reason}、¥{offer:,}でお譲りいただくことは"
          f"可能でしょうか？ご検討いただけますと幸いです。よろしくお願いいたします。")
    en = f"(Hi, I'm interested in this item. Since {en_reason}, would you accept ¥{offer:,}? Thank you!)"
    return f"{ja}\n{en}"


async def rank(listings: list[dict], verdicts: list[dict]) -> dict:
    by_id = {l.get("id"): l for l in listings or []}
    pairs = [(by_id[v["listing_id"]], v) for v in verdicts or [] if v.get("listing_id") in by_id]

    # best score first; a sketchy listing needs a 10-point lead to beat a clean one
    good = sorted((p for p in pairs if p[1]["risk"] != "scam"),
                  key=lambda p: -(p[1]["deal_score"] - (10 if p[1]["risk"] == "sketchy" else 0)))
    top = [{"listing": l, "verdict": v, "draft_message": draft_message(l, v)} for l, v in good[:TOP_N]]

    bad = sorted((p for p in pairs if p[1]["risk"] == "scam"), key=lambda p: p[0].get("price_jpy") or 0)
    skipped = [{"listing": l, "verdict": v, "reason": scam.skip_reason(l, FLAGS.get(l.get("id"), []))}
               for l, v in bad[:MAX_SKIPPED]]
    return {"top": top, "skipped": skipped}
