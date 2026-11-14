"""Scouts as its own AgentField node, so the orchestrator's app.call("scouts.<fn>") works and the
scout steps show up as their own box in the workflow graph.

    af server                       # control plane
    python -m scouts.node           # this node, id "scouts", port SCOUTS_PORT (default 8002)
    python -m brains.node           # Kiril's node, port 8003
    USE_AGENTFIELD=1 USE_FAKE_DATA=0 python -m bot.app
"""
from __future__ import annotations

import os

from agentfield import Agent

from . import core

app = Agent(
    node_id=os.getenv("SCOUT_NODE", "scouts"),
    agentfield_server=os.getenv("AGENTFIELD_SERVER", "http://localhost:8080"),
)


@app.reasoner(tags=["scouts", "tavily", "daytona"])
async def search(query: str, budget_jpy: int | None = None, marketplaces: list[str] | None = None) -> list[dict]:
    """Live listings: Tavily search → Tavily extract → Puppeteer in Daytona if that fails."""
    return await core.search(query, budget_jpy, marketplaces)


@app.reasoner(tags=["scouts", "price-history"])
async def sold_prices(query: str, marketplaces: list[str] | None = None) -> list[dict]:
    """Recently sold items per marketplace; brains turns them into Comps."""
    return await core.sold_prices(query, marketplaces)


@app.reasoner(tags=["scouts"])
async def last_run() -> dict:
    """Counts from the latest search (marketplaces, listings, sold, rejected, errors)."""
    return {k: v for k, v in core.LAST_RUN.items() if k != "rejections"}


if __name__ == "__main__":
    app.serve(port=int(os.getenv("SCOUTS_PORT", "8002")))
