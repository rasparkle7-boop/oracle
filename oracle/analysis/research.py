"""Context synthesis: injuries, availability, fatigue, weather, pitch, news.

This module converts heterogeneous public evidence into explicit model
adjustments. Every adjustment is bounded, auditable and exposed to the UI.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ..models import ratings
from ..ingest.weather import classify_cricket, classify_football


def _freshness(timestamp: str | None, threshold_hours: float) -> str:
    if not timestamp:
        return "unknown"
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return "fresh" if age <= threshold_hours else "stale"
    except Exception:
        return "unknown"


def _news_flags(items: list[dict]) -> dict:
    tags: dict[str, int] = {}
    for item in items or []:
        for tag in item.get("tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
    return tags


def _injury_impact(players: list[dict]) -> tuple[float, list[dict]]:
    total = 0.0
    normalised = []
    for p in players or []:
        value = float(p.get("market_value") or 0)
        base = 0.025 + 0.022 * math.log10(1 + value / 1_000_000)
        if p.get("type") == "suspension":
            base *= 1.15
        elif p.get("type") in ("doubt", "doubtful"):
            base *= 0.6
        base = min(0.11, base)
        total += base
        normalised.append({**p, "impact": round(base, 3)})
    return min(0.30, total), normalised


def build_context(fixture: dict, *, details: dict | None = None, news_home: list[dict] | None = None,
                  news_away: list[dict] | None = None, form_index: dict | None = None,
                  h2h_data: dict | None = None, venue_stats: dict | None = None,
                  weather: dict | None = None) -> dict:
    sport = fixture["sport"]
    details = details or {}
    news_home = news_home or []
    news_away = news_away or []
    form_index = form_index or {}
    h2h_data = h2h_data or {}
    venue_stats = venue_stats or {}
    weather = weather or details.get("weather") or {}

    home_form_matches = form_index.get(fixture.get("home_team_id"), [])
    away_form_matches = form_index.get(fixture.get("away_team_id"), [])
    home_form = ratings.form_summary(home_form_matches, 6)
    away_form = ratings.form_summary(away_form_matches, 6)
    home_fatigue = ratings.congestion(home_form_matches, fixture["kickoff_utc"])
    away_fatigue = ratings.congestion(away_form_matches, fixture["kickoff_utc"])
    home_flags = _news_flags(news_home)
    away_flags = _news_flags(news_away)

    home_unavail = (details.get("unavailable") or {}).get("home") or []
    away_unavail = (details.get("unavailable") or {}).get("away") or []
    home_impact, home_players = _injury_impact(home_unavail)
    away_impact, away_players = _injury_impact(away_unavail)

    # Unverified news injury signal only when structured availability is absent
    if not home_unavail:
        home_impact = min(0.12, 0.025 * home_flags.get("injury", 0))
    if not away_unavail:
        away_impact = min(0.12, 0.025 * away_flags.get("injury", 0))

    manager_change = bool(home_flags.get("manager") or away_flags.get("manager"))
    weather_info = {}
    pitch = {}
    adjustments: dict[str, float] = {}
    flags: list[str] = []

    if sport == "football":
        weather_info = weather or {}
        wx = classify_football(weather_info) if weather_info else {}
        if wx.get("flags"):
            flags.extend(wx["flags"])
        adjustments["weather_goal_effect"] = float(wx.get("goal_effect", 0.0))
        # availability (attack and defence split, bounded)
        adjustments["home_attack_mult"] = round(max(0.7, 1 - 0.55 * home_impact - 0.07 * home_fatigue["load"]), 3)
        # defence_mult multiplies the OPPONENT's expected goals: >1 means the
        # depleted side is easier to score against.
        adjustments["home_defence_mult"] = round(min(1.35, 1 + 0.38 * home_impact + 0.05 * home_fatigue["load"]), 3)
        adjustments["away_attack_mult"] = round(max(0.7, 1 - 0.55 * away_impact - 0.07 * away_fatigue["load"]), 3)
        adjustments["away_defence_mult"] = round(min(1.35, 1 + 0.38 * away_impact + 0.05 * away_fatigue["load"]), 3)
        if home_impact > 0.12:
            flags.append("home key absences")
        if away_impact > 0.12:
            flags.append("away key absences")
        if home_fatigue["load"] > 0.55:
            flags.append("home congestion")
        if away_fatigue["load"] > 0.55:
            flags.append("away congestion")
        if manager_change:
            flags.append("managerial instability")
    else:
        pitch = classify_cricket(weather, (fixture.get("raw") or {}).get("format") if isinstance(fixture.get("raw"), dict) else "T20")
        dew = float(pitch.get("dew_risk") or 0.0)
        flags.extend(pitch.get("flags") or [])
        adjustments["home_bat_mult"] = round(1 - 0.35 * home_impact, 3)
        adjustments["home_bowl_mult"] = round(1 - 0.30 * home_impact, 3)
        adjustments["away_bat_mult"] = round(1 - 0.35 * away_impact, 3)
        adjustments["away_bowl_mult"] = round(1 - 0.30 * away_impact, 3)
        if home_impact > 0.08:
            flags.append("home key player absence")
        if away_impact > 0.08:
            flags.append("away key player absence")

    depth = "model"
    signals = []
    if details:
        depth = "enhanced"
        signals.append("structured availability / venue data")
    if news_home or news_away:
        depth = "enhanced"
        signals.append("live news research")
    if details and (news_home or news_away):
        depth = "full"
    if not details and not (news_home or news_away):
        depth = "model"
    if (fixture.get("raw") or {}).get("coverage") == "lower" if isinstance(fixture.get("raw"), dict) else False:
        depth = "partial"

    citations = []
    if details:
        citations.append({"title": "FotMob match centre", "source": "FotMob",
                          "url": f"https://www.fotmob.com/matches/{str(fixture['id']).replace('fb:', '')}",
                          "type": "fixture"})
    for item in (news_home + news_away):
        if item.get("url"):
            citations.append({"title": item.get("title"), "source": item.get("source"),
                              "url": item.get("url"), "published": item.get("published"),
                              "type": "news"})
    if weather_info:
        citations.append({"title": "Weather forecast", "source": weather_info.get("source") or "Open-Meteo",
                          "url": "https://open-meteo.com/", "type": "weather"})
    # de-duplicate citations by url
    seen = set()
    unique_citations = []
    for c in citations:
        key = c.get("url")
        if key and key not in seen:
            seen.add(key)
            unique_citations.append(c)

    referee = {
        "name": details.get("referee"),
        "country": details.get("referee_country"),
        "matches": details.get("referee_matches"),
        "stats": details.get("referee_stats") or {},
    }
    latest_news = None
    for item in (news_home + news_away):
        if item.get("published") and (latest_news is None or item["published"] > latest_news):
            latest_news = item["published"]
    data_quality = [
        {"category": "Event", "status": "verified", "reliability": "High",
         "provider": "FotMob fixture feed", "last_updated": fixture.get("updated_at") or fixture.get("kickoff_utc"),
         "freshness": "scheduled", "missing": "",
         "notes": f"{fixture.get('home_name')} vs {fixture.get('away_name')} · {fixture.get('kickoff_utc')}"},
        {"category": "Lineups", "status": "confirmed" if details.get("lineups_available") else "not published",
         "reliability": "High" if details.get("lineups_available") else "Low",
         "provider": "FotMob match centre", "last_updated": context_fetched_at if (context_fetched_at := datetime.now(timezone.utc).isoformat()) else None,
         "freshness": _freshness(context_fetched_at, 6), "missing": "" if details.get("lineups_available") else "confirmed XI",
         "notes": "confirmed XI" if details.get("lineups_available") else "expected/projected XI unavailable"},
        {"category": "Injuries", "status": "structured" if (home_players or away_players) else
         ("news only" if (home_flags.get("injury") or away_flags.get("injury")) else "no verified report"),
         "reliability": "High" if (home_players or away_players) else "Low",
         "provider": "FotMob availability + Google News", "last_updated": context_fetched_at,
         "freshness": _freshness(context_fetched_at, 24), "missing": "" if (home_players or away_players) else "structured absence list",
         "notes": f"{len(home_players)} home · {len(away_players)} away structured absences"},
        {"category": "Form", "status": f"{home_form.get('matches', 0)}/{away_form.get('matches', 0)} matches",
         "reliability": "Medium" if min(home_form.get("matches", 0), away_form.get("matches", 0)) < 4 else "High",
         "provider": "ORACLE local results warehouse", "last_updated": (home_form.get("recent") or [{}])[0].get("kickoff") if home_form.get("recent") else None,
         "freshness": _freshness((home_form.get("recent") or [{}])[0].get("kickoff") if home_form.get("recent") else None, 24 * 7),
         "missing": "" if min(home_form.get("matches", 0), away_form.get("matches", 0)) >= 4 else "sample size",
         "notes": f"{home_form.get('sequence', '—')} vs {away_form.get('sequence', '—')}"},
        {"category": "Tactics", "status": "partial" if (details.get("formation") or manager_change) else "not verified",
         "reliability": "Medium" if details.get("formation") else "Low",
         "provider": "FotMob match centre", "last_updated": context_fetched_at,
         "freshness": _freshness(context_fetched_at, 24), "missing": "" if details.get("formation") else "formation/lineup structure",
         "notes": "formation/manager signal" if details.get("formation") else "no verified tactical feed"},
        {"category": "Weather", "status": "forecast" if weather_info else "unavailable",
         "reliability": "Medium" if weather_info else "Low",
         "provider": "Open-Meteo / FotMob", "last_updated": weather_info.get("updated") or context_fetched_at,
         "freshness": _freshness(weather_info.get("updated") or context_fetched_at, 6), "missing": "" if weather_info else "weather forecast",
         "notes": weather_info.get("description") or "no forecast attached"},
        {"category": "Venue/travel", "status": "verified" if (details.get("stadium") or fixture.get("venue")) else "partial",
         "reliability": "High" if details.get("stadium") else "Medium",
         "provider": "FotMob match centre", "last_updated": context_fetched_at,
         "freshness": _freshness(context_fetched_at, 24 * 30), "missing": "" if (details.get("stadium") or fixture.get("venue")) else "venue",
         "notes": details.get("stadium") or fixture.get("venue") or "venue not published"},
        {"category": "Referee", "status": "assigned" if referee["name"] else "not assigned",
         "reliability": "High" if referee["name"] and referee["stats"] else "Medium" if referee["name"] else "Low",
         "provider": "FotMob match centre", "last_updated": context_fetched_at,
         "freshness": _freshness(context_fetched_at, 24), "missing": "" if referee["name"] else "referee assignment",
         "notes": referee["name"] or "no referee published"},
        {"category": "News", "status": "sourced" if (news_home or news_away) else "none",
         "reliability": "Medium" if (news_home or news_away) else "Low",
         "provider": "Google News RSS / ESPN", "last_updated": latest_news,
         "freshness": _freshness(latest_news, 24), "missing": "" if (news_home or news_away) else "news coverage",
         "notes": f"{len(news_home)} home · {len(news_away)} away articles"},
        {"category": "Market data", "status": "benchmark-only", "reliability": "n/a",
         "provider": "ESPN public odds / DraftKings (optional Odds Bench)", "last_updated": None,
         "freshness": "benchmark", "missing": "not used by core model",
         "notes": "ORACLE core is market-free; prices are isolated in the Odds Bench tab"},
    ]
    data_gaps = [q["category"] + ": " + q["status"] for q in data_quality
                 if q["status"] in ("not published", "no verified report", "not verified", "unavailable", "none", "not assigned")]
    return {
        "depth": depth,
        "signals": signals,
        "data_quality": data_quality,
        "data_gaps": data_gaps,
        "data_cutoff": datetime.now(timezone.utc).isoformat(),
        "market_policy": "market-free",
        "referee": referee,
        "lineups": {
            "available": bool(details.get("lineups_available")),
            "status": "confirmed" if details.get("lineups_available") else "not_confirmed",
            "type": details.get("lineup_type") or "unavailable",
            "home_starters": (details.get("starters") or {}).get("home") or [],
            "away_starters": (details.get("starters") or {}).get("away") or [],
            "home_formation": (details.get("formation") or {}).get("home"),
            "away_formation": (details.get("formation") or {}).get("away"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "flags": sorted(set(flags)),
        "adjustments": adjustments,
        "injuries": {"home": home_players, "away": away_players,
                     "home_impact": round(home_impact, 3), "away_impact": round(away_impact, 3)},
        "news": {"home": news_home[:8], "away": news_away[:8],
                 "home_tags": home_flags, "away_tags": away_flags},
        "form": {"home": home_form, "away": away_form},
        "fatigue": {"home": home_fatigue, "away": away_fatigue},
        "weather": weather_info,
        "weather_class": classify_football(weather_info) if sport == "football" and weather_info else pitch,
        "pitch": pitch,
        "venue": {"name": details.get("stadium") or fixture.get("venue"),
                  "city": details.get("city") or fixture.get("city"),
                  "capacity": details.get("capacity"), "surface": details.get("surface"),
                  "stats": venue_stats},
        "h2h": h2h_data,
        "tactical": {
            "manager_change": manager_change,
            "home_formation": (details.get("formation") or {}).get("home"),
            "away_formation": (details.get("formation") or {}).get("away"),
            "lineups_available": details.get("lineups_available", False),
            "referee": details.get("referee"),
            "referee_stats": details.get("referee_stats") or {},
        },
        "citations": unique_citations[:16],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
