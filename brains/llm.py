"""The one place brains talks to a model.

Order of preference:
  1. AgentField `app.ai(system=, user=, schema=)` once the orchestrator calls `brains.llm.set_app(app)`
     (or `brains.attach(app)`), so every model call shows up in the AgentField workflow graph.
  2. Anthropic API directly, if ANTHROPIC_API_KEY is set (fallback when AgentField isn't up).
  3. None → callers use their rules-only templates.

Set BRAINS_LLM=0 to force rules-only (fast, offline, deterministic)."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TypeVar

from pydantic import BaseModel

log = logging.getLogger("brains.llm")

T = TypeVar("T", bound=BaseModel)

_app = None
_sem = asyncio.Semaphore(int(os.getenv("BRAINS_LLM_PARALLEL", "8")))
TIMEOUT = float(os.getenv("BRAINS_LLM_TIMEOUT", "25"))
ANTHROPIC_MODEL = os.getenv("BRAINS_MODEL", "claude-opus-5-5")


def set_app(app) -> None:
    """Give brains the AgentField Agent so model calls go through app.ai()."""
    global _app
    _app = app


def enabled() -> bool:
    return os.getenv("BRAINS_LLM", "1") != "0" and (_app is not None or bool(os.getenv("ANTHROPIC_API_KEY")))


def _coerce(result, schema: type[T]) -> T | None:
    if isinstance(result, schema):
        return result
    if isinstance(result, BaseModel):
        return schema.model_validate(result.model_dump())
    if isinstance(result, dict):
        return schema.model_validate(result)
    if isinstance(result, str):
        text = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return schema.model_validate_json(text)
    # AgentField may wrap the reply in a response object
    for attr in ("parsed", "data", "text", "content"):
        if hasattr(result, attr):
            return _coerce(getattr(result, attr), schema)
    return None


async def _via_anthropic(system: str, user: str, schema: type[T]) -> T | None:
    import anthropic

    client = anthropic.AsyncAnthropic()
    resp = await client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=4000,
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    return resp.parsed_output


async def structured(system: str, user: str, schema: type[T]) -> T | None:
    """Ask the model for a `schema` instance. Never raises; returns None on any failure."""
    if not enabled():
        return None
    async with _sem:
        try:
            if _app is not None:
                raw = await asyncio.wait_for(_app.ai(system=system, user=user, schema=schema), TIMEOUT)
            else:
                raw = await asyncio.wait_for(_via_anthropic(system, user, schema), TIMEOUT)
            return _coerce(raw, schema)
        except Exception as e:  # model down / slow / bad JSON → caller falls back to templates
            log.warning("llm call failed (%s): %s", type(e).__name__, e)
            return None
