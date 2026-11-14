# scouts (Julius)

Live listings and sold prices from Mercari, Yahoo Auctions, Jimoty and eBay, in the shared
`Listing` / `SoldItem` shapes from `plan/`.

Pipeline per marketplace: **Tavily search** (limited to the site's domains) → keep only
single-listing URLs → drop accessories / other models by title → **Tavily extract** (full page,
images) → **Puppeteer in Daytona** if the extract has no price → parse into `Listing`.

## For Ivan (orchestrator)

```python
import scouts
listings = await scouts.search("Sony A7III", 90_000, ["mercari", "yahoo_auctions"])  # list[Listing]
sold     = await scouts.sold_prices("Sony A7III", ["mercari", "yahoo_auctions", "ebay"])  # list[SoldItem]
scouts.LAST_RUN  # {"marketplaces", "listings", "sold", "rejected", "rejections": [...], "errors": {...}}
```

- Running `search` and `sold_prices` in parallel is fine: `sold_prices` waits for an in-flight search of
  the same query, so sold-out items spotted while searching still count as sold prices.
- `LAST_RUN` gives the header line counts ("Searched 4 marketplaces · 63 listings · 41 sold prices · 11 rejected").
  `rejected` here is scout-side rejections (accessories, other models, over budget, already sold).
- One marketplace failing never raises; it shows up in `LAST_RUN["errors"]` and the rest still return.
- `USE_AGENTFIELD=1`: run `python -m scouts.node` (node id `scouts`, port `SCOUTS_PORT`=8002). Reasoners
  `search` / `sold_prices` match `app.call("scouts.<fn>")`; `last_run` returns the counts.
- `python -m scouts save "<item>" --budget <yen>` writes everything the offline demo needs to `demo_data/`:
  `buy.json` / `sell.json` (what orchestrator `DEMO_MODE=1` serves, built by running brains on the real
  results), plus raw `listings.json` / `sold.json` (what scouts' own `DEMO_MODE=1` and `python -m brains` read).

## For Kiril (brains)

- Any field not found is `null`. A `null` seller field means "not visible on the page", not "new account".
- `seller.rating` is on a 0-5 scale. Yahoo/eBay "% positive" is converted as `% / 20` (99% → 4.95).
- `seller.account_age` is a raw string when found ("Mar 2014", "2023年5月"), usually `null` on Mercari.
  (brains parses these. Note `schemas.py` / `fake_data.json` use int days, while brains reads numbers as months.)
- `title` is always a string (`""` if not found).
- `description` is the page text (up to 3,000 chars), so LINE / bank transfer / ジャンク checks can run on it.
- eBay prices are converted at `USD_JPY` (env, default 150), item price only, shipping not included.

## Setup

```
python3 -m venv .venv && .venv/bin/pip install -r scouts/requirements.txt
# .env at repo root: TAVILY_API_KEY=..., DAYTONA_API_KEY=...
```

## Commands

```
python -m scouts check  "Sony A7III"                    # T+0 check: does Tavily find listing pages per site?
python -m scouts search "Sony A7III" --budget 90000 -m mercari,yahoo_auctions
python -m scouts sold   "Sony A7III" -m yahoo_auctions,ebay
python -m scouts snapshot                               # build Daytona Chromium snapshot (once, at T+0)
python -m scouts fetch  "https://jp.mercari.com/item/m..."   # Puppeteer-in-Daytona on one page
python -m scouts save   "Sony A7III" --budget 90000     # T+70: write demo_data/ for offline demo
python -m pytest tests/scouts                           # offline tests, no keys needed
```

Settings (env): `SCOUTS_MAX_RESULTS` (20), `SCOUTS_SEARCH_DEPTH` (advanced), `SCOUTS_PUPPETEER`
(1; set 0 to skip Daytona), `DAYTONA_SNAPSHOT` (lowball-puppeteer), `DAYTONA_PARALLEL` (2), `USD_JPY` (150).
