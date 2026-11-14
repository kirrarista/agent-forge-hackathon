# brains (Kiril)

Price history, scam checks, ranking, lowball offers, sell advice. Plain dicts in the shared shapes from `plan/`.

## For Ivan (orchestrator)

```python
import brains
comps    = brains.comps(sold)                      # list[Comps], one per marketplace (sync, no AI)
verdicts = await brains.evaluate(listings, comps)  # list[Verdict], one AI call per non-scam listing
ranked   = await brains.rank(listings, verdicts)   # Ranked: top ≤5 with draft_message, skipped ≤5 with reason
advice   = await brains.sell_advice(item, comps)   # {"asking_price_jpy", "quick_sale_jpy", "patient_jpy",
                                                   #  "best_marketplace", "median_by_marketplace", "draft_listing"}
```

- `evaluate` must run before `rank` in the same process (rank reuses the rule flags for skip reasons / drafts).
- `USE_AGENTFIELD=1`: run `python -m brains.node` (node id `brains`, port `BRAINS_PORT`=8003). Reasoners
  `comps` / `evaluate` / `rank` / `sell_advice` match `app.call("brains.<fn>")`; model = `AI_MODEL` env via LiteLLM.
- No AgentField app attached → falls back to Anthropic API if `ANTHROPIC_API_KEY` is set → else rules-only
  templates. `BRAINS_LLM=0` forces rules-only (fast, deterministic; use if the model is slow on stage).
- `comps` with 0-1 sold items for a marketplace → `median_jpy`/`p25_jpy`/`p75_jpy` are `null`; skip those in the 📊 line.
- `draft_message` is Japanese + an English gloss in parentheses on the second line.

## For Julius (scouts)

Fields the scam rules use, most important first: `price_jpy`, `description` (LINE / bank transfer / ジャンク
regexes), `seller.review_count`, `seller.rating` (0-5), `seller.account_age` (raw string OK: "Mar 2014",
"2023年5月", "3ヶ月"), `image_urls` (reused-photo check), `title`. `null` = unknown, never treated as new account.

## Rules

| Check | Result |
|---|---|
| price < 40% of sold median | scam |
| price 40-70% of median | counts as sketchy only if something else is sketchy |
| seller: < 3 months old, < 5 reviews, rating < 4.0 | sketchy |
| LINE / WhatsApp / bank transfer / 直接取引 / email in text | scam |
| description too short (< 50 chars, Japanese chars count 2.5×) | sketchy |
| 写真はイメージです / stock photos | sketchy |
| ジャンク / 部品取り / 動作未確認 / for parts | sketchy + con |
| same image URL in another seller's listing | sketchy |

2+ sketchy → scam. eBay listings are judged against Japanese sold prices (eBay comps exclude shipping/fees).
Deal score: 50 = at median, +1 per 1% under, −15 per sketchy flag, −4 per info con, +5 trusted seller; model may move it ±10.
Offer: p25 of sold prices, never above asking, −4% per con, floor 70% of asking, rounded down to ¥500.

## Commands

```
python -m brains                      # run on demo_data/ (or the test fixture) and print everything
python -m brains listings.json sold.json
BRAINS_LLM=0 python -m brains         # rules only
python -m pytest tests/brains
```
