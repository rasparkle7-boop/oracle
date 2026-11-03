"""ORACLE reasoning core.

Deterministic, auditable synthesis of model probabilities and researched
context. This is intentionally not a wrapper around bookmaker consensus: the
narrative explains the model's own numbers, the evidence behind them, and the
ways the conclusion can fail.
"""
from __future__ import annotations

from typing import Any

from ..models import ratings


def pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{100 * float(x):.{digits}f}%"


def num(x: float | None, digits: int = 2) -> str:
    if x is None:
        return "n/a"
    return f"{float(x):.{digits}f}"


def _signed(x: float, digits: int = 1) -> str:
    return f"{x:+.{digits}f}"


def _grade(depth: str) -> str:
    return {"full": "A", "enhanced": "B", "model": "C", "partial": "D"}.get(depth, "C")


def _form_line(form: dict) -> str:
    seq = form.get("sequence") or "—"
    return f"{seq} ({form.get('wins', 0)}W-{form.get('draws', 0)}D-{form.get('losses', 0)}L, {form.get('goals_for', 0):.0f}GF/{form.get('goals_against', 0):.0f}GA)"


def _injuries_text(players: list[dict]) -> str:
    if not players:
        return "no confirmed absences in the structured feed"
    parts = []
    for p in players[:4]:
        ret = f" (return {p.get('expected_return')})" if p.get("expected_return") else ""
        parts.append(f"{p.get('name')} — {p.get('type')}{ret}")
    return "; ".join(parts)


def _market_line(prediction: dict, key: str) -> str:
    for m in prediction.get("markets") or []:
        if m.get("key") == key:
            return f"{m['probability'] * 100:.1f}% (fair {m['fair_odds']:.2f})"
    return "n/a"


