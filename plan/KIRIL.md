# Kiril: Brains (Role C)

## What we're building

Lowball is a Telegram deal agent. You send `/buy Sony A7III under ¥90k` or `/sell my RTX 3080`.
It searches Japanese marketplaces, compares prices against recent sold prices, flags scams, and
replies with the top 3-5 deals, a lowball offer for each, and a draft message to the seller.
Nothing is sent to a seller until you tap Approve.

```
Telegram: "/buy Sony A7III under ¥90k" or "/sell my RTX 3080"
   │
   ▼
Orchestrator agent (AgentField): reads the request, sends out agents        ← Ivan
   ├── Scout agents, one per marketplace (Mercari, Yahoo Auctions, Jimoty, eBay)   ← Julius
   │     Tavily search → Tavily extract → Puppeteer in Daytona if that fails
   ├── Price history agent: sold prices → median + 25th–75th percentile range      ← Kiril
   └── Scam check agent, run on each listing                                       ← Kiril
   │
   ▼
Ranking agent: top 3–5, pros/cons, lowball offer, draft seller message             ← Kiril
   │
   ▼
Telegram summary + buttons [✅ Approve] [💬 Send offer] [❌ Skip]                    ← Ivan
```

Sponsor tools: Tavily, Daytona, AgentField. We skip Nosana.

## Shared contract

This section is identical in IVAN.md, JULIUS.md and KIRIL.md. Change it only if all three agree,
then change it in all three.

Language: Python 3.11+, async everywhere. All prices are integers in yen.

### Data shapes

```
Listing:  { "id", "marketplace", "url", "title", "price_jpy", "condition",
            "seller": {"name", "rating", "review_count", "account_age"},
            "description", "image_urls": [] }

SoldItem: { "marketplace", "title", "price_jpy", "url" }

Comps:    { "marketplace", "median_jpy", "p25_jpy", "p75_jpy", "n_sold", "sample_urls": [] }

Verdict:  { "listing_id", "risk": "ok|sketchy|scam", "deal_score": 0-100,
            "pros": [], "cons": [], "suggested_offer_jpy" }

Ranked:   { "top":     [ {"listing": Listing, "verdict": Verdict, "draft_message": str} ],
            "skipped": [ {"listing": Listing, "verdict": Verdict, "reason": str} ] }
```

- `marketplace` is one of `"mercari"`, `"yahoo_auctions"`, `"jimoty"`, `"ebay"`.
- Any field a scout can't find is `null`, never missing. Brains must cope with `null`.
- `id` is `"<marketplace>:<site's own id or a hash of the url>"`.

### Functions at the seams

```python
# scouts/  (Julius)
async def search(query: str, budget_jpy: int | None, marketplaces: list[str]) -> list[Listing]
async def sold_prices(query: str, marketplaces: list[str]) -> list[SoldItem]

# brains/  (Kiril)
def comps(sold: list[SoldItem]) -> list[Comps]
async def evaluate(listings: list[Listing], comps: list[Comps]) -> list[Verdict]
async def rank(listings: list[Listing], verdicts: list[Verdict]) -> Ranked
async def sell_advice(item: str, comps: list[Comps]) -> dict   # {"asking_price_jpy", "draft_listing"}

# orchestrator.py + bot/  (Ivan)
async def run_buy(query: str, budget_jpy: int | None) -> dict   # {"comps", "ranked", "stats"}
async def run_sell(item: str) -> dict
```

### Repo layout

```
bot/              Ivan    Telegram handlers, message template, buttons
orchestrator.py   Ivan    AgentField app, run_buy / run_sell, pause/approve
scouts/           Julius  one module per marketplace + Daytona/Puppeteer fallback
brains/           Kiril   comps, scam rules, ranking, prompts
schemas.py        shared  the shapes above as TypedDicts or pydantic models
fake_data.json    shared  {"listings": [...], "sold": [...], "comps": [...], "verdicts": [...], "ranked": {...}}
.env.example      shared  TELEGRAM_BOT_TOKEN, TAVILY_API_KEY, DAYTONA_API_KEY, model key
```

Ivan pushes `schemas.py`, `fake_data.json` and `.env.example` by T+10. Until T+45 everyone codes
against `fake_data.json` and nobody waits on anybody. Each person stays inside their own folder,
so merges don't conflict.

## Your job

You own every judgment the agent makes: what a fair price is, which listings are scams, which
deals are best, what to offer and what to say to the seller.

- Price history: turn raw `SoldItem`s into `Comps` per marketplace.
- Scam and bad-listing checks on every `Listing`.
- Ranking: top 3-5, pros and cons, deal score, lowball offer, draft seller message.
- Sell mode: suggested asking price and a draft listing.

You don't fetch pages or touch Telegram. You take `Listing`s and `SoldItem`s in and return
`Comps`, `Verdict`s and `Ranked`. Everything you write can be built and tested against
`fake_data.json` with no network and no API keys except the model key.

## Scam and bad-listing rules

Quick rules first, then one AI call per listing for what rules can't see.

