"""Turn raw page text (Tavily extract, Tavily search snippet or Puppeteer innerText)
into the shared Listing / SoldItem shapes. Pure functions, no network, so they're testable
against saved text.

Anything we can't find is None, never missing (shared contract)."""
from __future__ import annotations

import os
import re
import unicodedata

from .sites import Site

USD_JPY = float(os.getenv("USD_JPY", "150"))

_YEN = re.compile(r"(?:¥|￥)\s*([0-9][0-9,]{2,})|([0-9][0-9,]{2,})\s*円")
_USD = re.compile(r"(?:US\s*)?\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
# Amounts preceded by these words are shipping, points, fees... not the item price.
_SKIP_CTX = ("送料", "ポイント", "クーポン", "手数料", "pt", "割引", "OFF", "off", "開始",
             "shipping", "Shipping", "postage", "import", "Import")
# Amounts preceded by these words are very likely the item price; prefer them.
_PRICE_CTX = ("価格", "現在", "落札", "即決", "販売価格", "Price", "price", "Sold", "sold")

CONDITIONS_JA = ("新品、未使用", "新品未使用", "未使用に近い", "目立った傷や汚れなし", "やや傷や汚れあり",
                 "傷や汚れあり", "全体的に状態が悪い", "ジャンク", "未使用", "中古", "新品")
_EN_CONDITION = re.compile(
    r"Condition\s*:?\s*(Brand New|New(?: other)?|Open box|Used|Pre-owned|For parts or not working|"
    r"Certified - Refurbished|Excellent - Refurbished|Very Good - Refurbished|Good - Refurbished|"
    r"Seller refurbished)", re.I)

_TITLE_SUFFIXES = re.compile(
    r"\s*(?:[|｜\-–—]\s*)?(?:by\s+)?(?:メルカリ.*|Mercari.*|ヤフオク!?.*|Yahoo!?オークション.*|"
    r"ジモティー.*|eBay.*)$")


def _to_int(s: str) -> int:
    return int(float(s.replace(",", "")))


def _ctx(text: str, start: int, n: int = 14) -> str:
    """Label text just before an amount, cut at the previous amount so labels don't bleed across
    ("開始 1円 落札 92,000円" → " 落札 " for the second amount)."""
    before = text[max(0, start - n):start]
    return re.split(r"[0-9円¥￥$]", before)[-1]


def find_price(text: str, currency: str = "JPY") -> int | None:
    """Best-guess item price in yen. Prefers amounts labelled as the price, skips shipping/points."""
    if not text:
        return None
    pat = _YEN if currency == "JPY" else _USD
    candidates: list[tuple[int, int]] = []  # (priority, amount_jpy)
    for m in pat.finditer(text):
        raw = next(g for g in m.groups() if g)
        try:
            amount = _to_int(raw)
        except ValueError:
            continue
        if currency == "USD":
            amount = round(float(raw.replace(",", "")) * USD_JPY)
        if amount < 300:
            continue
        before = _ctx(text, m.start())
        if any(w in before for w in _SKIP_CTX):
            continue
        prio = 0 if any(w in before for w in _PRICE_CTX) else 1
        candidates.append((prio, amount))
        if len(candidates) > 40:
            break
    if not candidates:
        return None
    best = min(c[0] for c in candidates)
    return next(a for p, a in candidates if p == best)


def find_condition(text: str) -> str | None:
    if not text:
        return None
    m = _EN_CONDITION.search(text)
    if m:
        return m.group(1)
    m = re.search(r"(?:商品の状態|状態)\s*[:：]?\s*\n?\s*(" + "|".join(map(re.escape, CONDITIONS_JA)) + ")", text)
    if m:
        return m.group(1)
    for c in CONDITIONS_JA:
        if c in text:
            return c
    return None


def find_seller(text: str) -> dict:
    seller = {"name": None, "rating": None, "review_count": None, "account_age": None}
    if not text:
        return seller
    for pat in (r"([0-9][0-9,]*)\s*件の評価", r"評価\s*[:：]?\s*([0-9][0-9,]*)",
                r"\(([0-9][0-9,]*)\)\s*[0-9.]+\s*%\s*[Pp]ositive",
                r"([0-9][0-9,]*)\s*(?:reviews|ratings|feedback)\b"):
        m = re.search(pat, text)
        if m:
            seller["review_count"] = _to_int(m.group(1))
            break
    m = (re.search(r"([0-9]{2,3}(?:\.[0-9]+)?)\s*%\s*(?:[Pp]ositive|良い評価)", text)
         or re.search(r"良い評価(?:の割合)?\s*[:：]?\s*([0-9]{2,3}(?:\.[0-9]+)?)\s*%", text))
    if m:
        seller["rating"] = round(min(float(m.group(1)), 100.0) / 20, 2)  # % positive → 0-5 scale
    else:
        m = re.search(r"(?:★|評価平均)\s*([1-5](?:\.[0-9])?)\b", text)
        if m:
            seller["rating"] = float(m.group(1))
    m = re.search(r"(?:登録日|利用開始|開始日|Joined|Member since)\s*[:：]?\s*"
                  r"([0-9]{4}\s*[年/.\-]\s*[0-9]{1,2}(?:\s*月)?|[A-Za-z]{3,9}\.?\s+[0-9]{4})", text)
    if m:
        seller["account_age"] = m.group(1).strip()
    m = re.search(r"(?:出品者|販売者|投稿者|Seller|Sold by)\s*[:：]?\s*\n?\s*([^\n|]{1,40})", text)
    if m:
        name = m.group(1).strip(" :：")
        if name and not re.fullmatch(r"[0-9,.%()\s]+", name) and "情報" not in name:
            seller["name"] = name
    return seller


def clean_title(title: str | None) -> str | None:
    if not title:
        return None
    t = _TITLE_SUFFIXES.sub("", title.strip())
    return t.strip() or title.strip()


def clean_text(text: str | None, limit: int = 3000) -> str | None:
    if not text:
        return None
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)          # markdown images
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)           # markdown links → text
    t = re.sub(r"[ \t　]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()[:limit] or None


def is_sold(text: str, site: Site) -> bool:
    return bool(text) and any(m in text for m in site.sold_markers)


def to_listing(*, site: Site, url: str, title: str | None, text: str | None,
               image_urls: list[str] | None = None) -> dict:
    item_id = site.item_id(url) or str(abs(hash(url)))
    body = text or ""
    return {
        "id": f"{site.key}:{item_id}",
        "marketplace": site.key,
        "url": url,
        "title": clean_title(title),
        "price_jpy": find_price(body, site.currency),
        "condition": find_condition(body),
        "seller": find_seller(body),
        "description": clean_text(body),
        "image_urls": [u for u in (image_urls or []) if isinstance(u, str) and u.startswith("http")][:20],
    }


def to_sold(*, site: Site, url: str, title: str | None, price_jpy: int | None) -> dict:
    return {"marketplace": site.key, "title": clean_title(title), "price_jpy": price_jpy, "url": url}


def sold_from_results_page(text: str, site: Site) -> list[dict]:
    """Parse a sold/completed-items results page in markdown (Tavily extract):
    each [title](item-url) followed by a price within the next few hundred characters."""
    out, seen = [], set()
    links = list(re.finditer(r"\[([^\]]{4,200})\]\((https?://[^)\s]+)\)", text or ""))
    for i, m in enumerate(links):
        title, url = m.group(1).strip(), m.group(2)
        if not site.item_id(url) or url in seen or title.startswith("!"):
            continue
        end = min(m.end() + 400, links[i + 1].start() if i + 1 < len(links) else len(text))
        price = find_price(text[m.end():end], site.currency)
        if price:
            seen.add(url)
            out.append(to_sold(site=site, url=url, title=title, price_jpy=price))
    return out


# ---------- relevance filter ----------

_ACCESSORY = ("ケース", "カバー", "バッテリー", "充電器", "チャージャー", "ストラップ", "フィルム", "保護ガラス",
              "キャップ", "アダプター", "アダプタ", "グリップ", "ケーブル", "互換", "対応",
              "case", "cover", "battery", "charger", "strap", "protector", "adapter", "cable",
              "compatible", "replacement", "skin")
_INCLUDED = ("付き", "付属", "セット", "一式", "本体", "ボディ", "body", "with", "w/", "bundle", "kit", "+")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("α", "a").replace("ⅲ", "iii").replace("ⅱ", "ii").replace("ⅳ", "iv")
    return re.sub(r"[\s\-_/・.]", "", s)


def model_tokens(query: str) -> list[str]:
    q = unicodedata.normalize("NFKC", query).lower()
    return [_norm(t) for t in re.split(r"\s+", q) if any(c.isdigit() for c in t) and not t.startswith("¥")]


def reject_reason(query: str, title: str | None) -> str | None:
    """None if the listing looks like the thing asked for, else a short reason."""
    if not title:
        return "no title"
    nt, nq = _norm(title), _norm(query)
    tokens = model_tokens(query)
    if tokens and not all(t in nt for t in tokens):
        return "different model"
    acc = [w for w in _ACCESSORY if _norm(w) in nt and _norm(w) not in nq]
    if acc and not any(_norm(w) in nt for w in _INCLUDED):
        return f"accessory ({acc[0]})"
    return None
