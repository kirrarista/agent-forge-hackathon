import asyncio, json, os
from pathlib import Path

os.environ["BRAINS_LLM"] = "0"  # rules-only, offline

import brains
from brains import scam

DATA = json.loads((Path(__file__).parent / "fixture.json").read_text())


def run(coro):
    return asyncio.run(coro)


def test_comps_trims_and_handles_small():
    c = {x["marketplace"]: x for x in brains.comps(DATA["sold"])}
    assert c["mercari"]["n_sold"] == 8  # battery + junk dropped
    assert 90000 <= c["mercari"]["median_jpy"] <= 97000
    assert c["mercari"]["p25_jpy"] <= c["mercari"]["median_jpy"] <= c["mercari"]["p75_jpy"]
    assert c["jimoty"]["n_sold"] == 1 and c["jimoty"]["median_jpy"] is None
    assert brains.comps([]) == []


def test_verdicts():
    comps = brains.comps(DATA["sold"])
    verdicts = {v["listing_id"]: v for v in run(brains.evaluate(DATA["listings"], comps))}
    for bad in ("jimoty:j1", "jimoty:j2", "mercari:m4"):
        assert verdicts[bad]["risk"] == "scam", (bad, verdicts[bad])
        assert verdicts[bad]["deal_score"] == 0
    for ok in ("mercari:m1", "yahoo_auctions:y1", "mercari:m2", "ebay:e1"):
        assert verdicts[ok]["risk"] == "ok", (ok, verdicts[ok])
    # null seller is unknown, not new
    assert verdicts["mercari:m3"]["risk"] == "ok"
    assert any("not visible" in c for c in verdicts["mercari:m3"]["cons"])
    m1 = verdicts["mercari:m1"]
    assert m1["deal_score"] > verdicts["mercari:m2"]["deal_score"]
    assert m1["suggested_offer_jpy"] <= 78000 and m1["suggested_offer_jpy"] % 500 == 0


def test_rank():
    comps = brains.comps(DATA["sold"])
    verdicts = run(brains.evaluate(DATA["listings"], comps))
    ranked = run(brains.rank(DATA["listings"], verdicts))
    assert 3 <= len(ranked["top"]) <= 5
    assert ranked["top"][0]["listing"]["id"] == "mercari:m1"
    assert all(t["draft_message"] for t in ranked["top"])
    assert {s["listing"]["id"] for s in ranked["skipped"]} == {"jimoty:j1", "jimoty:j2", "mercari:m4"}
    reasons = {s["listing"]["id"]: s["reason"] for s in ranked["skipped"]}
    assert "LINE" in reasons["jimoty:j2"]
    assert "under the average" in reasons["jimoty:j1"]
    assert all(len(r) < 160 for r in reasons.values())


def test_sell():
    out = run(brains.sell_advice("Sony α7III", brains.comps(DATA["sold"])))
    assert out["asking_price_jpy"] and out["draft_listing"]
    assert out["quick_sale_jpy"] <= out["asking_price_jpy"] <= out["patient_jpy"]


def test_nulls_everywhere():
    l = {"id": "mercari:x", "marketplace": "mercari", "url": None, "title": None, "price_jpy": None,
         "condition": None, "seller": {"name": None, "rating": None, "review_count": None, "account_age": None},
         "description": None, "image_urls": []}
    v = run(brains.evaluate([l], []))[0]
    assert v["risk"] in ("ok", "sketchy") and v["suggested_offer_jpy"] is None
    run(brains.rank([l], [v]))


def test_account_age():
    assert scam.account_age_months("1ヶ月") == 1
    assert scam.account_age_months("Mar 2014") > 100
    assert scam.account_age_months("2023年5月") > 12
    assert scam.account_age_months(None) is None
    assert scam.account_age_months(48) == 48  # numeric = months (schemas.py)


def test_page_chrome_ignored():
    desc = ("* 本日終了 ★美品★シャッター数 1188回 現在 81,000 円\n"
            "* M2318【現状品】OLYMPUS OM-D E-M10 ボディ 現在 52,700 円\n"
            "## 故障時も安心！ PayPayほけん・あんしん修理\nLINEで送る\n"
            "★機能面 スレ傷、液晶傷。撮影＆動作確認済み。付属品は画像に掲載しているものがすべてです。")
    l = {"id": "yahoo_auctions:z", "marketplace": "yahoo_auctions", "title": "Sony a7III ボディ", "price_jpy": 85000,
         "condition": None, "seller": {"name": None, "rating": None, "review_count": None, "account_age": None},
         "description": desc, "image_urls": ["a"]}
    flags = scam.check(l, None, [l])
    assert not [f for f in flags if f["level"] in ("scam", "sketchy")], flags


def _listing(**kw):
    base = {"id": "mercari:s1", "marketplace": "mercari", "url": "u", "title": "Sony α7III", "price_jpy": 80000,
            "condition": None, "seller": {"name": "a", "rating": 4.9, "review_count": 100, "account_age": None},
            "description": "シャッター回数約2,400回。元箱・バッテリー・充電器付き。動作確認済みです。", "image_urls": []}
    return base | kw


def test_sold_items_never_recommended():
    comps = brains.comps(DATA["sold"])
    sold_ones = [
        _listing(id="mercari:s1", description=_listing()["description"] + "\nこの商品は売り切れました"),
        _listing(id="yahoo_auctions:s2", marketplace="yahoo_auctions", description="このオークションは終了しています 落札者：abc"),
        _listing(id="ebay:s3", marketplace="ebay", description="Sony A7III body. This listing sold on Nov 10."),
        _listing(id="mercari:s4", title="【SOLD】Sony α7III"),
    ]
    live = _listing(id="mercari:ok", description=_listing()["description"] + "\nおすすめ商品 売り切れ SOLD")  # chrome badges
    listings = sold_ones + [live]
    verdicts = run(brains.evaluate(listings, comps))
    ranked = run(brains.rank(listings, verdicts))
    ids = {t["listing"]["id"] for t in ranked["top"]} | {s["listing"]["id"] for s in ranked["skipped"]}
    assert ids == {"mercari:ok"}, ids


def test_retail_in_verdict_and_sell_cap():
    comps = brains.comps(DATA["sold"])
    v = run(brains.evaluate([_listing()], comps, retail={"price_jpy": 200000, "source": "kakaku.com"}))[0]
    assert v["new_price_jpy"] == 200000 and v["sold_median_jpy"]
    assert any("below the new price" in p for p in v["pros"])
    out = run(brains.sell_advice("x", comps, retail={"price_jpy": 90000}))
    assert out["asking_price_jpy"] <= 90000 * 0.9
