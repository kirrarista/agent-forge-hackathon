# Julius: Scouts (Role B)

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

You own getting real data in: live listings and recent sold prices from each marketplace,
converted to `Listing` and `SoldItem`.

- Tavily search limited to marketplace domains, then Tavily extract on each listing link.
- Puppeteer inside a Daytona sandbox for pages Tavily can't read (JavaScript-built pages).
- Parsing each site's page into the shared shape, with `null` for anything you can't find.
- Saved real results for the offline demo.

You don't compute medians, score deals or judge scams. Hand over raw `SoldItem`s and `Listing`s;
Kiril does the rest. The fields Kiril's scam checks depend on most are `price_jpy`,
`seller.review_count`, `seller.rating`, `seller.account_age` and the full `description`, so
spend parsing effort there first.

## Do this before anything else

Run a Tavily search limited to `jp.mercari.com` and `auctions.yahoo.co.jp` for the demo item and
look at what comes back.

- Individual listing pages with prices → Tavily is your main path, Puppeteer is the fallback.
- Category pages, search pages or nothing → Puppeteer in Daytona is your main path. Tell Ivan
  and Kiril right away, because one marketplace by T+45 gets tighter.

Then run Tavily extract on one returned link and check whether price, seller and description are
in the text. This five-minute check decides the rest of your 90 minutes.

## Your timeline

**T+0 to 10**
- [ ] Tavily and Daytona keys in `.env`.
- [ ] Start building the Daytona snapshot with Chromium and Puppeteer installed. It takes a
      while, so start it now and let it run in the background.
- [ ] The Tavily check above.

**T+10 to 45**
- [ ] `scouts/mercari.py` (or whichever site the check showed works best): Tavily search with
      `include_domains` → Tavily extract → `Listing`.
- [ ] `scouts/__init__.py`: `search()` fans out to marketplace modules with `asyncio.gather`
      and merges results; one failing marketplace returns `[]` and doesn't break the others.
- [ ] `sold_prices()` for the same marketplace (Mercari sold-out items, or Yahoo Auctions
      completed listings).
- [ ] Filter out listings over `budget_jpy` and obvious non-matches (accessories, cases, lens
      only).

**T+45: checkpoint.** Real listings and sold prices from one marketplace reach Telegram through
Ivan's orchestrator.

**T+45 to 70**
- [ ] Second marketplace.
- [ ] eBay sold prices (convert to yen, note fees and shipping).
- [ ] Puppeteer fallback: when Tavily extract returns nothing usable, run the scraper script in
      a Daytona sandbox created from the snapshot.

**T+70: stop adding features.**
- [ ] Save real results for the demo item to `demo_data/listings.json` and
      `demo_data/sold.json`, so the demo can run from files if a site blocks us.

**T+70 to 90**
- [ ] Help choose the demo item: run two or three candidates and pick the one with the most
      listings, a clear price spread and at least one obviously sketchy listing.
- [ ] Rehearse with the team.

## Tasks for your coding agents

One agent per marketplace, one on Daytona. Each has a done-when line.

1. **Mercari scout.** Tavily search with `include_domains=["jp.mercari.com"]`, extract, parse to
   `Listing`. Done when: `python -m scouts.mercari "Sony A7III"` prints at least 5 valid
   `Listing`s with real prices.
2. **Yahoo Auctions scout.** Same, for `auctions.yahoo.co.jp`, plus the completed-listings
   search for `SoldItem`s. Done when: at least 5 listings and 10 sold items print.
3. **Jimoty scout.** Same, for `jmty.jp`. Lower priority; this is where the scam examples
   tend to show up, which makes the demo better.
4. **eBay sold prices.** Sold/completed search for the item, converted to yen. Done when: at
   least 10 `SoldItem`s print.
5. **Daytona snapshot + Puppeteer.** Snapshot with Chromium installed up front; a Node script
   `scrape.js <url>` that prints page JSON; a Python wrapper `scouts/daytona.py` with
   `async def fetch(url) -> dict` that creates a sandbox from the snapshot and runs the script
   with `sandbox.process.exec`. Done when: `fetch()` returns the price for one listing URL
   Tavily couldn't read.
6. **Normaliser and tests.** One `to_listing(raw, marketplace)` per site, tested against saved
   HTML/text so parsing doesn't depend on a live site. Done when: every output passes
   validation against `schemas.py`.

Tavily notes from our planning: search accepts a list of domains to include (up to 300), and
extract reads a full page from a link. Daytona: create sandboxes from a snapshot and run commands
with `sandbox.process.exec`. Have your agents check the Tavily and Daytona SDK docs for the exact
call names before writing against them.

## What to cut if things go wrong

- Puppeteer gets blocked or the snapshot isn't ready → Tavily only, plus the saved results.
- eBay sold prices are hard to get → use Yahoo Auctions' completed-listings search as the price
  benchmark.
- A marketplace returns junk by T+60 → drop it. Two solid marketplaces beat four flaky ones.
- Seller fields aren't in the page text → leave them `null` and tell Kiril, so the scam check
  doesn't treat "unknown" as "new account".

## Who needs what

- **You need from Ivan:** `schemas.py` and `fake_data.json` by T+10; the orchestrator calling
  `scouts.search` by T+45.
- **You need from Kiril:** word on which `Listing` fields the scam checks can't live without.
- **They need from you:** the Tavily-check result within the first 15 minutes; working
  `search` and `sold_prices` on one marketplace by T+45; `demo_data/` at T+70.
