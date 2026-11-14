"""Bare-minimum obs tests. Run: python -m pytest tests/obs -q"""
import asyncio

import pytest


@pytest.fixture()
def obs(tmp_path, monkeypatch):
    import obs

    monkeypatch.setattr(obs, "ENABLED", True)
    monkeypatch.setattr(obs, "LOG", tmp_path / "events.jsonl")
    return obs


def test_emit_writes_line(obs):
    obs.emit("bot_started", pid=123)
    events = obs.read_events()
    assert len(events) == 1
    assert events[0]["kind"] == "bot_started"
    assert events[0]["data"]["pid"] == 123


def test_disabled_is_noop(obs, monkeypatch):
    monkeypatch.setattr(obs, "ENABLED", False)
    obs.emit("bot_started", pid=1)
    assert not obs.LOG.exists()
    assert obs.read_events() == []


def test_run_lifecycle_and_correlation(obs):
    async def go():
        with obs.run("buy", query="Sony A7III", mode="fake") as rid:
            assert obs.current_run_id() == rid
            obs.emit("run_finished", op="buy", mode="fake", duration_ms=1, scams_flagged=2)
            obs.emit("button", action="approve", ok=True)

    asyncio.run(go())
    events = obs.read_events()
    assert [e["kind"] for e in events] == ["run_started", "run_finished", "button"]
    assert len({e["run_id"] for e in events}) == 1  # all correlated
    assert obs.current_run_id() is None  # ContextVar reset after the run


def test_stage_times_and_records_error(obs):
    async def ok():
        async with obs.stage("search", node="scouts"):
            await asyncio.sleep(0.02)

    async def bad():
        async with obs.stage("rank", node="brains"):
            raise ValueError("boom")

    asyncio.run(ok())
    with pytest.raises(ValueError):
        asyncio.run(bad())
    events = obs.read_events()
    assert events[0]["data"]["ok"] is True
    assert events[0]["data"]["duration_ms"] >= 15
    assert events[1]["data"]["ok"] is False
    assert "boom" in events[1]["data"]["error"]