def football_analysis(fixture: dict, prediction: dict, context: dict) -> dict:
    home = fixture["home_name"]
    away = fixture["away_name"]
    probs = {"home": prediction["home_prob"], "draw": prediction["draw_prob"], "away": prediction["away_prob"]}
    pick_side = prediction.get("pick_side") or max(probs, key=probs.get)
    pick = prediction.get("pick")
    conf = prediction.get("confidence") or {}
    feats = prediction.get("features") or {}
    ctx_form = context.get("form") or {}
    hf, af = ctx_form.get("home") or {}, ctx_form.get("away") or {}
    inj = context.get("injuries") or {}
    flags = context.get("flags") or []
    weather = context.get("weather") or {}
    h2h = context.get("h2h") or {}
    xgh = prediction.get("expected_home")
    xga = prediction.get("expected_away")
    diff = (xgh or 0) - (xga or 0)
    base = feats.get("base_rates") or {}
    prior = base.get(pick_side, 0.33)
    edge = prediction.get("edge", 0)
    favorite = home if pick_side == "home" else away if pick_side == "away" else "the draw"
    underdog = away if pick_side == "home" else home if pick_side == "away" else (away if probs["away"] >= probs["home"] else home)

    home_pros, home_cons, away_pros, away_cons = [], [], [], []
    if (xgh or 0) > (xga or 0):
        home_pros.append(f"Projected xG edge: {num(xgh)} vs {num(xga)}")
        away_cons.append(f"Concedes a projected {num(xgh)} xG")
    else:
        away_pros.append(f"Projected xG edge: {num(xga)} vs {num(xgh)}")
        home_cons.append(f"Concedes a projected {num(xga)} xG")
    if feats.get("home_advantage", 0) > 0.1:
        home_pros.append(f"Home coefficient +{num(feats.get('home_advantage'))} goals")
    if hf.get("form_pct", 0) >= 55:
        home_pros.append(f"Recent form {_form_line(hf)}")
    elif hf.get("matches", 0):
        home_cons.append(f"Recent form only {_form_line(hf)}")
    if af.get("form_pct", 0) >= 55:
        away_pros.append(f"Recent form {_form_line(af)}")
    elif af.get("matches", 0):
        away_cons.append(f"Recent form only {_form_line(af)}")
    if inj.get("home_impact", 0) > 0.05:
        home_cons.append(f"Availability hit: {_injuries_text(inj.get('home'))}")
        away_pros.append("Opponent carries confirmed absences")
    if inj.get("away_impact", 0) > 0.05:
        away_cons.append(f"Availability hit: {_injuries_text(inj.get('away'))}")
        home_pros.append("Opponent carries confirmed absences")
    if (context.get("fatigue") or {}).get("home", {}).get("load", 0) > 0.55:
        home_cons.append(f"Congestion: {(context['fatigue']['home'].get('matches_21d') or 0)} matches in 21 days")
    if (context.get("fatigue") or {}).get("away", {}).get("load", 0) > 0.55:
        away_cons.append(f"Congestion: {(context['fatigue']['away'].get('matches_21d') or 0)} matches in 21 days")
    if probs["draw"] >= 0.27:
        home_cons.append(f"Draw risk is material at {pct(probs['draw'])}")
        away_cons.append(f"Draw risk is material at {pct(probs['draw'])}")
    if not home_pros:
        home_pros.append("No dominant model edge; home advantage is the main lever")
    if not away_pros:
        away_pros.append("No dominant model edge; the model sees a tight match")
    if not home_cons:
        home_cons.append("No material red flag in the verified data")
    if not away_cons:
        away_cons.append("No material red flag in the verified data")

    edge_thesis = [
        f"ORACLE's independent goal model makes {favorite} the {pct(max(probs.values()))} favourite; "
        f"the league prior for that outcome is {pct(prior)}, a model edge of {_signed(edge * 100)}pp.",
        f"Projected goals: {home} {num(xgh)} — {away} {num(xga)} (goal difference {_signed(diff)}).",
    ]
    if hf.get("matches") or af.get("matches"):
        edge_thesis.append(f"Form: {home} {hf.get('sequence', '—')} vs {away} {af.get('sequence', '—')}.")
    if inj.get("home_impact", 0) > 0.05 or inj.get("away_impact", 0) > 0.05:
        edge_thesis.append(
            f"Availability: {home} impact {inj.get('home_impact', 0):.2f}, "
            f"{away} impact {inj.get('away_impact', 0):.2f} (bounded 0–0.30 scale).")
    if weather.get("description") or weather.get("temperature_c") is not None:
        edge_thesis.append(
            f"Weather: {weather.get('description') or 'forecast'} · {weather.get('temperature_c', 'n/a')}°C · "
            f"wind {weather.get('wind_kph', 'n/a')} kph · rain chance {weather.get('precip_chance', 'n/a')}%.")

    risks = []
    if conf.get("score", 0) < 55:
        risks.append(f"Low model conviction ({conf.get('score')}/100): the top outcome is only {pct(max(probs.values()))}.")
    if probs["draw"] >= 0.25:
        risks.append(f"The draw is live at {pct(probs['draw'])}; a single goal can flip the result.")
    if (hf.get("matches") or 0) < 6 or (af.get("matches") or 0) < 6:
        risks.append("Thin fitted sample for at least one side; ratings are shrunk toward the league mean.")
    if inj.get("home_impact", 0) > 0.08 or inj.get("away_impact", 0) > 0.08:
        risks.append("Injury/suspension information can change before kickoff; re-run after confirmed line-ups.")
    if flags:
        risks.append("Context flags: " + ", ".join(flags) + ".")
    risks.append("A single match is a high-variance event. A 50% probability is a coin-flip with a lean, not a guarantee.")

    why_not = (
        f"{underdog} can flip the model if they win the xG battle ({num(xga if underdog == away else xgh)} projected), "
        f"avoid an early goal against, and keep the game level into the final third. "
        f"The model still assigns {pct(probs['away'] if underdog == away else probs['home'])} to that path."
    )

    tactical = {
        "home": {"team": home, "pros": home_pros[:5], "cons": home_cons[:5]},
        "away": {"team": away, "pros": away_pros[:5], "cons": away_cons[:5]},
    }
    key_battles = [
        f"{home} attack ({num(feats.get('home_attack'))}) vs {away} defence ({num(feats.get('away_defence'))})",
        f"{away} attack ({num(feats.get('away_attack'))}) vs {home} defence ({num(feats.get('home_defence'))})",
    ]
    if h2h.get("matches"):
        key_battles.append(
            f"H2H: {home} {h2h.get('home_wins', 0)}W · {h2h.get('draws', 0)}D · {away} {h2h.get('away_wins', 0)}W "
            f"in the last {len(h2h.get('matches'))} meetings.")

    edge_quality = ("STRONG" if abs(edge) >= 0.08 and conf.get("score", 0) >= 62 else
                    "MODERATE" if abs(edge) >= 0.04 else "THIN" if abs(edge) >= 0.015 else "NONE")
    market_read = (
        f"Fair odds are derived from ORACLE's probabilities only: {home} {_market_line(prediction, '1x2_home')}, "
        f"draw {_market_line(prediction, '1x2_draw')}, {away} {_market_line(prediction, '1x2_away')}. "
        f"Over 2.5: {_market_line(prediction, 'over_2_5')}; BTTS yes: {_market_line(prediction, 'btts_yes')}. "
        "No bookmaker price is used as an input.")
    secondary = prediction.get("secondary") or []
    if secondary:
        market_read += " Secondary model leans: " + ", ".join(
            f"{m['label']} {pct(m['probability'])}" for m in secondary[:3]) + "."

    headline = (f"{pick} · {pct(prediction.get('pick_prob'))} model probability"
                if edge_quality != "NONE" else f"No clear edge · {pick} only {pct(prediction.get('pick_prob'))}")
    verdict = (
        f"ORACLE selects {pick} at {pct(prediction.get('pick_prob'))} (fair {prediction.get('pick_fair')}). "
        + (f"The model edge is {edge_quality}; treat this as a lean rather than a conviction play. " if edge_quality in ("THIN", "NONE") else "")
        + f"The independent goal model projects {home} {num(xgh)} — {away} {num(xga)}. "
        f"Conviction is {conf.get('label', 'LOW')} ({conf.get('score', 0)}/100); research grade {_grade(context.get('depth', 'model'))}."
    )
    narrative = [
        verdict,
        "Why this side: " + " ".join(edge_thesis),
        f"What can go wrong: " + " ".join(risks[:3]),
        f"The {underdog} path: " + why_not,
    ]
    return {
        "headline": headline, "verdict": verdict, "edge_thesis": edge_thesis,
        "tactical": tactical, "risks": risks, "why_not": why_not,
        "key_battles": key_battles, "market_read": market_read,
        "research_grade": _grade(context.get("depth", "model")),
        "edge_quality": edge_quality,
        "confidence_note": (
            f"Confidence {conf.get('score', 0)}/100 ({conf.get('label', 'LOW')}). "
            f"Data depth {conf.get('data', 0):.2f}, entropy {conf.get('entropy', 0):.2f}, "
            f"separation {conf.get('separation', 0):.2f}."),
        "model_trace": [
            {"label": "Home attack", "value": num(feats.get("home_attack"))},
            {"label": "Home defence", "value": num(feats.get("home_defence"))},
            {"label": "Away attack", "value": num(feats.get("away_attack"))},
            {"label": "Away defence", "value": num(feats.get("away_defence"))},
            {"label": "Home advantage", "value": num(feats.get("home_advantage"))},
            {"label": "Low-score rho", "value": num(feats.get("rho"))},
            {"label": "League goals/match", "value": num(feats.get("league_goals_avg"))},
            {"label": "Projected xG", "value": f"{num(xgh)} – {num(xga)}"},
        ],
        "narrative": narrative,
    }


