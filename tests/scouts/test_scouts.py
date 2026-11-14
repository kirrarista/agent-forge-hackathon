"""Offline tests for scouts: parsers on saved-style page text, and the full pipeline against a fake Tavily."""
import asyncio

import pytest

from scouts import core, parse
from scouts.sites import SITES

MERCARI_PAGE = """
# SONY α7 III ILCE-7M3 ボディ シャッター回数2400回 元箱付き
¥78,000 (税込) 送料込み
## 商品の説明
購入後2年ほど使用しました。液晶に小さな傷があります。シリアル番号 1234567。
## 商品の情報
商品の状態
目立った傷や汚れなし
配送料の負担 送料込み(出品者負担)
## 出品者
カメラ好きの山田
312件の評価
"""

YAHOO_PAGE = """
Sony α7III ボディ 中古 ジャンク扱い
現在 52,000円（税込）
即決 60,000円
送料 1,200円
出品者 tokyo_seller 評価 8 良い評価の割合 87.5%
状態 やや傷や汚れあり
ご連絡はLINEでお願いします
"""

EBAY_PAGE = """
Sony Alpha a7 III Mirrorless Camera Body
US $749.99
Shipping: US $45.00
Condition: Used
Sold by camera_world (5,312) 99.8% positive feedback
Member since Mar 2014
"""

YAHOO_CLOSED = """
[Sony α7III ボディ 美品](https://auctions.yahoo.co.jp/jp/auction/x123456789)
開始 1円 落札 92,000円 入札 34
[SONY α7 III ILCE-7M3 レンズキット](https://auctions.yahoo.co.jp/jp/auction/k987654321)
落札 101,500円
[α7III 用 バッテリー NP-FZ100 互換](https://auctions.yahoo.co.jp/jp/auction/b111111111)
落札 2,300円
"""


def test_mercari_listing():
    url = "https://jp.mercari.com/item/m12345678901"
    lst = parse.to_listing(site=SITES["mercari"], url=url, title="SONY α7 III ボディ - メルカリ",
                           text=MERCARI_PAGE, image_urls=["https://static.mercdn.net/a.jpg", "data:x"])
    assert lst["id"] == "mercari:m12345678901"
    assert lst["title"] == "SONY α7 III ボディ"
    assert lst["price_jpy"] == 78000
    assert lst["condition"] == "目立った傷や汚れなし"
    assert lst["seller"]["review_count"] == 312
    assert lst["image_urls"] == ["https://static.mercdn.net/a.jpg"]
    assert set(lst) == {"id", "marketplace", "url", "title", "price_jpy", "condition", "seller",
                        "description", "image_urls"}
    assert set(lst["seller"]) == {"name", "rating", "review_count", "account_age"}


def test_yahoo_listing_prefers_current_price_and_keeps_scam_signals():
    lst = parse.to_listing(site=SITES["yahoo_auctions"], url="https://page.auctions.yahoo.co.jp/jp/auction/x123456789",
                           title="Sony α7III", text=YAHOO_PAGE)
    assert lst["id"] == "yahoo_auctions:x123456789"
    assert lst["price_jpy"] == 52000
    assert lst["seller"]["review_count"] == 8
    assert lst["seller"]["rating"] == 4.38
    assert "LINE" in lst["description"] and "ジャンク" in lst["description"]


def test_ebay_listing_converts_usd_and_skips_shipping():
    lst = parse.to_listing(site=SITES["ebay"], url="https://www.ebay.com/itm/Sony-a7-III/123456789012",
                           title="Sony Alpha a7 III | eBay", text=EBAY_PAGE)
    assert lst["id"] == "ebay:123456789012"
    assert lst["price_jpy"] == round(749.99 * parse.USD_JPY)
    assert lst["condition"] == "Used"
    assert lst["seller"]["review_count"] == 5312
    assert lst["seller"]["account_age"] == "Mar 2014"
    assert lst["title"] == "Sony Alpha a7 III"


