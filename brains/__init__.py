"""Brains (Kiril): price history, scam checks, ranking, sell advice.

Shared-contract API:
    comps(sold)                      -> list[Comps]
    await evaluate(listings, comps)  -> list[Verdict]
    await rank(listings, verdicts)   -> Ranked
    await sell_advice(item, comps)   -> {"asking_price_jpy", "draft_listing", ...}

For Ivan: direct import works as-is. With USE_AGENTFIELD=1 run `python -m brains.node`: it registers
an AgentField node "brains" with reasoners comps / evaluate / rank / sell_advice, matching
app.call("brains.<fn>"), and routes its model calls through app.ai().
"""
from . import llm
from .comps import comps, pooled
from .evaluate import evaluate
from .rank import rank
from .sell import sell_advice

__all__ = ["comps", "evaluate", "rank", "sell_advice", "pooled", "attach"]


def attach(app) -> None:
    llm.set_app(app)
