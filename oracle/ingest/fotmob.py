"""FotMob public feed adapter.

Used only for fixture discovery, results, venues, weather, lineups and
unavailability lists. No bookmaker prices are read or stored.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings
from ..db import upsert_competition, upsert_fixture, upsert_team
from .http import fetch_json, gather_limited, make_client

BASE = "https://www.fotmob.com/api/data"
LOGO_TEAM = "https://images.fotmob.com/image_resources/logo/teamlogo/{id}.png"
LOGO_LEAGUE = "https://images.fotmob.com/image_resources/logo/leaguelogo/{id}.png"

COUNTRY_NAMES = {
    "ENG": "England", "ESP": "Spain", "ITA": "Italy", "GER": "Germany", "FRA": "France",
    "POR": "Portugal", "NED": "Netherlands", "BEL": "Belgium", "TUR": "Turkey", "GRE": "Greece",
    "SCO": "Scotland", "WAL": "Wales", "IRL": "Ireland", "NIR": "Northern Ireland", "AUT": "Austria",
    "SUI": "Switzerland", "DEN": "Denmark", "NOR": "Norway", "SWE": "Sweden", "FIN": "Finland",
    "POL": "Poland", "CZE": "Czechia", "CRO": "Croatia", "SRB": "Serbia", "ROU": "Romania",
    "BUL": "Bulgaria", "HUN": "Hungary", "ISR": "Israel", "RUS": "Russia", "UKR": "Ukraine",
    "USA": "United States", "MEX": "Mexico", "BRA": "Brazil", "ARG": "Argentina", "CHI": "Chile",
    "COL": "Colombia", "PER": "Peru", "URU": "Uruguay", "ECU": "Ecuador", "PAR": "Paraguay",
    "BOL": "Bolivia", "VEN": "Venezuela", "JPN": "Japan", "KOR": "South Korea", "CHN": "China",
    "AUS": "Australia", "KSA": "Saudi Arabia", "UAE": "United Arab Emirates", "QAT": "Qatar",
    "IND": "India", "INT": "International", "INT-2": "International", "MAR": "Morocco",
    "EGY": "Egypt", "RSA": "South Africa", "NGA": "Nigeria", "GHA": "Ghana", "TUN": "Tunisia",
    "ALG": "Algeria", "CAN": "Canada", "NZL": "New Zealand", "THA": "Thailand", "VIE": "Vietnam",
    "IDN": "Indonesia", "MAS": "Malaysia", "SGP": "Singapore", "HK": "Hong Kong", "IRN": "Iran",
    "IRQ": "Iraq", "JOR": "Jordan", "KUW": "Kuwait", "OMA": "Oman", "BAH": "Bahrain",
    "LIB": "Lebanon", "SYR": "Syria", "UZB": "Uzbekistan", "KAZ": "Kazakhstan", "AZE": "Azerbaijan",
    "ARM": "Armenia", "GEO": "Georgia", "BLR": "Belarus", "MDA": "Moldova", "ALB": "Albania",
    "MKD": "North Macedonia", "BIH": "Bosnia and Herzegovina", "SVN": "Slovenia", "SVK": "Slovakia",
    "LTU": "Lithuania", "LVA": "Latvia", "EST": "Estonia", "LUX": "Luxembourg", "MLT": "Malta",
    "ISL": "Iceland", "CYP": "Cyprus", "CRC": "Costa Rica", "HON": "Honduras", "GUA": "Guatemala",
    "SLV": "El Salvador", "PAN": "Panama", "JAM": "Jamaica", "TRI": "Trinidad and Tobago",
    "SEN": "Senegal", "CIV": "Ivory Coast", "CMR": "Cameroon", "ZIM": "Zimbabwe", "KEN": "Kenya",
    "UGA": "Uganda", "TZA": "Tanzania", "ZAM": "Zambia", "MOZ": "Mozambique", "ANG": "Angola",
    "BEN": "Benin", "BFA": "Burkina Faso", "MLI": "Mali", "GUI": "Guinea", "GAB": "Gabon",
    "COD": "DR Congo", "CGO": "Congo", "SUD": "Sudan", "ETH": "Ethiopia", "ERI": "Eritrea",
}

TIER1 = (
    "champions league", "europa league", "conference league", "world cup", "european championship",
    "copa libertadores", "copa america", "premier league", "laliga", "la liga", "serie a",
    "bundesliga", "ligue 1", "eredivisie", "primeira liga", "brasileirao", "liga mx", "mls",
    "saudi pro league", "afc champions league", "caf champions league", "eredivisie",
)
TOP_DIVISION = (
    "premier league", "championship", "laliga", "la liga", "serie a", "serie b", "bundesliga",
    "2. bundesliga", "ligue 1", "ligue 2", "primeira liga", "eredivisie", "pro league",
    "super lig", "super league", "j1 league", "k league", "a-league", "liga profesional",
    "primera division", "copa", "cup", "trophy", "championship", "division",
)


ELITE_COUNTRIES = {
    "England", "Spain", "Italy", "Germany", "France", "Netherlands", "Portugal",
    "Brazil", "Argentina", "Mexico", "United States", "Turkey", "Belgium",
    "Scotland", "Russia", "Ukraine", "Saudi Arabia", "Japan", "South Korea",
}
CONTINENTAL = (
    "champions league", "europa league", "conference league", "world cup",
    "copa libertadores", "copa america", "copa sudamericana", "european championship",
    "afc champions", "caf champions", "nations league", "club world cup",
)
TOP_DOMESTIC = (
    "premier league", "la liga", "laliga", "serie a", "bundesliga", "ligue 1",
    "eredivisie", "primeira liga", "brasileirao", "liga mx", "mls", "liga profesional",
    "super lig", "j1 league", "k league",
)
LOWER_MARKERS = ("2.", "ii", "b ", "u18", "u19", "u20", "u21", "youth", "reserve", "women", "femenil")


def _importance(league: str, country: str, gender: str = "male") -> float:
    name = (league or "").lower()
    country = country or ""
    score = 0.55
    if any(k in name for k in CONTINENTAL):
        score = 0.97 if "world cup" in name else 0.93
    elif country in ELITE_COUNTRIES:
        if any(k in name for k in TOP_DOMESTIC) and not any(k in name for k in LOWER_MARKERS):
            score = 0.87
        elif "cup" in name or "copa" in name or "trophy" in name:
            score = 0.73
        elif any(k in name for k in LOWER_MARKERS):
            score = 0.62
        else:
            score = 0.68
    elif country in ("International", "INT", "INT-2", ""):
        score = 0.70
    else:
        score = 0.58
    if "women" in name or "femenil" in name or "w." in name or gender == "female":
        score -= 0.10
    if any(k in name for k in ("u18", "u19", "u20", "u21", "youth", "reserve")):
        score -= 0.16
    if "friendly" in name:
        score -= 0.12
    return round(max(0.2, min(0.98, score)), 2)


def _season_label(dt: datetime) -> str:
    y = dt.year
    if dt.month >= 7:
        return f"{y}-{(y + 1) % 100:02d}"
    return f"{y - 1}-{y % 100:02d}"


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def normalise_feed(payload: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (competitions, teams, fixtures) normalised dictionaries."""
    comps: dict[str, dict] = {}
    teams: dict[str, dict] = {}
    fixtures: list[dict] = []
    for league in payload.get("leagues", []) or []:
        league_id = league.get("id")
        name = league.get("name") or "Unknown competition"
        ccode = league.get("ccode") or league.get("countryCode") or ""
        country = COUNTRY_NAMES.get(ccode, ccode or "International")
        comp_id = f"fb:c{league_id}"
        comps[comp_id] = {
            "id": comp_id, "sport": "football", "name": name, "country": country,
            "tier": 1 if any(k in name.lower() for k in TIER1) else 2,
            "logo": LOGO_LEAGUE.format(id=league_id), "source": "fotmob",
            "metadata": {"fotmob_id": league_id, "ccode": ccode, "parent_id": league.get("parentLeagueId")},
        }
        for match in league.get("matches", []) or []:
            status = match.get("status") or {}
            reason = status.get("reason") or {}
            if reason.get("shortKey") == "postponed" or reason.get("short") == "PP":
                state = "postponed"
            elif reason.get("shortKey") in ("cancelled", "aborted"):
                state = "cancelled"
            elif status.get("finished"):
                state = "finished"
            elif status.get("started"):
                state = "live"
            else:
                state = "scheduled"
            kickoff = status.get("utcTime") or match.get("status", {}).get("utcTime")
            if not kickoff and match.get("timeTS"):
                kickoff = datetime.fromtimestamp(match["timeTS"] / 1000, timezone.utc).isoformat()
            ko = _parse_utc(kickoff)
            if not ko:
                continue
            home = match.get("home") or {}
            away = match.get("away") or {}
            if not home.get("name") or not away.get("name"):
                continue
            hid = f"fb:t{home.get('id')}"
            aid = f"fb:t{away.get('id')}"
            for tid, t in ((hid, home), (aid, away)):
                teams[tid] = {
                    "id": tid, "sport": "football", "name": t.get("longName") or t.get("name"),
                    "short_name": t.get("name"), "country": country,
                    "logo": LOGO_TEAM.format(id=t.get("id")),
                    "metadata": {"fotmob_id": t.get("id")},
                }
            hs = home.get("score")
            as_ = away.get("score")
            fixture = {
                "id": f"fb:{match.get('id')}", "sport": "football", "competition_id": comp_id,
                "season": _season_label(ko), "round": match.get("tournamentStage") or league.get("round"),
                "kickoff_utc": ko.isoformat().replace("+00:00", "Z"), "status": state,
                "home_team_id": hid, "away_team_id": aid,
                "home_name": home.get("longName") or home.get("name"),
                "away_name": away.get("longName") or away.get("name"),
                "venue": None, "city": None, "country": country,
                "home_score": None if hs is None else str(hs),
                "away_score": None if as_ is None else str(as_),
                "home_score_num": float(hs) if isinstance(hs, (int, float)) else None,
                "away_score_num": float(as_) if isinstance(as_, (int, float)) else None,
                "score_detail": status.get("scoreStr") or reason.get("short") or "",
                "winner_team_id": (hid if isinstance(hs, (int, float)) and isinstance(as_, (int, float)) and hs > as_ else
                                   aid if isinstance(hs, (int, float)) and isinstance(as_, (int, float)) and as_ > hs else None),
                "source": "fotmob", "source_url": f"https://www.fotmob.com/leagues/{league_id}/overview",
                "importance": _importance(name, country, "female" if "(w)" in name.lower() else "male"),
                "raw": {"fotmob_id": match.get("id"), "league_id": league_id, "status_id": match.get("statusId")},
            }
            fixtures.append(fixture)
    return list(comps.values()), list(teams.values()), fixtures