def test_missing_fields_are_none():
    lst = parse.to_listing(site=SITES["jimoty"], url="https://jmty.jp/tokyo/sale-ele/article-abc12",
                           title=None, text="")
    assert lst["price_jpy"] is None and lst["condition"] is None and lst["description"] is None
    assert lst["seller"] == {"name": None, "rating": None, "review_count": None, "account_age": None}


def test_sold_results_page():
    sold = parse.sold_from_results_page(YAHOO_CLOSED, SITES["yahoo_auctions"])
    assert [s["price_jpy"] for s in sold] == [92000, 101500, 2300]
    assert all(set(s) == {"marketplace", "title", "price_jpy", "url"} for s in sold)


@pytest.mark.parametrize("title,reason", [
    ("SONY α7 III ILCE-7M3 ボディ", None),
    ("ソニー a7iii 本体 バッテリー2個付き", None),
    ("α7III 用 バッテリー NP-FZ100 互換", "accessory"),
    ("Sony α7 IV ボディ", "different model"),
])
def test_relevance(title, reason):
    got = parse.reject_reason("Sony A7III", title)
    assert (got is None) if reason is None else got.startswith(reason)


# ---------- pipeline with a fake Tavily ----------

class FakeTavily:
    def __init__(self):
        self.extract_calls = 0

    async def search(self, query, include_domains, **kw):
        if include_domains == ["jp.mercari.com"]:
            return {"results": [
                {"url": "https://jp.mercari.com/item/m11111111111", "title": "SONY α7 III ボディ - メルカリ", "content": ""},
                {"url": "https://jp.mercari.com/item/m11111111111", "title": "dup", "content": ""},
                {"url": "https://jp.mercari.com/item/m22222222222", "title": "α7III 互換バッテリー", "content": ""},
                {"url": "https://jp.mercari.com/item/m33333333333", "title": "Sony α7III 美品", "content": ""},
                {"url": "https://jp.mercari.com/item/m44444444444", "title": "a7III ボディ 高い", "content": ""},
                {"url": "https://jp.mercari.com/search?keyword=a7iii", "title": "search page", "content": ""},
            ]}
        return {"results": []}

    async def extract(self, urls, **kw):
        self.extract_calls += 1
        pages = {
            "https://jp.mercari.com/item/m11111111111": MERCARI_PAGE,
            "https://jp.mercari.com/item/m33333333333": "Sony α7III 美品\n¥95,000\n売り切れました",
            "https://jp.mercari.com/item/m44444444444": "a7III\n¥120,000",
            "https://jp.mercari.com/search?keyword=Sony+A7III&status=sold_out":
                "[Sony α7III ボディ](https://jp.mercari.com/item/m55555555555)\n¥99,000",
        }
        return {"results": [{"url": u, "raw_content": pages[u], "images": []} for u in urls if u in pages]}


@pytest.fixture
def fake(monkeypatch):
    f = FakeTavily()
    monkeypatch.setattr(core, "_client", f)
    monkeypatch.setattr(core, "_extract_cache", {})
    monkeypatch.setattr(core, "_sold_seen", {})
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    return f


def test_search_pipeline(fake):
    listings = asyncio.run(core.search("Sony A7III", 90_000, ["mercari", "jimoty"]))
    assert [l["id"] for l in listings] == ["mercari:m11111111111"]
    reasons = {r["reason"].split(" ")[0] for r in core.LAST_RUN["rejections"]}
    assert reasons == {"accessory", "already", "over"}
    assert core.LAST_RUN["marketplaces"] == 2 and core.LAST_RUN["listings"] == 1
    assert core.LAST_RUN["errors"] == {}

    sold = asyncio.run(core.sold_prices("Sony A7III", ["mercari"]))
    assert sorted(s["price_jpy"] for s in sold) == [95000, 99000]  # one seen while searching, one from sold page


