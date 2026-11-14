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
