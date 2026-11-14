# Ivan: Telegram and glue (Role A)

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

You own everything the user touches and the wiring between the other two.

- The Telegram bot: `/buy`, `/sell`, the summary message, the three buttons.
- The AgentField app: the orchestrator, the calls out to scouts and brains, the pause that waits
  for the Approve tap, and the workflow diagram we show during the demo.
- `schemas.py`, `fake_data.json`, `.env.example` (first 10 minutes).
- The demo: recording the backup video and running the rehearsal.

You don't write scraping code or scam/price logic. If a listing looks wrong, tell Julius. If a
score or offer looks wrong, tell Kiril.

## Your timeline

**T+0 to 10**
- [ ] Create the bot with BotFather, put the token in `.env`.
- [ ] Push `schemas.py`, `fake_data.json` (5 listings, 20 sold items, comps, verdicts, one
      `ranked` with 3 top and 1 skipped), `.env.example`. Tell the others when it's up.
- [ ] Run `af server` and get one example agent connected. Start a 15-minute timer on this.

**T+10 to 45** (against fake data)
- [ ] `/buy <item> under ¥<n>k` parses into `query` and `budget_jpy`.
- [ ] `run_buy` returns the fake `ranked`; the bot renders it in the message format below.
- [ ] The three buttons appear and each one triggers a callback.
- [ ] Orchestrator calls scouts and brains through `app.call()`, still returning fake data.

**T+45: checkpoint.** One real search goes from Telegram through Julius's scouts and Kiril's
brains and back to Telegram, on one marketplace. You do the wiring. If it doesn't work, cut
features until it does.

**T+45 to 70**
- [ ] Approve button resumes the paused run (`app.pause()`).
- [ ] `/sell <item>` calls `run_sell` and renders asking price plus draft listing.
- [ ] "Send offer" shows Kiril's draft message for that listing.

**T+70: stop adding features.**
- [ ] Record a full successful run on video.
- [ ] Add a `DEMO_MODE=1` switch that serves Julius's saved real results instead of live search.

**T+70 to 90**
- [ ] Polish the message. Choose the demo item with the team (check it returns good results).
- [ ] Rehearse the 3-minute demo twice, Telegram and the AgentField dashboard side by side.

## Target message

```
🔎 Sony A7III, budget ¥90k
Searched 4 marketplaces · 63 listings · 41 sold prices · 11 rejected

📊 Recent sold prices (average)
Mercari ¥98k · Yahoo Auctions ¥94k · eBay ¥112k (after fees and shipping)

🥇 ¥78,000, Mercari · deal score 86
✅ 2,400 shutter clicks, box included, seller has 312 reviews (4.9★)
⚠️ Small scratch on the screen
💬 Suggested offer: ¥72,000 (draft message ready)
🔗 link

🚩 Skipped: ¥39,800, Jimoty. Price is 60% under the average, new account, asks to talk on LINE.

[✅ Approve #1] [💬 Send offer] [❌ Skip]
```

The header counts come from `stats`, the 📊 line from `comps`, each 🥇 block from `ranked.top`,
each 🚩 line from `ranked.skipped`.

## Tasks for your coding agents

Run these in parallel. Each has a done-when line.

1. **Bot handlers.** `python-telegram-bot` (or aiogram), `/buy` and `/sell` parsing, inline
   keyboard with three buttons, callback handler.
   Done when: `/buy Sony A7III under ¥90k` gets a reply with three tappable buttons.
2. **Message template.** One function `render(result) -> str` that turns `{"comps", "ranked",
   "stats"}` into the target message. Handle `null` fields and Telegram's 4096-character limit.
   Done when: rendering `fake_data.json` matches the target message layout.
3. **AgentField skeleton.** Orchestrator agent with `run_buy` and `run_sell`, `app.call()` to
   scout and brain agents, `app.pause()` before any offer is sent.
   Done when: a run shows up as a graph in the AgentField dashboard.
4. **Approve/resume.** The Approve callback resumes the paused run by its run id.
   Done when: tapping Approve changes the run from paused to completed in the dashboard.

`app.ai()`, `app.pause()` and `app.call()` are the names from our planning notes. Have your agent
check the AgentField SDK docs for the exact signatures before writing against them.

## What to cut if things go wrong

- AgentField setup takes more than 15 minutes → run scouts and brains as plain Python async
  tasks (`asyncio.gather`) and connect AgentField at the end if there's time.
- Approve button not resuming by T+60 → the button just replies "✅ noted".
- Live search flaky at demo time → `DEMO_MODE=1` and the saved results.

## Who needs what

- **You need from Julius:** `scouts.search` and `scouts.sold_prices` working on one marketplace
  by T+45; saved real results in `demo_data/` at T+70.
- **You need from Kiril:** `brains.comps`, `brains.evaluate`, `brains.rank` by T+45;
  `brains.sell_advice` by about T+60.
- **They need from you:** `schemas.py` and `fake_data.json` by T+10, and a shout the moment the
  shared contract changes.
