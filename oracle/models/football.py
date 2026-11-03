"""Dixon-Coles / bivariate Poisson football engine.

The model is fitted independently for each competition with time decay and
empirical-Bayes shrinkage. It never reads a bookmaker price. Outputs are
probabilities and fair odds derived only from the fitted goal model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from .. import db

from .handicap import (effective_probability, european_handicap, fair_decimal,
                       settlement_from_margin)

MAX_GOALS = 10
HOME_BASE = {"home": 0.45, "draw": 0.26, "away": 0.29}


@dataclass
class CompetitionModel:
    competition_id: str
    mu: float
    home_adv: float
    rho: float
    attack: dict[str, float]
    defence: dict[str, float]  # higher = better defence
    matches: dict[str, int]
    base_rates: dict[str, float]
    n_matches: int
    goals_avg: float
    fitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class FootballModelBook:
    competitions: dict[str, CompetitionModel]
    fallback: CompetitionModel
    team_prior: dict[str, dict]
    global_home_adv: float
    global_rho: float
    global_mu: float
    trained_at: str
    training_matches: int


def _tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    if x == 0 and y == 0:
        value = 1.0 - lh * la * rho
    elif x == 0 and y == 1:
        value = 1.0 + lh * rho
    elif x == 1 and y == 0:
        value = 1.0 + la * rho
    elif x == 1 and y == 1:
        value = 1.0 - rho
    else:
        value = 1.0
    return max(value, 1e-9)


def score_grid(lh: float, la: float, rho: float = -0.03, max_goals: int = MAX_GOALS) -> np.ndarray:
    lh = float(max(0.05, min(6.0, lh)))
    la = float(max(0.05, min(6.0, la)))
    x = np.arange(max_goals + 1)
    px = poisson.pmf(x, lh)
    py = poisson.pmf(x, la)
    grid = np.outer(px, py)
    for i in range(2):
        for j in range(2):
            grid[i, j] *= _tau(i, j, lh, la, rho)
    total = grid.sum()
    if total <= 0 or not np.isfinite(total):
        grid = np.outer(px, py)
        total = grid.sum()
    return grid / total


def grid_markets(grid: np.ndarray, home: str, away: str,
                 lh: float | None = None, la: float | None = None,
                 rho: float = -0.03) -> tuple[dict, list[dict]]:
    n = grid.shape[0]
    idx = np.arange(n)
    diff = np.subtract.outer(idx, idx)
    totals = np.add.outer(idx, idx)
    home_win = float(np.tril(grid, -1).sum())
    draw = float(np.trace(grid))
    away_win = float(np.triu(grid, 1).sum())
    btts = float(grid[1:, 1:].sum())

    def ou(line: float):
        over = float(grid[totals > line].sum())
        under = float(grid[totals < line].sum())
        push = float(grid[totals == line].sum())
        return over, under, push

    markets: list[dict] = []

    def add(key, label, group, prob, selection=None, line=None, settlement=None,
            fair_odds=None, correlation_supported=True, assumption=None, breakdown=None):
        prob = max(0.0001, min(0.9999, float(prob)))
        row = {
            "key": key, "label": label, "group": group, "selection": selection or label,
            "line": line, "probability": round(prob, 4),
            "fair_odds": round(float(fair_odds), 4) if fair_odds else round(1 / prob, 2),
            "settlement": settlement,
            "correlation_supported": bool(correlation_supported),
        }
        if assumption:
            row["assumption"] = assumption
        if breakdown:
            row["settlement_breakdown"] = breakdown
        markets.append(row)

    # 1X2
    add("1x2_home", f"{home} win", "result", home_win, home,
        settlement={"type": "result", "side": "home"})
    add("1x2_draw", "Draw", "result", draw, "Draw",
        settlement={"type": "result", "side": "draw"})
    add("1x2_away", f"{away} win", "result", away_win, away,
        settlement={"type": "result", "side": "away"})
    # Double chance
    add("dc_1x", f"{home} or draw", "double_chance", home_win + draw,
        settlement={"type": "dc", "sides": ["home", "draw"]})
    add("dc_12", "No draw", "double_chance", home_win + away_win,
        settlement={"type": "dc", "sides": ["home", "away"]})
    add("dc_x2", f"Draw or {away}", "double_chance", draw + away_win,
        settlement={"type": "dc", "sides": ["draw", "away"]})
    # Draw no bet
    if home_win + away_win > 0:
        add("dnb_home", f"{home} draw no bet", "draw_no_bet", home_win / (home_win + away_win),
            home, settlement={"type": "dnb", "side": "home"})
        add("dnb_away", f"{away} draw no bet", "draw_no_bet", away_win / (home_win + away_win),
            away, settlement={"type": "dnb", "side": "away"})
    # BTTS
    add("btts_yes", "Both teams score", "btts", btts,
        settlement={"type": "btts", "value": "yes"})
    add("btts_no", "Not both teams score", "btts", 1 - btts,
        settlement={"type": "btts", "value": "no"})
    # BTTS + result
    yes = (idx[:, None] > 0) & (idx[None, :] > 0)
    no = ~yes
    result_masks = {
        "home": diff > 0, "draw": diff == 0, "away": diff < 0,
    }
    for btts_value, bmask in (("yes", yes), ("no", no)):
        for side, rmask in result_masks.items():
            prob = float(grid[bmask & rmask].sum())
            side_label = home if side == "home" else away if side == "away" else "Draw"
            add(f"btts_{btts_value}_{side}", f"BTTS {btts_value} + {side_label}",
                "btts_result", prob, f"BTTS {btts_value} + {side_label}",
                settlement={"type": "btts_result", "btts": btts_value, "side": side})
    # Main totals
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        over, under, _ = ou(line)
        add(f"over_{str(line).replace('.', '_')}", f"Over {line} goals", "totals", over,
            line=line, settlement={"type": "total", "line": line, "side": "over"})
        add(f"under_{str(line).replace('.', '_')}", f"Under {line} goals", "totals", under,
            line=line, settlement={"type": "total", "line": line, "side": "under"})
    # Exact total goals
    for goals in range(0, 5):
        prob = float(grid[totals == goals].sum())
        add(f"exact_goals_{goals}", f"Exactly {goals} goals", "exact_goals", prob,
            line=goals, settlement={"type": "exact_goals", "goals": goals})
    add("exact_goals_5plus", "5+ goals", "exact_goals", float(grid[totals >= 5].sum()),
        line=5, settlement={"type": "exact_goals", "goals": 5, "plus": True})
    # Team totals
    for side, probs in (("home", grid.sum(axis=1)), ("away", grid.sum(axis=0))):
        team_name = home if side == "home" else away
        for line in (0.5, 1.5, 2.5, 3.5):
            over = float(probs[idx > line].sum())
            under = float(probs[idx < line].sum())
            add(f"{side}_team_over_{str(line).replace('.', '_')}", f"{team_name} over {line}",
                "team_totals", over, selection=team_name, line=line,
                settlement={"type": "team_total", "team": side, "line": line, "side": "over"})
            add(f"{side}_team_under_{str(line).replace('.', '_')}", f"{team_name} under {line}",
                "team_totals", under, selection=team_name, line=line,
                settlement={"type": "team_total", "team": side, "line": line, "side": "under"})
    # Asian handicap incl. quarter lines
    margin_values = idx - 0  # placeholder; use diff distribution below
    home_margin_probs = np.array([float(grid[diff == m].sum()) for m in range(-(n - 1), n)])
    margin_values = np.arange(-(n - 1), n)
    ah_lines = (-2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0,
                0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
    for line in ah_lines:
        st_home = settlement_from_margin(margin_values, home_margin_probs, line)
        fair_home = fair_decimal(st_home)
        p_home = effective_probability(st_home)
        add(f"ah_home_{line:+g}", f"{home} {line:+g}", "asian_handicap", p_home,
            selection=home, line=line, fair_odds=fair_home,
            settlement={"type": "ah", "side": "home", "line": line},
            correlation_supported=False, breakdown=st_home)
        # away line is the mirror; use the same distribution with -diff
        away_margin_probs = home_margin_probs[::-1]
        st_away = settlement_from_margin(margin_values, away_margin_probs, line)
        fair_away = fair_decimal(st_away)
        p_away = effective_probability(st_away)
        add(f"ah_away_{line:+g}", f"{away} {line:+g}", "asian_handicap", p_away,
            selection=away, line=line, fair_odds=fair_away,
            settlement={"type": "ah", "side": "away", "line": line},
            correlation_supported=False, breakdown=st_away)
    # European handicap
    for line in (-2.0, -1.0, 0.0, 1.0, 2.0):
        eh = european_handicap(grid, line)
        for side, prob in eh.items():
            label = home if side == "home" else away if side == "away" else "Draw"
            add(f"eh_{line:+g}_{side}", f"EH {line:+g} · {label}", "european_handicap",
                prob, selection=label, line=line,
                settlement={"type": "eh", "side": side, "line": line})
    # Winning margin
    add("margin_draw", "Winning margin: draw", "winning_margin", draw,
        settlement={"type": "margin", "side": "draw"})
    for side, op in (("home", ">"), ("away", "<")):
        for margin in (1, 2, 3):
            mask = (diff == margin) if side == "home" else (diff == -margin)
            prob = float(grid[mask].sum())
            name = home if side == "home" else away
            add(f"margin_{side}_{margin}", f"{name} by {margin}{'+' if margin == 3 else ''}",
                "winning_margin", prob, settlement={"type": "margin", "side": side, "margin": margin})
    # Win to nil / clean sheet
    add("home_win_nil", f"{home} win to nil", "special",
        float(sum(grid[i, 0] for i in range(1, n))),
        settlement={"type": "win_nil", "team": "home"})
    add("away_win_nil", f"{away} win to nil", "special",
        float(sum(grid[0, j] for j in range(1, n))),
        settlement={"type": "win_nil", "team": "away"})
    add("home_clean_sheet", f"{home} clean sheet", "special", float(grid[:, 0].sum()),
        settlement={"type": "clean_sheet", "team": "home"})
    add("away_clean_sheet", f"{away} clean sheet", "special", float(grid[0, :].sum()),
        settlement={"type": "clean_sheet", "team": "away"})
    # Correct score top 10
    flat = grid.flatten()
    for k in np.argsort(flat)[::-1][:10]:
        i, j = divmod(int(k), n)
        prob = float(flat[k])
        add(f"cs_{i}_{j}", f"Correct score {i}-{j}", "correct_score", prob,
            f"{i}-{j}", settlement={"type": "correct", "score": f"{i}-{j}"})
    # First-half / second-half markets (explicit model assumption)
    if lh is not None and la is not None:
        half_grid = score_grid(lh * 0.45, la * 0.45, rho)
        second_grid = score_grid(lh * 0.55, la * 0.55, rho)
        ht = half_grid
        ht_totals = np.add.outer(idx, idx)
        for line in (0.5, 1.5):
            add(f"fh_over_{str(line).replace('.', '_')}", f"First half over {line}",
                "halves", float(ht[ht_totals > line].sum()),
                line=line, assumption="independent halves; 45/55 xG split",
                correlation_supported=False,
                settlement={"type": "half_total", "half": 1, "line": line, "side": "over"})
            add(f"fh_under_{str(line).replace('.', '_')}", f"First half under {line}",
                "halves", float(ht[ht_totals < line].sum()),
                line=line, assumption="independent halves; 45/55 xG split",
                correlation_supported=False,
                settlement={"type": "half_total", "half": 1, "line": line, "side": "under"})
        ht_result = {"home": float(np.tril(ht, -1).sum()), "draw": float(np.trace(ht)),
                     "away": float(np.triu(ht, 1).sum())}
        for side, prob in ht_result.items():
            label = home if side == "home" else away if side == "away" else "Draw"
            add(f"ht_{side}", f"Half-time: {label}", "halves", prob,
                assumption="first-half Poisson; 45% xG share", correlation_supported=False,
                settlement={"type": "ht_result", "side": side})
        # Build the joint HT/FT result distribution from the two independent
        # half-score grids. FT is cumulative, so multiplying HT and FT outcome
        # marginals would incorrectly treat the shared first-half goals as
        # independent of the final score.
        htft_probs = {
            (ht_side, ft_side): 0.0
            for ht_side in ("home", "draw", "away")
            for ft_side in ("home", "draw", "away")
        }
        for hi in range(n):
            for ai in range(n):
                p_ht = float(ht[hi, ai])
                if p_ht <= 0:
                    continue
                ht_side = "home" if hi > ai else "away" if hi < ai else "draw"
                for si in range(n):
                    for sa in range(n):
                        p = p_ht * float(second_grid[si, sa])
                        if p <= 0:
                            continue
                        final_home, final_away = hi + si, ai + sa
                        ft_side = "home" if final_home > final_away else "away" if final_home < final_away else "draw"
                        htft_probs[(ht_side, ft_side)] += p
        total_htft = sum(htft_probs.values()) or 1
        for (ht_side, ft_side), prob in htft_probs.items():
            hn = home if ht_side == "home" else away if ht_side == "away" else "Draw"
            fn = home if ft_side == "home" else away if ft_side == "away" else "Draw"
            add(f"htft_{ht_side}_{ft_side}", f"HT {hn} / FT {fn}", "halves", prob / total_htft,
                assumption="independent half-score models; 45/55 xG split", correlation_supported=False,
                settlement={"type": "htft", "ht": ht_side, "ft": ft_side})
        for k in np.argsort(ht.flatten())[::-1][:5]:
            i, j = divmod(int(k), n)
            add(f"ht_cs_{i}_{j}", f"Half-time score {i}-{j}", "halves",
                float(ht[i, j]), f"{i}-{j}",
                assumption="first-half Poisson; 45% xG share",
                correlation_supported=False,
                settlement={"type": "half_correct", "score": f"{i}-{j}"})

    top_k = np.argsort(flat)[::-1][:10]
    top_score_rows = []
    for k in top_k:
        i, j = divmod(int(k), n)
        prob = float(flat[k])
        top_score_rows.append({
            "score": f"{i}-{j}",
            "probability": round(prob, 4),
            "fair_odds": round(1 / max(prob, 1e-6), 2),
        })

    goal_diff_probs = {}
    for delta in range(-(n - 1), n):
        prob = float(grid[diff == delta].sum())
        if prob > 0:
            goal_diff_probs[str(delta)] = round(prob, 4)

    summary = {
        "home_win": round(home_win, 4), "draw": round(draw, 4), "away_win": round(away_win, 4),
        "btts": round(btts, 4), "over_2_5": round(ou(2.5)[0], 4),
        "under_2_5": round(ou(2.5)[1], 4),
        "expected_total": round(float((lh or 0.0) + (la or 0.0)), 3) if lh is not None and la is not None else None,
        "home_clean_sheet": round(float(grid[:, 0].sum()), 4),
        "away_clean_sheet": round(float(grid[0, :].sum()), 4),
        "most_likely_score": top_score_rows[0]["score"] if top_score_rows else None,
        "most_likely_score_probability": top_score_rows[0]["probability"] if top_score_rows else None,
        "top_scorelines": top_score_rows,
        "goal_difference_probs": goal_diff_probs,
        "top_scores": top_score_rows,
        "home_xg": None, "away_xg": None,
    }
    return summary, markets

def _base_rates(home_goals: np.ndarray, away_goals: np.ndarray, weights: np.ndarray) -> dict:
    total = weights.sum()
    if total <= 0:
        return dict(HOME_BASE)
    home = float(weights[home_goals > away_goals].sum() / total)
    draw = float(weights[home_goals == away_goals].sum() / total)
    away = float(weights[home_goals < away_goals].sum() / total)
    return {
        "home": round(0.7 * home + 0.3 * HOME_BASE["home"], 4),
        "draw": round(0.7 * draw + 0.3 * HOME_BASE["draw"], 4),
        "away": round(0.7 * away + 0.3 * HOME_BASE["away"], 4),
    }


def fit_dixon_coles(home_goals, away_goals, home_ids, away_ids, days_ago,
                    half_life: float = 180.0, reg: float | None = None) -> dict:
    """Fit one competition. Returns parameters."""
    hg = np.asarray(home_goals, dtype=float)
    ag = np.asarray(away_goals, dtype=float)
    h = np.asarray(home_ids)
    a = np.asarray(away_ids)
    days = np.asarray(days_ago, dtype=float)
    teams = sorted(set(h.tolist()) | set(a.tolist()))
    if len(teams) < 2 or len(hg) < 4:
        return {}
    index = {t: i for i, t in enumerate(teams)}
    hi = np.array([index[t] for t in h])
    ai = np.array([index[t] for t in a])
    weights = np.clip(0.5 ** (days / half_life), 0.05, 1.0)
    n = len(teams)
    wsum = float(weights.sum())
    avg_goals = float((weights * (hg + ag)).sum() / (2 * wsum))
    away_avg = float((weights * ag).sum() / wsum)
    mu = math.log(max(0.2, away_avg))
    reg = reg if reg is not None else 1.0 + 12.0 / max(len(hg), 1)

    def unpack(p):
        att = p[:n]
        dfn = p[n:2 * n]
        # centre for identifiability
        att = att - att.mean()
        dfn = dfn - dfn.mean()
        gamma, rho = p[2 * n], p[2 * n + 1]
        return att, dfn, gamma, rho

    def nll(p):
        att, dfn, gamma, rho = unpack(p)
        lh = np.exp(mu + att[hi] - dfn[ai] + gamma)
        la = np.exp(mu + att[ai] - dfn[hi])
        lh = np.clip(lh, 1e-4, 8)
        la = np.clip(la, 1e-4, 8)
        ll = hg * np.log(lh) - lh + ag * np.log(la) - la
        # Dixon-Coles low-score correction
        tau = np.ones_like(lh)
        m00 = (hg == 0) & (ag == 0)
        m01 = (hg == 0) & (ag == 1)
        m10 = (hg == 1) & (ag == 0)
        m11 = (hg == 1) & (ag == 1)
        tau[m00] = 1 - lh[m00] * la[m00] * rho
        tau[m01] = 1 + lh[m01] * rho
        tau[m10] = 1 + la[m10] * rho
        tau[m11] = 1 - rho
        tau = np.clip(tau, 1e-8, None)
        ll = ll + np.log(tau)
        return (-(weights * ll).sum() + reg * float((p[:2 * n] ** 2).sum())
                + 3.0 * (gamma - 0.22) ** 2 + 14.0 * (rho + 0.03) ** 2)

    x0 = np.concatenate([np.zeros(2 * n), [0.22, -0.03]])
    bounds = [(-1.8, 1.8)] * (2 * n) + [(-0.2, 0.65), (-0.08, 0.08)]
    try:
        result = minimize(nll, x0, method="L-BFGS-B", bounds=bounds,
                          options={"maxiter": 220, "ftol": 1e-7, "maxls": 40})
        p = result.x
    except Exception:
        return {}
    att, dfn, gamma, rho = unpack(p)
    counts = {t: int(((h == t) | (a == t)).sum()) for t in teams}
    return {
        "teams": teams, "attack": {t: float(att[index[t]]) for t in teams},
        "defence": {t: float(dfn[index[t]]) for t in teams},
        "home_adv": float(gamma), "rho": float(rho), "mu": float(mu),
        "matches": counts, "base_rates": _base_rates(hg, ag, weights),
        "n_matches": int(len(hg)), "goals_avg": float(avg_goals),
        "success": bool(getattr(result, "success", False)),
    }


def load_training_data(history_days: int = 420, before_iso: str | None = None,
                       as_of_iso: str | None = None) -> list[dict]:
    reference_iso = as_of_iso or before_iso
    try:
        reference = datetime.fromisoformat(reference_iso.replace("Z", "+00:00")) if reference_iso else datetime.now(timezone.utc)
        reference = reference.astimezone(timezone.utc)
    except (TypeError, ValueError):
        reference = datetime.now(timezone.utc)
    cutoff = reference.timestamp() - history_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
    upper = before_iso or "9999-12-31T00:00:00Z"
    with db.db() as conn:
        rows = db.rows(
            conn,
            """SELECT id, competition_id, home_team_id, away_team_id, home_name, away_name,
                      home_score_num, away_score_num, kickoff_utc
               FROM fixtures
               WHERE sport='football' AND status='finished'
                 AND home_score_num IS NOT NULL AND away_score_num IS NOT NULL
                 AND kickoff_utc >= ? AND kickoff_utc < ?""",
            (cutoff_iso, upper),
        )
    out = []
    for r in rows:
        try:
            ko = datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00"))
        except Exception:
            continue
        if r["home_score_num"] is None or r["away_score_num"] is None:
            continue
        if not (0 <= r["home_score_num"] <= 15 and 0 <= r["away_score_num"] <= 15):
            continue
        out.append({**r, "days_ago": max(0.0, (reference - ko).total_seconds() / 86400)})
    return out


def train(history_days: int = 420, before_iso: str | None = None,
          persist: bool = True, as_of_iso: str | None = None) -> FootballModelBook:
    data = load_training_data(history_days, before_iso=before_iso, as_of_iso=as_of_iso)
    by_comp: dict[str, list[dict]] = {}
    for row in data:
        by_comp.setdefault(row["competition_id"], []).append(row)

    competitions: dict[str, CompetitionModel] = {}
    team_prior: dict[str, dict] = {}
    for comp_id, rows in by_comp.items():
        if len(rows) < 12:
            continue
        fitted = fit_dixon_coles(
            [r["home_score_num"] for r in rows], [r["away_score_num"] for r in rows],
            [r["home_team_id"] for r in rows], [r["away_team_id"] for r in rows],
            [r["days_ago"] for r in rows],
        )
        if not fitted or "attack" not in fitted:
            continue
        competitions[comp_id] = CompetitionModel(
            competition_id=comp_id, mu=fitted["mu"], home_adv=fitted["home_adv"],
            rho=fitted["rho"], attack=fitted["attack"], defence=fitted["defence"],
            matches=fitted["matches"], base_rates=fitted["base_rates"],
            n_matches=fitted["n_matches"], goals_avg=fitted["goals_avg"],
        )
        for team, count in fitted["matches"].items():
            team_prior.setdefault(team, {"attack": [], "defence": [], "matches": 0})
            team_prior[team]["attack"].append(fitted["attack"][team])
            team_prior[team]["defence"].append(fitted["defence"][team])
            team_prior[team]["matches"] += count

    # League-level fallback parameters are a weighted average of the fitted
    # competitions. This avoids an 8,000-parameter global fit that would
    # overfit sparse leagues and is not needed for prediction.
    if competitions:
        weight_sum = sum(c.n_matches for c in competitions.values())
        global_home = sum(c.home_adv * c.n_matches for c in competitions.values()) / weight_sum
        global_rho = sum(c.rho * c.n_matches for c in competitions.values()) / weight_sum
    else:
        global_home, global_rho = 0.22, -0.03
    total_goals = sum((r["home_score_num"] + r["away_score_num"]) for r in data)
    global_mu = math.log(max(0.35, total_goals / (2 * max(1, len(data)))))

    fallback = CompetitionModel(
        competition_id="__fallback__", mu=global_mu, home_adv=global_home, rho=global_rho,
        attack={}, defence={}, matches={}, base_rates=dict(HOME_BASE),
        n_matches=len(data), goals_avg=math.exp(global_mu),
    )
    book = FootballModelBook(
        competitions=competitions, fallback=fallback, team_prior=team_prior,
        global_home_adv=global_home, global_rho=global_rho, global_mu=global_mu,
        trained_at=datetime.now(timezone.utc).isoformat(),
        training_matches=len(data),
    )
    if persist:
        persist_ratings(book)
    return book


def persist_ratings(book: FootballModelBook) -> None:
    from ..models.ratings import football_elo  # local import avoids cycle
    elo = football_elo()
    # A team can appear in several competitions. Persist the rating from the
    # competition where it has the most fitted matches, not whichever
    # competition happened to be written last.
    best: dict[str, tuple[int, CompetitionModel]] = {}
    for comp in book.competitions.values():
        for team, count in comp.matches.items():
            if team not in best or count > best[team][0]:
                best[team] = (count, comp)
    with db.db() as conn:
        for team, (count, comp) in best.items():
            db.upsert_rating(conn, {
                "team_id": team, "sport": "football", "competition_id": comp.competition_id,
                "as_of": book.trained_at, "attack": round(comp.attack.get(team, 0.0), 4),
                "defence": round(comp.defence.get(team, 0.0), 4),
                "elo": round(elo.get(team, 1450.0), 1), "matches": count,
                "wins": 0, "draws": 0, "losses": 0,
                "goals_for": 0, "goals_against": 0, "form": [],
                "home_advantage": round(comp.home_adv, 4),
                "metadata": {"competition_matches": comp.n_matches,
                             "goals_avg": round(comp.goals_avg, 3),
                             "rho": round(comp.rho, 4)},
            })
    db.log("info", "model", f"football model trained on {book.training_matches} matches",
           {"competitions": len(book.competitions)})


def team_strength(book: FootballModelBook, team_id: str, comp_id: str) -> tuple[float, float, int]:
    comp = book.competitions.get(comp_id)
    if comp and team_id in comp.attack:
        return comp.attack[team_id], comp.defence[team_id], comp.matches.get(team_id, 0)
    prior = book.team_prior.get(team_id)
    if prior and prior["attack"]:
        return float(np.mean(prior["attack"])), float(np.mean(prior["defence"])), int(prior["matches"])
    return 0.0, 0.0, 0


def expected_goals(book: FootballModelBook, comp_id: str, home_id: str, away_id: str,
                   home_attack_mult: float = 1.0, home_defence_mult: float = 1.0,
                   away_attack_mult: float = 1.0, away_defence_mult: float = 1.0,
                   weather_goal_effect: float = 0.0) -> tuple[float, float, CompetitionModel]:
    comp = book.competitions.get(comp_id) or book.fallback
    ha, hd, hm = team_strength(book, home_id, comp_id)
    aa, ad, am = team_strength(book, away_id, comp_id)
    # shrink very low-sample ratings toward league average
    if hm < 4:
        ha *= hm / 4
        hd *= hm / 4
    if am < 4:
        aa *= am / 4
        ad *= am / 4
    lh = math.exp(comp.mu + ha - ad + comp.home_adv)
    la = math.exp(comp.mu + aa - hd)
    lh *= max(0.55, home_attack_mult) * max(0.55, away_defence_mult)
    la *= max(0.55, away_attack_mult) * max(0.55, home_defence_mult)
    factor = max(0.8, min(1.2, 1.0 + weather_goal_effect))
    lh *= factor
    la *= factor
    return max(0.15, min(5.5, lh)), max(0.15, min(5.5, la)), comp


def confidence(home_prob: float, draw_prob: float, away_prob: float,
               home_matches: int, away_matches: int, depth: str = "model") -> dict:
    probs = np.array([home_prob, draw_prob, away_prob], dtype=float)
    probs = np.clip(probs, 1e-6, 1)
    probs = probs / probs.sum()
    entropy = float(-(probs * np.log(probs)).sum() / math.log(3))
    separation = float(np.sort(probs)[-1] - np.sort(probs)[-2])
    data = min(1.0, (home_matches + away_matches) / 28.0)
    depth_score = {"model": 0.35, "enhanced": 0.7, "full": 1.0, "partial": 0.2}.get(depth, 0.35)
    raw = 0.34 * data + 0.28 * (1 - entropy) + 0.23 * min(1.0, separation / 0.35) + 0.15 * depth_score
    cap = {"full": 95.0, "enhanced": 78.0, "model": 62.0, "partial": 48.0}.get(depth, 62.0)
    score = round(min(cap, 100 * max(0.05, min(0.98, raw))), 1)
    if score >= 72:
        label = "HIGH"
    elif score >= 55:
        label = "MEDIUM"
    else:
        label = "LOW"
    return {"score": score, "label": label, "data": round(data, 3),
            "entropy": round(entropy, 3), "separation": round(separation, 3),
            "depth": depth_score}


def predict(book: FootballModelBook, fixture: dict, context: dict | None = None) -> dict:
    ctx = context or {}
    comp_id = fixture.get("competition_id")
    home = fixture["home_team_id"]
    away = fixture["away_team_id"]
    adj = ctx.get("adjustments", {})
    lh, la, comp = expected_goals(
        book, comp_id, home, away,
        home_attack_mult=adj.get("home_attack_mult", 1.0),
        home_defence_mult=adj.get("home_defence_mult", 1.0),
        away_attack_mult=adj.get("away_attack_mult", 1.0),
        away_defence_mult=adj.get("away_defence_mult", 1.0),
        weather_goal_effect=adj.get("weather_goal_effect", 0.0),
    )
    _, _, home_m = team_strength(book, home, comp_id)
    _, _, away_m = team_strength(book, away, comp_id)
    grid = score_grid(lh, la, comp.rho)
    summary, markets = grid_markets(grid, fixture["home_name"], fixture["away_name"],
                                    lh, la, comp.rho)
    summary["home_xg"] = round(lh, 3)
    summary["away_xg"] = round(la, 3)

    probs = {"home": summary["home_win"], "draw": summary["draw"], "away": summary["away_win"]}
    base = comp.base_rates or HOME_BASE
    # Empirical-Bayes calibration: with thin samples, shrink the model's 1X2
    # distribution toward the competition base rate. This prevents a handful
    # of matches from producing fake 95% certainties.
    data_weight = min(1.0, (home_m + away_m) / 24.0)
    w = 0.40 + 0.60 * data_weight
    blended = {k: w * probs[k] + (1 - w) * base.get(k, HOME_BASE[k]) for k in probs}
    norm = sum(blended.values()) or 1
    probs = {k: v / norm for k, v in blended.items()}
    pick_side = max(probs, key=probs.get)
    pick_prob = probs[pick_side]
    edge = float(pick_prob - base.get(pick_side, HOME_BASE.get(pick_side, 1 / 3)))
    depth = ctx.get("depth", "model")
    conf = confidence(probs["home"], probs["draw"], probs["away"], home_m, away_m, depth)
    conf["calibration"] = round(w, 3)
    summary["home_win"] = round(probs["home"], 4)
    summary["draw"] = round(probs["draw"], 4)
    summary["away_win"] = round(probs["away"], 4)
    pick_label = (fixture["home_name"] if pick_side == "home" else
                  fixture["away_name"] if pick_side == "away" else "Draw")

    # secondary high-probability markets for the dossier
    secondary = sorted(
        [m for m in markets if m["group"] in ("double_chance", "totals", "btts", "asian_handicap")],
        key=lambda m: -m["probability"],
    )[:6]

    features = {
        "home_attack": round(team_strength(book, home, comp_id)[0], 3),
        "home_defence": round(team_strength(book, home, comp_id)[1], 3),
        "away_attack": round(team_strength(book, away, comp_id)[0], 3),
        "away_defence": round(team_strength(book, away, comp_id)[1], 3),
        "home_matches": home_m, "away_matches": away_m,
        "home_advantage": round(comp.home_adv, 3), "rho": round(comp.rho, 3),
        "league_goals_avg": round(comp.goals_avg, 2), "competition_model": comp.competition_id,
        "base_rates": base,
    }
    return {
        "home_prob": round(probs["home"], 4), "draw_prob": round(probs["draw"], 4),
        "away_prob": round(probs["away"], 4), "pick": pick_label, "pick_side": pick_side,
        "pick_prob": round(pick_prob, 4), "pick_fair": round(1 / max(pick_prob, 1e-4), 2),
        "edge": round(edge, 4), "confidence": conf, "expected_home": round(lh, 3),
        "expected_away": round(la, 3), "markets": markets, "secondary": secondary,
        "score_grid": {"home_xg": round(lh, 2), "away_xg": round(la, 2),
                       "grid": [[round(float(v), 5) for v in row] for row in grid],
                       "top_scores": summary["top_scores"]},
        "summary": summary, "features": features,
    }
