"""Cricsheet open-data adapter for historical cricket results.

Cricsheet is the canonical open ball-by-ball archive. We use the small
`recently_played_30_json.zip` snapshot for current team/venue form, with an
optional deep archive for backtesting.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings
from ..db import upsert_history
from .http import make_client

URLS = {
    "recent": "https://cricsheet.org/downloads/recently_played_30_json.zip",
    "t20": "https://cricsheet.org/downloads/t20s_json.zip",
    "odi": "https://cricsheet.org/downloads/odis_json.zip",
    "test": "https://cricsheet.org/downloads/tests_json.zip",
}


def _zip_path(kind: str):
    return settings.cache_dir / f"cricsheet_{kind}.zip"


def _score(innings: list[dict], team: str) -> tuple[float | None, float | None]:
    runs = 0.0
    wickets = 0.0
    found = False
    for inn in innings:
        if inn.get("team") != team:
            continue
        found = True
        runs += float((inn.get("runs") or {}).get("total") or 0)
        wickets += float((inn.get("runs") or {}).get("wickets") or 0)
    return (runs, wickets) if found else (None, None)


def parse_match(stem: str, data: dict) -> dict | None:
    info = data.get("info") or {}
    teams = info.get("teams") or []
    if len(teams) < 2:
        return None
    dates = info.get("dates") or []
    outcome = info.get("outcome") or {}
    winner = outcome.get("winner")
    event = info.get("event") or {}
    innings = data.get("innings") or []
    hs, hw = _score(innings, teams[0])
    as_, aw = _score(innings, teams[1])
    return {
        "id": f"crc:{stem}", "sport": "cricket",
        "competition": event.get("name") or info.get("series") or "International",
        "played_on": dates[0] if dates else None,
        "home_team": teams[0], "away_team": teams[1],
        "home_score": hs, "away_score": as_, "home_wickets": hw, "away_wickets": aw,
        "winner": winner,
        "venue": info.get("venue"), "city": info.get("city"),
        "format": (info.get("match_type") or "T20").upper(),
        "neutral": 1 if info.get("neutral_venue") else 0,
        "source": "cricsheet",
        "metadata": {
            "event": event, "toss": info.get("toss"), "overs": info.get("overs"),
            "player_of_match": info.get("player_of_match"), "gender": info.get("gender"),
            "team_type": info.get("team_type"), "outcome": outcome,
            "dates": dates,
            "innings": [{"team": i.get("team"), "runs": (i.get("runs") or {}).get("total"),
                         "wickets": (i.get("runs") or {}).get("wickets"),
                         "balls": (i.get("runs") or {}).get("balls")} for i in innings],
        },
    }


async def download(kind: str = "recent") -> bool:
    path = _zip_path(kind)
    if path.exists() and path.stat().st_size > 1000:
        return True
    async with make_client() as client:
        try:
            r = await client.get(URLS[kind], timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
            return True
        except Exception:
            return False


async def ingest(kind: str = "recent", max_files: int | None = None) -> dict:
    from .. import db

    ok = await download(kind)
    if not ok:
        db.log("warn", "cricsheet", f"download failed for {kind}")
        return {"matches": 0, "error": "download failed"}
    path = _zip_path(kind)
    count = 0
    skipped = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * 2)
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json") and not n.startswith("__")]
        names.sort()
        if max_files:
            names = names[-max_files:]
        with db.db() as conn:
            for name in names:
                try:
                    data = json.loads(zf.read(name).decode("utf-8"))
                    rec = parse_match(name.rsplit("/", 1)[-1].replace(".json", ""), data)
                    if not rec:
                        skipped += 1
                        continue
                    if kind != "recent" and rec.get("played_on"):
                        try:
                            dt = datetime.fromisoformat(rec["played_on"]).replace(tzinfo=timezone.utc)
                            if dt < cutoff:
                                skipped += 1
                                continue
                        except Exception:
                            pass
                    upsert_history(conn, rec)
                    count += 1
                except Exception:
                    skipped += 1
    db.log("info", "cricsheet", f"ingested {count} historical cricket matches ({kind})",
           {"skipped": skipped})
    return {"matches": count, "skipped": skipped, "kind": kind}
