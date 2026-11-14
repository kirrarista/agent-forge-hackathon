"""Scam and bad-listing rules. One small function per row of the rules table in plan/KIRIL.md.

Each rule returns a list of Flag dicts: {"rule", "level", "en", "ja"}
  level "scam"    → listing is a scam on its own
  level "sketchy" → two or more of these make a scam
  level "deal"    → price 40-70% of average: sketchy only if something else is also sketchy
  level "info"    → a con worth showing, doesn't change risk (e.g. seller history not visible)
"""
from __future__ import annotations

import re
from datetime import date


def flag(rule: str, level: str, en: str, ja: str = "") -> dict:
    return {"rule": rule, "level": level, "en": en, "ja": ja}


# Lines of page chrome scouts' page text drags in: other listings' price tiles, insurance ads, nav.
_NOISE_LINE = re.compile(r"(?:現在|即決|送料)\s*[\d,]+\s*円|[\d,]+\s*円\s*$|PayPay|ほけん|あんしん修理|違反商品|"
                         r"フリマ|おすすめ|関連(?:商品|オークション)|閲覧履歴|この出品者の|ウォッチ|ログイン|"
                         r"Share|LINEで送る|LINEで共有|Similar items|Sponsored|You may also like", re.I)


def clean(text: str | None) -> str:
    return "\n".join(line for line in (text or "").splitlines() if not _NOISE_LINE.search(line))


def _text(listing: dict) -> str:
    return f"{listing.get('title') or ''}\n{clean(listing.get('description'))}"


# ---------- price vs sold average ----------

def price_vs_comps(listing: dict, ref: dict | None) -> list[dict]:
    price, med = listing.get("price_jpy"), (ref or {}).get("median_jpy")
    if price and not med:
        return [flag("no_comps", "info", "no recent sold prices to compare", "比較できる取引相場なし")]
    if not price or not med:
        return []
    ratio = price / med
    pct = round((1 - ratio) * 100)
    if ratio < 0.4:
        return [flag("price", "scam", f"price is {pct}% under the average", f"相場より{pct}%も安すぎる")]
    if ratio < 0.7:
        return [flag("price", "deal", f"price is {pct}% under the average", f"相場より{pct}%安い")]
    return []


# ---------- seller ----------

_YM = re.compile(r"(20\d\d|19\d\d)\s*(?:年\s*(\d{1,2})\s*月|[/-](\d{1,2}))?")
_EN_MONTH = re.compile(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d\d)", re.I)
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
_REL = re.compile(r"(\d+)\s*(day|week|month|year|日|週間|ヶ月|か月|カ月|年)", re.I)