def cricket_analysis(fixture: dict, prediction: dict, context: dict) -> dict:
    home, away = fixture["home_name"], fixture["away_name"]
    probs = {"home": prediction["home_prob"], "draw": prediction["draw_prob"], "away": prediction["away_prob"]}
    pick = prediction.get("pick")
    pick_side = prediction.get("pick_side")
    conf = prediction.get("confidence") or {}
    feats = prediction.get("features") or {}
    summary = prediction.get("summary") or {}
    fmt = feats.get("format") or "T20"
    ctx_form = context.get("form") or {}
    hf, af = ctx_form.get("home") or {}, ctx_form.get("away") or {}
    inj = context.get("injuries") or {}
    pitch = context.get("pitch") or {}
    weather = context.get("weather") or {}
    venue = context.get("venue") or {}
    vstats = venue.get("stats") or {}
    home_proj = (summary.get("projected_home") or {})
    away_proj = (summary.get("projected_away") or {})
    first = (summary.get("projected_first_innings") or {})
    draw = probs.get("draw", 0)
    favorite = home if pick_side == "home" else away if pick_side == "away" else "the draw"
    underdog = away if pick_side == "home" else home if pick_side == "away" else home

    edge_thesis = [
        f"ORACLE's {fmt} Monte Carlo makes {favorite} the {pct(max(probs.values()))} favourite "
        f"(model edge {_signed(prediction.get('edge', 0) * 100)}pp vs a neutral prior).",
        f"Projected score band: {home} {home_proj.get('mean', 'n/a')} "
        f"(p10–p90 {home_proj.get('p10', 'n/a')}–{home_proj.get('p90', 'n/a')}) vs "
        f"{away} {away_proj.get('mean', 'n/a')} "
        f"(p10–p90 {away_proj.get('p10', 'n/a')}–{away_proj.get('p90', 'n/a')}).",
    ]
    if fmt == "TEST":
        edge_thesis.append(f"Test model draw mass is {pct(draw)}; the result is simulated at session level, not ball-by-ball.")
    else:
        edge_thesis.append(f"First-innings projection: {first.get('mean', 'n/a')} runs (p10–p90 {first.get('p10', 'n/a')}–{first.get('p90', 'n/a')}).")
    if feats.get("venue_avg_first"):
        edge_thesis.append(
            f"Venue: {venue.get('name') or fixture.get('venue') or 'unknown'} averages {feats.get('venue_avg_first')} "
            f"first-innings runs; chase win rate {pct(feats.get('venue_chase_rate'))} across "
            f"{feats.get('venue_matches', 0)} tracked matches.")
    if feats.get("dew_risk"):
        edge_thesis.append(f"Dew risk {pct(feats.get('dew_risk'))}: the chasing side gets a small late-innings boost.")
    if hf.get("matches") or af.get("matches"):
        edge_thesis.append(f"Recent form: {home} {hf.get('sequence', '—')} vs {away} {af.get('sequence', '—')}.")

    home_pros, home_cons, away_pros, away_cons = [], [], [], []
    if feats.get("home_bat", 0) >= 1.0:
        home_pros.append(f"Batting index {num(feats.get('home_bat'))} (above format baseline)")
    else:
        home_cons.append(f"Batting index {num(feats.get('home_bat'))} (below format baseline)")
    if feats.get("home_bowl", 0) <= 1.0:
        home_pros.append(f"Bowling index {num(feats.get('home_bowl'))} (suppresses scoring)")
    else:
        home_cons.append(f"Bowling index {num(feats.get('home_bowl'))} (leaks runs)")
    if feats.get("away_bat", 0) >= 1.0:
        away_pros.append(f"Batting index {num(feats.get('away_bat'))}")
    else:
        away_cons.append(f"Batting index {num(feats.get('away_bat'))}")
    if feats.get("away_bowl", 0) <= 1.0:
        away_pros.append(f"Bowling index {num(feats.get('away_bowl'))}")
    else:
        away_cons.append(f"Bowling index {num(feats.get('away_bowl'))}")
    if inj.get("home_impact", 0) > 0.04:
        home_cons.append(f"Availability: {_injuries_text(inj.get('home'))}")
    if inj.get("away_impact", 0) > 0.04:
        away_cons.append(f"Availability: {_injuries_text(inj.get('away'))}")
    if (context.get("fatigue") or {}).get("home", {}).get("rest_days") is not None:
        rest = context["fatigue"]["home"]["rest_days"]
        if rest < 2:
            home_cons.append(f"Quick turnaround: {rest} days rest")
    if (context.get("fatigue") or {}).get("away", {}).get("rest_days") is not None:
        rest = context["fatigue"]["away"]["rest_days"]
        if rest < 2:
            away_cons.append(f"Quick turnaround: {rest} days rest")
    if fmt == "TEST" and draw > 0.2:
        home_cons.append(f"Draw mass {pct(draw)}")
        away_cons.append(f"Draw mass {pct(draw)}")
    if not home_pros:
        home_pros.append("No strong model edge in the current sample")
    if not away_pros:
        away_pros.append("No strong model edge in the current sample")
    if not home_cons:
        home_cons.append("No material red flag in the verified data")
    if not away_cons:
        away_cons.append("No material red flag in the verified data")

    risks = []
    if conf.get("score", 0) < 55:
        risks.append(f"Low conviction ({conf.get('score')}/100): limited verified match data for at least one side.")
    if fmt != "TEST":
        risks.append("T20/ODI variance is extreme: one powerplay or one death over can swing the result.")
        risks.append("Toss and dew can change the value of batting first; the model averages both orientations.")
    else:
        risks.append("Test outcomes depend on declaration timing, follow-on decisions and weather loss.")
    if feats.get("dew_risk"):
        risks.append(f"Dew risk {pct(feats.get('dew_risk'))} favours the chase.")
    if inj.get("home_impact", 0) > 0.04 or inj.get("away_impact", 0) > 0.04:
        risks.append("Playing XIs are not final; re-run after the toss and confirmed line-ups.")
    if not feats.get("venue_matches"):
        risks.append("Limited venue sample; pitch behaviour is inferred from competition baselines.")
    risks.append("A single match is high variance. Treat this as a probability, not a certainty.")

    why_not = (
        f"{underdog} can flip the model with an early wicket cluster, a top-order collapse avoided, "
        f"and a strong death-bowling phase. The simulation still gives that path "
        f"{pct(probs['away'] if underdog == away else probs['home'])}.")
    tactical = {
        "home": {"team": home, "pros": home_pros[:5], "cons": home_cons[:5]},
        "away": {"team": away, "pros": away_pros[:5], "cons": away_cons[:5]},
    }
    key_battles = [
        f"{home} batting ({num(feats.get('home_bat'))}) vs {away} bowling ({num(feats.get('away_bowl'))})",
        f"{away} batting ({num(feats.get('away_bat'))}) vs {home} bowling ({num(feats.get('home_bowl'))})",
    ]
    if feats.get("venue_avg_first"):
        key_battles.append(f"Pitch/venue: {feats.get('venue_avg_first')} avg first innings, chase rate {pct(feats.get('venue_chase_rate'))}")
    if feats.get("dew_risk"):
        key_battles.append(f"Dew: {pct(feats.get('dew_risk'))}")

    edge_quality = ("STRONG" if abs(prediction.get("edge", 0)) >= 0.08 and conf.get("score", 0) >= 62 else
                    "MODERATE" if abs(prediction.get("edge", 0)) >= 0.04 else
                    "THIN" if abs(prediction.get("edge", 0)) >= 0.015 else "NONE")
    market_read = (
        f"Fair odds from ORACLE only: {home} {_market_line(prediction, 'winner_home')}, "
        f"{away} {_market_line(prediction, 'winner_away')}"
        + (f", draw {_market_line(prediction, 'winner_draw')}" if fmt == "TEST" else
           f", tie {_market_line(prediction, 'tie')}") + ". No bookmaker price is an input.")
    headline = (f"{pick} · {pct(prediction.get('pick_prob'))} model probability"
                if edge_quality != "NONE" else f"No clear edge · {pick} only {pct(prediction.get('pick_prob'))}")
    verdict = (
        f"ORACLE selects {pick} at {pct(prediction.get('pick_prob'))} (fair {prediction.get('pick_fair')}) "
        f"in this {fmt} fixture. "
        + (f"Edge quality {edge_quality}; this is a lean, not a conviction play. " if edge_quality in ("THIN", "NONE") else "")
        + f"Conviction {conf.get('label', 'LOW')} ({conf.get('score', 0)}/100), "
        f"research grade {_grade(context.get('depth', 'model'))}."
    )
    narrative = [verdict, "Why: " + " ".join(edge_thesis), "What can go wrong: " + " ".join(risks[:3]),
                 f"Underdog path: {why_not}"]
    return {
        "headline": headline, "verdict": verdict, "edge_thesis": edge_thesis,
        "tactical": tactical, "risks": risks, "why_not": why_not,
        "key_battles": key_battles, "market_read": market_read,
        "research_grade": _grade(context.get("depth", "model")),
        "edge_quality": edge_quality,
        "confidence_note": (
            f"Confidence {conf.get('score', 0)}/100 ({conf.get('label', 'LOW')}). "
            f"Data {conf.get('data', 0):.2f}, separation {conf.get('separation', 0):.2f}, "
            f"format {fmt}."),
        "model_trace": [
            {"label": "Home batting", "value": num(feats.get("home_bat"))},
            {"label": "Home bowling", "value": num(feats.get("home_bowl"))},
            {"label": "Away batting", "value": num(feats.get("away_bat"))},
            {"label": "Away bowling", "value": num(feats.get("away_bowl"))},
            {"label": "Elo home/away", "value": f"{num(feats.get('home_elo'), 0)} / {num(feats.get('away_elo'), 0)}"},
            {"label": "Venue avg 1st inns", "value": num(feats.get("venue_avg_first"), 0)},
            {"label": "Dew risk", "value": pct(feats.get("dew_risk"))},
            {"label": "Simulations", "value": str(summary.get("simulations") or 0)},
        ],
        "narrative": narrative,
    }


