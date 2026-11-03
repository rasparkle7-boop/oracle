"""Cricbuzz public schedule adapter.

Cricbuzz renders its schedule into a React Server Component payload. We parse
the embedded JSON (no browser required) to discover every match in the active
international, franchise and domestic series. No betting markets are read.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings
from ..db import upsert_competition, upsert_fixture, upsert_team
from .http import fetch_text, gather_limited, make_client

BASE = "https://www.cricbuzz.com"
SCHEDULE_CATEGORIES = ("international", "league", "domestic")
RSC_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.S)

SERIES_IMPORTANCE = (
    ("world cup", 0.98), ("ashes", 0.96), ("champions trophy", 0.94), ("ipl", 0.96),
    ("indian premier league", 0.96), ("big bash", 0.88), ("bbl", 0.88), ("psl", 0.86),
    ("pakistan super league", 0.86), ("sa20", 0.84), ("ilt20", 0.82), ("caribbean premier", 0.82),
    ("cpl", 0.82), ("the hundred", 0.84), ("lanka premier", 0.72), ("nepal premier", 0.68),
    ("ranji", 0.6), ("sheffield shield", 0.62), ("county championship", 0.62),
    ("tour of", 0.8), ("vs", 0.72), ("tri-series", 0.76), ("t20 challenge", 0.62),
)


def _importance(series: str, fmt: str, match_type: str) -> float:
    s = (series or "").lower()
    score = 0.6
    for key, val in SERIES_IMPORTANCE:
        if key in s:
            score = max(score, val)
    if "women" in s:
        score -= 0.1
    if "u19" in s or "u23" in s or "emerging" in s:
        score -= 0.18
    if (match_type or "").lower() == "domestic":
        score -= 0.05
    if fmt == "TEST":
        score += 0.03
    return round(max(0.2, min(0.99, score)), 2)


def parse_rsc(html: str) -> str:
    chunks = RSC_RE.findall(html)
    out = []
    for chunk in chunks:
        try:
            out.append(json.loads('"' + chunk + '"'))
        except Exception:
            continue
    return "".join(out)


def extract_match_infos(html: str) -> list[dict]:
    """Return full match objects: {"matchInfo": {...}, "matchScore": {...}}."""
    text = parse_rsc(html)
    found: dict[int, dict] = {}
    for match in re.finditer(r'\{"matchInfo":', text):
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[match.start():])
        except Exception:
            continue
        info = obj.get("matchInfo") if isinstance(obj, dict) else None
        if isinstance(info, dict) and "matchId" in info:
            mid = info.get("matchId")
            if mid is not None and mid not in found:
                found[mid] = obj
    return list(found.values())


def discover_series(html: str) -> list[dict]:
    links = sorted(set(re.findall(r'/cricket-series/(\d+)/([a-z0-9-]+)', html)))
    seen: dict[str, str] = {}
    for sid, slug in links:
        seen.setdefault(sid, slug)
    return [{"id": sid, "slug": slug} for sid, slug in seen.items()]


def _ms(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc)
    except Exception:
        return None


def _score_block(block: dict | None) -> tuple[str | None, float | None, float | None]:
    if not block:
        return None, None, None
    innings = [v for k, v in block.items() if isinstance(v, dict) and "runs" in v]
    if not innings:
        return None, None, None
    last = innings[-1]
    runs = last.get("runs")
    wkts = last.get("wickets")
    overs = last.get("overs")
    if runs is None:
        return None, None, None
    txt = f"{runs}"
    if wkts is not None:
        txt += f"/{wkts}"
    if overs is not None:
        txt += f" ({overs})"
    return txt, float(runs), (float(wkts) if wkts is not None else None)


def _status(info: dict) -> str:
    state = (info.get("state") or "").lower()
    status = (info.get("status") or "").lower()
    if state in ("complete", "finished", "result"):
        return "finished"
    if any(k in state for k in ("stumps", "innings break", "live", "tea", "lunch", "rain", "delay",
                                "drinks", "day", "break", "abandon", "no result")):
        return "live"
    if any(k in status for k in ("won by", "drawn", "no result", "abandon", "tied")):
        return "finished"
    if any(k in status for k in ("starts at", "starts in", "preview", "upcoming", "yet to")):
        return "scheduled"
    return "scheduled"


def _winner(info: dict, home: str, away: str) -> str | None:
    status = info.get("status") or ""
    low = status.lower()
    if "drawn" in low or "no result" in low or "abandoned" in low:
        return None
    for name in (home, away):
        if low.startswith(name.lower() + " won") or f"{name.lower()} won" in low:
            return name
    return None


def _format(info: dict) -> str:
    return (info.get("matchFormat") or "T20").upper()


def normalise_matches(matches: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    comps: dict[str, dict] = {}
    teams: dict[str, dict] = {}
    fixtures: list[dict] = []
    for match in matches:
        info = match.get("matchInfo") or {}
        match_score = match.get("matchScore") or {}
        start = _ms(info.get("startDate"))
        if not start:
            continue
        series_id = info.get("seriesId")
        series = info.get("seriesName") or "Cricket"
        comp_id = f"cr:c{series_id}"
        fmt = _format(info)
        match_type = info.get("matchType") or "international"
        comps[comp_id] = {
            "id": comp_id, "sport": "cricket", "name": series,
            "country": "International" if match_type.lower() == "international" else "Domestic",
            "tier": 1 if _importance(series, fmt, match_type) >= 0.8 else 2,
            "logo": None, "source": "cricbuzz",
            "metadata": {"cricbuzz_series_id": series_id, "match_type": match_type},
        }
        t1 = info.get("team1") or {}
        t2 = info.get("team2") or {}
        if not t1.get("teamName") or not t2.get("teamName"):
            continue
        hid = f"cr:t{t1.get('teamId')}"
        aid = f"cr:t{t2.get('teamId')}"
        for tid, t in ((hid, t1), (aid, t2)):
            teams[tid] = {
                "id": tid, "sport": "cricket", "name": t.get("teamName"),
                "short_name": t.get("teamSName"), "country": None, "logo": None,
                "metadata": {"cricbuzz_team_id": t.get("teamId")},
            }
        s1, r1, _ = _score_block(match_score.get("team1Score"))
        s2, r2, _ = _score_block(match_score.get("team2Score"))
        state = _status(info)
        winner_name = _winner(info, t1.get("teamName"), t2.get("teamName"))
        winner_id = hid if winner_name == t1.get("teamName") else aid if winner_name == t2.get("teamName") else None
        venue = (info.get("venueInfo") or {})
        fixture = {
            "id": f"cr:{info.get('matchId')}", "sport": "cricket", "competition_id": comp_id,
            "season": str(start.year), "round": info.get("matchDesc"),
            "kickoff_utc": start.isoformat().replace("+00:00", "Z"), "status": state,
            "home_team_id": hid, "away_team_id": aid,
            "home_name": t1.get("teamName"), "away_name": t2.get("teamName"),
            "venue": venue.get("ground"), "city": venue.get("city"),
            "country": "International" if match_type.lower() == "international" else "Domestic",
            "home_score": s1, "away_score": s2, "home_score_num": r1, "away_score_num": r2,
            "score_detail": info.get("status") or info.get("stateTitle") or "",
            "winner_team_id": winner_id,
            "source": "cricbuzz",
            "source_url": f"https://www.cricbuzz.com/cricket-series/{series_id}",
            "importance": _importance(series, fmt, match_type),
            "raw": {"format": fmt, "match_type": match_type, "state": info.get("state"),
                    "series_id": series_id, "match_desc": info.get("matchDesc"),
                    "is_time_announced": info.get("isTimeAnnounced"),
                    "end_date": info.get("endDate")},
        }
        fixtures.append(fixture)
    return list(comps.values()), list(teams.values()), fixtures


async def _fetch_series(client: httpx.AsyncClient, item: dict) -> list[dict]:
    url = f"{BASE}/cricket-series/{item['id']}/{item['slug']}/matches"
    html = await fetch_text(client, url, cache_key=f"cricbuzz:series:{item['id']}", ttl=1800)
    infos = extract_match_infos(html)
    return [m for m in infos if str((m.get("matchInfo") or {}).get("seriesId")) == str(item["id"])]


async def discover_and_sync() -> dict:
    from .. import db

    async with make_client() as client:
        pages = await gather_limited(
            [lambda cat=category: fetch_text(client, f"{BASE}/cricket-schedule/upcoming-series/{cat}",
                                      cache_key=f"cricbuzz:sched:{cat}", ttl=1800)
             for category in SCHEDULE_CATEGORIES],
            limit=3,
            on_error=lambda exc: db.log("warn", "cricbuzz", str(exc)[:200]),
        )
        series: dict[str, dict] = {}
        for html in pages:
            if not html:
                continue
            for item in discover_series(html):
                series.setdefault(item["id"], item)
        # the live page adds currently running series outside the schedule nav
        try:
            live_html = await fetch_text(client, f"{BASE}/cricket-match/live-scores",
                                          cache_key="cricbuzz:live", ttl=600)
            for item in discover_series(live_html):
                series.setdefault(item["id"], item)
        except Exception:
            pass

        results = await gather_limited(
            [lambda it=item: _fetch_series(client, it) for item in series.values()],
            limit=settings.cricket_workers,
            on_error=lambda exc: db.log("warn", "cricbuzz-series", str(exc)[:200]),
        )

    all_matches: dict[int, dict] = {}
    for matches in results:
        for m in matches or []:
            info = m.get("matchInfo") or {}
            if info.get("matchId") is not None:
                all_matches.setdefault(info["matchId"], m)
    comps, teams, fixtures = normalise_matches(list(all_matches.values()))
    with db.db() as conn:
        for comp in comps:
            upsert_competition(conn, comp)
        for team in teams:
            upsert_team(conn, team)
        for fx in fixtures:
            upsert_fixture(conn, fx)
    db.log("info", "cricbuzz", f"synced {len(fixtures)} cricket fixtures from {len(series)} series",
           {"series": len(series), "matches": len(fixtures)})
    return {"series": len(series), "fixtures": len(fixtures), "competitions": len(comps),
            "teams": len(teams)}
