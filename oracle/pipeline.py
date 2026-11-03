"""Autonomous orchestration: discover -> research -> model -> reason -> persist."""
from __future__ import annotations

import asyncio
import difflib
import json
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from . import db
from .analysis.analyst import build_analysis
from .analysis.research import build_context
from .config import settings
from .ingest import cricbuzz, cricsheet, fotmob, news
from .ingest.weather import classify_cricket, forecast as weather_forecast, geocode
from .models import cricket as cricket_model
from .models import football as football_model
from .models import ratings

_SYNC_LOCK = threading.Lock()
_SWEEP_LOCK = threading.Lock()
_FOOTBALL_BOOK: football_model.FootballModelBook | None = None
_FOOTBALL_BOOK_AT = 0.0
_CRICKET_BOOK: cricket_model.CricketBook | None = None
_CRICKET_BOOK_AT = 0.0
_LAST_SYNC: dict[str, Any] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_models(force: bool = False) -> tuple[football_model.FootballModelBook, cricket_model.CricketBook]:
    global _FOOTBALL_BOOK, _FOOTBALL_BOOK_AT, _CRICKET_BOOK, _CRICKET_BOOK_AT
    now = time.time()
    if force or _FOOTBALL_BOOK is None or now - _FOOTBALL_BOOK_AT > 6 * 3600:
        _FOOTBALL_BOOK = football_model.train(history_days=max(400, settings.history_days))
        _FOOTBALL_BOOK_AT = now
    if force or _CRICKET_BOOK is None or now - _CRICKET_BOOK_AT > 3 * 3600:
        _CRICKET_BOOK = cricket_model.train()
        _CRICKET_BOOK_AT = now
    return _FOOTBALL_BOOK, _CRICKET_BOOK


def upcoming_fixtures(days: int | None = None, include_live: bool = False) -> list[dict]:
    days = days if days is not None else settings.window_days
    now = _now()
    end = now + timedelta(days=days)
    statuses = ("scheduled", "live") if include_live else ("scheduled",)
    with db.db() as conn:
        return db.rows(
            conn,
            f"""SELECT f.*, c.name AS competition_name, c.country AS competition_country,
                       c.tier AS competition_tier, c.logo AS competition_logo
                FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
                WHERE f.kickoff_utc >= ? AND f.kickoff_utc <= ?
                  AND f.status IN ({','.join('?' for _ in statuses)})
                ORDER BY f.kickoff_utc ASC LIMIT ?""",
            (_iso(now - timedelta(minutes=10)), _iso(end), *statuses, settings.max_fixtures),
        )


def _details_for(fixtures: list[dict], limit: int) -> dict[str, dict]:
    football = [f for f in fixtures if f["sport"] == "football"]
    if not football:
        return {}
    targets = sorted(football, key=lambda f: -(f.get("importance") or 0))[:limit]
    # enrich_fixtures expects raw dict; hydrate from JSON
    for f in targets:
        if isinstance(f.get("raw"), str):
            f["raw"] = db.json_loads(f["raw"], {}) or {}
    try:
        return asyncio.run(fotmob.enrich_fixtures(targets, limit=limit))
    except Exception as exc:  # noqa: BLE001
        db.log("warn", "pipeline", f"detail enrichment failed: {exc}")
        return {}


async def _news_for(fixtures: list[dict], limit: int) -> dict[str, list[dict]]:
    pairs = []
    seen = set()
    for f in sorted(fixtures, key=lambda x: -(x.get("importance") or 0)):
        for side in ("home", "away"):
            name = f.get(f"{side}_name")
            if name and (name, f["sport"]) not in seen:
                seen.add((name, f["sport"]))
                pairs.append((name, f["sport"]))
    pairs = pairs[:limit]
    try:
        return await news.research_teams(pairs, limit=limit)
    except Exception as exc:  # noqa: BLE001
        db.log("warn", "pipeline", f"news research failed: {exc}")
        return {}


def _cricket_venue_stats(book: cricket_model.CricketBook, fixture: dict) -> dict:
    key = cricket_model.norm(fixture.get("venue") or "")
    return book.venues.get(key, {})


def _football_h2h(fixture: dict) -> dict:
    try:
        return ratings.h2h(fixture["home_team_id"], fixture["away_team_id"], "football")
    except Exception:
        return {}


def _weather_for_fixture(fixture: dict, details: dict | None) -> dict:
    if details and details.get("weather"):
        return details["weather"]
    if fixture.get("sport") == "cricket" and fixture.get("city") and (fixture.get("importance") or 0) >= 0.7:
        # Best-effort: geocode city and forecast at kickoff. Cached aggressively.
        try:
            geo = asyncio.run(geocode(fixture["city"]))
            if geo:
                w = asyncio.run(weather_forecast(geo["latitude"], geo["longitude"], fixture["kickoff_utc"]))
                return w or {}
        except Exception:
            return {}
    return {}


def _build_one(fixture: dict, book_fb, book_cr, details, news_home, news_away,
               form_index, h2h, venue_stats, weather) -> tuple[dict, dict, dict]:
    context = build_context(
        fixture, details=details, news_home=news_home, news_away=news_away,
        form_index=form_index, h2h_data=h2h, venue_stats=venue_stats, weather=weather,
    )
    if fixture["sport"] == "cricket":
        prediction = cricket_model.predict(book_cr, fixture, context)
    else:
        prediction = football_model.predict(book_fb, fixture, context)
    analysis = build_analysis(fixture, prediction, context)
    return context, prediction, analysis