def build_analysis(fixture: dict, prediction: dict, context: dict) -> dict:
    base = (cricket_analysis(fixture, prediction, context)
            if fixture.get("sport") == "cricket"
            else football_analysis(fixture, prediction, context))
    base["protocol"] = _protocol(fixture, prediction, context, base)
    base["data_quality"] = base["protocol"]["data_quality"]
    base["data_gaps"] = base["protocol"]["data_gaps"]
    base["responsible_gambling"] = RESPONSIBLE_GAMBLING
    return base


# ---------------------------------------------------------------------------
# Forecast protocol sections (market-free)
# ---------------------------------------------------------------------------

RESPONSIBLE_GAMBLING = (
    "This is a probabilistic research forecast, not financial advice or a guaranteed outcome. "
    "Sports events are inherently uncertain. Never wager more than you can afford to lose. "
    "If betting stops being entertainment, seek support from a responsible-gambling resource."
)


def _referee_text(context: dict) -> str:
    ref = context.get("referee") or {}
    if not ref.get("name"):
        return "Referee not published; no card/foul adjustment applied."
    stats = ref.get("stats") or {}
    bits = []
    if ref.get("matches"):
        matches = ref["matches"]
        bits.append(f"{int(matches) if float(matches).is_integer() else matches} matches")
    if stats.get("yellowCards") is not None:
        bits.append(f"{stats['yellowCards']} yellows/match")
    if stats.get("fouls") is not None:
        bits.append(f"{stats['fouls']} fouls/match")
    if stats.get("penalties") is not None:
        bits.append(f"{stats['penalties']} penalties")
    return f"{ref['name']}" + (" · " + " · ".join(bits) if bits else " · profile limited")


