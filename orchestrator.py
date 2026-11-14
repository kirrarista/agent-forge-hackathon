"""Lowball orchestrator — Ivan's glue between Telegram, scouts (Julius) and brains (Kiril).

Data modes (env, read at import — bot/app.py loads .env first):
  USE_FAKE_DATA=1  -> fake_data.json (default; everyone builds against this until T+45)
  DEMO_MODE=1      -> demo_data/buy.json / demo_data/sell.json, saved BuyResult/SellResult
                      dicts (Julius's saved real results, T+70)
  both 0           -> live: scouts.search / scouts.sold_prices + brains.comps / evaluate /
                      rank / sell_advice

AgentField is optional (USE_AGENTFIELD=1). Without it, scouts/brains are plain async
imports — the plan's sanctioned fallback. With it, seam calls go through app.call()
so the workflow shows as a graph in the dashboard, and an approve_offer reasoner
demonstrates the app.pause() human-approval gate. Run `python -m brains.node`
alongside `af server` so brains' model calls go through the AgentField app.

SDK names verified against agentfield.ai docs + PyPI (Nov 2026):
  Agent(node_id=...), @app.reasoner(), await app.call("node.reasoner", **kwargs),
  await app.pause(approval_request_id=..., expires_in_hours=...) -> ApprovalResult.approved
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from schemas import MARKETPLACES

ROOT = Path(__file__).resolve().parent
USE_FAKE_DATA = os.getenv("USE_FAKE_DATA", "1") == "1"
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
USE_AGENTFIELD = os.getenv("USE_AGENTFIELD", "0") == "1"
SCOUT_NODE = os.getenv("SCOUT_NODE", "scouts")
BRAIN_NODE = os.getenv("BRAIN_NODE", "brains")


# ---------------------------------------------------------------- data sources

def _load_fake() -> dict:
    return json.loads((ROOT / "fake_data.json").read_text(encoding="utf-8"))


def _load_demo(name: str) -> dict:
    path = ROOT / "demo_data" / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — ask Julius for the saved real results (due T+70)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _stats(query: str, budget_jpy: int | None, listings: list, sold: list, ranked: dict) -> dict:
    return {
        "query": query,
        "budget_jpy": budget_jpy,
        "marketplaces": len(MARKETPLACES),
        "listings": len(listings),
        "sold": len(sold),
        "rejected": len(ranked.get("skipped") or []),
    }


# ---------------------------------------------------------------- AgentField (optional)

_app = None


def get_app():
    """The AgentField app, or None when disabled / not installed."""
    global _app
    if _app is None and USE_AGENTFIELD:
        from agentfield import Agent  # optional dependency

        _app = Agent(node_id="lowball")
        _register_reasoners(_app)
    return _app


def _register_reasoners(app) -> None:
    @app.reasoner(tags=["lowball"])
    async def buy(query: str, budget_jpy: int | None = None) -> dict:
        return await run_buy(query, budget_jpy)

    @app.reasoner(tags=["lowball"])
    async def sell(item: str) -> dict:
        return await run_sell(item)

    @app.reasoner(tags=["lowball", "approval"])
    async def approve_offer(run_id: str) -> dict:
        """Human-in-the-loop gate: pauses until a human approves in the dashboard.

        Demo: `af call lowball.approve_offer --in '{"run_id": "..."}'`, then approve
        in the AgentField dashboard. The Telegram Approve button uses the local
        registry below (plan's T+60 cut-line: the button must always work).
        """
        result = await app.pause(approval_request_id=f"lowball-{run_id}", expires_in_hours=1)
        approved = bool(getattr(result, "approved", False))
        if approved:
            approve(run_id)
        else:
            skip(run_id)
        return {"run_id": run_id, "approved": approved}


async def _call(node: str, reasoner: str, **kwargs):
    """One seam call: app.call() when AgentField is on, direct import otherwise."""
    app = get_app()
    if app is not None:
        return await app.call(f"{node}.{reasoner}", **kwargs)
    module_name = "scouts" if node == SCOUT_NODE else "brains"
    try:
        module = __import__(module_name)
    except ImportError as exc:
        raise RuntimeError(
            f"{module_name}/ not available yet — it lands at T+45. "
            "Keep USE_FAKE_DATA=1 until then."
        ) from exc
    fn = getattr(module, reasoner)
    if asyncio.iscoroutinefunction(fn):
        return await fn(**kwargs)
    return fn(**kwargs)  # brains.comps is sync per the contract


# ---------------------------------------------------------------- approval registry

_runs: dict[str, dict] = {}


def new_run(result: dict) -> str:
    run_id = uuid.uuid4().hex[:8]
    _runs[run_id] = {"status": "paused", "result": result}
    return run_id


def get_run(run_id: str) -> dict | None:
    return _runs.get(run_id)


def approve(run_id: str) -> bool:
    run = _runs.get(run_id)
    if not run or run["status"] != "paused":
        return False
    run["status"] = "approved"
    return True


def skip(run_id: str) -> bool:
    run = _runs.get(run_id)
    if not run or run["status"] != "paused":
        return False
    run["status"] = "skipped"
    return True


# ---------------------------------------------------------------- the seams

async def run_buy(query: str, budget_jpy: int | None = None) -> dict:
    """-> {"comps", "ranked", "stats"}"""
    if USE_FAKE_DATA:
        data = _load_fake()
        return {
            "comps": data["comps"],
            "ranked": data["ranked"],
            "stats": _stats(query, budget_jpy, data["listings"], data["sold"], data["ranked"]),
        }
    if DEMO_MODE:
        return _load_demo("buy")

    marketplaces = list(MARKETPLACES)
    # scouts/README: call search BEFORE sold_prices — sold-out items spotted while
    # searching are reused as sold prices, so these must not run in parallel.
    listings = await _call(
        SCOUT_NODE, "search", query=query, budget_jpy=budget_jpy, marketplaces=marketplaces
    )
    sold = await _call(SCOUT_NODE, "sold_prices", query=query, marketplaces=marketplaces)
    comps = await _call(BRAIN_NODE, "comps", sold=sold)
    verdicts = await _call(BRAIN_NODE, "evaluate", listings=listings, comps=comps)
    ranked = await _call(BRAIN_NODE, "rank", listings=listings, verdicts=verdicts)
    return {"comps": comps, "ranked": ranked, "stats": _stats(query, budget_jpy, listings, sold, ranked)}


async def run_sell(item: str) -> dict:
    """-> {"asking_price_jpy", "draft_listing", "comps"}"""
    if USE_FAKE_DATA:
        comps = _load_fake()["comps"]
        median = comps[0]["median_jpy"] if comps else 0
        return {
            "asking_price_jpy": int(median * 1.05),
            "draft_listing": (
                f"【美品】{item}\n\n動作確認済み。目立った傷なし。\n"
                "元箱・付属品付き。発送は24時間以内。\n"
                "ご質問はお気軽にどうぞ。"
            ),
            "comps": comps,
        }
    if DEMO_MODE:
        return _load_demo("sell")

    sold = await _call(SCOUT_NODE, "sold_prices", query=item, marketplaces=list(MARKETPLACES))
    comps = await _call(BRAIN_NODE, "comps", sold=sold)
    advice = await _call(BRAIN_NODE, "sell_advice", item=item, comps=comps)
    return {**advice, "comps": comps}


# ---------------------------------------------------------------- AgentField entrypoint

def serve() -> None:
    app = get_app()
    if app is None:
        raise SystemExit("Set USE_AGENTFIELD=1 and `pip install agentfield` to run this.")
    # README shows app.run(); the PyPI quickstart shows agent.serve(port=...). Support both.
    if hasattr(app, "serve"):
        app.serve(port=int(os.getenv("PORT", "8001")))
    else:
        app.run()


if __name__ == "__main__":
    serve()