def account_age_months(raw, today: date | None = None) -> float | None:
    """'Mar 2014', '2023年5月', '2 months', '3ヶ月' → months since joining. None if unparseable."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)  # schemas.py: numeric = months
    s, today = str(raw), today or date.today()
    if m := _EN_MONTH.search(s):
        y, mo = int(m.group(2)), _MONTHS.index(m.group(1).lower()[:3]) + 1
        return (today.year - y) * 12 + today.month - mo
    if m := _YM.search(s):
        y, mo = int(m.group(1)), int(m.group(2) or m.group(3) or 1)
        return (today.year - y) * 12 + today.month - mo
    if m := _REL.search(s):
        n, unit = int(m.group(1)), m.group(2).lower()
        per = {"day": 1 / 30, "日": 1 / 30, "week": 0.25, "週間": 0.25, "year": 12, "年": 12}
        return n * per.get(unit, 1)
    return None


def seller(listing: dict) -> list[dict]:
    s = listing.get("seller") or {}
    rc, rating, age = s.get("review_count"), s.get("rating"), account_age_months(s.get("account_age"))
    out = []
    problems = []
    if age is not None and age < 3:
        problems.append(("new account", "新規アカウント"))
    if rc is not None and rc < 5:
        problems.append((f"only {rc} review{'s' if rc != 1 else ''}", f"評価{rc}件のみ"))
    if rating is not None and rating < 4.0:
        problems.append((f"low rating ({rating:.1f}★)", f"評価が低い（{rating:.1f}）"))
    if problems:
        out.append(flag("seller", "sketchy", ", ".join(p[0] for p in problems), "、".join(p[1] for p in problems)))
    if rc is None and rating is None and age is None:
        out.append(flag("seller_unknown", "info", "seller history not visible", "出品者情報が見えない"))
    return out


# ---------- off-platform payment / contact ----------

_OFF_PLATFORM = [
    (re.compile(r"LINE\s*(?:ID|@|で(?:連絡|やり取り|やりとり|交換|お願い)|追加|交換)|ライン(?:ID|で|追加)|連絡は\s*(?:LINE|ライン)", re.I),
     "asks to talk on LINE", "LINEでの連絡を要求"),
    (re.compile(r"(?:add|contact|message|text|reach)\s+(?:me\s+)?(?:on|via|at)\s+(?:line|whatsapp|telegram|wechat|kakao)|whats\s*app|wechat", re.I),
     "asks to move the chat off-platform", "外部アプリへの誘導"),
    (re.compile(r"銀行振込|銀行振り込み|先振込|先振り込み|現金書留|bank\s*transfer|wire\s*transfer|western\s*union|"
                r"pay\s*(?:me\s*)?(?:outside|directly|via\s*paypal\s*friends)|paypal\s*f&f|gift\s*card|"
                r"直接取引|直取引|サイト外", re.I),
     "asks to pay off the platform", "サイト外での支払いを要求"),
    (re.compile(r"\bDM\s*me\b|\bdm\s*for\s*price\b|メールで(?:連絡|ご連絡)|メアド|@gmail\.com|@yahoo\.co\.jp", re.I),
     "asks to contact outside the site", "サイト外での連絡を要求"),
]


def off_platform(listing: dict) -> list[dict]:
    text = _text(listing)
    hits = [(en, ja) for rx, en, ja in _OFF_PLATFORM if rx.search(text)]
    if not hits:
        return []
    return [flag("off_platform", "scam", hits[0][0], hits[0][1])]


# ---------- listing quality ----------

_STOCK = re.compile(r"写真は(?:いずれも|全て|すべて)?イメージ|イメージ(?:画像|写真)です|画像はイメージ|stock\s*(?:photo|image)s?|photos?\s*(?:are|is)\s*for\s*reference", re.I)

def listing_quality(listing: dict) -> list[dict]:
    desc = (listing.get("description") or "").strip()
    out = []
    cjk = sum(1 for ch in desc if ord(ch) >= 0x3000)  # Japanese says more per character
    if listing.get("description") is not None and len(desc) + 1.5 * cjk < 50:
        out.append(flag("vague", "sketchy", "vague description", "説明が少ない"))
    if _STOCK.search(_text(listing)):
        out.append(flag("stock_photos", "sketchy", "uses stock photos, not the actual item", "写真がイメージ画像"))
    if not listing.get("image_urls"):
        out.append(flag("no_photos", "info", "no photos found", "写真が見当たらない"))
    return out


# ---------- hidden condition ----------

_JUNK = re.compile(r"ジャンク|部品取り|故障|動作不良|動作未確認|通電のみ|for\s*parts|not\s*working|untested|broken", re.I)
# common boilerplate on Yahoo Auctions / Mercari: worth a con, not a red flag
_AS_IS = re.compile(r"現状品|現状渡し|難あり|訳あり|as[\s-]is|ノークレーム", re.I)


def hidden_condition(listing: dict) -> list[dict]:
    text = _text(listing) + "\n" + (listing.get("condition") or "")
    if m := _JUNK.search(text):
        return [flag("junk", "sketchy", f"says \"{m.group(0)}\" (sold as-is / for parts)", f"「{m.group(0)}」と記載")]
    if m := _AS_IS.search(text):
        return [flag("as_is", "info", f"sold as-is (\"{m.group(0)}\"), no returns", f"「{m.group(0)}」")]
    return []


# ---------- reused photos ----------

def reused_photos(listing: dict, all_listings: list[dict]) -> list[dict]:
    mine = set(listing.get("image_urls") or [])
    if not mine:
        return []
    my_seller = (listing.get("seller") or {}).get("name")
    for other in all_listings:
        if other.get("id") == listing.get("id"):
            continue
        other_seller = (other.get("seller") or {}).get("name")
        if my_seller and other_seller and my_seller == other_seller:
            continue  # same seller reusing their own photos is fine
        if mine & set(other.get("image_urls") or []):
            return [flag("reused_photos", "sketchy", "same photos used in another listing", "他の出品と同じ写真")]
    return []


# ---------- combine ----------

def check(listing: dict, ref: dict | None, all_listings: list[dict]) -> list[dict]:
    flags = []
    for rule in (lambda l: price_vs_comps(l, ref), seller, off_platform, listing_quality, hidden_condition,
                 lambda l: reused_photos(l, all_listings)):
        try:
            flags += rule(listing)
        except Exception:  # a parsing surprise in one rule must not kill the run
            pass
    return flags


def risk(flags: list[dict]) -> str:
    levels = [f["level"] for f in flags]
    if "scam" in levels:
        return "scam"
    sketchy = levels.count("sketchy")
    if sketchy and "deal" in levels:
        sketchy += 1  # a too-good price only counts when something else is off too
    if sketchy >= 2:
        return "scam"
    return "sketchy" if sketchy == 1 else "ok"


def skip_reason(listing: dict, flags: list[dict]) -> str:
    """One line for the 🚩 Skipped row, e.g. 'Price is 60% under the average, new account, asks to talk on LINE.'"""
    ordered = sorted((f for f in flags if f["level"] != "info"),
                     key=lambda f: {"scam": 0, "deal": 1, "sketchy": 2}.get(f["level"], 3))
    parts = [f["en"] for f in ordered][:3] or ["too many red flags"]
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."