def _expected_script(fixture: dict, prediction: dict, context: dict) -> dict:
    sport = fixture.get("sport")
    weather = context.get("weather") or {}
    flags = context.get("flags") or []
    if sport == "cricket":
        summary = prediction.get("summary") or (prediction.get("score_grid") or {}).get("summary") or {}
        first = summary.get("projected_first_innings") or {}
        total = summary.get("projected_total")
        return {
            "format": summary.get("format") or (prediction.get("features") or {}).get("format"),
            "expected_first_innings": first.get("mean"),
            "expected_total": total,
            "likely_scenario": (
                f"Model projects {fixture['home_name']} and {fixture['away_name']} in the "
                f"{first.get('mean', 'n/a')} first-innings band. "
                f"Dew/weather: {', '.join(flags) if flags else 'no material flag'}."),
            "alternative_scenario": "A wicket cluster in the powerplay or a death-over collapse moves the win probability sharply.",
            "main_upset_risk": "Toss, dew and a single high-leverage over can override the strength gap.",
            "referee_weather_impact": f"{weather.get('description') or 'weather n/a'}; {', '.join(flags) if flags else 'no weather advisory'}.",
        }
    xgh = prediction.get("expected_home") or 0
    xga = prediction.get("expected_away") or 0
    total = xgh + xga
    avg_team = (prediction.get("features") or {}).get("league_goals_avg") or 1.3
    avg_total = avg_team * 2
    pace = "high" if total > avg_total * 1.12 else "low" if total < avg_total * 0.88 else "neutral"
    underdog = fixture["away_name"] if prediction.get("pick_side") == "home" else fixture["home_name"]
    underdog_p = prediction.get("away_prob") if prediction.get("pick_side") == "home" else prediction.get("home_prob")
    return {
        "expected_total": round(total, 2),
        "expected_margin": round(xgh - xga, 2),
        "pace": f"{pace} ({total:.2f} projected goals vs {avg_total:.2f} league total average)",
        "pace_label": pace.upper(),
        "likely_scenario": (
            f"{prediction.get('pick')} controls the projected xG lane "
            f"({xgh:.2f}–{xga:.2f}); the model's most likely score is "
            f"{((prediction.get('score_grid') or {}).get('top_scores') or [{}])[0].get('score', 'n/a')}."),
        "alternative_scenario": (
            f"{underdog} keeps the game level into the final third; the draw is "
            f"{pct(prediction.get('draw_prob'))} and an early goal changes the game state."),
        "main_upset_risk": f"{underdog} has a {pct(underdog_p)} path, mainly via set pieces, transition and variance.",
        "referee_weather_impact": f"{_referee_text(context)} Weather: {weather.get('description') or 'n/a'}.",
    }