| Check | Rule | Result |
|---|---|---|
| Price vs sold average | under 40% of the average sold price | `scam` |
| Price vs sold average | 40-70% of the average | "a deal, check carefully": `sketchy` unless everything else is clean |
| Seller | new account, fewer than 5 reviews, or a low rating | `sketchy` |
| Off-platform | asks to pay or chat off the platform (LINE, bank transfer, "DM me") | `scam` |
| Listing quality | vague description, no serial number, stock photos only | `sketchy` |
| Hidden condition | "for parts" or "junk" (ジャンク) in the text | `sketchy`, and say so in `cons` |
| Reused photos | the same `image_urls` appear in other listings | `sketchy` |

Two or more `sketchy` hits on one listing → `scam`. A `null` seller field means "unknown", so
it adds a con ("seller history not visible") and doesn't count as a new account.

Every listing with `risk: "scam"` goes to `Ranked.skipped` with a one-line `reason` written for
the Telegram message, like: "Price is 60% under the average, new account, asks to talk on LINE."

## Your timeline

**T+0 to 10**
- [ ] Model key in `.env`. Agree the shared contract with Ivan and Julius.
- [ ] Add 2-3 deliberately bad listings to `fake_data.json` (one priced at 35% of average, one
      asking for LINE, one ジャンク) so the scam checks have something to catch.

**T+10 to 45** (against fake data)
- [ ] `brains/comps.py`: median, p25, p75, `n_sold`, up to 3 `sample_urls` per marketplace.
      Drop outliers first (accessories and broken units drag the median down).
- [ ] `brains/scam.py`: the rules table above as plain functions, each returning a flag and a
      reason.
- [ ] `brains/evaluate.py`: rules + one AI call per listing → `Verdict`. Run the calls
      concurrently.
- [ ] `brains/rank.py`: sort by `deal_score`, take top 3-5, write `draft_message`, fill
      `skipped`.

**T+45: checkpoint.** Julius's real listings go through your `comps`, `evaluate` and `rank` and
come out in Telegram.

**T+45 to 70**
- [ ] Tune on real data: real listings have `null`s, odd conditions and Japanese text. Fix what
      breaks.
- [ ] `sell_advice`: asking price from the same `Comps` (around the median for a quick sale, up
      to p75 for a patient one) plus a draft listing.
- [ ] Cross-marketplace comps: eBay prices after fees and shipping.

**T+70: stop adding features.**

**T+70 to 90**
- [ ] Read the output for the demo item line by line. Pros, cons and the draft message get read
      aloud in the demo, so they need to sound right.
- [ ] Rehearse with the team.

## Tasks for your coding agents

Run these in parallel. Each has a done-when line.

1. **Price math.** `comps(sold)` with outlier trimming. Pure Python, no AI.
   Done when: unit tests pass on `fake_data.json`, including a marketplace with 0 or 1 sold
   items (return `null` stats, `n_sold` as counted).
2. **Scam rules.** One small function per row of the rules table.
   Done when: the three bad fake listings come out as `scam` and the good ones as `ok`.
3. **Verdict prompt.** One AI call with a fixed output format: input is a `Listing` plus its
   marketplace's `Comps` plus the rule flags; output is exactly `pros`, `cons`, `deal_score`,
   `suggested_offer_jpy`. Rule-based `risk` wins over the model's opinion.
   Done when: 10 runs on the same listing all parse and scores stay within about 10 points.
4. **Offer and draft message.** Lowball offer: start around p25 of sold prices, never above the
   asking price, steeper when the listing has cons, rounded to ¥500. Draft message in polite
   Japanese (with an English gloss for the demo), mentioning one concrete reason for the price.
   Done when: the draft reads like something you'd send.
5. **Sell mode.** `sell_advice(item, comps)`.
   Done when: `/sell` on fake data returns an asking price and a listing draft.

Deal score, so everyone's agents agree on it: 100 means well under the sold median from a
trusted seller in good condition; 50 means priced at the median; anything `scam` scores 0.

`app.ai()` is the AgentField call for structured model output in our planning notes. Have your
agent check the AgentField SDK docs for the exact signature. Keep the model call behind one
function of your own (`brains/llm.py`), so it can be swapped for a direct model API call in one
place if AgentField isn't ready.

## What to cut if things go wrong

- AgentField not ready (Ivan's call at T+15) → call the model API directly from `brains/llm.py`.
- AI calls slow or flaky → rules-only verdicts, with a templated pros/cons and offer at p25.
- eBay comps missing → use Yahoo Auctions completed listings as the only benchmark.
- Sell mode not done by T+65 → drop it from the demo.

## Who needs what

- **You need from Julius:** real `Listing`s and `SoldItem`s by T+45, and a heads-up on which
  seller fields are reliably filled in per marketplace.
- **You need from Ivan:** `schemas.py` and `fake_data.json` by T+10; word by T+15 on whether
  AgentField is in or out.
- **They need from you:** `comps`, `evaluate`, `rank` importable by T+45; `sell_advice` by about
  T+60; `reason` and `draft_message` strings short enough for a Telegram message.
