"""Brains (Kiril): price history, scam checks, ranking, sell advice.

Shared-contract API:
    comps(sold)                      -> list[Comps]
    await evaluate(listings, comps, retail=None) -> list[Verdict]   (sold items: deal_score 0, "sold": True)
    await retail_price(query)        -> {"price_jpy", "kind", "source", "url"} | None   (new price in Japan)
    await rank(listings, verdicts)   -> Ranked
    await sell_advice(item, comps)   -> {"asking_price_jpy", "draft_listing", ...}

For Ivan: direct import works as-is. With USE_AGENTFIELD=1 run `python -m brains.node`: it registers
an AgentField node "brains" with reasoners comps / evaluate / rank / sell_advice, matching
app.call("brains.<fn>"), and routes its model calls through app.ai().
"""
from pathlib import Path

try:  # pick up ANTHROPIC_API_KEY / OPENAI_API_KEY / AI_MODEL from the repo .env
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from . import llm
from .comps import comps, pooled
from .evaluate import evaluate
from .rank import rank
from .retail import retail_price
from .sell import sell_advice

__all__ = ["comps", "evaluate", "rank", "sell_advice", "retail_price", "pooled", "attach"]


def attach(app) -> None:
    llm.set_app(app)