def _fallback_data_quality(fixture: dict, context: dict) -> list[dict]:
    inj = context.get("injuries") or {}
    form = context.get("form") or {}
    hf, af = form.get("home") or {}, form.get("away") or {}
    weather = context.get("weather") or {}
    ref = context.get("referee") or {}
    news = context.get("news") or {}
    lineups = context.get("lineups") or {}
    return [
        {"category": "Event", "status": "verified", "reliability": "High",
         "notes": f"{fixture.get('home_name')} vs {fixture.get('away_name')}"},
        {"category": "Lineups", "status": "confirmed" if lineups.get("available") else "not published",
         "reliability": "High" if lineups.get("available") else "Low",
         "notes": "confirmed XI" if lineups.get("available") else "projected XI unavailable"},
        {"category": "Injuries", "status": "structured" if (inj.get("home") or inj.get("away")) else "no verified report",
         "reliability": "High" if (inj.get("home") or inj.get("away")) else "Low",
         "notes": f"{len(inj.get('home') or [])} home · {len(inj.get('away') or [])} away structured absences"},
        {"category": "Form", "status": f"{hf.get('matches', 0)}/{af.get('matches', 0)} matches",
         "reliability": "Medium" if min(hf.get("matches", 0), af.get("matches", 0)) < 4 else "High",
         "notes": f"{hf.get('sequence', '—')} vs {af.get('sequence', '—')}"},
        {"category": "Tactics", "status": "partial" if lineups.get("home_formation") else "not verified",
         "reliability": "Medium" if lineups.get("home_formation") else "Low",
         "notes": "formation/manager signal" if lineups.get("home_formation") else "no verified tactical feed"},
        {"category": "Weather", "status": "forecast" if weather else "unavailable",
         "reliability": "Medium" if weather else "Low",
         "notes": weather.get("description") or "no forecast attached"},
        {"category": "Venue/travel", "status": "verified" if (context.get("venue") or {}).get("name") else "partial",
         "reliability": "High" if (context.get("venue") or {}).get("name") else "Medium",
         "notes": (context.get("venue") or {}).get("name") or "venue not published"},
        {"category": "Referee", "status": "assigned" if ref.get("name") else "not assigned",
         "reliability": "High" if ref.get("name") and ref.get("stats") else "Medium" if ref.get("name") else "Low",
         "notes": ref.get("name") or "no referee published"},
        {"category": "News", "status": "sourced" if (news.get("home") or news.get("away")) else "none",
         "reliability": "Medium" if (news.get("home") or news.get("away")) else "Low",
         "notes": f"{len(news.get('home') or [])} home · {len(news.get('away') or [])} away articles"},
        {"category": "Market data", "status": "disabled by policy", "reliability": "n/a",
         "notes": "ORACLE is market-free; no odds are read"},
    ]


