"""Optional bookmaker-odds benchmark adapter (ESPN public odds).

This module is deliberately isolated from the core ORACLE forecast. It is used
only by the labelled benchmark layer and never feeds the model probabilities.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .. import db

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
    "Accept": "application/json",
}

LEAGUE_SLUGS = {
    "premier league": "eng.1",
    "championship": "eng.2",
    "laliga": "esp.1",
    "la liga": "esp.1",
    "serie a": "ita.1",
    "bundesliga": "ger.1",
    "ligue 1": "fra.1",
    "eredivisie": "ned.1",
    "primeira liga": "por.1",
    "champions league": "uefa.champions",
    "europa league": "uefa.europa",
    "conference league": "uefa.europa.conf",
    "mls": "usa.1",
    "liga mx": "mex.1",
    "liga profesional": "arg.1",
    "brasileirao": "bra.1",
}


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|sc|ac|club|de|the)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def american_to_decimal(value: Any) -> float | None:
    try:
        ml = float(str(value).replace("+", ""))
    except Exception:
        return None
    if ml == 0:
        return None
    return round(1 + (ml / 100 if ml > 0 else 100 / abs(ml)), 4)


def _find_event(events: list[dict], home: str, away: str) -> dict | None:
    target = {_norm(home), _norm(away)}
    best = None
    for e in events:
        comp = (e.get("competitions") or [{}])[0]
        names = [_norm((c.get("team") or {}).get("displayName") or (c.get("team") or {}).get("name") or "")
                 for c in comp.get("competitors", [])]
        score = 0
        for n in names:
            if n in target:
                score += 1
            else:
                score += max((difflib.SequenceMatcher(None, n, t).ratio() for t in target), default=0) * 0.5
        if best is None or score > best[0]:
            best = (score, e)
    return best[1] if best and best[0] >= 1.2 else None


def _selection_name(kind: str, market: str, comp: dict) -> str:
    return kind


def _price(group: dict | None) -> tuple[float | None, float | None]:
    if not group:
        return None, None
    close = group.get("close") or group.get("open") or {}
    return american_to_decimal(close.get("odds")), close.get("line")


def fetch_fixture_odds(fixture: dict) -> dict:
    """Fetch ESPN/DraftKings odds for a football fixture. Returns markets."""
    comp_name = (fixture.get("competition_name") or "").lower()
    slug = LEAGUE_SLUGS.get(comp_name)
    if not slug:
        return {"available": False, "message": f"No benchmark odds adapter for {fixture.get('competition_name')}"}
    try:
        ko = datetime.fromisoformat(fixture["kickoff_utc"].replace("Z", "+00:00"))
    except Exception:
        return {"available": False, "message": "Invalid kickoff time"}
    date = ko.strftime("%Y%m%d")
    try:
        r = httpx.get(f"{BASE}/{slug}/scoreboard?dates={date}", headers=HEADERS, timeout=25, follow_redirects=True)
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "message": f"Odds fetch failed: {exc}"}
    event = _find_event(payload.get("events") or [], fixture["home_name"], fixture["away_name"])
    if not event:
        return {"available": False, "message": "No ESPN event match for this fixture"}
    comp = (event.get("competitions") or [{}])[0]
    odds_list = comp.get("odds") or []
    if not odds_list:
        return {"available": False, "message": "ESPN event has no published odds"}
    odds = odds_list[0]
    provider = (odds.get("provider") or {}).get("name") or "ESPN"
    home_name = fixture["home_name"]
    away_name = fixture["away_name"]
    markets = []

    def add(market, selection, decimal, line=None, american=None):
        if decimal:
            markets.append({"market": market, "selection": selection, "line": line,
                            "decimal": decimal, "american": american,
                            "implied": round(1 / decimal, 5)})

    ml = odds.get("moneyline") or {}
    dh, _ = _price(ml.get("home"))
    da, _ = _price(ml.get("away"))
    dd, _ = _price(ml.get("draw"))
    if dh:
        add("Moneyline", home_name, dh, line=0.0)
    if dd:
        add("Moneyline", "Draw", dd, line=0.0)
    if da:
        add("Moneyline", away_name, da, line=0.0)

    spread = odds.get("pointSpread") or {}
    sh, shl = _price(spread.get("home"))
    sa, sal = _price(spread.get("away"))
    if sh:
        add("Spread", f"{home_name} {shl or ''}".strip(), sh, line=_line_num(shl))
    if sa:
        add("Spread", f"{away_name} {sal or ''}".strip(), sa, line=_line_num(sal))

    total = odds.get("total") or {}
    to, tol = _price(total.get("over"))
    tu, tul = _price(total.get("under"))
    ou = odds.get("overUnder")
    if to:
        add("Total", f"Over {ou or tol or ''}".strip(), to, line=_line_num(ou or tol))
    if tu:
        add("Total", f"Under {ou or tul or ''}".strip(), tu, line=_line_num(ou or tul))

    return {
        "available": bool(markets),
        "provider": provider,
        "event_id": event.get("id"),
        "event_name": event.get("name"),
        "source": "ESPN public odds",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
        "link": (odds.get("link") or {}).get("href"),
        "venue": (comp.get("venue") or {}).get("fullName"),
        "city": ((comp.get("venue") or {}).get("address") or {}).get("city"),
        "message": "" if markets else "No supported markets parsed",
    }


def _line_num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("o", "").replace("u", "").replace("+", ""))
    except Exception:
        return 0.0


def store_odds(fixture_id: str, data: dict) -> None:
    if not data.get("available"):
        return
    with db.db() as conn:
        conn.execute("DELETE FROM market_odds WHERE fixture_id=? AND source=?",
                     (fixture_id, data.get("source")))
        if data.get("venue"):
            conn.execute("""UPDATE fixtures SET venue=COALESCE(NULLIF(venue,''), ?),
                                   city=COALESCE(NULLIF(city,''), ?)
                            WHERE id=?""", (data["venue"], data.get("city"), fixture_id))
        for m in data["markets"]:
            db.upsert_market_odds(conn, {
                "fixture_id": fixture_id, "fetched_at": data["fetched_at"],
                "source": data["source"], "provider": data.get("provider"),
                "event_id": data.get("event_id"), "market": m["market"],
                "selection": m["selection"], "line": m.get("line"),
                "american": m.get("american"), "decimal": m["decimal"],
                "implied": m["implied"], "raw": {"link": data.get("link")},
            })


def cached_odds(fixture_id: str, ttl_minutes: int = 15) -> dict | None:
    with db.db() as conn:
        rows = db.rows(conn, "select * from market_odds where fixture_id=? order by fetched_at desc", (fixture_id,))
    if not rows:
        return None
    try:
        fetched = datetime.fromisoformat(rows[0]["fetched_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - fetched > timedelta(minutes=ttl_minutes):
            return None
    except Exception:
        return None
    return {"available": True, "provider": rows[0].get("provider"),
            "event_id": rows[0].get("event_id"), "source": rows[0].get("source"),
            "fetched_at": rows[0].get("fetched_at"), "markets": rows,
            "message": ""}