async def fetch_day(client: httpx.AsyncClient, day: date, ttl: int | None = None) -> dict:
    if ttl is None:
        today = datetime.now(timezone.utc).date()
        ttl = 900 if day >= today else 86400
    return await fetch_json(
        client, f"{BASE}/matches?date={day.strftime('%Y%m%d')}",
        cache_key=f"fotmob:day:{day.isoformat()}", ttl=ttl,
    )


async def sync_days(days: list[date], progress=None) -> dict:
    """Fetch many days in parallel and upsert fixtures. Returns stats."""
    from .. import db

    async with make_client() as client:
        async def one(day: date):
            payload = await fetch_day(client, day)
            return day, payload

        results = await gather_limited(
            [lambda d=d: one(d) for d in days],
            limit=settings.football_workers,
            on_error=lambda exc: db.log("warn", "fotmob", str(exc)[:300]),
        )

    total_fx = 0
    total_comps = 0
    total_teams = 0
    seen_comps: set[str] = set()
    with db.db() as conn:
        for item in results:
            if not item:
                continue
            _, payload = item
            comps, teams, fixtures = normalise_feed(payload)
            for comp in comps:
                if comp["id"] not in seen_comps:
                    upsert_competition(conn, comp)
                    seen_comps.add(comp["id"])
                    total_comps += 1
            for team in teams:
                upsert_team(conn, team)
                total_teams += 1
            for fx in fixtures:
                upsert_fixture(conn, fx)
                total_fx += 1
        if progress:
            progress(1.0, f"{total_fx} football fixtures normalised")
    return {"fixtures": total_fx, "competitions": total_comps, "teams": total_teams,
            "days": [d.isoformat() for d in days]}