def _protocol(fixture: dict, prediction: dict, context: dict, analysis: dict) -> dict:
    sport = fixture.get("sport")
    feats = prediction.get("features") or {}
    ctx_form = context.get("form") or {}
    hf, af = ctx_form.get("home") or {}, ctx_form.get("away") or {}
    inj = context.get("injuries") or {}
    flags = context.get("flags") or []
    depth = context.get("depth", "model")
    conf = prediction.get("confidence") or {}
    edge = float(prediction.get("edge") or 0)
    pick_p = float(prediction.get("pick_prob") or 0)

    # Key player availability (structured where available)
    key_players = []
    for side, team in (("home", fixture["home_name"]), ("away", fixture["away_name"])):
        for p in (inj.get(side) or [])[:6]:
            key_players.append({
                "team": team, "player": p.get("name"), "status": p.get("type") or "out",
                "expected_return": p.get("expected_return") or "",
                "impact": p.get("impact"), "evidence": "structured match-centre availability",
                "confidence": "High" if p.get("type") in ("injury", "suspension") else "Medium",
            })
    player_note = (
        "No player-level minutes/usage/stat log feed is connected. Player projections are therefore "
        "not fabricated; only confirmed availability is shown."
        if not context.get("lineups", {}).get("available") else
        "Lineups are published, but player-level usage projections still require a player-log feed."
    )

    # Factor attribution
    factors = []
    factors.append({
        "factor": "Independent model edge vs competition base rate",
        "direction": "for the pick" if edge >= 0 else "against the pick",
        "size": "Large" if abs(edge) >= 0.08 else "Medium" if abs(edge) >= 0.035 else "Small",
        "evidence": f"model {pct(pick_p)} vs base prior; edge {edge*100:+.1f}pp",
        "timestamp": prediction.get("generated_at") or context.get("data_cutoff"),
        "confidence": "High" if conf.get("data", 0) > 0.6 else "Medium",
    })
    if sport == "football":
        diff = (prediction.get("expected_home") or 0) - (prediction.get("expected_away") or 0)
        factors.append({
            "factor": "Projected xG gap",
            "direction": "home" if diff > 0 else "away",
            "size": "Large" if abs(diff) >= 0.8 else "Medium" if abs(diff) >= 0.3 else "Small",
            "evidence": f"{prediction.get('expected_home')} – {prediction.get('expected_away')} xG",
            "timestamp": prediction.get("generated_at") or context.get("data_cutoff"),
            "confidence": "High" if conf.get("data", 0) > 0.6 else "Medium",
        })
    else:
        factors.append({
            "factor": "Batting / bowling strength gap",
            "direction": "for the pick" if pick_p >= 0.5 else "against the pick",
            "size": "Medium",
            "evidence": f"bat {feats.get('home_bat')}/{feats.get('away_bat')}, bowl {feats.get('home_bowl')}/{feats.get('away_bowl')}",
            "timestamp": prediction.get("generated_at") or context.get("data_cutoff"),
            "confidence": "Medium",
        })
    if (inj.get("home_impact") or 0) + (inj.get("away_impact") or 0) > 0.04:
        factors.append({
            "factor": "Availability / absences",
            "direction": "mixed" if (inj.get("home_impact") or 0) > 0 and (inj.get("away_impact") or 0) > 0 else "favours the less-depleted side",
            "size": "Large" if max(inj.get("home_impact") or 0, inj.get("away_impact") or 0) > 0.15 else "Medium",
            "evidence": f"home impact {inj.get('home_impact')}, away impact {inj.get('away_impact')}",
            "timestamp": context.get("data_cutoff"),
            "confidence": "High" if (inj.get("home") or inj.get("away")) else "Low",
        })
    if (hf.get("matches") or 0) + (af.get("matches") or 0) > 0:
        factors.append({
            "factor": "Recent form",
            "direction": "home" if hf.get("form_pct", 0) > af.get("form_pct", 0) else "away",
            "size": "Medium",
            "evidence": f"{hf.get('sequence', '—')} vs {af.get('sequence', '—')}",
            "timestamp": context.get("data_cutoff"),
            "confidence": "Medium" if min(hf.get("matches", 0), af.get("matches", 0)) >= 4 else "Low",
        })
    if flags:
        factors.append({
            "factor": "Context flags",
            "direction": "uncertainty",
            "size": "Medium",
            "evidence": ", ".join(flags[:6]),
            "timestamp": context.get("data_cutoff"),
            "confidence": "Medium",
        })
    if schema_ref := (context.get("referee") or {}).get("name"):
        factors.append({
            "factor": "Referee profile",
            "direction": "cards/fouls environment",
            "size": "Small",
            "evidence": _referee_text(context),
            "timestamp": context.get("data_cutoff"),
            "confidence": "Medium" if (context.get("referee") or {}).get("stats") else "Low",
        })
    factors.append({
        "factor": "Research depth",
        "direction": "confidence",
        "size": "Large" if depth in ("full", "enhanced") else "Medium",
        "evidence": f"{depth} · grade {analysis.get('research_grade', 'C')}",
        "timestamp": context.get("data_cutoff"),
        "confidence": "High" if depth == "full" else "Medium",
    })

    # Scenarios (qualitative where the triggering input is unconfirmed)
    scenarios = [
        {"name": "Base case — availability and weather as listed",
         "probability": "not quantified (model base case)",
         "effect": analysis.get("verdict", "")},
        {"name": "Key player confirmed out / limited",
         "probability": "conditional on team announcement",
         "effect": f"attack/usage multiplier already bounded at home {inj.get('home_impact', 0)} / away {inj.get('away_impact', 0)}; re-run after the XI."},
        {"name": "Weather/track shift",
         "probability": "not quantified",
         "effect": f"flags: {', '.join(flags) if flags else 'none'}; weather model is a forecast, not a guarantee."},
        {"name": "Early goal / powerplay wicket changes game state",
         "probability": "not quantified",
         "effect": "the model already integrates match-level variance; live re-forecast is required after a material early event."},
    ]

    data_gaps = list(context.get("data_gaps") or [])
    if not context.get("lineups", {}).get("available"):
        data_gaps.append("Confirmed lineups not published at forecast time")
    data_gaps.append("Player-level minutes/usage/stat logs not connected")
    data_gaps.append("Market odds intentionally not used (market-free policy)")
    data_gaps = list(dict.fromkeys(data_gaps))

    final = (
        f"{prediction.get('pick')} is the model's {pct(pick_p)} lean, not a certainty. "
        f"Conviction is {conf.get('label', 'LOW')} ({conf.get('score', 0)}/100), research grade "
        f"{analysis.get('research_grade', 'C')}. The main failure paths are "
        f"{', '.join((analysis.get('risks') or ['unmodelled variance'])[:3])}."
    )
    market_read = (
        "No odds provided. ORACLE is market-free: it can provide model probabilities, but it cannot "
        "calculate market edge, CLV or implied value. Fair odds shown elsewhere are 1 / model probability."
    )
    data_quality = context.get("data_quality") or _fallback_data_quality(fixture, context)
    for q in data_quality:
        q.setdefault("provider", "ORACLE local")
        q.setdefault("freshness", "unknown")
        q.setdefault("missing", "")
        q.setdefault("last_updated", context.get("data_cutoff"))

    if sport == "football":
        used = [
            {"input": "Dixon–Coles attack / defence", "role": "core",
             "evidence": f"home {num(feats.get('home_attack'))}/{num(feats.get('home_defence'))}, away {num(feats.get('away_attack'))}/{num(feats.get('away_defence'))}"},
            {"input": "Home advantage", "role": "core", "evidence": f"coefficient {num(feats.get('home_advantage'))}"},
            {"input": "Low-score rho", "role": "core", "evidence": f"rho {num(feats.get('rho'))}"},
            {"input": "Availability multipliers", "role": "context adjustment",
             "evidence": f"home impact {inj.get('home_impact', 0)}, away impact {inj.get('away_impact', 0)}"},
            {"input": "Fatigue multipliers", "role": "context adjustment",
             "evidence": f"home load {((context.get('fatigue') or {}).get('home') or {}).get('load', 0)}, away load {((context.get('fatigue') or {}).get('away') or {}).get('load', 0)}"},
            {"input": "Weather goal effect", "role": "context adjustment",
             "evidence": f"effect {((context.get('adjustments') or {}).get('weather_goal_effect', 0))}"},
        ]
    else:
        used = [
            {"input": "Batting / bowling indices", "role": "core",
             "evidence": f"bat {feats.get('home_bat')}/{feats.get('away_bat')}, bowl {feats.get('home_bowl')}/{feats.get('away_bowl')}"},
            {"input": "Format Elo", "role": "core", "evidence": f"{num(feats.get('home_elo'), 0)} / {num(feats.get('away_elo'), 0)}"},
            {"input": "Venue first-innings / chase rate", "role": "core",
             "evidence": f"avg {feats.get('venue_avg_first')}, chase {pct(feats.get('venue_chase_rate'))}"},
            {"input": "Toss orientation / dew", "role": "context adjustment",
             "evidence": f"dew risk {pct(feats.get('dew_risk'))}"},
            {"input": "Availability multipliers", "role": "context adjustment",
             "evidence": f"home impact {inj.get('home_impact', 0)}, away impact {inj.get('away_impact', 0)}"},
        ]
    model_usage = {
        "used": used,
        "context_only": [
            {"input": "News headlines", "reason": "displayed for the analyst; only aggregated injury signals enter the model when structured availability is missing"},
            {"input": "Referee profile", "reason": "shown for context; not used by the current model"},
            {"input": "Head-to-head", "reason": "shown for context; not used by the current model"},
            {"input": "Bookmaker odds", "reason": "benchmark-only; never read by the core model"},
        ],
        "unavailable": [
            "Player-level minutes / usage / stat logs",
            "Confirmed lineups when not published",
            "Historical xG and shot volume",
        ],
    }
    goal_totals = []
    if sport == "football":
        for m in prediction.get("markets") or []:
            if m.get("group") == "totals" and m.get("key", "").startswith("over_"):
                goal_totals.append({"label": m.get("label"), "probability": m.get("probability"),
                                    "fair_odds": m.get("fair_odds")})
    else:
        summary = prediction.get("summary") or (prediction.get("score_grid") or {}).get("summary") or {}
        goal_totals = [{"label": x.get("label"), "probability": x.get("probability"),
                        "fair_odds": x.get("fair_odds")} for x in (summary.get("total_markets") or [])]
    return {
        "data_quality": data_quality,
        "data_cutoff": context.get("data_cutoff"),
        "market_policy": context.get("market_policy", "market-free"),
        "expected_script": _expected_script(fixture, prediction, context),
        "key_players": key_players,
        "player_projection_note": player_note,
        "player_correlations": [
            "Player-level usage correlations are not quantified because no player-log feed is connected.",
            f"Structured availability is already priced as bounded multipliers: home impact {inj.get('home_impact', 0)}, away impact {inj.get('away_impact', 0)}.",
            "If a key starter is ruled out after publication, re-run the dossier; teammate usage and team strength can move together.",
        ],
        "factors": factors[:7],
        "scenarios": scenarios,
        "data_gaps": data_gaps,
        "model_usage": model_usage,
        "goal_totals": goal_totals,
        "what_would_increase_confidence": [
            "Confirmed XI / roster and minutes restrictions",
            "Player-level usage and recent game logs",
            "Referee assignment with card/foul profile",
            "Updated weather/track forecast close to kickoff",
        ],
        "final_assessment": final,
        "market_read": market_read,
        "responsible_gambling": RESPONSIBLE_GAMBLING,
    }
