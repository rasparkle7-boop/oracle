"""Team form, Elo and rest/travel context."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import db


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def football_elo(history_days: int = 730, k: float = 20.0, home_adv: float = 55.0) -> dict[str, float]:
    cutoff = datetime.now(timezone.utc).timestamp() - history_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
    with db.db() as conn:
        rows = db.rows(
            conn,
            """SELECT home_team_id, away_team_id, home_score_num, away_score_num, kickoff_utc
               FROM fixtures WHERE sport='football' AND status='finished'
                 AND home_score_num IS NOT NULL AND away_score_num IS NOT NULL
                 AND kickoff_utc >= ? ORDER BY kickoff_utc ASC""",
            (cutoff_iso,),
        )
    ratings: dict[str, float] = {}
    for r in rows:
        h, a = r["home_team_id"], r["away_team_id"]
        rh = ratings.setdefault(h, 1500.0)
        ra = ratings.setdefault(a, 1500.0)
        expected = 1.0 / (1.0 + 10 ** ((ra - (rh + home_adv)) / 400.0))
        hs, as_ = r["home_score_num"], r["away_score_num"]
        actual = 1.0 if hs > as_ else 0.5 if hs == as_ else 0.0
        margin = abs(hs - as_)
        mult = 1.0 if margin <= 1 else 1.5 if margin == 2 else (11 + margin) / 8.0
        delta = k * mult * (actual - expected)
        ratings[h] = rh + delta
        ratings[a] = ra - delta
    return {team: round(value, 1) for team, value in ratings.items()}


def build_form_index(sport: str = "football", history_days: int = 400) -> dict[str, list[dict]]:
    cutoff = datetime.now(timezone.utc).timestamp() - history_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
    with db.db() as conn:
        rows = db.rows(
            conn,
            """SELECT f.*, c.name AS competition_name FROM fixtures f
               LEFT JOIN competitions c ON c.id=f.competition_id
               WHERE f.sport=? AND f.status='finished' AND f.kickoff_utc >= ?
               ORDER BY f.kickoff_utc DESC""",
            (sport, cutoff_iso),
        )
    index: dict[str, list[dict]] = {}
    for r in rows:
        for side, team, opp in (("home", r["home_team_id"], r["away_name"]),
                                ("away", r["away_team_id"], r["home_name"])):
            if not team:
                continue
            if side == "home":
                gf, ga = r["home_score_num"], r["away_score_num"]
            else:
                gf, ga = r["away_score_num"], r["home_score_num"]
            result = "W" if (gf is not None and ga is not None and gf > ga) else \
                     "D" if (gf is not None and ga is not None and gf == ga) else \
                     "L" if gf is not None and ga is not None else "?"
            index.setdefault(team, []).append({
                "fixture_id": r["id"], "kickoff": r["kickoff_utc"], "competition": r["competition_name"],
                "opponent": opp, "side": side, "gf": gf, "ga": ga, "result": result,
                "score": f"{int(gf)}-{int(ga)}" if gf is not None and ga is not None else r["score_detail"],
            })
    return index


def form_summary(matches: list[dict], limit: int = 6) -> dict:
    recent = matches[:limit]
    wins = sum(1 for m in recent if m["result"] == "W")
    draws = sum(1 for m in recent if m["result"] == "D")
    losses = sum(1 for m in recent if m["result"] == "L")
    gf = sum((m["gf"] or 0) for m in recent)
    ga = sum((m["ga"] or 0) for m in recent)
    points = wins * 3 + draws
    max_points = max(1, len(recent) * 3)
    return {
        "matches": len(recent), "wins": wins, "draws": draws, "losses": losses,
        "goals_for": round(gf, 1), "goals_against": round(ga, 1),
        "ppq": round(points / max(1, len(recent)), 2),
        "form_pct": round(100 * points / max_points, 1),
        "sequence": "".join(m["result"] for m in recent),
        "recent": recent,
    }


def rest_days(matches: list[dict], kickoff_iso: str) -> float | None:
    ko = _dt(kickoff_iso)
    if not ko:
        return None
    for m in matches:
        dt = _dt(m.get("kickoff"))
        if dt and dt < ko:
            return round((ko - dt).total_seconds() / 86400, 1)
    return None


def congestion(matches: list[dict], kickoff_iso: str, window_days: int = 21) -> dict:
    ko = _dt(kickoff_iso)
    if not ko:
        return {"matches_21d": 0, "rest_days": None, "load": 0.0}
    count = 0
    for m in matches:
        dt = _dt(m.get("kickoff"))
        if dt and 0 < (ko - dt).total_seconds() <= window_days * 86400:
            count += 1
    rest = rest_days(matches, kickoff_iso)
    load = min(1.0, count / 6.0)
    if rest is not None and rest < 4:
        load = min(1.0, load + (4 - rest) * 0.08)
    return {"matches_21d": count, "rest_days": rest, "load": round(load, 3)}


def h2h(home_id: str, away_id: str, sport: str = "football", limit: int = 6) -> dict:
    with db.db() as conn:
        rows = db.rows(
            conn,
            """SELECT * FROM fixtures
               WHERE sport=? AND status='finished'
                 AND ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
               ORDER BY kickoff_utc DESC LIMIT ?""",
            (sport, home_id, away_id, away_id, home_id, limit),
        )
    out = []
    home_wins = draws = away_wins = 0
    for r in rows:
        hs, as_ = r["home_score_num"], r["away_score_num"]
        if hs is None or as_ is None:
            continue
        if hs == as_:
            draws += 1
        elif (hs > as_ and r["home_team_id"] == home_id) or (as_ > hs and r["away_team_id"] == home_id):
            home_wins += 1
        else:
            away_wins += 1
        out.append({"date": r["kickoff_utc"], "home": r["home_name"], "away": r["away_name"],
                    "score": f"{int(hs)}-{int(as_)}", "competition": r["competition_id"]})
    return {"matches": out, "home_wins": home_wins, "draws": draws, "away_wins": away_wins}