async def fetch_details(client: httpx.AsyncClient, match_id: int | str, ttl: int = 3600) -> dict | None:
    try:
        return await fetch_json(
            client, f"{BASE}/matchDetails?matchId={match_id}",
            cache_key=f"fotmob:detail:{match_id}", ttl=ttl,
        )
    except Exception:
        return None


def _starters(team: dict) -> list[dict]:
    out = []
    for p in (team or {}).get("starters", []) or []:
        out.append({
            "name": p.get("name"), "position": p.get("position"),
            "shirt": p.get("shirtNumber") or p.get("shirt"),
            "rating": p.get("rating"),
        })
    return out


def _unavailable(team: dict) -> list[dict]:
    out = []
    for p in (team or {}).get("unavailable", []) or []:
        u = p.get("unavailability") or {}
        out.append({
            "name": p.get("name"), "type": u.get("type") or "unavailable",
            "expected_return": u.get("expectedReturn") or u.get("expectedReturnDate") or "",
            "market_value": p.get("marketValue") or 0,
            "age": p.get("age"), "id": p.get("id"),
        })
    return out


def referee_matches(stats: dict) -> float | None:
    try:
        return float(stats.get("matches")) if stats.get("matches") is not None else None
    except Exception:
        return None


def normalise_details(payload: dict) -> dict:
    content = payload.get("content") or {}
    facts = content.get("matchFacts") or {}
    info = facts.get("infoBox") or {}
    stadium = info.get("Stadium") or {}
    weather = content.get("weather") or {}
    lineup = content.get("lineup") or {}
    home_line = lineup.get("homeTeam") or {}
    away_line = lineup.get("awayTeam") or {}
    h2h = content.get("h2h") or {}
    table = content.get("table") or {}
    form = facts.get("teamForm") or []
    referee = info.get("Referee") or {}
    referee_stats = {}
    for stat in referee.get("stats") or []:
        if isinstance(stat, dict) and stat.get("type"):
            referee_stats[stat["type"]] = stat.get("value")

    def form_summary(rows):
        if not rows:
            return []
        return [{"result": r.get("resultString"), "score": r.get("score"),
                 "date": (r.get("date") or {}).get("utcTime"),
                 "opponent": (r.get("tooltipText") or {}).get("homeTeam") if str(r.get("home", {}).get("id")) != str(rows[0].get("teamId")) else (r.get("tooltipText") or {}).get("awayTeam")}
                for r in rows[:6]]

    h2h_matches = []
    for m in (h2h.get("matches") or [])[:8]:
        h2h_matches.append({
            "date": m.get("date"), "home": (m.get("home") or {}).get("name"),
            "away": (m.get("away") or {}).get("name"),
            "score": m.get("score"), "winner": m.get("winner"),
            "league": (m.get("league") or {}).get("name") if isinstance(m.get("league"), dict) else m.get("league"),
        })
    table_rows = []
    for side in ("home", "away"):
        rows = ((table.get(side) or {}).get("all") or []) if isinstance(table.get(side), dict) else []
        for r in rows[:20]:
            table_rows.append({"side": side, "team": r.get("name"), "position": r.get("idx"),
                               "points": r.get("pts"), "played": r.get("played"),
                               "wins": r.get("wins"), "draws": r.get("draws"), "losses": r.get("losses"),
                               "goals_for": r.get("scoresStr")})
    return {
        "stadium": stadium.get("name"), "city": stadium.get("city"), "country": stadium.get("country"),
        "lat": stadium.get("lat"), "lon": stadium.get("long"), "capacity": stadium.get("capacity"),
        "surface": stadium.get("surface"), "referee": referee.get("text"),
        "referee_country": referee.get("country"), "referee_matches": referee_matches(referee_stats),
        "referee_stats": referee_stats,
        "weather": {
            "temperature_c": weather.get("temperature"), "wind_kph": weather.get("windSpeed"),
            "humidity": weather.get("relativeHumidity"), "precip_chance": weather.get("precipChance"),
            "precipitation": weather.get("precipitation"), "description": weather.get("description"),
            "updated": weather.get("lastUpdated"),
        } if weather else {},
        "unavailable": {
            "home": _unavailable(home_line), "away": _unavailable(away_line),
        },
        "lineups_available": bool(home_line.get("starters") or away_line.get("starters")),
        "lineup_type": lineup.get("lineupType") or ("confirmed" if (home_line.get("starters") or away_line.get("starters")) else "unavailable"),
        "starters": {"home": _starters(home_line), "away": _starters(away_line)},
        "formation": {"home": home_line.get("formation"), "away": away_line.get("formation")},
        "h2h": h2h_matches,
        "form": {"home": form_summary(form[0] if len(form) > 0 else []),
                 "away": form_summary(form[1] if len(form) > 1 else [])},
        "table": table_rows,
        "coverage": (payload.get("general") or {}).get("coverageLevel"),
        "round": info.get("Tournament", {}).get("roundName") if isinstance(info.get("Tournament"), dict) else None,
    }


async def enrich_fixtures(fixtures: list[dict], limit: int = 240) -> dict:
    """Fetch rich detail for the most important fixtures, persist the context."""
    from .. import db

    targets = sorted(fixtures, key=lambda f: -(f.get("importance") or 0))[:limit]
    details: dict[str, dict] = {}
    async with make_client() as client:
        async def one(fx: dict):
            mid = (fx.get("raw") or {}).get("fotmob_id") or fx["id"].split(":")[1]
            payload = await fetch_details(client, mid, ttl=1800 if fx["status"] == "scheduled" else 86400)
            if payload:
                return fx["id"], normalise_details(payload)
            return fx["id"], None

        results = await gather_limited(
            [lambda f=f: one(f) for f in targets],
            limit=settings.football_workers,
            on_error=lambda exc: db.log("warn", "fotmob-detail", str(exc)[:200]),
        )
    for item in results:
        if item and item[1]:
            details[item[0]] = item[1]
    return details
