"""Background automation loop."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from . import db, pipeline
from .config import settings

_STARTED = False
_THREAD: threading.Thread | None = None
_LAST_SETTLE = 0.0
_LAST_SWEEP = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _due() -> bool:
    last = db.get_state("last_sync", {}) or {}
    at = last.get("at") if isinstance(last, dict) else None
    if not at:
        return True
    try:
        last_dt = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except Exception:
        return True
    return _now() - last_dt > timedelta(minutes=settings.fixtures_refresh_minutes)


def loop() -> None:
    db.log("info", "scheduler", "automation loop started",
           {"tick": settings.tick_seconds, "window_days": settings.window_days})
    while True:
        try:
            if _due():
                db.log("info", "scheduler", "scheduled cycle triggered")
                pipeline.run_full_sync()
                db.set_state("next_sync", _iso(_now() + timedelta(minutes=settings.fixtures_refresh_minutes)))
            else:
                # Settle finished matches every five minutes so the review ledger
                # stays current even between full discovery cycles.
                global _LAST_SETTLE, _LAST_SWEEP
                if time.time() - _LAST_SWEEP > 300 and not pipeline._SYNC_LOCK.locked():
                    try:
                        pipeline.research_sweep(25)
                    except Exception as exc:  # noqa: BLE001
                        db.log("warn", "sweep", f"sweep error: {exc}")
                    _LAST_SWEEP = time.time()
                if time.time() - _LAST_SETTLE > 300:
                    try:
                        pipeline.settle_predictions()
                    except Exception as exc:  # noqa: BLE001
                        db.log("warn", "settle", f"settlement error: {exc}")
                    _LAST_SETTLE = time.time()
                # Lightweight freshness check: if no predictions exist for some
                # fixtures inside the window, queue a cycle sooner.
                with db.db() as conn:
                    missing = db.scalar(
                        conn,
                        """SELECT count(*) FROM fixtures f
                           LEFT JOIN predictions p ON p.fixture_id=f.id
                           WHERE f.status='scheduled' AND p.fixture_id IS NULL
                             AND f.kickoff_utc>=? AND f.kickoff_utc<=?""",
                        (_iso(_now() - timedelta(minutes=5)),
                         _iso(_now() + timedelta(days=settings.window_days))),
                    )
                if missing and missing > 50:
                    db.log("info", "scheduler", f"{missing} fixtures lack predictions; queueing cycle")
                    pipeline.run_full_sync()
        except Exception as exc:  # noqa: BLE001
            db.log("error", "scheduler", f"loop error: {exc}")
        time.sleep(max(15, settings.tick_seconds))


def start() -> None:
    global _STARTED, _THREAD
    if _STARTED or not settings.scheduler_enabled:
        return
    _STARTED = True
    _THREAD = threading.Thread(target=loop, name="oracle-scheduler", daemon=True)
    _THREAD.start()


def status() -> dict:
    last = db.get_state("last_sync", {}) or {}
    next_sync = db.get_state("next_sync")
    return {
        "enabled": settings.scheduler_enabled,
        "running": bool(_THREAD and _THREAD.is_alive()),
        "tick_seconds": settings.tick_seconds,
        "refresh_minutes": settings.fixtures_refresh_minutes,
        "window_days": settings.window_days,
        "last_sync": last,
        "next_sync": next_sync,
        "server_time": _iso(_now()),
    }
