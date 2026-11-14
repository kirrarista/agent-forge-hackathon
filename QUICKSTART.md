# Lowball — Windows quickstart

PowerShell shown; cmd and Git Bash equivalents noted. All commands run from the repo root.

## 0. Prerequisites

- Python 3.11+ — check with `python --version`. If missing: `winget install Python.Python.3.12`
  (or install from python.org, tick "Add to PATH").
- A Telegram bot token from [@BotFather](https://t.me/BotFather) (`/newbot`).

## 1. One-time setup

```powershell
cd C:\Users\xproG\Desktop\agent-forge-hackathon
python -m venv .venv
.venv\Scripts\Activate.ps1          # cmd: .venv\Scripts\activate.bat · Git Bash: source .venv/Scripts/activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env         # cmd: copy .env.example .env
notepad .env                        # paste TELEGRAM_BOT_TOKEN
```

If PowerShell refuses to activate the venv:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again.

## 2. Run the bot (fake data — works right now, no other keys needed)

```powershell
python -m bot.app
```

In Telegram, message your bot:

- `/buy Sony A7III under ¥90k` → top 3 deals, 🚩 skipped scam line, three buttons
- `/sell my RTX 3080` → asking price + draft listing
- ✅ Approve / 💬 Send offer / ❌ Skip all work against the fake data

`USE_FAKE_DATA=1` is the default, so this runs before Julius's and Kiril's code is wired in.
Stop with Ctrl+C.

## 3. Go live (T+45, once scouts + brains are integrated)

```powershell
python -m pip install -r scouts/requirements.txt -r brains/requirements.txt
```

In `.env`: set `TAVILY_API_KEY`, `DAYTONA_API_KEY`, and the model pair
(`AI_MODEL=gpt-4o` + `OPENAI_API_KEY`, or `AI_MODEL=anthropic/claude-opus-5-5` + `ANTHROPIC_API_KEY`).
Then set `USE_FAKE_DATA=0` and run `python -m bot.app` again.

Sanity-check the pieces separately:

```powershell
python -m scouts check "Sony A7III"     # does Tavily find listings per site?
python -m brains                        # prints comps/verdicts/ranking on the fixture
```

## 4. AgentField mode (optional — the demo graph + approval pause)

```powershell
python -m pip install agentfield
af server                               # terminal 1
python -m brains.node                   # terminal 2 (Kiril's model calls route through the app)
python orchestrator.py                  # terminal 3 (serves the lowball reasoners)
python -m bot.app                       # terminal 4
```

Set `USE_AGENTFIELD=1` in `.env`. The `af` CLI installs via a bash script
(`curl -fsSL https://agentfield.ai/install.sh | bash`) — on Windows run it in Git Bash or WSL;
if it misbehaves, keep the AgentField terminals under WSL and the bot native.

## 5. Offline demo (T+70)

```powershell
python -m scouts save "Sony A7III" --budget 90000   # writes demo_data/
```

Then `USE_FAKE_DATA=0`, `DEMO_MODE=1`. Note: the orchestrator's demo path currently expects
`demo_data/buy.json`; aligning it with scouts' `listings.json`/`sold.json` output is a pending fix.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python` not found | Use `py -3.12` instead, or reinstall with "Add to PATH" |
| venv activation blocked | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `ModuleNotFoundError: scouts` / `brains` | Keep `USE_FAKE_DATA=1` until T+45, or run step 3's installs |
| Emoji/Japanese garbled in console | Use Windows Terminal, or `chcp 65001` first (Telegram itself renders fine) |
| Bot silent, no errors | Wrong token in `.env`, or another `python -m bot.app` instance is polling — kill it |
| `⚠️ Search failed: ... not available yet` | Live mode before scouts/brains landed — back to `USE_FAKE_DATA=1` |