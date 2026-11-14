"""Puppeteer fallback in a Daytona sandbox, for marketplace pages Tavily can't read.

Build the snapshot once (takes a few minutes, do it at T+0):
    python -m scouts snapshot
Then every fetch() reuses one sandbox created from that snapshot."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from pathlib import Path

log = logging.getLogger("scouts.daytona")

SNAPSHOT = os.getenv("DAYTONA_SNAPSHOT", "lowball-puppeteer")
SCRAPE_JS = Path(__file__).with_name("scrape.js")
_ENV = {"CHROME_PATH": "/usr/bin/chromium", "NODE_PATH": "/app/node_modules"}

_state: dict = {}
_lock = asyncio.Lock()
_sem = asyncio.Semaphore(int(os.getenv("DAYTONA_PARALLEL", "2")))  # Chromium per fetch; keep memory sane


def enabled() -> bool:
    return bool(os.getenv("DAYTONA_API_KEY")) and os.getenv("SCOUTS_PUPPETEER", "1") != "0"


def _image():
    from daytona import Image
    return (
        Image.debian_slim("3.12")
        .run_commands(
            "apt-get update && apt-get install -y --no-install-recommends "
            "chromium fonts-noto-cjk nodejs npm ca-certificates && rm -rf /var/lib/apt/lists/*",
            "mkdir -p /app && cd /app && npm init -y >/dev/null && "
            "PUPPETEER_SKIP_DOWNLOAD=1 npm install puppeteer-core@22.15.0 && chmod -R a+rwX /app",
        )
        .env(_ENV)
        .workdir("/app")
    )


async def build_snapshot() -> None:
    from daytona import AsyncDaytona, CreateSnapshotParams
    async with AsyncDaytona() as d:
        await d.snapshot.create(CreateSnapshotParams(name=SNAPSHOT, image=_image()), on_logs=print)
    print(f"snapshot '{SNAPSHOT}' ready")


async def _sandbox():
    async with _lock:
        if "sb" not in _state:
            from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams
            d = AsyncDaytona()
            sb = await d.create(
                CreateSandboxFromSnapshotParams(snapshot=SNAPSHOT, auto_stop_interval=15,
                                                labels={"app": "lowball"}),
                timeout=180,
            )
            script = f"{await sb.get_user_home_dir()}/scrape.js"
            await sb.fs.upload_file(SCRAPE_JS.read_bytes(), script)
            _state.update(d=d, sb=sb, script=script)
            log.info("daytona sandbox ready")
    return _state["sb"], _state["script"]


async def fetch(url: str, item_pattern: str | None = None) -> dict:
    """Render a page with Chromium. Returns {ok, url, title, text, images, items} (see scrape.js)."""
    sb, script = await _sandbox()
    cmd = f"node {shlex.quote(script)} {shlex.quote(url)}"
    if item_pattern:
        cmd += f" {shlex.quote(item_pattern)}"
    async with _sem:
        res = await sb.process.exec(cmd, env=_ENV, timeout=90)
    for line in reversed((res.result or "").strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {"ok": False, "url": url, "error": f"exit {res.exit_code}: {(res.result or '')[-300:]}"}


async def close() -> None:
    async with _lock:
        if "sb" in _state:
            try:
                await _state["sb"].delete()
            finally:
                await _state["d"].close()
                _state.clear()
