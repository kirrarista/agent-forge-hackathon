"""Brains as its own AgentField node, so the orchestrator's app.call("brains.<fn>") works and the
brains steps show up as a separate box in the workflow graph.

    af server                       # control plane (Ivan)
    python -m brains.node           # this node, id "brains", port BRAINS_PORT (default 8003)

Model: AgentField routes app.ai() through LiteLLM. Set AI_MODEL (e.g. "gpt-4o" with OPENAI_API_KEY,
or "anthropic/claude-opus-5-5" with ANTHROPIC_API_KEY) in .env."""
from __future__ import annotations

import os

from agentfield import Agent, AIConfig

import brains

app = Agent(
    node_id=os.getenv("BRAIN_NODE", "brains"),
    agentfield_server=os.getenv("AGENTFIELD_SERVER", "http://localhost:8080"),
    ai_config=AIConfig(model=os.getenv("AI_MODEL", "gpt-4o")),
)
brains.attach(app)  # every evaluate / sell_advice model call goes through app.ai()


@app.reasoner(tags=["brains", "price-history"])
async def comps(sold: list[dict]) -> list[dict]:
    return brains.comps(sold)


@app.reasoner(tags=["brains", "scam-check"])
async def evaluate(listings: list[dict], comps: list[dict]) -> list[dict]:
    return await brains.evaluate(listings, comps)


@app.reasoner(tags=["brains", "ranking"])
async def rank(listings: list[dict], verdicts: list[dict]) -> dict:
    return await brains.rank(listings, verdicts)


@app.reasoner(tags=["brains", "sell"])
async def sell_advice(item: str, comps: list[dict]) -> dict:
    return await brains.sell_advice(item, comps)


if __name__ == "__main__":
    app.serve(port=int(os.getenv("BRAINS_PORT", "8003")))
