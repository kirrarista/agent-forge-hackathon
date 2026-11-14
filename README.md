# Lowball

A Telegram deal agent. Send `/buy Sony A7III under ¥90k` or `/sell my RTX 3080`. It searches
Mercari, Yahoo Auctions, Jimoty and eBay, compares listings with recent sold prices, flags scams,
and replies with the top deals, a lowball offer and a draft message to the seller. Nothing is
sent until you tap Approve.

| Folder | Owner | What it does |
|---|---|---|
| `bot/`, `orchestrator.py` | Ivan | Telegram bot, message layout, buttons, AgentField wiring |
| `scouts/` | Julius | Live listings and sold prices (Tavily → Daytona Puppeteer fallback) — [README](scouts/README.md) |
| `brains/` | Kiril | Price history, scam checks, ranking, offers, sell advice — [README](brains/README.md) |
| `schemas.py`, `fake_data.json` | shared | The data contract; per-person plans in [`plan/`](plan/) |

## Setup

```bash
git clone https://github.com/kirrarista/agent-forge-hackathon.git && cd agent-forge-hackathon
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r scouts/requirements.txt -r brains/requirements.txt
cp .env.example .env
```

Fill in `.env`. Which keys you need depends on what you run:

| Key | Needed for |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Always (create the bot with @BotFather) |
| `TAVILY_API_KEY` | Live search (`USE_FAKE_DATA=0`) |
| `DAYTONA_API_KEY` | Puppeteer fallback for pages Tavily can't read (optional) |
| `ANTHROPIC_API_KEY`, or `AI_MODEL` + its key (e.g. `gpt-4o` + `OPENAI_API_KEY`) | AI pros/cons and draft messages. Without one, brains runs rules-only. |

## Run it

Pick one mode. Every mode is `python -m bot.app`, then send `/buy Sony A7III under ¥90k` to your bot.

**1. Fake data** (default; only the bot token needed)

```bash
python -m bot.app
```

**2. Live** (real marketplaces)

```bash
USE_FAKE_DATA=0 python -m bot.app
```

Building the Daytona snapshot once lets the Puppeteer fallback work. It takes a few minutes:
`python -m scouts snapshot`.

**3. Demo / offline** (replays a saved real run; use this if a site blocks us on stage)

```bash
python -m scouts save "Sony A7III" --budget 90000     # writes demo_data/ (needs live keys once)
DEMO_MODE=1 USE_FAKE_DATA=0 python -m bot.app
```

**4. AgentField** (shows the agent workflow graph next to Telegram)

Install the `af` CLI once: `curl -sSf https://agentfield.ai/get | bash`, then check it with `af --version`
([quickstart](https://agentfield.ai/docs/learn/quickstart)). Then, in four terminals:

```bash
af server                                             # control plane + dashboard: http://localhost:8080
python -m scouts.node                                 # node "scouts", port 8002
python -m brains.node                                 # node "brains", port 8003
USE_AGENTFIELD=1 USE_FAKE_DATA=0 python -m bot.app
```

## Test pieces without Telegram

```bash
python -m scouts check  "Sony A7III" -m mercari,yahoo_auctions   # does Tavily find listing pages?
python -m scouts search "Sony A7III" --budget 90000 -m mercari     # real listings as JSON
python -m scouts sold   "Sony A7III" -m yahoo_auctions,ebay        # real sold prices
python -m brains                                                   # brains on demo_data/ or test fixture
python -m pytest tests/                                            # offline, no keys needed
```

## When something breaks

| Problem | Switch |
|---|---|
| Model slow or failing | `BRAINS_LLM=0` (rules-only verdicts) |
| Daytona down or slow | `SCOUTS_PUPPETEER=0` (Tavily only) |
| A marketplace blocks us | `DEMO_MODE=1` with saved `demo_data/` |
| AgentField won't start | `USE_AGENTFIELD=0` (plain async calls, same result) |
| One marketplace errors | Nothing; the others still return. See `scouts.LAST_RUN["errors"]`. |
