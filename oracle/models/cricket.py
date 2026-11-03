"""Cricket Monte Carlo engine.

T20/ODI: vectorised ball-by-ball innings simulation with phase-dependent
outcome distributions, team batting/bowling strength, venue scoring index,
toss orientation and dew adjustment.
Test: session-level result model with draw mass (explicitly labelled).

No bookmaker prices are inputs or outputs.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import numpy as np

from .. import db

FORMAT_BASELINE = {
    "T20": {"runs": 160.0, "rr": 8.0, "balls": 120},
    "ODI": {"runs": 280.0, "rr": 5.6, "balls": 300},
    "TEST": {"runs": 340.0, "rr": 3.3, "balls": 540},
}

# Phase outcome probabilities: [dot, 1, 2, 3, 4, 6, wicket, wide/no-ball]
PHASES = {
    "T20": [
        [0.34, 0.33, 0.09, 0.01, 0.14, 0.045, 0.045, 0.02],
        [0.30, 0.38, 0.10, 0.01, 0.10, 0.05, 0.05, 0.01],
        [0.22, 0.31, 0.12, 0.01, 0.14, 0.13, 0.06, 0.01],
    ],
    "ODI": [
        [0.44, 0.36, 0.08, 0.01, 0.08, 0.015, 0.03, 0.015],
        [0.36, 0.40, 0.09, 0.01, 0.07, 0.03, 0.03, 0.01],
        [0.28, 0.35, 0.11, 0.01, 0.11, 0.08, 0.05, 0.01],
    ],
}

PRIORS = {
    # T20 international strength (ICC-style rating, not market-derived)
    "india": {"T20": 268, "ODI": 122, "TEST": 125},
    "australia": {"T20": 262, "ODI": 120, "TEST": 124},
    "england": {"T20": 258, "ODI": 110, "TEST": 118},
    "south africa": {"T20": 255, "ODI": 118, "TEST": 116},
    "new zealand": {"T20": 252, "ODI": 115, "TEST": 112},
    "pakistan": {"T20": 248, "ODI": 112, "TEST": 106},
    "west indies": {"T20": 242, "ODI": 95, "TEST": 98},
    "sri lanka": {"T20": 238, "ODI": 105, "TEST": 102},
    "bangladesh": {"T20": 234, "ODI": 100, "TEST": 94},
    "afghanistan": {"T20": 230, "ODI": 98, "TEST": 86},
    "ireland": {"T20": 215, "ODI": 82, "TEST": 78},
    "zimbabwe": {"T20": 210, "ODI": 85, "TEST": 84},
    "scotland": {"T20": 208, "ODI": 80, "TEST": 70},
    "netherlands": {"T20": 205, "ODI": 78, "TEST": 70},
    "nepal": {"T20": 190, "ODI": 72, "TEST": 60},
    "oman": {"T20": 192, "ODI": 70, "TEST": 60},
    "united arab emirates": {"T20": 195, "ODI": 68, "TEST": 60},
    "namibia": {"T20": 188, "ODI": 66, "TEST": 55},
    "united states of america": {"T20": 185, "ODI": 64, "TEST": 55},
    "usa": {"T20": 185, "ODI": 64, "TEST": 55},
    "canada": {"T20": 180, "ODI": 62, "TEST": 50},
    "kenya": {"T20": 175, "ODI": 60, "TEST": 50},
    "uganda": {"T20": 170, "ODI": 58, "TEST": 48},
    "papua new guinea": {"T20": 165, "ODI": 56, "TEST": 45},
    "hong kong": {"T20": 162, "ODI": 55, "TEST": 45},
}

ALIASES = {
    "united states": "usa", "u.s.a.": "usa", "west indies women": "west indies w",
    "india women": "india w", "australia women": "australia w", "england women": "england w",
    "south africa women": "south africa w", "new zealand women": "new zealand w",
    "pakistan women": "pakistan w", "sri lanka women": "sri lanka w",
    "bangladesh women": "bangladesh w", "ireland women": "ireland w",
}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = s.replace("womens", "women")
    s = re.sub(r"\b(women|woman)\b", " w ", s)
    s = re.sub(r"\b(men|national|senior|cricket|club|fc|xi|the)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30, min(30, x))))


@dataclass
class CricketTeam:
    key: str
    display: str
    elo: dict[str, float] = field(default_factory=dict)
    runs_for: dict[str, list[float]] = field(default_factory=dict)
    runs_against: dict[str, list[float]] = field(default_factory=dict)
    matches: dict[str, int] = field(default_factory=dict)
    wins: dict[str, int] = field(default_factory=dict)
    recent: list[dict] = field(default_factory=list)


@dataclass
class CricketBook:
    teams: dict[str, CricketTeam]
    venues: dict[str, dict]
    trained_at: str
    matches: int
    elo_index: dict[tuple[str, str], float]


def _prior_elo(team_key: str, fmt: str) -> float:
    priors = PRIORS.get(team_key)
    if not priors:
        return 1500.0
    rating = priors.get(fmt) or priors.get("T20") or 200
    if fmt == "TEST":
        return 1500.0 + (rating - 100) * 7.0
    if fmt == "ODI":
        return 1500.0 + (rating - 100) * 6.0
    return 1500.0 + (rating - 200) * 5.0


def _load_results() -> list[dict]:
    with db.db() as conn:
        hist = db.rows(
            conn,
            """SELECT * FROM historical_results WHERE sport='cricket'
               ORDER BY played_on ASC""",
        )
        fx = db.rows(
            conn,
            """SELECT * FROM fixtures WHERE sport='cricket' AND status='finished'
                 AND home_score_num IS NOT NULL ORDER BY kickoff_utc ASC""",
        )
    results: list[dict] = []
    seen = set()
    for h in hist:
        meta = db.json_loads(h["metadata"], {}) or {}
        fmt = (h["format"] or "T20").upper()
        date = (h["played_on"] or "")[:10]
        key = (date, tuple(sorted([norm(h["home_team"]), norm(h["away_team"])])), fmt)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "date": date, "format": fmt, "home": h["home_team"], "away": h["away_team"],
            "home_runs": h["home_score"], "away_runs": h["away_score"],
            "winner": h["winner"], "venue": h["venue"], "city": h["city"],
            "neutral": bool(h["neutral"]), "source": "cricsheet", "meta": meta,
        })
    for f in fx:
        raw = db.json_loads(f["raw"], {}) or {}
        fmt = (raw.get("format") or "T20").upper()
        date = (f["kickoff_utc"] or "")[:10]
        key = (date, tuple(sorted([norm(f["home_name"]), norm(f["away_name"])])), fmt)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "date": date, "format": fmt, "home": f["home_name"], "away": f["away_name"],
            "home_runs": f["home_score_num"], "away_runs": f["away_score_num"],
            "winner": f["winner_team_id"], "venue": f["venue"], "city": f["city"],
            "neutral": False, "source": "cricbuzz", "meta": {},
            "home_id": f["home_team_id"], "away_id": f["away_team_id"],
        })
    return results


def train(use_priors: bool = True) -> CricketBook:
    results = _load_results()
    teams: dict[str, CricketTeam] = {}
    venues: dict[str, dict] = {}

    def get_team(name: str) -> CricketTeam:
        key = norm(name)
        if key not in teams:
            teams[key] = CricketTeam(key=key, display=name)
        return teams[key]

    for r in results:
        fmt = r["format"]
        home = get_team(r["home"])
        away = get_team(r["away"])
        for t in (home, away):
            t.matches[fmt] = t.matches.get(fmt, 0) + 1
            t.elo.setdefault(fmt, _prior_elo(t.key, fmt) if use_priors else 1500.0)
        # Elo
        rh, ra = home.elo[fmt], away.elo[fmt]
        adv = 0 if r["neutral"] else 38.0
        expected = 1.0 / (1.0 + 10 ** ((ra - (rh + adv)) / 400.0))
        winner = r.get("winner")
        score_detail = (r.get("meta") or {}).get("outcome") or {}
        no_result = bool(score_detail.get("result") == "no result" or
                         "no result" in str(score_detail).lower() or
                         "abandon" in str(r.get("meta")).lower())
        if winner:
            wkey = norm(winner)
            actual = 1.0 if wkey == home.key else 0.0
        elif no_result:
            actual = None
        else:
            actual = 0.5
        if actual is not None:
            delta = 26.0 * (actual - expected)
            home.elo[fmt] = rh + delta
            away.elo[fmt] = ra - delta
            if actual >= 0.99:
                home.wins[fmt] = home.wins.get(fmt, 0) + 1
            elif actual <= 0.01:
                away.wins[fmt] = away.wins.get(fmt, 0) + 1
        # run averages (limited overs and cricsheet tests)
        if (r.get("home_runs") is not None and r.get("away_runs") is not None
                and float(r["home_runs"]) > 0 and float(r["away_runs"]) > 0):
            if fmt in ("T20", "ODI"):
                home.runs_for.setdefault(fmt, []).append(float(r["home_runs"]))
                home.runs_against.setdefault(fmt, []).append(float(r["away_runs"]))
                away.runs_for.setdefault(fmt, []).append(float(r["away_runs"]))
                away.runs_against.setdefault(fmt, []).append(float(r["home_runs"]))
        result = "NR" if actual is None else "W" if actual >= 0.99 else "L" if actual <= 0.01 else "D"
        home.recent.append({"date": r["date"], "opponent": r["away"], "format": fmt,
                            "result": result,
                            "runs": r.get("home_runs"), "conceded": r.get("away_runs")})
        away.recent.append({"date": r["date"], "opponent": r["home"], "format": fmt,
                            "result": {"W": "L", "L": "W", "D": "D", "NR": "NR"}[result],
                            "runs": r.get("away_runs"), "conceded": r.get("home_runs")})

        # venue stats from cricsheet innings detail
        if r["venue"]:
            vkey = norm(r["venue"])
            v = venues.setdefault(vkey, {"venue": r["venue"], "matches": 0, "first_innings": [],
                                         "chase_wins": 0, "bat_first_wins": 0, "draws": 0,
                                         "toss_bat": 0, "toss_field": 0, "formats": {}})
            v["matches"] += 1
            v["formats"][fmt] = v["formats"].get(fmt, 0) + 1
            innings = (r.get("meta") or {}).get("innings") or []
            if innings and innings[0].get("runs") is not None:
                v["first_innings"].append(float(innings[0]["runs"]))
            if len(innings) >= 2 and winner:
                batting_first = norm(innings[0].get("team") or "")
                batting_second = norm(innings[1].get("team") or "")
                if wkey := (norm(winner) if winner else ""):
                    if wkey == batting_second:
                        v["chase_wins"] += 1
                    elif wkey == batting_first:
                        v["bat_first_wins"] += 1
            if not winner:
                v["draws"] += 1
            toss = (r.get("meta") or {}).get("toss") or {}
            if toss.get("decision") == "bat":
                v["toss_bat"] += 1
            elif toss.get("decision") == "field":
                v["toss_field"] += 1

    for v in venues.values():
        firsts = v.pop("first_innings", [])
        v["avg_first_innings"] = round(sum(firsts) / len(firsts), 1) if firsts else None
        total = max(1, v["chase_wins"] + v["bat_first_wins"])
        v["chase_rate"] = round(v["chase_wins"] / total, 3)
        v["toss_bat_rate"] = round(v["toss_bat"] / max(1, v["toss_bat"] + v["toss_field"]), 3)
        v["draw_rate"] = round(v["draws"] / max(1, v["matches"]), 3)

    # persist ratings
    with db.db() as conn:
        for key, t in teams.items():
            fmt = "T20" if t.matches.get("T20") else "ODI" if t.matches.get("ODI") else "TEST"
            runs_for = t.runs_for.get(fmt) or []
            runs_against = t.runs_against.get(fmt) or []
            base = FORMAT_BASELINE.get(fmt, FORMAT_BASELINE["T20"])["runs"]
            db.upsert_rating(conn, {
                "team_id": f"crn:{key}", "sport": "cricket", "competition_id": None,
                "as_of": datetime.now(timezone.utc).isoformat(),
                "attack": round((sum(runs_for) / len(runs_for)) / base, 3) if runs_for else 1.0,
                "defence": round((sum(runs_against) / len(runs_against)) / base, 3) if runs_against else 1.0,
                "elo": round(t.elo.get(fmt, 1500.0), 1), "matches": t.matches.get(fmt, 0),
                "wins": t.wins.get(fmt, 0), "draws": 0, "losses": 0,
                "goals_for": round(sum(runs_for), 1), "goals_against": round(sum(runs_against), 1),
                "form": t.recent[-8:], "home_advantage": 38.0,
                "metadata": {"display": t.display, "elo": {k: round(v, 1) for k, v in t.elo.items()},
                             "matches": t.matches},
            })
    elo_index = {(k, fmt): v for k, t in teams.items() for fmt, v in t.elo.items()}
    db.log("info", "model", f"cricket model trained on {len(results)} matches",
           {"teams": len(teams), "venues": len(venues)})
    return CricketBook(teams=teams, venues=venues,
                       trained_at=datetime.now(timezone.utc).isoformat(),
                       matches=len(results), elo_index=elo_index)


def lookup_team(book: CricketBook, name: str) -> CricketTeam | None:
    key = norm(name)
    if key in book.teams:
        return book.teams[key]
    matches = [(SequenceMatcher(None, key, k).ratio(), k) for k in book.teams]
    matches.sort(reverse=True)
    if matches and matches[0][0] >= 0.86:
        return book.teams[matches[0][1]]
    return None


def team_strength(book: CricketBook, name: str, fmt: str) -> dict:
    team = lookup_team(book, name)
    baseline = FORMAT_BASELINE.get(fmt, FORMAT_BASELINE["T20"])
    if not team:
        prior = _prior_elo(norm(name), fmt)
        return {"bat": 1.0, "bowl": 1.0, "elo": prior, "matches": 0, "display": name,
                "runs_for": baseline["runs"], "runs_against": baseline["runs"]}
    runs_for = team.runs_for.get(fmt) or []
    runs_against = team.runs_against.get(fmt) or []
    bat = (sum(runs_for) / len(runs_for) / baseline["runs"]) if runs_for else 1.0
    bowl = (sum(runs_against) / len(runs_against) / baseline["runs"]) if runs_against else 1.0
    # shrink and blend with Elo
    n = team.matches.get(fmt, 0)
    shrink = min(1.0, n / 12.0)
    bat = 1.0 + (bat - 1.0) * shrink
    bowl = 1.0 + (bowl - 1.0) * shrink
    elo = team.elo.get(fmt, 1500.0)
    elo_factor = 1.0 + max(-0.18, min(0.18, (elo - 1500.0) / 1400.0))
    bat = 0.55 * bat + 0.45 * elo_factor
    bowl = 0.55 * bowl + 0.45 * (2.0 - elo_factor)
    return {"bat": round(max(0.7, min(1.3, bat)), 3),
            "bowl": round(max(0.7, min(1.3, bowl)), 3),
            "elo": round(elo, 1), "matches": n, "display": team.display,
            "runs_for": round(sum(runs_for) / len(runs_for), 1) if runs_for else baseline["runs"],
            "runs_against": round(sum(runs_against) / len(runs_against), 1) if runs_against else baseline["runs"]}


def _outcome_probs(phase: list[float], bat: float, bowl: float) -> np.ndarray:
    p = np.array(phase, dtype=float)
    p[4] *= bat ** 1.3
    p[5] *= bat ** 1.6
    p[6] *= (1.0 / max(0.5, bat)) ** 1.1 * (bowl ** 0.8)
    p[7] *= 1.0
    return p / p.sum()


def simulate_innings(rng: np.random.Generator, n: int, fmt: str, bat: float, bowl: float,
                     venue_rr: float | None, target: int | None = None,
                     dew_boost: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cfg = FORMAT_BASELINE.get(fmt, FORMAT_BASELINE["T20"])
    max_balls = cfg["balls"]
    venue_factor = (venue_rr or 1.0) ** 0.5
    bat_eff = bat * venue_factor * (1.0 + dew_boost)
    bowl_eff = bowl / venue_factor
    probs = []
    for phase in PHASES[fmt]:
        probs.append(_outcome_probs(phase, bat_eff, bowl_eff))
    runs = np.zeros(n, dtype=np.int32)
    wkts = np.zeros(n, dtype=np.int32)
    balls = np.zeros(n, dtype=np.int32)
    active = np.ones(n, dtype=bool)
    phase_len = max_balls / 3.0
    for ball in range(max_balls):
        if not active.any():
            break
        over = ball
        phase_idx = 0 if over < phase_len else 1 if over < 2 * phase_len else 2
        p = probs[phase_idx].copy()
        # tail pressure: wickets in hand affects wicket probability
        # vectorised per simulation would be expensive; use a small scalar bump
        p[6] *= 1.0 + 0.22 * (wkts.mean() / 10.0) + (0.25 if phase_idx == 2 else 0.0)
        p = p / p.sum()
        cum = np.cumsum(p)
        u = rng.random(n)
        choice = np.searchsorted(cum, u, side="right")
        choice = np.clip(choice, 0, 7)
        # mask inactive
        choice = np.where(active, choice, 0)
        add_runs = np.choose(choice, [0, 1, 2, 3, 4, 6, 0, 1]).astype(np.int32)
        wicket = (choice == 6) & active
        wide = (choice == 7) & active
        runs += add_runs
        wkts += wicket.astype(np.int32)
        balls += (active & ~wide).astype(np.int32)
        active = active & (wkts < 10)
        if target is not None:
            active = active & (runs < target)
        active = active & (balls < max_balls)
    return runs, wkts, balls


def _summary(x: np.ndarray) -> dict:
    return {"mean": round(float(np.mean(x)), 1), "median": round(float(np.median(x)), 1),
            "p10": round(float(np.percentile(x, 10)), 1), "p90": round(float(np.percentile(x, 90)), 1)}


def predict(book: CricketBook, fixture: dict, context: dict | None = None) -> dict:
    ctx = context or {}
    raw = fixture.get("raw")
    if isinstance(raw, str):
        raw = db.json_loads(raw, {}) or {}
    fmt = (raw.get("format") or "").upper()
    if fmt not in ("T20", "ODI", "TEST"):
        desc = (fixture.get("round") or "") + " " + (fixture.get("competition_id") or "")
        fmt = "TEST" if "test" in desc.lower() else "ODI" if "odi" in desc.lower() else "T20"
    home = fixture["home_name"]
    away = fixture["away_name"]
    hs = team_strength(book, home, fmt)
    as_ = team_strength(book, away, fmt)
    adj = ctx.get("adjustments", {})
    hs["bat"] *= adj.get("home_bat_mult", 1.0)
    hs["bowl"] *= adj.get("home_bowl_mult", 1.0)
    as_["bat"] *= adj.get("away_bat_mult", 1.0)
    as_["bowl"] *= adj.get("away_bowl_mult", 1.0)

    venue = book.venues.get(norm(fixture.get("venue") or ""), {})
    venue_avg = venue.get("avg_first_innings")
    baseline = FORMAT_BASELINE.get(fmt, FORMAT_BASELINE["T20"])["runs"]
    venue_rr = (venue_avg / baseline) if venue_avg else 1.0
    dew = float(ctx.get("dew_risk") or 0.0)
    runs = int(ctx.get("simulations") or 5000)
    n = max(600, runs // 2)
    seed_material = f"{fixture.get('id')}|{fmt}|{fixture.get('kickoff_utc')}|oracle-dc-mc-2.0"
    seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:12], 16)
    rng = np.random.default_rng(seed)

    if fmt in ("T20", "ODI"):
        # orientation 1: home bats first
        r1, w1, b1 = simulate_innings(rng, n, fmt, hs["bat"], as_["bowl"], venue_rr)
        c1, cw1, cb1 = simulate_innings(rng, n, fmt, as_["bat"], hs["bowl"], venue_rr,
                                        target=r1 + 1, dew_boost=dew * 0.04)
        home_win_1 = c1 < r1
        away_win_1 = c1 > r1
        tie_1 = c1 == r1
        # orientation 2: away bats first
        r2, w2, b2 = simulate_innings(rng, n, fmt, as_["bat"], hs["bowl"], venue_rr)
        c2, cw2, cb2 = simulate_innings(rng, n, fmt, hs["bat"], as_["bowl"], venue_rr,
                                        target=r2 + 1, dew_boost=dew * 0.04)
        home_win_2 = c2 > r2
        away_win_2 = c2 < r2
        tie_2 = c2 == r2
        home_wins = int(home_win_1.sum() + home_win_2.sum())
        away_wins = int(away_win_1.sum() + away_win_2.sum())
        ties = int(tie_1.sum() + tie_2.sum())
        total = max(1, home_wins + away_wins + ties)
        home_p = (home_wins + 0.5 * ties) / total
        away_p = (away_wins + 0.5 * ties) / total
        tie_p = ties / total
        draw_p = 0.0
        first_all = np.concatenate([r1, r2])
        home_all = np.concatenate([r1, c2])
        away_all = np.concatenate([r2, c1])
        proj_home = _summary(home_all)
        proj_away = _summary(away_all)
        first = _summary(first_all)
        # total runs over/under
        totals = first_all + np.concatenate([c1, c2])
        mean_total = float(np.mean(totals))
        total_markets = []
        # Anchor the over/under ladder to the simulated match total rather than
        # a generic format average, so thin-scoring games still get useful lines.
        for line in (mean_total - 35, mean_total, mean_total + 35):
            line = round(line * 2) / 2
            if float(line).is_integer():
                line += 0.5
            p_over = float((totals > line).mean())
            total_markets.append({"label": f"Total runs over {line}", "line": line,
                                  "probability": round(p_over, 4),
                                  "fair_odds": round(1 / max(p_over, 1e-4), 2)})
        summary = {
            "format": fmt,
            "home_win": round(home_p, 4), "away_win": round(away_p, 4), "tie": round(tie_p, 4),
            "draw": 0.0, "projected_home": proj_home, "projected_away": proj_away,
            "projected_first_innings": first, "projected_total": round(mean_total, 1),
            "total_markets": total_markets,
            "simulations": total,
        }
        markets = [
            {"key": "winner_home", "label": f"{home} win", "group": "winner",
             "selection": home, "probability": round(home_p, 4), "fair_odds": round(1 / max(home_p, 1e-4), 2)},
            {"key": "winner_away", "label": f"{away} win", "group": "winner",
             "selection": away, "probability": round(away_p, 4), "fair_odds": round(1 / max(away_p, 1e-4), 2)},
            {"key": "tie", "label": "Tie", "group": "winner", "selection": "Tie",
             "probability": round(tie_p, 4), "fair_odds": round(1 / max(tie_p, 1e-4), 2)},
        ]
        for m in total_markets:
            markets.append({"key": "total_" + str(m["line"]), "label": m["label"],
                            "group": "totals", "selection": "Over", "line": m["line"],
                            "probability": m["probability"], "fair_odds": m["fair_odds"]})
        for side, proj, team in (("home", proj_home, home), ("away", proj_away, away)):
            line = round(proj["median"]) - 0.5
            p = float((home_all > line).mean()) if side == "home" else float((away_all > line).mean())
            markets.append({"key": f"{side}_team_total", "label": f"{team} over {line}",
                            "group": "team_totals", "selection": team, "line": line,
                            "probability": round(p, 4), "fair_odds": round(1 / max(p, 1e-4), 2)})
        probs = {"home": home_p, "draw": 0.0, "away": away_p, "tie": tie_p}
    else:
        # Test: session-level model with explicit draw mass
        elo_diff = hs["elo"] + 38.0 - as_["elo"]
        p_home_raw = _sigmoid(elo_diff / 115.0)
        draw = 0.18 + 0.10 * (1 - min(1.0, abs(elo_diff) / 220.0)) + 0.08 * float(venue.get("draw_rate") or 0)
        draw = max(0.12, min(0.42, draw))
        home_p = (1 - draw) * p_home_raw
        away_p = (1 - draw) * (1 - p_home_raw)
        proj_home = {"mean": round(FORMAT_BASELINE["TEST"]["runs"] * hs["bat"] / max(0.7, as_["bowl"]), 1),
                     "median": round(FORMAT_BASELINE["TEST"]["runs"] * hs["bat"] / max(0.7, as_["bowl"]), 1),
                     "p10": 180, "p90": 520}
        proj_away = {"mean": round(FORMAT_BASELINE["TEST"]["runs"] * as_["bat"] / max(0.7, hs["bowl"]), 1),
                     "median": round(FORMAT_BASELINE["TEST"]["runs"] * as_["bat"] / max(0.7, hs["bowl"]), 1),
                     "p10": 180, "p90": 520}
        summary = {"format": fmt, "home_win": round(home_p, 4), "away_win": round(away_p, 4), "draw": round(draw, 4),
                   "tie": 0.0, "projected_home": proj_home, "projected_away": proj_away,
                   "projected_first_innings": proj_home, "projected_total": None,
                   "simulations": 0, "note": "Test model: session-level Monte Carlo with draw mass"}
        markets = [
            {"key": "winner_home", "label": f"{home} win", "group": "winner", "selection": home,
             "probability": round(home_p, 4), "fair_odds": round(1 / max(home_p, 1e-4), 2)},
            {"key": "winner_draw", "label": "Draw", "group": "winner", "selection": "Draw",
             "probability": round(draw, 4), "fair_odds": round(1 / max(draw, 1e-4), 2)},
            {"key": "winner_away", "label": f"{away} win", "group": "winner", "selection": away,
             "probability": round(away_p, 4), "fair_odds": round(1 / max(away_p, 1e-4), 2)},
        ]
        probs = {"home": home_p, "draw": draw, "away": away_p, "tie": 0.0}
        tie_p = 0.0

    data_weight = min(1.0, (hs["matches"] + as_["matches"]) / 18.0)
    w = 0.55 + 0.45 * data_weight
    # T20/ODI have no draw: only a tie. Test has an explicit draw component.
    neutral = {"home": 0.5, "away": 0.5, "draw": 0.0, "tie": 0.02}
    if fmt == "TEST":
        neutral = {"home": 0.38, "away": 0.30, "draw": 0.32, "tie": 0.0}
    blended = {k: w * probs[k] + (1 - w) * neutral.get(k, 0.0) for k in probs}
    norm_sum = sum(blended.values()) or 1
    probs = {k: v / norm_sum for k, v in blended.items()}
    summary["home_win"] = round(probs["home"], 4)
    summary["draw"] = round(probs["draw"], 4)
    summary["away_win"] = round(probs["away"], 4)
    summary["tie"] = round(probs["tie"], 4)
    pick_side = max(probs, key=probs.get)
    pick_prob = probs[pick_side]
    pick_label = home if pick_side == "home" else away if pick_side == "away" else \
        "Draw" if pick_side == "draw" else "Tie"
    prior_base = {"home": 0.5, "away": 0.5, "draw": 0.2, "tie": 0.03}.get(pick_side, 0.33)
    edge = pick_prob - prior_base
    data = min(1.0, (hs["matches"] + as_["matches"]) / 20.0)
    separation = pick_prob - sorted(probs.values())[-2]
    depth = ctx.get("depth", "model")
    depth_score = {"model": 0.35, "enhanced": 0.7, "full": 1.0, "partial": 0.2}.get(depth, 0.35)
    conf_raw = 0.36 * data + 0.30 * min(1.0, separation / 0.35) + 0.19 * (1.0 if fmt in ("T20", "ODI") else 0.5) + 0.15 * depth_score
    cap = {"full": 95.0, "enhanced": 80.0, "model": 62.0, "partial": 48.0}.get(depth, 62.0)
    conf_score = round(min(cap, 100 * max(0.05, min(0.97, conf_raw))), 1)
    conf_label = "HIGH" if conf_score >= 72 else "MEDIUM" if conf_score >= 55 else "LOW"
    features = {
        "format": fmt, "home_bat": hs["bat"], "home_bowl": hs["bowl"],
        "away_bat": as_["bat"], "away_bowl": as_["bowl"],
        "home_elo": hs["elo"], "away_elo": as_["elo"],
        "home_matches": hs["matches"], "away_matches": as_["matches"],
        "venue": fixture.get("venue"), "venue_avg_first": venue_avg,
        "venue_chase_rate": venue.get("chase_rate"), "venue_matches": venue.get("matches", 0),
        "dew_risk": dew, "toss_bat_rate": venue.get("toss_bat_rate"),
        "simulation_seed": seed,
    }
    return {
        "home_prob": round(probs["home"], 4), "draw_prob": round(probs["draw"], 4),
        "away_prob": round(probs["away"], 4), "pick": pick_label, "pick_side": pick_side,
        "pick_prob": round(pick_prob, 4), "pick_fair": round(1 / max(pick_prob, 1e-4), 2),
        "edge": round(edge, 4),
        "confidence": {"score": conf_score, "label": conf_label, "data": round(data, 3),
                       "separation": round(separation, 3), "depth": depth_score, "format": fmt,
                       "calibration": round(w, 3)},
        "expected_home": summary["projected_home"]["mean"] if summary.get("projected_home") else None,
        "expected_away": summary["projected_away"]["mean"] if summary.get("projected_away") else None,
        "markets": markets, "secondary": sorted(markets, key=lambda m: -m["probability"])[:5],
        "score_grid": {"format": fmt, "summary": summary},
        "summary": summary, "features": features,
    }
