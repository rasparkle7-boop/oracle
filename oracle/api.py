"""FastAPI service + static mission-control UI."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db, pipeline, scheduler
from .analysis.benchmark import build_benchmark
from .config import settings

WEB = Path(__file__).parent / "web"
DEV_RELOAD = os.getenv("ORACLE_DEV_RELOAD", "0") == "1"
_DEV_VERSION = 0
_DEV_WATCH_STARTED = False


def _web_signature():
    files = [p for p in WEB.rglob("*") if p.is_file() and p.suffix in (".js", ".css", ".html", ".svg", ".woff2")]
    if not files:
        return (0, 0.0)
    return (len(files), max(p.stat().st_mtime for p in files), sum(p.stat().st_mtime for p in files))


def _watch_web():
    global _DEV_VERSION
    last = _web_signature()
    while True:
        time.sleep(1.0)
        current = _web_signature()
        if current != last:
            last = current
            _DEV_VERSION += 1


app = FastAPI(title=settings.app_name, version=settings.version)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    global _DEV_WATCH_STARTED
    db.init_db()
    db.log("info", "api", "ORACLE API online", {"version": settings.version})
    scheduler.start()
    if DEV_RELOAD and not _DEV_WATCH_STARTED:
        _DEV_WATCH_STARTED = True
        threading.Thread(target=_watch_web, name="oracle-web-watch", daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "name": "ORACLE", "version": settings.version,
            "model": settings.model_version, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/overview")
def overview() -> dict:
    return pipeline.overview()


@app.get("/api/fixtures")
def fixtures(
    sport: str | None = None,
    competition: str | None = None,
    q: str | None = None,
    days: int = Query(7, ge=1, le=30),
    min_confidence: float = Query(0, ge=0, le=100),
    sort: str = "kickoff",
    limit: int = Query(60, ge=1, le=300),
    offset: int = Query(0, ge=0),
    depth: str | None = None,
    watchlist: bool = False,
) -> dict:
    return pipeline.list_fixtures(sport=sport, competition=competition, q=q, days=days,
                                  min_confidence=min_confidence, sort=sort, limit=limit,
                                  offset=offset, depth=depth, only_watch=watchlist)


@app.get("/api/fixtures/{fixture_id:path}")
def fixture(fixture_id: str) -> dict:
    data = pipeline.fixture_detail(fixture_id)
    if not data:
        raise HTTPException(404, "fixture not found")
    return data


@app.post("/api/fixtures/{fixture_id:path}/analyze")
def analyze(fixture_id: str) -> dict:
    result = pipeline.analyze_fixture(fixture_id)
    if result.get("status") != "ok":
        raise HTTPException(400, result.get("message", "analysis failed"))
    return result


@app.post("/api/sync")
def sync(force_models: bool = False) -> dict:
    job = db.create_job("manual_sync", "manual cycle queued")

    def run():
        pipeline.run_full_sync(force_models=force_models, job_id=job)

    threading.Thread(target=run, name="oracle-manual-sync", daemon=True).start()
    return {"status": "queued", "job_id": job}


@app.get("/api/jobs")
def jobs(limit: int = 20) -> dict:
    with db.db() as conn:
        items = db.rows(conn, "select * from sync_jobs order by started_at desc limit ?", (limit,))
    for item in items:
        item["stats"] = db.json_loads(item.get("stats"), {})
    return {"items": items}


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    with db.db() as conn:
        item = db.row(conn, "select * from sync_jobs where id=?", (job_id,))
    if not item:
        raise HTTPException(404, "job not found")
    item["stats"] = db.json_loads(item.get("stats"), {})
    return item


@app.get("/api/search")
def search(q: str = Query("", min_length=0, max_length=120),
           limit: int = Query(20, ge=1, le=50)) -> dict:
    return pipeline.search_all(q, limit)


@app.get("/api/teams/{team_id:path}")
def team(team_id: str) -> dict:
    data = pipeline.team_detail(team_id)
    if not data:
        raise HTTPException(404, "team not found")
    return data


@app.get("/api/slip")
def slip(stake: float = Query(100, ge=1, le=1_000_000),
         threshold: float = Query(90, ge=1, le=99),
         days: int = Query(7, ge=1, le=30),
         sport: str | None = None,
         max_legs: int = Query(5, ge=1, le=8),
         min_confidence: float = Query(45, ge=0, le=100),
         market_types: str | None = None) -> dict:
    return pipeline.build_model_slip(stake=stake, threshold=threshold / 100,
                                     days=days, sport=sport, max_legs=max_legs,
                                     min_confidence=min_confidence, market_types=market_types)


@app.get("/api/competitions")
def competitions(sport: str | None = None) -> dict:
    return {"items": pipeline.competitions(sport)}


@app.get("/api/automation")
def automation() -> dict:
    with db.db() as conn:
        runs = db.rows(conn, "select * from model_runs order by started_at desc limit 10")
        logs = db.rows(conn, "select * from event_log order by id desc limit 80")
    for r in runs:
        r["metrics"] = db.json_loads(r.get("metrics"), {})
    for l in logs:
        l["payload"] = db.json_loads(l.get("payload"), {})
    return {"scheduler": scheduler.status(), "runs": runs, "logs": logs,
            "sources": settings.sources}


@app.get("/api/logs")
def logs(limit: int = 100) -> dict:
    with db.db() as conn:
        items = db.rows(conn, "select * from event_log order by id desc limit ?", (limit,))
    for i in items:
        i["payload"] = db.json_loads(i.get("payload"), {})
    return {"items": items}


@app.post("/api/watch/{fixture_id:path}")
def watch(fixture_id: str, note: str | None = None) -> dict:
    return pipeline.watch_toggle(fixture_id, note)


@app.delete("/api/watch/{fixture_id:path}")
def unwatch(fixture_id: str) -> dict:
    with db.db() as conn:
        conn.execute("DELETE FROM watchlist WHERE fixture_id=?", (fixture_id,))
    return {"watchlisted": False}


@app.post("/api/research/sweep")
def research_sweep() -> dict:
    return pipeline.research_sweep(30)


@app.get("/api/benchmark/{fixture_id:path}")
def benchmark(fixture_id: str, stake: float = Query(100, ge=1, le=1_000_000),
              refresh: bool = False) -> dict:
    return build_benchmark(fixture_id, stake=stake, refresh=refresh)


@app.post("/api/benchmark/{fixture_id:path}/refresh")
def benchmark_refresh(fixture_id: str, stake: float = Query(100, ge=1, le=1_000_000)) -> dict:
    return build_benchmark(fixture_id, stake=stake, refresh=True)


@app.get("/api/review")
def review(limit: int = Query(30, ge=1, le=200)) -> dict:
    return pipeline.review_summary(limit)


@app.post("/api/settle")
def settle() -> dict:
    return pipeline.settle_predictions()


@app.get("/api/backtest")
def backtest(days: int = Query(30, ge=7, le=120)) -> dict:
    try:
        return pipeline.backtest_football(days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"backtest failed: {exc}")


@app.get("/api/export")
def export(sport: str | None = None, days: int = 7) -> StreamingResponse:
    data = pipeline.list_fixtures(sport=sport, days=days, limit=300, sort="kickoff")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["fixture_id", "sport", "competition", "kickoff_utc", "home", "away",
                     "home_prob", "draw_prob", "away_prob", "pick", "pick_prob",
                     "fair_odds", "edge", "confidence", "depth", "headline"])
    for item in data["items"]:
        writer.writerow([item.get("id"), item.get("sport"), item.get("competition_name"),
                         item.get("kickoff_utc"), item.get("home_name"), item.get("away_name"),
                         item.get("home_prob"), item.get("draw_prob"), item.get("away_prob"),
                         item.get("pick"), item.get("pick_prob"), item.get("pick_fair"),
                         item.get("edge"), item.get("confidence"), item.get("data_depth"),
                         item.get("headline")])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=oracle_fixtures.csv"})


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def event_generator():
        while True:
            try:
                ov = pipeline.overview()
                payload = {
                    "counts": ov.get("counts"), "sports": ov.get("sports"),
                    "depth": ov.get("depth"), "last_sync": ov.get("last_sync", {}).get("at"),
                    "signals": (ov.get("signals") or [])[:3],
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception as exc:  # noqa: BLE001
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
            await asyncio.sleep(6)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/dev/status")
def dev_status() -> dict:
    return {"enabled": DEV_RELOAD, "version": _DEV_VERSION}


@app.get("/api/dev/reload")
async def dev_reload() -> StreamingResponse:
    if not DEV_RELOAD:
        raise HTTPException(404, "dev reload disabled")

    async def generator():
        last = _DEV_VERSION
        while True:
            if _DEV_VERSION != last:
                last = _DEV_VERSION
                yield f"data: {json.dumps({'version': last})}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Static UI (mounted last so /api routes win)
if WEB.exists():
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