def test_one_marketplace_failing_does_not_break_others(fake, monkeypatch):
    async def boom(site, query):
        if site.key == "jimoty":
            raise RuntimeError("blocked")
        return (await FakeTavily().search(query, list(site.domains)))["results"]
    monkeypatch.setattr(core, "_tavily_search", boom)
    listings = asyncio.run(core.search("Sony A7III", 90_000, ["mercari", "jimoty"]))
    assert len(listings) == 1
    assert "jimoty" in core.LAST_RUN["errors"]


def test_parallel_sold_prices_still_gets_sold_items_from_search(fake):
    """The orchestrator gathers search and sold_prices; sold-out items found by search must still count."""
    async def both():
        return await asyncio.gather(core.search("Sony A7III", 90_000, ["mercari"]),
                                    core.sold_prices("Sony A7III", ["mercari"]))
    listings, sold = asyncio.run(both())
    assert len(listings) == 1
    assert sorted(s["price_jpy"] for s in sold) == [95000, 99000]


def test_save_demo_writes_orchestrator_files(fake, tmp_path, monkeypatch):
    import json, sys, types
    stub = types.ModuleType("brains")
    stub.comps = lambda sold: [{"marketplace": "mercari", "median_jpy": 97000, "p25_jpy": 95000,
                                "p75_jpy": 99000, "n_sold": len(sold), "sample_urls": []}]

    async def evaluate(listings, comps):
        return [{"listing_id": l["id"], "risk": "ok", "deal_score": 80, "pros": [], "cons": [],
                 "suggested_offer_jpy": 72000} for l in listings]

    async def rank(listings, verdicts):
        return {"top": [{"listing": listings[0], "verdict": verdicts[0], "draft_message": "x"}], "skipped": []}

    async def sell_advice(item, comps):
        return {"asking_price_jpy": 97000, "draft_listing": f"【美品】{item}"}

    stub.evaluate, stub.rank, stub.sell_advice = evaluate, rank, sell_advice
    monkeypatch.setitem(sys.modules, "brains", stub)
    monkeypatch.setattr(core, "DEMO_DIR", tmp_path)

    meta = asyncio.run(core.save_demo("Sony A7III", 90_000, ["mercari"]))
    buy = json.loads((tmp_path / "buy.json").read_text())
    sell = json.loads((tmp_path / "sell.json").read_text())
    assert set(buy) == {"comps", "ranked", "stats"}
    assert set(buy["stats"]) == {"query", "budget_jpy", "marketplaces", "listings", "sold", "rejected"}
    assert buy["stats"]["listings"] == 1 and buy["stats"]["sold"] == 2 and buy["stats"]["rejected"] == 3
    assert {"asking_price_jpy", "draft_listing", "comps"} <= set(sell)
    assert (tmp_path / "listings.json").exists() and (tmp_path / "sold.json").exists()
    assert meta["top"] == 1


def test_node_registers_reasoners():
    pytest.importorskip("agentfield")
    from scouts import node
    assert callable(node.search) and callable(node.sold_prices)
    assert node.app.node_id == "scouts"


def test_demo_mode(tmp_path, monkeypatch):
    import json
    (tmp_path / "listings.json").write_text(json.dumps([
        {"marketplace": "mercari", "price_jpy": 80000}, {"marketplace": "ebay", "price_jpy": 70000},
        {"marketplace": "mercari", "price_jpy": 99000}]))
    (tmp_path / "sold.json").write_text(json.dumps([{"marketplace": "mercari", "price_jpy": 1}]))
    monkeypatch.setattr(core, "DEMO_DIR", tmp_path)
    monkeypatch.setenv("DEMO_MODE", "1")
    assert len(asyncio.run(core.search("x", 90_000, ["mercari"]))) == 1
    assert len(asyncio.run(core.sold_prices("x", ["mercari"]))) == 1
