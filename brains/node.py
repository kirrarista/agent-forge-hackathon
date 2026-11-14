"""Brains as its own AgentField node, so the orchestrator's app.call("brains.<fn>") works and the
brains steps show up as a separate box in the workflow graph.

    af server                       # control plane (Ivan)
    python -m brains.node           # this node, id "brains", port BRAINS_PORT (default 8003)

Model: AgentField routes app.ai() through LiteLLM. With OPENROUTER_API_KEY set it uses
openrouter/$OPENROUTER_MODEL (default anthropic/claude-haiku-5.5); AI_MODEL overrides."""
from __future__ import annotations

import os

from agentfield import Agent, AIConfig

import brains  # loads .env before the AIConfig below reads it

app = Agent(
    node_id=os.getenv("BRAIN_NODE", "brains"),
    agentfield_server=os.getenv("AGENTFIELD_SERVER", "http://localhost:8080"),
    ai_config=AIConfig(model=os.getenv("AI_MODEL") or (
        "openrouter/" + os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-5.5")
        if os.getenv("OPENROUTER_API_KEY") else "gpt-4o")),
)
brains.attach(app)  # every evaluate / sell_advice model call goes through app.ai()


@app.reasoner(tags=["brains", "price-history"])
async def comps(sold: list[dict]) -> list[dict]:
    return brains.comps(sold)


@app.reasoner(tags=["brains", "scam-check"])
async def evaluate(listings: list[dict], comps: list[dict], retail: dict | None = None) -> list[dict]:
    return await brains.evaluate(listings, comps, retail)


@app.reasoner(tags=["brains", "ranking"])
async def rank(listings: list[dict], verdicts: list[dict]) -> dict:
    return await brains.rank(listings, verdicts)


@app.reasoner(tags=["brains", "sell"])
async def sell_advice(item: str, comps: list[dict], retail: dict | None = None,
                      listings: list[dict] | None = None) -> dict:
    return await brains.sell_advice(item, comps, retail, listings)


@app.reasoner(tags=["brains", "retail-price"])
async def retail_price(query: str) -> dict | None:
    return await brains.retail_price(query)


if __name__ == "__main__":
    app.serve(port=int(os.getenv("BRAINS_PORT", "8003")))
