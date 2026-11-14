"""Bare-minimum observability for Lowball (Ivan). Stdlib only, no new deps.

One append-only JSONL file is the whole store. emit() never raises and is a
no-op when OBS_ENABLED=0. Importing this module has no side effects (no file,
no thread) until the first enabled emit.

Teammates can adopt later with one line, e.g. inside brains/llm.py structured():
    obs.emit("llm_call", model=..., latency_ms=..., tokens_in=..., tokens_out=...)
Unknown kinds land in the event feed; no schema change needed.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from pathlib import Path

ENABLED = os.getenv("OBS_ENABLED", "1") == "1"
LOG = Path(os.getenv("OBS_LOG", "./obs_data/events.jsonl")).resolve()
PORT = int(os.getenv("OBS_PORT", "8787"))

_run_id: ContextVar[str | None] = ContextVar("obs_run_id", default=None)


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def emit(kind: str, **data) -> None:
    """Append one event. Never raises; no-op when disabled."""
    if not ENABLED:
        return
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.time(), "kind": kind, "run_id": _run_id.get(), "data": data}
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def current_run_id() -> str | None:
    return _run_id.get()


@asynccontextmanager
async def stage(name: str, **fields):
    """Time one seam call; emits ok/error and re-raises on failure."""
    t0 = time.perf_counter()
    try:
        yield
    except Exception as exc:
        emit("stage", stage=name, duration_ms=_ms(t0), ok=False, error=repr(exc)[:200], **fields)
        raise
    else:
        emit("stage", stage=name, duration_ms=_ms(t0), ok=True, **fields)


@contextmanager
def run(op: str, **fields):
    """Run lifecycle: sets the run_id ContextVar, emits run_started / run_failed."""
    rid = uuid.uuid4().hex[:8]
    token = _run_id.set(rid)
    t0 = time.perf_counter()
    emit("run_started", op=op, **fields)
    try:
        yield rid
    except Exception as exc:
        emit("run_failed", op=op, duration_ms=_ms(t0), error=repr(exc)[:500], **fields)
        raise
    finally:
        _run_id.reset(token)


def read_events(limit: int = 500) -> list[dict]:
    """Last `limit` events, oldest first. [] when the log is missing/empty."""
    try:
        with open(LOG, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except (FileNotFoundError, OSError):
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------- read-side (dashboard + /stats)

def summarize(events: list[dict]) -> dict:
    """Materialize runs + counters from events. Shared by the dashboard and /stats."""
    runs: dict[str, dict] = {}
    order: list[str] = []
    c = {"runs": 0, "buy": 0, "sell": 0, "failed": 0, "scams": 0,
         "approvals": 0, "offers": 0, "skips": 0, "errors": 0, "avg_ms": 0}
    for e in events:
        kind, data, rid = e.get("kind"), e.get("data") or {}, e.get("run_id")
        if kind == "run_started" and rid:
            runs[rid] = {"run_id": rid, "op": data.get("op"), "query": data.get("query"),
                         "budget_jpy": data.get("budget_jpy"), "mode": data.get("mode"),
                         "status": "running", "started_ts": e.get("ts"), "scams": 0}
            order.append(rid)
            c["runs"] += 1
            op = data.get("op", "buy")
            c[op] = c.get(op, 0) + 1
        elif kind == "run_finished" and rid in runs:
            r = runs[rid]
            r.update(status="paused" if r["op"] == "buy" else "finished",
                     finished_ts=e.get("ts"), scams=data.get("scams_flagged", 0) or 0,
                     top=data.get("top", 0), listings=data.get("listings", 0),
                     sold=data.get("sold", 0), asking_price_jpy=data.get("asking_price_jpy"))
            r["duration_ms"] = round((e.get("ts", 0) - r.get("started_ts", 0)) * 1000)
            c["scams"] += r["scams"]
        elif kind == "run_failed" and rid in runs:
            runs[rid].update(status="failed", error=data.get("error"),
                             duration_ms=data.get("duration_ms"))
            c["failed"] += 1
            c["errors"] += 1
        elif kind == "button":
            brid = data.get("run_id")
            if data.get("action") == "approve" and data.get("ok"):
                c["approvals"] += 1
                if brid in runs:
                    runs[brid]["status"] = "approved"
            elif data.get("action") == "offer":
                c["offers"] += 1
            elif data.get("action") == "skip" and data.get("ok"):
                c["skips"] += 1
                if brid in runs:
                    runs[brid]["status"] = "skipped"
    durations = [r["duration_ms"] for r in runs.values() if r.get("duration_ms")]
    c["avg_ms"] = round(sum(durations) / len(durations)) if durations else 0
    recent = [runs[rid] for rid in order[-20:]][::-1]
    return {"counters": c, "runs": recent, "total_runs": len(runs)}


def summary_text(events: list[dict], n: int = 10) -> str:
    """Telegram /stats message."""
    if not ENABLED:
        return "Observability is off (OBS_ENABLED=0)."
    s = summarize(events)
    c = s["counters"]
    if not s["total_runs"]:
        return "No runs recorded yet."
    emoji = {"running": "⏳", "paused": "⏸", "approved": "✅",
             "skipped": "❌", "failed": "⚠️", "finished": "💰"}
    lines = [
        f"📊 Lowball — last {n} runs",
        f"Runs: {c['runs']} · {c['buy']} buy / {c['sell']} sell · {c['failed']} failed",
        f"🚩 {c['scams']} scams · ✅ {c['approvals']} approvals · 💬 {c['offers']} offers · ❌ {c['skips']} skips",
        f"Avg: {c['avg_ms'] / 1000:.1f}s",
        "",
    ]
    for r in s["runs"][:n]:
        q = (r.get("query") or "")[:30]
        dur = f"{r['duration_ms'] / 1000:.1f}s" if r.get("duration_ms") else "—"
        lines.append(f"{emoji.get(r['status'], '•')} {r['op']} \"{q}\" · {r.get('mode', '?')} · {dur} · {r.get('scams', 0)} 🚩")
    lines.append(f"\nDashboard: http://localhost:{PORT}")
    return "\n".join(lines)