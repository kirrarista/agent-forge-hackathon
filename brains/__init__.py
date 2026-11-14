"""Brains (Kiril): price history, scam checks, ranking, sell advice.

Shared-contract API:
    comps(sold)                      -> list[Comps]
    await evaluate(listings, comps)  -> list[Verdict]
    await rank(listings, verdicts)   -> Ranked
    await sell_advice(item, comps)   -> {"asking_price_jpy", "draft_listing", ...}

For Ivan: call `brains.attach(app)` once with the AgentField Agent so model calls go through
app.ai(); `brains.router` is an AgentRouter with the four functions as reasoners if you want them
as nodes in the workflow graph (`app.include_router(brains.router)` then `app.call("<node>.brains_rank", ...)`).
"""
from . import llm
from .comps import comps, pooled
from .evaluate import evaluate
from .rank import rank
from .sell import sell_advice

__all__ = ["comps", "evaluate", "rank", "sell_advice", "pooled", "attach", "router"]


def attach(app) -> None:
    llm.set_app(app)


try:
    from agentfield import AgentRouter

    router = AgentRouter(prefix="brains", tags=["brains"])

    @router.reasoner()
    async def price_history(sold: list[dict]) -> list[dict]:
        return comps(sold)

    @router.reasoner()
    async def scam_check(listings: list[dict], comps: list[dict]) -> list[dict]:
        return await evaluate(listings, comps)

    @router.reasoner()
    async def ranking(listings: list[dict], verdicts: list[dict]) -> dict:
        return await rank(listings, verdicts)

    @router.reasoner()
    async def sell(item: str, comps: list[dict]) -> dict:
        return await sell_advice(item, comps)
except Exception:  # agentfield not installed → plain functions still work
    router = None