def persist_one(fixture: dict, context: dict, prediction: dict, analysis: dict) -> None:
    now = _iso(_now())
    lineups = context.get("lineups") or {}
    lineups_status = "confirmed" if lineups.get("available") else "not_confirmed"
    lineup_fingerprint = tuple(sorted(
        [str(p.get("name")) for p in (lineups.get("home_starters") or [])] +
        [str(p.get("name")) for p in (lineups.get("away_starters") or [])]
    ))
    confidence = (prediction.get("confidence") or {}).get("score", 0)
    with db.db() as conn:
        last = db.row(
            conn,
            """SELECT model_version, home_prob, draw_prob, away_prob, pick, pick_prob,
                      confidence, data_depth, lineups_status, lineups_fingerprint
               FROM prediction_history WHERE fixture_id=? ORDER BY id DESC LIMIT 1""",
            (fixture["id"],),
        )
        same = False
        if last:
            same = (
                last["model_version"] == settings.model_version
                and abs(float(last["home_prob"] or 0) - float(prediction["home_prob"])) < 0.0025
                and abs(float(last["draw_prob"] or 0) - float(prediction["draw_prob"])) < 0.0025
                and abs(float(last["away_prob"] or 0) - float(prediction["away_prob"])) < 0.0025
                and last["pick"] == prediction["pick"]
                and abs(float(last["pick_prob"] or 0) - float(prediction["pick_prob"])) < 0.0025
                and abs(float(last["confidence"] or 0) - float(confidence or 0)) < 0.5
                and last["data_depth"] == context.get("depth", "model")
                and last["lineups_status"] == lineups_status
                and (last.get("lineups_fingerprint") or "") == "|".join(lineup_fingerprint)
            )
        if not same:
            conn.execute(
                """INSERT INTO prediction_history(fixture_id, created_at, model_version, home_prob,
                       draw_prob, away_prob, pick, pick_side, pick_prob, confidence, data_depth,
                       lineups_status, lineups_fingerprint, input_snapshot, analysis_snapshot)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fixture["id"], now, settings.model_version, prediction["home_prob"],
                 prediction["draw_prob"], prediction["away_prob"], prediction["pick"],
                 prediction.get("pick_side"), prediction["pick_prob"], confidence,
                 context.get("depth", "model"), lineups_status, "|".join(lineup_fingerprint),
                 db.json_dumps({"features": prediction.get("features") or {},
                                "adjustments": context.get("adjustments") or {},
                                "injuries": context.get("injuries") or {},
                                "weather": context.get("weather") or {},
                                "fatigue": context.get("fatigue") or {},
                                "data_cutoff": context.get("data_cutoff"),
                                "lineups": context.get("lineups") or {},
                                "lineups_fingerprint": list(lineup_fingerprint),
                                "citations": len(context.get("citations") or [])}),
                 db.json_dumps({"headline": analysis.get("headline"),
                                "verdict": analysis.get("verdict"),
                                "research_grade": analysis.get("research_grade"),
                                "edge_quality": analysis.get("edge_quality"),
                                "risks": (analysis.get("risks") or [])[:5]})),
            )

        db.upsert_prediction(conn, {
            "fixture_id": fixture["id"], "sport": fixture["sport"],
            "model_version": settings.model_version, "generated_at": now,
            "home_prob": prediction["home_prob"], "draw_prob": prediction["draw_prob"],
            "away_prob": prediction["away_prob"], "pick": prediction["pick"],
            "pick_side": prediction.get("pick_side"), "pick_prob": prediction["pick_prob"],
            "pick_fair": prediction["pick_fair"], "edge": prediction["edge"],
            "confidence": (prediction.get("confidence") or {}).get("score", 0),
            "data_depth": context.get("depth", "model"),
            "expected_home": prediction.get("expected_home"),
            "expected_away": prediction.get("expected_away"),
            "markets": prediction.get("markets") or [],
            "score_grid": prediction.get("score_grid") or {},
            "analysis": analysis,
            "features": {**(prediction.get("features") or {}),
                         "confidence_detail": prediction.get("confidence") or {}},
        })
        db.upsert_research(conn, {
            "fixture_id": fixture["id"], "generated_at": now, "depth": context.get("depth", "model"),
            "home_news_count": len(context.get("news", {}).get("home") or []),
            "away_news_count": len(context.get("news", {}).get("away") or []),
            "injury_signals": context.get("injuries") or {},
            "weather": context.get("weather") or {},
            "pitch": context.get("pitch") or {},
            "fatigue": context.get("fatigue") or {},
            "tactical": context.get("tactical") or {},
            "citations": context.get("citations") or [],
            "summary": analysis.get("verdict"),
            "raw": context,
        })


def run_full_sync(force_models: bool = False, include_history: bool = False,
                  job_id: str | None = None, progress: Any = None) -> dict:
    """One complete autonomous cycle. Safe to run in a background thread."""
    global _LAST_SYNC
    job = job_id or db.create_job("full_sync", "discovering fixtures")
    if not _SYNC_LOCK.acquire(blocking=False):
        db.update_job(job, status="failed", message="A sync is already running")
        return {"status": "busy", "message": "A sync is already running", "job_id": job}
    started = time.time()
    stats: dict[str, Any] = {}
    try:
        db.init_db()
        today = _now().date()
        days = [today + timedelta(days=i) for i in range(-7 if not include_history else -settings.history_days,
                                                        settings.window_days + 1)]
        if progress:
            progress(0.05, "Fetching football fixtures")
        fb = asyncio.run(fotmob.sync_days(days))
        stats["football_fixtures"] = fb
        if progress:
            progress(0.2, "Fetching cricket schedules")
        cr = asyncio.run(cricbuzz.discover_and_sync())
        stats["cricket_fixtures"] = cr
        if progress:
            progress(0.28, "Loading Cricsheet archive")
        try:
            cs = asyncio.run(cricsheet.ingest("recent"))
            stats["cricsheet"] = cs
        except Exception as exc:
            db.log("warn", "pipeline", f"cricsheet skipped: {exc}")

        if progress:
            progress(0.35, "Training independent models")
        book_fb, book_cr = get_models(force=force_models)
        stats["models"] = {"football_matches": book_fb.training_matches,
                           "football_competitions": len(book_fb.competitions),
                           "cricket_matches": book_cr.matches,
                           "cricket_teams": len(book_cr.teams)}

        fixtures = upcoming_fixtures()
        stats["window_fixtures"] = len(fixtures)
        if progress:
            progress(0.42, f"Researching {min(settings.research_budget, len(fixtures))} priority fixtures")
        details = _details_for(fixtures, limit=min(settings.research_budget, 380))
        news_map = asyncio.run(_news_for(fixtures, limit=min(settings.research_budget, 420)))
        form_index = ratings.build_form_index("football", history_days=420)
        form_index_cr = ratings.build_form_index("cricket", history_days=420)
        form_index.update(form_index_cr)

        total = len(fixtures)
        processed = 0
        for f in fixtures:
            if isinstance(f.get("raw"), str):
                f["raw"] = db.json_loads(f["raw"], {}) or {}
            det = details.get(f["id"])
            hn = news_map.get(f["home_name"], [])
            an = news_map.get(f["away_name"], [])
            h2h = _football_h2h(f) if f["sport"] == "football" else {}
            vstats = _cricket_venue_stats(book_cr, f) if f["sport"] == "cricket" else {}
            weather = _weather_for_fixture(f, det) if det or f["sport"] == "cricket" else {}
            try:
                context, prediction, analysis = _build_one(
                    f, book_fb, book_cr, det, hn, an, form_index, h2h, vstats, weather)
                persist_one(f, context, prediction, analysis)
            except Exception as exc:  # noqa: BLE001
                db.log("error", "predict", f"{f['id']} failed: {exc}")
            processed += 1
            if progress and processed % 50 == 0:
                progress(0.42 + 0.55 * processed / max(1, total),
                         f"Analysed {processed}/{total} fixtures")

        elapsed = time.time() - started
        stats.update({"elapsed_seconds": round(elapsed, 1), "analysed": processed,
                      "depth_full": sum(1 for f in fixtures if f["id"] in details),
                      "news_teams": len(news_map)})
        _LAST_SYNC = {"at": _iso(_now()), "stats": stats, "elapsed": elapsed}
        db.set_state("last_sync", _LAST_SYNC)
        db.set_state("next_sync", _iso(_now() + timedelta(minutes=settings.fixtures_refresh_minutes)))
        db.update_job(job, status="completed", progress=1.0,
                      message=f"{processed} fixtures analysed in {elapsed:.1f}s", stats=stats)
        db.log("info", "pipeline", f"sync completed: {processed} fixtures in {elapsed:.1f}s", stats)
        if progress:
            progress(1.0, "Cycle complete")
        return {"status": "ok", "job_id": job, **stats}
    except Exception as exc:  # noqa: BLE001
        db.update_job(job, status="failed", message=str(exc)[:500])
        db.log("error", "pipeline", f"sync failed: {exc}")
        return {"status": "error", "job_id": job, "message": str(exc)}
    finally:
        _SYNC_LOCK.release()


def analyze_fixture(fixture_id: str) -> dict:
    """Deep-dive one fixture on demand (used by the dossier re-analyze button)."""
    db.init_db()
    with db.db() as conn:
        f = db.row(conn, """SELECT f.*, c.name AS competition_name, c.country AS competition_country,
                                   c.tier AS competition_tier
                            FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
                            WHERE f.id=?""", (fixture_id,))
    if not f:
        return {"status": "error", "message": "fixture not found"}
    if isinstance(f.get("raw"), str):
        f["raw"] = db.json_loads(f["raw"], {}) or {}
    book_fb, book_cr = get_models()
    details = {}
    if f["sport"] == "football":
        enriched = _details_for([f], 1)
        details = enriched.get(fixture_id, {})
    news_map = asyncio.run(_news_for([f], 4))
    form_index = ratings.build_form_index("football", 420)
    form_index.update(ratings.build_form_index("cricket", 420))
    h2h = _football_h2h(f) if f["sport"] == "football" else {}
    vstats = _cricket_venue_stats(book_cr, f) if f["sport"] == "cricket" else {}
    weather = _weather_for_fixture(f, details)
    context, prediction, analysis = _build_one(
        f, book_fb, book_cr, details,
        news_map.get(f["home_name"], []), news_map.get(f["away_name"], []),
        form_index, h2h, vstats, weather)
    persist_one(f, context, prediction, analysis)
    return {"status": "ok", "fixture_id": fixture_id, "analysis": analysis, "prediction": prediction}


def overview() -> dict:
    now = _now()
    end = now + timedelta(days=settings.window_days)
    with db.db() as conn:
        total_window = db.scalar(conn, "select count(*) from fixtures where status='scheduled' and kickoff_utc>=? and kickoff_utc<=?",
                                 (_iso(now - timedelta(minutes=10)), _iso(end)))
        predictions = db.scalar(conn, """select count(*) from predictions p join fixtures f on f.id=p.fixture_id
                                          where f.status='scheduled' and f.kickoff_utc>=? and f.kickoff_utc<=?""",
                               (_iso(now - timedelta(minutes=10)), _iso(end)))
        scheduled = db.scalar(conn, "select count(*) from fixtures where status='scheduled' and kickoff_utc>=?",
                              (_iso(now),))
        comps = db.scalar(conn, "select count(distinct competition_id) from fixtures where status='scheduled' and kickoff_utc>=? and kickoff_utc<=?",
                          (_iso(now), _iso(end)))
        sports = db.rows(conn, "select sport,count(*) n from fixtures where status='scheduled' and kickoff_utc>=? and kickoff_utc<=? group by sport",
                         (_iso(now), _iso(end)))
        depth = db.rows(conn, """select p.data_depth, count(*) n from predictions p
                                join fixtures f on f.id=p.fixture_id
                                where f.kickoff_utc>=? and f.kickoff_utc<=? group by p.data_depth""",
                        (_iso(now), _iso(end)))
        conf = db.scalar(conn, "select avg(confidence) from predictions")
        by_comp = db.rows(conn, """select c.name, c.sport, count(*) n from fixtures f
                                   join competitions c on c.id=f.competition_id
                                   where f.status='scheduled' and f.kickoff_utc>=? and f.kickoff_utc<=?
                                   group by c.id order by n desc limit 12""",
                          (_iso(now), _iso(end)))
        last_job = db.row(conn, "select * from sync_jobs order by started_at desc limit 1")
        model_runs = db.rows(conn, "select * from model_runs order by started_at desc limit 5")
        signals = db.rows(conn, """select f.id, f.home_name, f.away_name, f.kickoff_utc,
                                          p.pick, p.pick_prob, p.edge, p.confidence, p.data_depth,
                                          c.name AS competition_name
                                   from predictions p
                                   join fixtures f on f.id=p.fixture_id
                                   left join competitions c on c.id=f.competition_id
                                   where f.status='scheduled' and f.kickoff_utc>=?
                                   order by (p.confidence * f.importance) desc, p.confidence desc limit 8""", (_iso(now),))
    return {
        "generated_at": _iso(now),
        "window_days": settings.window_days,
        "counts": {
            "fixtures_window": total_window, "predictions": predictions,
            "scheduled_all": scheduled, "competitions_window": comps,
            "avg_confidence": round(float(conf or 0), 1),
        },
        "sports": {r["sport"]: r["n"] for r in sports},
        "depth": {r["data_depth"]: r["n"] for r in depth},
        "top_competitions": by_comp,
        "last_sync": db.get_state("last_sync", {}),
        "last_job": last_job,
        "model_runs": model_runs,
        "signals": signals,
        "engine": {
            "name": "ORACLE", "version": settings.version, "model": settings.model_version,
            "market_inputs": 0, "scheduler": settings.scheduler_enabled,
            "next_sync": db.get_state("next_sync"),
        },
    }


def fixture_detail(fixture_id: str) -> dict | None:
    with db.db() as conn:
        f = db.row(conn, """SELECT f.*, c.name AS competition_name, c.country AS competition_country,
                                   c.tier AS competition_tier, c.logo AS competition_logo,
                                   th.logo AS home_logo, ta.logo AS away_logo
                            FROM fixtures f
                            LEFT JOIN competitions c ON c.id=f.competition_id
                            LEFT JOIN teams th ON th.id=f.home_team_id
                            LEFT JOIN teams ta ON ta.id=f.away_team_id
                            WHERE f.id=?""", (fixture_id,))
        if not f:
            return None
        p = db.row(conn, "select * from predictions where fixture_id=?", (fixture_id,))
        r = db.row(conn, "select * from research where fixture_id=?", (fixture_id,))
        w = db.row(conn, "select * from watchlist where fixture_id=?", (fixture_id,))
        history = db.rows(conn, """SELECT id, created_at, model_version, home_prob, draw_prob,
                                          away_prob, pick, pick_prob, confidence, data_depth, lineups_status
                                   FROM prediction_history WHERE fixture_id=? ORDER BY id DESC LIMIT 12""",
                          (fixture_id,))
        odds_row = db.row(conn, """SELECT provider, fetched_at FROM market_odds
                                   WHERE fixture_id=? ORDER BY fetched_at DESC LIMIT 1""", (fixture_id,))
    for key in ("raw",):
        if f.get(key):
            f[key] = db.json_loads(f[key], {})
    if p:
        for key in ("markets", "score_grid", "analysis", "features"):
            p[key] = db.json_loads(p[key], [] if key == "markets" else {})
    if p and odds_row and isinstance(p.get("analysis"), dict):
        q = (p["analysis"].get("protocol") or {})
        for item in q.get("data_quality") or []:
            if item.get("category") == "Market data":
                item["provider"] = f"ESPN public odds / {odds_row.get('provider') or 'bookmaker'}"
                item["last_updated"] = odds_row.get("fetched_at")
                item["freshness"] = "fresh (benchmark)"
                item["missing"] = "not used by core model"
                item["notes"] = "benchmark only; core ORACLE remains market-free"
    if r:
        for key in ("injury_signals", "citations"):
            r[key] = db.json_loads(r[key], [])
        for key in ("weather", "pitch", "fatigue", "tactical", "raw"):
            r[key] = db.json_loads(r[key], {})
        venue = (r["raw"].get("venue") or {}) if isinstance(r.get("raw"), dict) else {}
        if not f.get("venue") and venue.get("name"):
            f["venue"] = venue.get("name")
        if not f.get("city") and venue.get("city"):
            f["city"] = venue.get("city")
    return {"fixture": f, "prediction": p, "research": r, "watchlisted": bool(w),
            "history": history, "comparison": team_comparison(f)}


def list_fixtures(sport: str | None = None, competition: str | None = None, q: str | None = None,
                  days: int = 7, min_confidence: float = 0, sort: str = "kickoff",
                  limit: int = 60, offset: int = 0, depth: str | None = None,
                  only_watch: bool = False) -> dict:
    now = _now()
    end = now + timedelta(days=days)
    where = ["f.kickoff_utc >= ?", "f.kickoff_utc <= ?", "f.status='scheduled'"]
    params: list[Any] = [_iso(now - timedelta(minutes=10)), _iso(end)]
    if sport in ("football", "cricket"):
        where.append("f.sport=?")
        params.append(sport)
    if competition:
        where.append("f.competition_id=?")
        params.append(competition)
    if q:
        where.append("(lower(f.home_name) like ? or lower(f.away_name) like ? or lower(c.name) like ?)")
        like = f"%{q.lower()}%"
        params.extend([like, like, like])
    if min_confidence:
        where.append("coalesce(p.confidence,0) >= ?")
        params.append(min_confidence)
    if depth:
        where.append("p.data_depth=?")
        params.append(depth)
    if only_watch:
        where.append("w.fixture_id is not null")
    order = {
        "kickoff": "f.kickoff_utc asc",
        "confidence": "coalesce(p.confidence,0) desc",
        "edge": "coalesce(p.edge,0) desc",
        "importance": "f.importance desc, f.kickoff_utc asc",
        "probability": "coalesce(p.pick_prob,0) desc",
    }.get(sort, "f.kickoff_utc asc")
    base = f"""FROM fixtures f
               LEFT JOIN competitions c ON c.id=f.competition_id
               LEFT JOIN predictions p ON p.fixture_id=f.id
               LEFT JOIN research r ON r.fixture_id=f.id
               LEFT JOIN watchlist w ON w.fixture_id=f.id
               LEFT JOIN teams th ON th.id=f.home_team_id
               LEFT JOIN teams ta ON ta.id=f.away_team_id
               WHERE {' AND '.join(where)}"""
    with db.db() as conn:
        total = db.scalar(conn, f"SELECT count(*) {base}", params)
        rows = db.rows(conn, f"""SELECT f.id, f.sport, f.competition_id, f.kickoff_utc, f.status,
                                        f.home_name, f.away_name, f.venue, f.city, f.home_score, f.away_score,
                                        f.importance, c.name AS competition_name, c.country AS competition_country,
                                        c.logo AS competition_logo, th.logo AS home_logo, ta.logo AS away_logo,
                                        p.home_prob, p.draw_prob, p.away_prob, p.pick, p.pick_side,
                                        p.pick_prob, p.pick_fair, p.edge, p.confidence, p.data_depth,
                                        json_extract(p.analysis,'$.headline') AS headline,
                                        json_extract(p.analysis,'$.verdict') AS verdict,
                                        json_extract(r.raw,'$.flags') AS flags,
                                        w.fixture_id IS NOT NULL AS watchlisted
                                 {base} ORDER BY {order} LIMIT ? OFFSET ?""",
                       params + [limit, offset])
    for r in rows:
        if r.get("flags"):
            try:
                r["flags"] = json.loads(r["flags"])
            except Exception:
                r["flags"] = []
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


def competitions(sport: str | None = None) -> list[dict]:
    with db.db() as conn:
        where = "WHERE f.kickoff_utc>=?" + (" AND f.sport=?" if sport else "")
        params = [_iso(_now())] + ([sport] if sport else [])
        return db.rows(conn, f"""SELECT c.id, c.name, c.sport, c.country, c.tier, count(*) n
                                 FROM fixtures f JOIN competitions c ON c.id=f.competition_id
                                 {where} GROUP BY c.id ORDER BY n DESC""", params)


def watch_toggle(fixture_id: str, note: str | None = None) -> dict:
    with db.db() as conn:
        existing = db.row(conn, "select * from watchlist where fixture_id=?", (fixture_id,))
        if existing:
            conn.execute("DELETE FROM watchlist WHERE fixture_id=?", (fixture_id,))
            return {"watchlisted": False}
        conn.execute("INSERT INTO watchlist(fixture_id, created_at, note) VALUES(?,?,?)",
                     (fixture_id, _iso(_now()), note))
        return {"watchlisted": True}


def backtest_football(days: int = 30) -> dict:
    """Seven-day walk-forward evaluation with strictly pre-fold training data."""
    days = max(7, min(120, int(days)))
    window_end = _now()
    window_start = window_end - timedelta(days=days)
    start_iso, end_iso = _iso(window_start), _iso(window_end)
    with db.db() as conn:
        test = db.rows(conn, """SELECT * FROM fixtures WHERE sport='football' AND status='finished'
                                AND kickoff_utc>=? AND kickoff_utc<?
                                AND home_score_num IS NOT NULL AND away_score_num IS NOT NULL
                                ORDER BY kickoff_utc ASC""", (start_iso, end_iso))
        comp_names = {r["id"]: r["name"] for r in db.rows(conn, "select id, name from competitions")}

    results: list[dict] = []
    folds: list[dict] = []
    cursor = window_start
    while cursor < window_end:
        fold_end = min(cursor + timedelta(days=7), window_end)
        fold_start_iso, fold_end_iso = _iso(cursor), _iso(fold_end)
        fold_rows = [r for r in test if fold_start_iso <= r["kickoff_utc"] < fold_end_iso]
        if fold_rows:
            book = football_model.train(
                history_days=1000, before_iso=fold_start_iso,
                as_of_iso=fold_start_iso, persist=False,
            )
            folds.append({
                "from": fold_start_iso, "to": fold_end_iso,
                "train_before": fold_start_iso,
                "training_matches": book.training_matches,
                "test_matches": len(fold_rows),
            })
            for fixture in fold_rows:
                if isinstance(fixture.get("raw"), str):
                    fixture["raw"] = db.json_loads(fixture["raw"], {}) or {}
                try:
                    prediction = football_model.predict(book, fixture)
                except Exception:
                    continue
                probs = np.array([prediction["home_prob"], prediction["draw_prob"], prediction["away_prob"]], dtype=float)
                actual = (0 if fixture["home_score_num"] > fixture["away_score_num"] else
                          1 if fixture["home_score_num"] == fixture["away_score_num"] else 2)
                prior = prediction.get("features", {}).get("base_rates") or {"home": 0.45, "draw": 0.26, "away": 0.29}
                baseline = np.array([prior.get("home", 0.45), prior.get("draw", 0.26), prior.get("away", 0.29)], dtype=float)
                baseline = baseline / baseline.sum() if baseline.sum() > 0 else np.array([0.45, 0.26, 0.29])
                onehot = np.zeros(3)
                onehot[actual] = 1.0
                results.append({
                    "competition_id": fixture["competition_id"],
                    "actual": actual,
                    "probabilities": probs,
                    "baseline": baseline,
                    "brier": float(((probs - onehot) ** 2).sum()),
                    "log_loss": float(-np.log(max(1e-9, probs[actual]))),
                    "correct": int(np.argmax(probs) == actual),
                    "baseline_brier": float(((baseline - onehot) ** 2).sum()),
                    "baseline_log_loss": float(-np.log(max(1e-9, baseline[actual]))),
                    "baseline_correct": int(np.argmax(baseline) == actual),
                    "home_baseline_correct": int(actual == 0),
                    "max_probability": float(probs.max()),
                })
        cursor = fold_end

    def metrics(rows: list[dict], model: str = "dixon_coles") -> dict:
        if not rows:
            return {"n": 0, "brier": None, "log_loss": None, "accuracy": None}
        brier_key = "brier" if model == "dixon_coles" else "baseline_brier"
        loss_key = "log_loss" if model == "dixon_coles" else "baseline_log_loss"
        correct_key = "correct" if model == "dixon_coles" else "baseline_correct"
        n = len(rows)
        return {
            "n": n,
            "brier": round(sum(r[brier_key] for r in rows) / n, 4),
            "log_loss": round(sum(r[loss_key] for r in rows) / n, 4),
            "accuracy": round(sum(r[correct_key] for r in rows) / n, 4),
        }

    cal_bins = []
    for bin_index in range(3, 10):
        lo, hi = bin_index / 10.0, (bin_index + 1) / 10.0
        vals = [r for r in results if lo <= r["max_probability"] < hi]
        if vals:
            cal_bins.append({
                "bin_low": lo, "bin_high": hi, "n": len(vals),
                "avg_pred": round(sum(r["max_probability"] for r in vals) / len(vals), 4),
                "accuracy": round(sum(r["correct"] for r in vals) / len(vals), 4),
            })

    by_comp: dict[str, list[dict]] = {}
    for result in results:
        by_comp.setdefault(result["competition_id"], []).append(result)
    dc_metrics = metrics(results)
    prior_metrics = metrics(results, "competition_base_rate")
    return {
        "window_days": days,
        "date_range": {"from": start_iso, "to": end_iso, "basis": "finished fixtures by kickoff"},
        "fold_days": 7,
        "folds": folds,
        "test_matches": len(results),
        "training_matches": max((f["training_matches"] for f in folds), default=0),
        "calibration": cal_bins,
        "brier": dc_metrics["brier"], "log_loss": dc_metrics["log_loss"],
        "accuracy": dc_metrics["accuracy"],
        "baseline_brier": prior_metrics["brier"],
        "baseline_log_loss": prior_metrics["log_loss"],
        "baseline_accuracy": prior_metrics["accuracy"],
        "home_baseline_accuracy": round(sum(r["home_baseline_correct"] for r in results) / len(results), 4) if results else None,
        "model_comparison": {
            "dixon_coles": dc_metrics,
            "competition_base_rate": prior_metrics,
        },
        "calibration_note": "Seven-day chronological folds; each fold's training and recency weights end before that fold starts.",
        "by_competition": [
            {"competition_id": key, "competition": comp_names.get(key, key),
             "matches": len(rows), "brier": metrics(rows)["brier"],
             "log_loss": metrics(rows)["log_loss"], "accuracy": metrics(rows)["accuracy"],
             "baseline_brier": metrics(rows, "competition_base_rate")["brier"]}
            for key, rows in sorted(by_comp.items(), key=lambda pair: -len(pair[1]))[:12]
        ],
    }


def repredict_all() -> dict:
    """Re-run models + reasoning from persisted research context (no network).

    Useful after calibration or narrative changes. Keeps the expensive
    discovery/research layer untouched.
    """
    db.init_db()
    fixtures = upcoming_fixtures()
    book_fb, book_cr = get_models()
    # form index is needed only when a research row is missing
    form_index = None
    updated = 0
    failed = 0
    with db.db() as conn:
        rows = {r["fixture_id"]: r for r in db.rows(conn, "select * from research")}
    for f in fixtures:
        if isinstance(f.get("raw"), str):
            f["raw"] = db.json_loads(f["raw"], {}) or {}
        r = rows.get(f["id"])
        context = db.json_loads(r["raw"], {}) if r else None
        if not context:
            if form_index is None:
                form_index = ratings.build_form_index("football", 420)
                form_index.update(ratings.build_form_index("cricket", 420))
            h2h = _football_h2h(f) if f["sport"] == "football" else {}
            vstats = _cricket_venue_stats(book_cr, f) if f["sport"] == "cricket" else {}
            context = build_context(f, h2h_data=h2h, venue_stats=vstats, form_index=form_index)
        try:
            prediction = cricket_model.predict(book_cr, f, context) if f["sport"] == "cricket" else football_model.predict(book_fb, f, context)
            analysis = build_analysis(f, prediction, context)
            persist_one(f, context, prediction, analysis)
            updated += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            db.log("error", "repredict", f"{f['id']}: {exc}")
    db.log("info", "repredict", f"re-predicted {updated} fixtures", {"failed": failed})
    return {"status": "ok", "updated": updated, "failed": failed, "fixtures": len(fixtures)}


def recompute_importance() -> dict:
    """Re-score fixture importance from the current competition taxonomy."""
    from .ingest.fotmob import _importance
    updated = 0
    with db.db() as conn:
        comps = db.rows(conn, "select id, name, country, metadata from competitions")
        for c in comps:
            meta = db.json_loads(c.get("metadata"), {}) or {}
            gender = meta.get("gender") or ("female" if "women" in (c["name"] or "").lower() else "male")
            score = _importance(c["name"], c["country"], gender)
            conn.execute("update fixtures set importance=? where competition_id=? and importance!=?",
                         (score, c["id"], score))
            updated += 1
    db.log("info", "pipeline", f"re-scored importance for {updated} competitions")
    return {"competitions": updated}


def research_sweep(limit: int = 30) -> dict:
    """Continuously deepen the least-researched in-window fixtures.

    Full sync handles the priority batch. This sweeper works through the long
    tail in small batches so coverage improves without a giant HTTP burst.
    """
    if not _SWEEP_LOCK.acquire(blocking=False):
        return {"status": "busy", "message": "a sweep is already running"}
    try:
        db.init_db()
        now = _now()
        with db.db() as conn:
            fixtures = db.rows(
                conn,
                """SELECT f.* FROM fixtures f
                   JOIN research r ON r.fixture_id=f.id
                   WHERE f.status='scheduled'
                     AND f.kickoff_utc>=? AND f.kickoff_utc<=?
                     AND r.depth IN ('model','enhanced')
                   ORDER BY f.importance DESC, f.kickoff_utc ASC LIMIT ?""",
                (_iso(now - timedelta(minutes=10)), _iso(now + timedelta(days=settings.window_days)), limit),
            )
        if not fixtures:
            return {"status": "ok", "updated": 0, "message": "coverage complete"}
        book_fb, book_cr = get_models()
        details = _details_for(fixtures, limit=limit)
        news_map = asyncio.run(_news_for(fixtures, limit=max(8, limit * 2)))
        form_index = ratings.build_form_index("football", 420)
        form_index.update(ratings.build_form_index("cricket", 420))
        updated = 0
        for f in fixtures:
            if isinstance(f.get("raw"), str):
                f["raw"] = db.json_loads(f["raw"], {}) or {}
            det = details.get(f["id"])
            h2h = _football_h2h(f) if f["sport"] == "football" else {}
            vstats = _cricket_venue_stats(book_cr, f) if f["sport"] == "cricket" else {}
            weather = _weather_for_fixture(f, det)
            try:
                context, prediction, analysis = _build_one(
                    f, book_fb, book_cr, det,
                    news_map.get(f["home_name"], []), news_map.get(f["away_name"], []),
                    form_index, h2h, vstats, weather)
                persist_one(f, context, prediction, analysis)
                updated += 1
            except Exception as exc:  # noqa: BLE001
                db.log("error", "sweep", f"{f['id']}: {exc}")
        db.log("info", "sweep", f"deepened {updated} fixtures", {"candidates": len(fixtures)})
        return {"status": "ok", "updated": updated, "candidates": len(fixtures)}
    finally:
        _SWEEP_LOCK.release()


# ---------------------------------------------------------------------------
# Post-match settlement / calibration ledger
# ---------------------------------------------------------------------------

def _actual_result(fixture: dict, prediction: dict) -> tuple[str, int, float, bool]:
    """Return (label, index, model_probability_for_actual, excluded)."""
    sport = fixture["sport"]
    if sport == "football":
        hs, as_ = fixture.get("home_score_num"), fixture.get("away_score_num")
        if hs is None or as_ is None:
            return "unresolved", -1, 0.0, True
        if hs > as_:
            return "home", 0, float(prediction.get("home_prob") or 0), False
        if hs < as_:
            return "away", 2, float(prediction.get("away_prob") or 0), False
        return "draw", 1, float(prediction.get("draw_prob") or 0), False

    # Cricket
    winner = fixture.get("winner_team_id")
    if winner and winner == fixture.get("home_team_id"):
        return "home", 0, float(prediction.get("home_prob") or 0), False
    if winner and winner == fixture.get("away_team_id"):
        return "away", 2, float(prediction.get("away_prob") or 0), False
    detail = (fixture.get("score_detail") or "").lower()
    raw = fixture.get("raw") or {}
    if isinstance(raw, str):
        raw = db.json_loads(raw, {}) or {}
    fmt = (raw.get("format") or "").upper()
    if "no result" in detail or "abandon" in detail:
        return "no_result", -1, 0.0, True
    if "tie" in detail:
        return "tie", 3, 0.0, True
    if "draw" in detail or fmt == "TEST":
        return "draw", 1, float(prediction.get("draw_prob") or 0), False
    return "unresolved", -1, 0.0, True


def settle_predictions() -> dict:
    """Settle finished fixtures against stored pre-match predictions."""
    now = _now()
    settled = 0
    skipped = 0
    with db.db() as conn:
        rows = db.rows(
            conn,
            """SELECT f.id AS fixture_id, f.sport, f.competition_id, f.kickoff_utc, f.status,
                      f.home_team_id, f.away_team_id, f.home_name, f.away_name,
                      f.home_score_num, f.away_score_num, f.score_detail, f.raw,
                      f.winner_team_id,
                      COALESCE(ph.home_prob, p.home_prob) AS home_prob,
                      COALESCE(ph.draw_prob, p.draw_prob) AS draw_prob,
                      COALESCE(ph.away_prob, p.away_prob) AS away_prob,
                      COALESCE(ph.pick, p.pick) AS pick,
                      COALESCE(ph.pick_side, p.pick_side) AS pick_side,
                      COALESCE(ph.pick_prob, p.pick_prob) AS pick_prob,
                      COALESCE(ph.confidence, p.confidence) AS confidence,
                      COALESCE(ph.data_depth, p.data_depth) AS data_depth,
                      p.score_grid
               FROM fixtures f
               JOIN predictions p ON p.fixture_id=f.id
               LEFT JOIN prediction_history ph ON ph.id = (
                   SELECT h.id FROM prediction_history h
                   WHERE h.fixture_id=f.id AND h.created_at <= f.kickoff_utc
                   ORDER BY h.id DESC LIMIT 1
               )
               LEFT JOIN settlements s ON s.fixture_id=f.id
               WHERE f.status='finished' AND f.kickoff_utc < ? AND s.fixture_id IS NULL
               ORDER BY f.kickoff_utc ASC LIMIT 800""",
            (_iso(now),),
        )
        for r in rows:
            if isinstance(r.get("raw"), str):
                r["raw"] = db.json_loads(r["raw"], {}) or {}
            actual, index, model_prob, excluded = _actual_result(r, r)
            if index < 0:
                if actual != "unresolved":
                    conn.execute(
                        """INSERT INTO settlements(fixture_id, sport, competition_id, kickoff_utc, settled_at,
                               actual_outcome, actual_index, model_prob, pick, pick_side, pick_correct,
                               brier, log_loss, confidence, data_depth, excluded, metadata, pick_prob)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(fixture_id) DO UPDATE SET settled_at=excluded.settled_at,
                             actual_outcome=excluded.actual_outcome, excluded=1""",
                        (r["fixture_id"], r["sport"], r["competition_id"], r["kickoff_utc"], _iso(now),
                         actual, None, 0.0, r.get("pick"), r.get("pick_side"), 0,
                         None, None, r.get("confidence"), r.get("data_depth"), 1,
                         db.json_dumps({"detail": r.get("score_detail")}), None),
                    )
                skipped += 1
                continue
            probs = [float(r.get("home_prob") or 0), float(r.get("draw_prob") or 0), float(r.get("away_prob") or 0)]
            onehot = [0.0, 0.0, 0.0]
            onehot[index] = 1.0
            brier = sum((p - a) ** 2 for p, a in zip(probs, onehot))
            log_loss = -math.log(max(model_prob, 1e-9))
            pick_correct = 1 if str(r.get("pick_side") or "") == actual else 0
            conn.execute(
                """INSERT INTO settlements(fixture_id, sport, competition_id, kickoff_utc, settled_at,
                       actual_outcome, actual_index, model_prob, pick, pick_side, pick_correct,
                       brier, log_loss, confidence, data_depth, excluded, metadata, pick_prob)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(fixture_id) DO UPDATE SET
                     settled_at=excluded.settled_at, actual_outcome=excluded.actual_outcome,
                     actual_index=excluded.actual_index, model_prob=excluded.model_prob,
                     pick_correct=excluded.pick_correct, brier=excluded.brier,
                     log_loss=excluded.log_loss, excluded=excluded.excluded, pick_prob=excluded.pick_prob""",
                (r["fixture_id"], r["sport"], r["competition_id"], r["kickoff_utc"], _iso(now),
                 actual, index, model_prob, r.get("pick"), r.get("pick_side"), pick_correct,
                 brier, log_loss, r.get("confidence"), r.get("data_depth"), 1 if excluded else 0,
                 db.json_dumps({"home_score": r.get("home_score_num"), "away_score": r.get("away_score_num"),
                                "detail": r.get("score_detail")}), r.get("pick_prob")),
            )
            settled += 1
    if settled:
        db.log("info", "settle", f"settled {settled} predictions", {"skipped": skipped})
    return {"settled": settled, "skipped": skipped}


def _review_summary_row(review: dict | None, row: dict) -> dict:
    if review:
        reasons = review.get("reasons") or []
        summary = review.get("summary") or f"{row.get('home_name')} vs {row.get('away_name')} reviewed against the stored pre-match call."
        verdict = review.get("verdict") or ("WIN" if row.get("pick_correct") else "LOSS")
        return {
            "fixture_id": row["fixture_id"], "sport": row["sport"],
            "competition": row.get("competition_name"), "home": row.get("home_name"),
            "away": row.get("away_name"), "kickoff": row.get("kickoff_utc"),
            "actual": row.get("actual_outcome"), "pick": row.get("pick"),
            "pick_correct": bool(row.get("pick_correct")), "model_prob": row.get("model_prob"),
            "brier": row.get("brier"), "log_loss": row.get("log_loss"),
            "confidence": row.get("confidence"), "depth": row.get("data_depth"),
            "excluded": bool(row.get("excluded")), "legacy": not bool(row.get("history_guarded")),
            "verdict": verdict, "summary": summary, "reasons": reasons,
            "market_reviews": review.get("market_reviews") or [],
        }
    return {
        "fixture_id": row["fixture_id"], "sport": row["sport"],
        "competition": row.get("competition_name"), "home": row.get("home_name"),
        "away": row.get("away_name"), "kickoff": row.get("kickoff_utc"),
        "actual": row.get("actual_outcome"), "pick": row.get("pick"),
        "pick_correct": bool(row.get("pick_correct")), "model_prob": row.get("model_prob"),
        "brier": row.get("brier"), "log_loss": row.get("log_loss"),
        "confidence": row.get("confidence"), "depth": row.get("data_depth"),
        "excluded": bool(row.get("excluded")), "legacy": not bool(row.get("history_guarded")),
        "verdict": "WIN" if row.get("pick_correct") else "LOSS",
        "summary": f"Reviewed against the stored pre-match prediction for {row.get('home_name')} vs {row.get('away_name')}.",
        "reasons": ["Outcome recorded. Narrative autopsy unavailable for this historical row."],
        "market_reviews": [],
    }


def review_summary(limit: int = 30) -> dict:
    with db.db() as conn:
        rows = db.rows(conn, """SELECT s.*, c.name AS competition_name, f.home_name, f.away_name,
                                       EXISTS (SELECT 1 FROM prediction_history h
                                               WHERE h.fixture_id=s.fixture_id
                                                 AND h.created_at <= s.kickoff_utc) AS history_guarded
                                FROM settlements s
                                LEFT JOIN competitions c ON c.id=s.competition_id
                                LEFT JOIN fixtures f ON f.id=s.fixture_id
                                ORDER BY s.settled_at DESC""")
        reviews = {r["fixture_id"]: r for r in db.rows(conn, "SELECT * FROM match_reviews ORDER BY settled_at DESC")}
        pending = db.scalar(conn, """SELECT count(*) FROM fixtures f JOIN predictions p ON p.fixture_id=f.id
                                     LEFT JOIN settlements s ON s.fixture_id=f.id
                                     WHERE f.status='finished' AND s.fixture_id IS NULL""")
        guarded = db.scalar(conn, """SELECT count(*) FROM settlements s
                                     WHERE EXISTS (SELECT 1 FROM prediction_history h
                                                   WHERE h.fixture_id=s.fixture_id
                                                     AND h.created_at <= s.kickoff_utc)""")
    valid = [r for r in rows if not r.get("excluded") and r.get("history_guarded")]
    legacy = [r for r in rows if not r.get("excluded") and not r.get("history_guarded")]
    def stats(items):
        if not items:
            return {"n": 0, "accuracy": None, "brier": None, "log_loss": None}
        n = len(items)
        return {"n": n,
                "accuracy": round(sum(r.get("pick_correct") or 0 for r in items) / n, 4),
                "brier": round(sum(r.get("brier") or 0 for r in items) / n, 4),
                "log_loss": round(sum(r.get("log_loss") or 0 for r in items) / n, 4)}
    by_sport = {}
    for r in valid:
        by_sport.setdefault(r["sport"], []).append(r)
    by_conf = {"<50": [], "50–60": [], "60–70": [], "70+": []}
    for r in valid:
        c = float(r.get("confidence") or 0)
        key = "<50" if c < 50 else "50–60" if c < 60 else "60–70" if c < 70 else "70+"
        by_conf[key].append(r)
    by_comp = {}
    for r in valid:
        by_comp.setdefault(r.get("competition_name") or r.get("competition_id") or "—", []).append(r)
    calibration = []
    for lo in (0.30, 0.40, 0.50, 0.60, 0.70, 0.80):
        hi = lo + 0.10
        vals = [r for r in valid if r.get("pick_prob") is not None and lo <= float(r["pick_prob"]) < hi]
        if vals:
            calibration.append({
                "bin_low": lo, "bin_high": hi, "n": len(vals),
                "avg_pred": round(sum(float(r["pick_prob"]) for r in vals) / len(vals), 4),
                "accuracy": round(sum(r.get("pick_correct") or 0 for r in vals) / len(vals), 4),
            })
    baseline = (round(sum(1 for r in valid if r.get("actual_outcome") == "home") / len(valid), 4)
                if valid else None)
    scope = valid if valid else rows
    kickoffs = [r.get("kickoff_utc") for r in scope if r.get("kickoff_utc")]
    recent = []
    for r in rows[:limit]:
        recent.append(_review_summary_row(reviews.get(r["fixture_id"]), r))
    return {
        "generated_at": _iso(_now()),
        "settled": len(rows), "valid": len(valid), "pending": pending,
        "guarded": len(valid), "legacy": len(legacy),
        "overall": stats(valid),
        "by_sport": {k: stats(v) for k, v in by_sport.items()},
        "by_confidence": {k: stats(v) for k, v in by_conf.items()},
        "by_competition": sorted(
            [{"competition": k, **stats(v)} for k, v in by_comp.items()],
            key=lambda x: -x["n"])[:12],
        "calibration": calibration,
        "baseline": {"home_always_accuracy": baseline,
                     "definition": "Always pick the home side; the minimum reference for 1X2 accuracy."},
        "date_range": {"from": min(kickoffs) if kickoffs else None,
                       "to": max(kickoffs) if kickoffs else None,
                       "basis": "guarded" if valid else "legacy"},
        "recent": recent,
        "sample_warning": ("Under 500 settled forecasts is noisy; treat accuracy and Brier as "
                           "preliminary, not proof of edge."),
        "note": "Settlements compare the stored pre-match prediction with the final result. "
                "No post-match information is used in the forecast.",
    }


# ---------------------------------------------------------------------------
# Search / team pages / model-fair slip builder (no bookmaker odds)
# ---------------------------------------------------------------------------

TEAM_ALIASES = {
    "man utd": "manchester united", "man united": "manchester united",
    "man city": "manchester city", "psg": "paris saint germain",
    "barca": "barcelona", "bayern": "bayern munchen", "bayern munich": "bayern munchen",
    "spurs": "tottenham hotspur", "wolves": "wolverhampton",
    "west ham": "west ham united", "brighton": "brighton hove albion",
    "newcastle": "newcastle united", "forest": "nottingham forest",
    "atletico": "atletico madrid", "real": "real madrid",
    "inter": "inter milan", "ac milan": "milan", "juve": "juventus",
    "dortmund": "borussia dortmund", "gladbach": "borussia monchengladbach",
    "leverkusen": "bayer leverkusen", "marseille": "olympique marseille",
    "lyon": "olympique lyonnais", "ajax": "ajax", "feyenoord": "feyenoord",
    "benfica": "benfica", "porto": "fc porto", "sporting": "sporting cp",
    "galatasaray": "galatasaray", "fenerbahce": "fenerbahce",
    "besiktas": "besiktas", "celtic": "celtic", "rangers": "rangers",
    "boca": "boca juniors", "river": "river plate", "flamengo": "flamengo",
    "palmeiras": "palmeiras", "corinthians": "corinthians", "santos": "santos",
    "india": "india", "ind": "india", "australia": "australia", "aus": "australia",
    "england": "england", "eng": "england", "new zealand": "new zealand", "nz": "new zealand",
    "south africa": "south africa", "sa": "south africa", "west indies": "west indies",
    "wi": "west indies", "sri lanka": "sri lanka", "sl": "sri lanka",
    "pakistan": "pakistan", "pak": "pakistan", "bangladesh": "bangladesh", "ban": "bangladesh",
}


def _norm_query(q: str) -> str:
    s = (q or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return TEAM_ALIASES.get(s, s)


def _form_from_rows(team_id: str, rows: list[dict]) -> dict:
    out = []
    for r in rows:
        if r["home_team_id"] == team_id:
            gf, ga = r.get("home_score_num"), r.get("away_score_num")
        else:
            gf, ga = r.get("away_score_num"), r.get("home_score_num")
        if gf is None or ga is None:
            continue
        out.append("W" if gf > ga else "L" if gf < ga else "D")
    return {"sequence": "".join(out), "wins": out.count("W"), "draws": out.count("D"), "losses": out.count("L")}


def _team_card(conn, team: dict, limit: int = 1) -> dict:
    next_fx = db.rows(
        conn,
        """SELECT f.id, f.home_name, f.away_name, f.kickoff_utc, f.competition_id,
                  c.name AS competition_name, p.pick, p.pick_prob, p.confidence, p.data_depth
           FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
           LEFT JOIN predictions p ON p.fixture_id=f.id
           WHERE f.status='scheduled' AND f.kickoff_utc>=?
             AND (f.home_team_id=? OR f.away_team_id=?)
           ORDER BY f.kickoff_utc ASC LIMIT ?""",
        (_iso(_now() - timedelta(minutes=10)), team["id"], team["id"], limit),
    )
    recent = db.rows(
        conn,
        """SELECT home_team_id, away_team_id, home_score_num, away_score_num, kickoff_utc
           FROM fixtures WHERE sport=? AND status='finished'
             AND (home_team_id=? OR away_team_id=?)
           ORDER BY kickoff_utc DESC LIMIT 6""",
        (team["sport"], team["id"], team["id"]),
    )
    return {**team, "next_fixtures": next_fx, "form": _form_from_rows(team["id"], recent),
            "recent_results": recent[:6]}


def search_all(q: str, limit: int = 20) -> dict:
    q = (q or "").strip()
    if len(q) < 2:
        return {"query": q, "teams": [], "competitions": [], "fixtures": [], "message": "type at least 2 characters"}
    norm = _norm_query(q)
    like = f"%{norm}%"
    with db.db() as conn:
        teams = db.rows(
            conn,
            """SELECT id, sport, name, short_name, country, logo FROM teams
               WHERE lower(name) LIKE ? OR lower(short_name) LIKE ?
               ORDER BY CASE WHEN lower(name)=? THEN 0 WHEN lower(name) LIKE ? THEN 1 ELSE 2 END, name
               LIMIT ?""",
            (like, like, norm, f"{norm}%", limit),
        )
        if not teams:
            # fuzzy fallback for misspellings and aliases
            all_teams = db.rows(conn, "SELECT id, sport, name, short_name, country, logo FROM teams")
            scored = []
            for t in all_teams:
                key = _norm_query(t.get("name") or "")
                ratio = difflib.SequenceMatcher(None, norm, key).ratio()
                if norm in key or key in norm:
                    ratio = max(ratio, 0.92)
                if ratio >= 0.66:
                    scored.append((ratio, t))
            scored.sort(key=lambda x: (-x[0], x[1]["name"]))
            teams = [t for _, t in scored[:limit]]
        team_cards = [_team_card(conn, t, 1) for t in teams]
        comps = db.rows(
            conn,
            """SELECT id, sport, name, country, logo FROM competitions
               WHERE lower(name) LIKE ?
               ORDER BY CASE WHEN lower(name)=? THEN 0 WHEN lower(name) LIKE ? THEN 1 ELSE 2 END, name
               LIMIT ?""",
            (like, norm, f"{norm}%", min(limit, 12)),
        )
        fixtures = db.rows(
            conn,
            """SELECT f.id, f.sport, f.home_name, f.away_name, f.kickoff_utc,
                      c.name AS competition_name, p.pick, p.pick_prob, p.confidence
               FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
               LEFT JOIN predictions p ON p.fixture_id=f.id
               WHERE f.status='scheduled' AND f.kickoff_utc>=?
                 AND (lower(f.home_name) LIKE ? OR lower(f.away_name) LIKE ? OR lower(c.name) LIKE ?)
               ORDER BY f.kickoff_utc ASC LIMIT ?""",
            (_iso(_now() - timedelta(minutes=10)), like, like, like, min(limit, 12)),
        )
    return {"query": q, "normalised": norm, "teams": team_cards,
            "competitions": comps, "fixtures": fixtures}


def team_detail(team_id: str) -> dict | None:
    with db.db() as conn:
        team = db.row(conn, "SELECT * FROM teams WHERE id=?", (team_id,))
        if not team:
            return None
        card = _team_card(conn, team, 8)
        rating = db.row(conn, "SELECT * FROM team_ratings WHERE team_id=?", (team_id,))
        comps = db.rows(
            conn,
            """SELECT c.id, c.name, c.country, count(*) n
               FROM fixtures f JOIN competitions c ON c.id=f.competition_id
               WHERE f.home_team_id=? OR f.away_team_id=?
               GROUP BY c.id ORDER BY n DESC LIMIT 8""",
            (team_id, team_id),
        )
        upcoming = db.rows(
            conn,
            """SELECT f.id, f.home_name, f.away_name, f.kickoff_utc, f.importance,
                      c.name AS competition_name, p.pick, p.pick_prob, p.confidence, p.data_depth
               FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
               LEFT JOIN predictions p ON p.fixture_id=f.id
               WHERE f.status='scheduled' AND f.kickoff_utc>=?
                 AND (f.home_team_id=? OR f.away_team_id=?)
               ORDER BY f.kickoff_utc ASC LIMIT 12""",
            (_iso(_now() - timedelta(minutes=10)), team_id, team_id),
        )
        recent = db.rows(
            conn,
            """SELECT f.id, f.home_name, f.away_name, f.kickoff_utc, f.home_score_num,
                      f.away_score_num, f.score_detail, c.name AS competition_name
               FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
               WHERE f.status='finished' AND (f.home_team_id=? OR f.away_team_id=?)
               ORDER BY f.kickoff_utc DESC LIMIT 10""",
            (team_id, team_id),
        )
    if rating:
        for key in ("form", "metadata"):
            if isinstance(rating.get(key), str):
                rating[key] = db.json_loads(rating[key], [] if key == "form" else {})
    return {"team": team, "card": card, "rating": rating, "competitions": comps,
            "upcoming": upcoming, "recent": recent}


def build_model_slip(stake: float = 100.0, threshold: float = 0.90, days: int = 7,
                      sport: str | None = None, max_legs: int = 5,
                      min_confidence: float = 45.0, market_types: str | None = None) -> dict:
    """Build a slip from model-generated match markets and fair odds.

    The engine keeps the legacy 1X2 model result as a fallback, but it also uses
    the full market catalogue already stored on each prediction (e.g. totals, BTTS,
    double chance, and Asian handicap). Combined probability is still the product
    of the selected legs for compatibility with the historical API contract, while
    the separate correlation-adjusted probability exposes a more conservative view
    when multiple legs come from the same fixture or market family.
    """
    stake = max(1.0, float(stake or 100))
    threshold = max(0.01, min(0.99, float(threshold or 0.90)))
    now = _now()
    where = ["f.status='scheduled'", "f.kickoff_utc>=?", "f.kickoff_utc<=?",
              "p.pick_prob IS NOT NULL", "p.confidence>=?"]
    params = [_iso(now - timedelta(minutes=10)), _iso(now + timedelta(days=days)), min_confidence]
    if sport in ("football", "cricket"):
        where.append("f.sport=?")
        params.append(sport)
    with db.db() as conn:
        rows = db.rows(
            conn,
            f"""SELECT f.id, f.sport, f.home_name, f.away_name, f.kickoff_utc, f.importance,
                        c.name AS competition_name, p.pick, p.pick_side, p.pick_prob, p.pick_fair,
                        p.confidence, p.data_depth, p.home_prob, p.draw_prob, p.away_prob,
                        p.markets
                FROM predictions p JOIN fixtures f ON f.id=p.fixture_id
                LEFT JOIN competitions c ON c.id=f.competition_id
                WHERE {' AND '.join(where)}
                ORDER BY p.pick_prob DESC, p.confidence DESC LIMIT 600""",
            params,
        )
    if not rows:
        return {"policy": "model-fair-odds", "stake": stake, "threshold": threshold,
                "legs": [], "combined_probability": 0.0, "meets_threshold": False,
                "message": "No predictions available for this filter."}

    allowed_market_types = set()
    if market_types:
        allowed_market_types = {item.strip().lower() for item in str(market_types).split(',') if item.strip()}

    def _clip_prob(value: Any) -> float | None:
        try:
            prob = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(prob):
            return None
        prob = max(0.01, min(0.99, prob))
        return prob

    def _market_group_name(market: dict) -> str:
        return str((market.get("group") or market.get("type") or market.get("market_group") or "special")).lower()

    def _selection_name(market: dict, fallback: str) -> str:
        selection = market.get("selection") or market.get("label") or market.get("name")
        if selection:
            return str(selection)
        return fallback

    def _market_label(market: dict, fallback: str) -> str:
        label = market.get("label") or market.get("name") or market.get("selection")
        if label:
            return str(label)
        return fallback

    seen_keys: set[tuple[str, str, str]] = set()
    candidates: list[dict] = []
    for row in rows:
        fixture_id = str(row["id"])
        home = row.get("home_name") or "Home"
        away = row.get("away_name") or "Away"
        match_name = f"{home} vs {away}"
        markets = db.json_loads(row.get("markets"), []) or []
        if not isinstance(markets, list):
            markets = []
        if markets:
            for market in markets:
                if not isinstance(market, dict):
                    continue
                prob = _clip_prob(market.get("probability"))
                if prob is None:
                    continue
                group = _market_group_name(market)
                if allowed_market_types and group not in allowed_market_types:
                    continue
                row_key = (fixture_id, str(market.get("key") or market.get("label") or market.get("selection") or market.get("name") or ""), group)
                if row_key in seen_keys:
                    continue
                seen_keys.add(row_key)
                fair = 1.0 / max(prob, 1e-6)
                confidence = float(row.get("confidence") or 0)
                candidates.append({
                    "fixture_id": fixture_id,
                    "match": match_name,
                    "competition": row.get("competition_name"),
                    "kickoff": row.get("kickoff_utc"),
                    "sport": row["sport"],
                    "market": _market_label(market, "model market"),
                    "market_group": group,
                    "selection": _selection_name(market, row.get("pick") or "Model pick"),
                    "probability": round(prob, 4),
                    "fair_odds": round(fair, 3),
                    "confidence": float(confidence),
                    "depth": row.get("data_depth") or "model",
                    "reason": f"{group} market · model {prob * 100:.1f}% · confidence {confidence:.0f} · {row.get('data_depth') or 'model'} research",
                })
        if not allowed_market_types or "result" in allowed_market_types:
            key = (fixture_id, "1x2_pick", "result")
            if key not in seen_keys:
                pick_prob = _clip_prob(row.get("pick_prob"))
                if pick_prob is not None:
                    seen_keys.add(key)
                    fair = 1.0 / max(pick_prob, 1e-6)
                    confidence = float(row.get("confidence") or 0)
                    candidates.append({
                        "fixture_id": fixture_id,
                        "match": match_name,
                        "competition": row.get("competition_name"),
                        "kickoff": row.get("kickoff_utc"),
                        "sport": row["sport"],
                        "market": "1X2 / model result",
                        "market_group": "result",
                        "selection": row.get("pick") or "Model pick",
                        "probability": round(pick_prob, 4),
                        "fair_odds": round(fair, 3),
                        "confidence": float(confidence),
                        "depth": row.get("data_depth") or "model",
                        "reason": f"model {pick_prob * 100:.1f}% · confidence {confidence:.0f} · {row.get('data_depth') or 'model'} research",
                    })

    if not candidates:
        return {"policy": "model-fair-odds", "stake": stake, "threshold": threshold,
                "legs": [], "combined_probability": 0.0, "meets_threshold": False,
                "message": "No valid market probabilities were available for this filter."}

    depth_weight = {"full": 1.0, "enhanced": 0.8, "model": 0.6, "partial": 0.4}
    for leg in candidates:
        quality = depth_weight.get(str(leg.get("depth") or "model").lower(), 0.6)
        leg["score"] = float(leg["probability"]) * (0.65 + 0.35 * quality) + 0.02 * (leg["confidence"] / 100.0)
    candidates.sort(key=lambda leg: leg["score"], reverse=True)

    selected: list[dict] = []
    combined = 1.0
    for leg in candidates:
        if len(selected) >= max_legs:
            break
        next_prob = combined * leg["probability"]
        if not selected:
            selected.append(leg)
            combined = leg["probability"]
            continue
        if next_prob >= threshold:
            selected.append(leg)
            combined = next_prob
        else:
            break
    if not selected:
        selected = [candidates[0]]
        combined = float(selected[0]["probability"])

    legs = []
    for leg in selected:
        legs.append({
            "fixture_id": leg["fixture_id"],
            "match": leg["match"],
            "competition": leg.get("competition"),
            "kickoff": leg.get("kickoff"),
            "sport": leg["sport"],
            "market": leg["market"],
            "market_group": leg["market_group"],
            "selection": leg["selection"],
            "probability": round(float(leg["probability"]), 4),
            "fair_odds": round(float(leg["fair_odds"]), 3),
            "confidence": leg.get("confidence"),
            "depth": leg.get("depth"),
            "reason": leg.get("reason"),
        })

    combined_probability = 1.0
    total_odds = 1.0
    for leg in legs:
        combined_probability *= leg["probability"]
        total_odds *= leg["fair_odds"]
    combined_probability = round(combined_probability, 6)
    total_odds = round(total_odds, 3)

    same_fixture_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for leg in legs:
        same_fixture_counts[leg["fixture_id"]] = same_fixture_counts.get(leg["fixture_id"], 0) + 1
        group_counts[leg["market_group"]] = group_counts.get(leg["market_group"], 0) + 1
    same_fixture_bonus = sum(max(0, count - 1) for count in same_fixture_counts.values())
    same_group_bonus = sum(max(0, count - 1) for count in group_counts.values())
    correlation_adjustment = max(0.68, 1.0 - (0.12 * same_fixture_bonus) - (0.08 * same_group_bonus))
    adjusted_probability = min(0.9999, max(0.0001, combined_probability * correlation_adjustment))

    potential_return = round(stake * total_odds, 2)
    potential_profit = round(potential_return - stake, 2)
    weakest = min(legs, key=lambda x: x["probability"]) if legs else None
    meets = combined_probability >= threshold
    weakest_depth = str((weakest or {}).get("depth") or "model").lower()
    weakest_conf = float((weakest or {}).get("confidence") or 0)
    if adjusted_probability < 0.55 or (weakest_depth in ("model", "partial") and weakest_conf < 65):
        risk = "High (thin research or low combined probability)"
    elif adjusted_probability < 0.85:
        risk = "Medium"
    else:
        risk = "Lower (not safe)"
    return {
        "policy": "model-fair-odds",
        "market_note": "Fair odds = 1 / model probability. Multi-market legs come from the model's live market catalogue; same-match and same-group selections are shown with a correlation adjustment for risk control. No bookmaker odds are read.",
        "stake": stake,
        "threshold": threshold,
        "meets_threshold": meets,
        "legs": legs,
        "combined_probability": combined_probability,
        "combined_fair_odds": total_odds,
        "correlation_adjustment": round(correlation_adjustment, 4),
        "correlation_adjusted_probability": round(adjusted_probability, 6),
        "potential_return": potential_return,
        "potential_profit": potential_profit,
        "weakest_leg": weakest,
        "risk": risk,
        "market_types": sorted({leg["market_group"] for leg in legs}),
        "data_quality": {d: sum(1 for x in legs if str(x["depth"]).lower() == d) for d in ("full", "enhanced", "model", "partial")},
        "message": ("Slip meets the model-probability threshold." if meets else
                    f"No slip meets the {threshold * 100:.0f}% threshold. The closest realistic slip is shown; "
                    f"its combined probability is {combined_probability * 100:.1f}% and its correlation-adjusted probability is {adjusted_probability * 100:.1f}%.")
    }


# ---------------------------------------------------------------------------
# Evidence-first team comparison
# ---------------------------------------------------------------------------

def _comparison_rows(conn, team_id: str, before: str, side: str | None = None,
                     limit: int = 10) -> list[dict]:
    where = ["f.status='finished'", "f.kickoff_utc < ?", "(f.home_team_id=? OR f.away_team_id=?)"]
    params: list[Any] = [before, team_id, team_id]
    if side == "home":
        where.append("f.home_team_id=?")
        params.append(team_id)
    elif side == "away":
        where.append("f.away_team_id=?")
        params.append(team_id)
    params.append(limit)
    return db.rows(
        conn,
        f"""SELECT f.id, f.home_team_id, f.away_team_id, f.home_name, f.away_name,
                   f.home_score_num, f.away_score_num, f.score_detail, f.kickoff_utc,
                   f.venue, c.name AS competition_name
            FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
            WHERE {' AND '.join(where)}
            ORDER BY f.kickoff_utc DESC LIMIT ?""",
        params,
    )


def _summarise_comparison(team_id: str, team_name: str, rows: list[dict], sport: str) -> dict:
    results = []
    gf = ga = 0.0
    wins = draws = losses = 0
    for r in rows:
        home = r["home_team_id"] == team_id
        scored = r["home_score_num"] if home else r["away_score_num"]
        conceded = r["away_score_num"] if home else r["home_score_num"]
        if sport == "football" and (scored is None or conceded is None):
            continue
        result = "?" if scored is None or conceded is None else "W" if scored > conceded else "L" if scored < conceded else "D"
        wins += result == "W"
        draws += result == "D"
        losses += result == "L"
        gf += scored or 0
        ga += conceded or 0
        results.append({
            "date": r["kickoff_utc"], "opponent": r["away_name"] if home else r["home_name"],
            "venue": "H" if home else "A", "score": f"{int(scored)}–{int(conceded)}" if scored is not None and conceded is not None else (r.get("score_detail") or "—"),
            "result": result, "competition": r.get("competition_name"),
        })
    n = max(1, len(results))
    dates = [r["kickoff_utc"] for r in rows if r.get("kickoff_utc")]
    return {
        "team": team_name, "matches": len(results),
        "wins": wins, "draws": draws, "losses": losses,
        "scored": round(gf, 1), "conceded": round(ga, 1),
        "scored_per_match": round(gf / n, 2), "conceded_per_match": round(ga / n, 2),
        "ppg": round((wins * 3 + draws) / n, 2),
        "sequence": "".join(x["result"] for x in results),
        "date_from": dates[-1] if dates else None, "date_to": dates[0] if dates else None,
        "recent": results,
    }


def team_comparison(fixture: dict) -> dict:
    before = fixture["kickoff_utc"]
    sport = fixture["sport"]
    with db.db() as conn:
        def rest(team_id):
            row = db.row(conn, """SELECT kickoff_utc FROM fixtures
                                  WHERE sport=? AND status='finished' AND kickoff_utc < ?
                                    AND (home_team_id=? OR away_team_id=?)
                                  ORDER BY kickoff_utc DESC LIMIT 1""",
                         (sport, before, team_id, team_id))
            if not row:
                return None
            try:
                last = datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
                ko = datetime.fromisoformat(before.replace("Z", "+00:00"))
                return round((ko - last).total_seconds() / 86400, 1)
            except Exception:
                return None

        def block(team_id, team_name, side):
            recent = _comparison_rows(conn, team_id, before, None, 10)
            split = _comparison_rows(conn, team_id, before, side, 10)
            return {
                "overall_10": _summarise_comparison(team_id, team_name, recent, sport),
                "overall_5": _summarise_comparison(team_id, team_name, recent[:5], sport),
                "split_10": _summarise_comparison(team_id, team_name, split, sport),
                "rest_days": rest(team_id),
            }

        home = block(fixture["home_team_id"], fixture["home_name"], "home")
        away = block(fixture["away_team_id"], fixture["away_name"], "away")
    return {
        "home": home, "away": away, "sport": sport,
        "source": "ORACLE local results warehouse (FotMob results + Cricbuzz results)",
        "limits": {
            "xg": "Unavailable — the public fixture feed does not provide historical xG",
            "shots": "Unavailable — the public fixture feed does not provide shots/shot volume",
            "lineups": "Unavailable unless the match centre publishes a confirmed XI",
            "competitions": "All competitions in the local warehouse; competition mix may differ between teams.",
        },
        "as_of": _iso(_now()),
    }
