"""Optional bookmaker benchmark layer.

The core ORACLE prediction is not modified here. This module only compares a
stored model probability with timestamped bookmaker odds for evaluation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from .. import db
from ..ingest.odds import cached_odds, fetch_fixture_odds, store_odds


def _grid(prediction: dict) -> np.ndarray | None:
    sg = prediction.get("score_grid")
    if isinstance(sg, str):
        sg = db.json_loads(sg, {})
    grid = (sg or {}).get("grid")
    if not grid:
        return None
    try:
        arr = np.array(grid, dtype=float)
        total = arr.sum()
        return arr / total if total > 0 else None
    except Exception:
        return None


def _model_prob(prediction: dict, market: str, selection: str, line: float | None,
                home: str, away: str) -> tuple[float | None, str]:
    if market == "Moneyline":
        if selection == home:
            return float(prediction.get("home_prob") or 0), "1X2 home"
        if selection == away:
            return float(prediction.get("away_prob") or 0), "1X2 away"
        return float(prediction.get("draw_prob") or 0), "1X2 draw"
    grid = _grid(prediction)
    if grid is None:
        return None, "score grid unavailable"
    n = grid.shape[0]
    idx = np.arange(n)
    totals = np.add.outer(idx, idx)
    if market == "Total":
        line = float(line if line is not None else 2.5)
        if selection.lower().startswith("over"):
            return float(grid[totals > line].sum()), f"P(total > {line})"
        return float(grid[totals < line].sum()), f"P(total < {line})"
    if market == "Spread":
        line = float(line or 0)
        diff = np.subtract.outer(idx, idx)  # home - away
        if selection.lower().startswith(home.lower()):
            cover = diff + line > 0
        else:
            cover = -diff + line > 0
        return float(grid[cover].sum()), f"P(spread {line:+g})"
    return None, "unsupported market"


def _value_rating(edge: float | None, model_prob: float | None) -> str:
    if model_prob is None or edge is None:
        return "INSUFFICIENT DATA"
    if edge >= 0.05:
        return "HIGH VALUE"
    if edge >= 0.02:
        return "MODERATE VALUE"
    if edge > -0.02:
        return "LOW VALUE"
    return "NO VALUE"


def _risk(model_prob: float | None, depth: str | None) -> str:
    if model_prob is None:
        return "Insufficient data"
    if model_prob < 0.20:
        return "High"
    if model_prob < 0.45:
        return "Medium"
    if depth in ("model", "partial"):
        return "Medium (thin research)"
    return "Lower (not safe)"


def build_benchmark(fixture_id: str, stake: float = 100.0, refresh: bool = False) -> dict:
    stake = max(1.0, float(stake or 100))
    with db.db() as conn:
        fixture = db.row(conn, """SELECT f.*, c.name AS competition_name
                                  FROM fixtures f LEFT JOIN competitions c ON c.id=f.competition_id
                                  WHERE f.id=?""", (fixture_id,))
        prediction = db.row(conn, "SELECT * FROM predictions WHERE fixture_id=?", (fixture_id,))
    if not fixture or not prediction:
        return {"available": False, "message": "fixture or prediction not found", "rows": []}
    if isinstance(prediction.get("score_grid"), str):
        prediction["score_grid"] = db.json_loads(prediction["score_grid"], {})
    market = cached_odds(fixture_id, ttl_minutes=15) if not refresh else None
    if not market:
        fetched = fetch_fixture_odds(fixture)
        if fetched.get("available"):
            store_odds(fixture_id, fetched)
            market = fetched
        else:
            return {"available": False, "message": fetched.get("message", "no odds"),
                    "fixture": fixture, "prediction": prediction, "rows": [],
                    "source": "ESPN public odds", "policy": "benchmark-only"}
    # Prefer rows from the database (authoritative timestamps).
    with db.db() as conn:
        stored = db.rows(conn, "SELECT * FROM market_odds WHERE fixture_id=? ORDER BY market, selection", (fixture_id,))
    if not stored:
        return {"available": False, "message": "no stored odds", "rows": []}
    # De-vig within each market group (and line for totals).
    groups: dict[str, list[dict]] = {}
    for r in stored:
        key = r["market"] if r["market"] != "Total" else f"{r['market']}:{r.get('line')}"
        groups.setdefault(key, []).append(r)
    fair: dict[int, float] = {}
    for rows in groups.values():
        over = sum(float(r.get("implied") or 0) for r in rows)
        for r in rows:
            fair[id(r)] = float(r.get("implied") or 0) / over if over > 0 else 0.0
    out = []
    for r in stored:
        model_p, basis = _model_prob(prediction, r["market"], r["selection"], r.get("line"),
                                     fixture["home_name"], fixture["away_name"])
        decimal = float(r.get("decimal") or 0)
        implied = float(r.get("implied") or (1 / decimal if decimal else 0))
        devig = fair.get(id(r), implied)
        edge = (model_p - devig) if model_p is not None else None
        profit = stake * (decimal - 1)
        ret = stake * decimal
        ev = (model_p * profit - (1 - model_p) * stake) if model_p is not None else None
        out.append({
            "market": r["market"], "selection": r["selection"], "line": r.get("line"),
            "decimal": round(decimal, 4), "implied": round(implied, 4),
            "devig": round(devig, 4), "model_prob": round(model_p, 4) if model_p is not None else None,
            "edge": round(edge, 4) if edge is not None else None,
            "stake": stake, "potential_return": round(ret, 2), "potential_profit": round(profit, 2),
            "ev": round(ev, 2) if ev is not None else None,
            "value": _value_rating(edge, model_p),
            "risk": _risk(model_p, prediction.get("data_depth")),
            "basis": basis, "provider": r.get("provider"),
        })
    priced = [x for x in out if x["decimal"] > 0]
    highest = max(priced, key=lambda x: x["decimal"]) if priced else None
    best_return = max(priced, key=lambda x: x["potential_return"]) if priced else None
    positive = [x for x in priced if x["ev"] is not None and x["model_prob"] is not None]
    balanced = max(positive, key=lambda x: (x["ev"], x["model_prob"])) if positive else None
    if balanced and balanced["model_prob"] < 0.35:
        # prefer a probability-weighted compromise if the max-EV leg is a longshot
        candidates = [x for x in positive if x["model_prob"] >= 0.35]
        if candidates:
            balanced = max(candidates, key=lambda x: (x["ev"], x["model_prob"]))
    best_prob = max(priced, key=lambda x: (x["model_prob"] or 0)) if priced else None
    moneyline = [x for x in priced if x["market"] == "Moneyline"]
    most_likely = max(moneyline, key=lambda x: (x["model_prob"] or 0)) if moneyline else None
    slip = None
    if best_prob:
        slip = {
            "legs": [best_prob], "combined_probability": best_prob["model_prob"],
            "combined_odds": best_prob["decimal"], "stake": stake,
            "potential_return": best_prob["potential_return"],
            "potential_profit": best_prob["potential_profit"],
            "threshold": 0.80, "meets_threshold": (best_prob["model_prob"] or 0) >= 0.80,
            "ev": best_prob["ev"], "pricing": "bookmaker odds",
        }
    return {
        "available": True, "fixture": fixture, "prediction": prediction,
        "rows": out, "stake": stake, "slip": slip,
        "best_return": best_return, "best_balanced": balanced, "highest_odds": highest,
        "most_likely": most_likely,
        "selection_rule": ("Most likely = highest model probability in the 1X2 market. "
                           "Best return = highest decimal odds. Best balanced = highest EV among "
                           "selections with model probability >= 35%; if none, highest model probability."),
        "devig_note": ("De-vig is calculated within each market group: fair = implied / sum(implied). "
                       "1X2 groups all three outcomes; spread and total groups use both sides."),
        "precision_note": ("Odds are stored to 4 decimal places; the table displays 2. "
                           "Return, profit and EV use the unrounded decimal price."),
        "source": stored[0].get("source"), "provider": stored[0].get("provider"),
        "fetched_at": stored[0].get("fetched_at"), "event_id": stored[0].get("event_id"),
        "policy": "benchmark-only", "market_free_core": True,
        "note": ("This is a benchmark layer. The core ORACLE forecast remains market-free; "
                 "bookmaker odds are shown only for comparison and are never used by the model."),
        "data_quality": {"depth": prediction.get("data_depth"), "confidence": prediction.get("confidence")},
    }
