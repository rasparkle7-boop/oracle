from oracle.analysis.analyst import build_analysis, football_analysis
from oracle.analysis.research import build_context


def make_fixture():
    return {
        "id": "fb:1", "sport": "football", "home_team_id": "H", "away_team_id": "A",
        "home_name": "Home FC", "away_name": "Away FC", "kickoff_utc": "2026-11-03T18:00:00Z",
        "competition_id": "comp", "competition_name": "Test League", "raw": {},
    }


def make_prediction():
    return {
        "home_prob": 0.52, "draw_prob": 0.26, "away_prob": 0.22,
        "pick": "Home FC", "pick_side": "home", "pick_prob": 0.52, "pick_fair": 1.92,
        "edge": 0.07, "confidence": {"score": 63, "label": "MEDIUM", "data": 0.7,
                                     "entropy": 0.9, "separation": 0.26, "depth": 0.7},
        "expected_home": 1.6, "expected_away": 1.1,
        "features": {"home_attack": 0.3, "home_defence": 0.2, "away_attack": 0.1,
                     "away_defence": 0.0, "home_advantage": 0.22, "rho": -0.03,
                     "league_goals_avg": 1.3, "base_rates": {"home": 0.45, "draw": 0.26, "away": 0.29}},
        "secondary": [], "markets": [], "summary": {}, "score_grid": {},
    }


def test_context_and_analysis_are_complete():
    fx = make_fixture()
    ctx = build_context(fx, news_home=[{"title": "Home star ruled out", "tags": ["injury"],
                                        "url": "https://example.com", "source": "Test"}],
                        news_away=[], weather={"temperature_c": 12, "wind_kph": 10,
                                             "precip_chance": 10, "description": "Clear"})
    a = football_analysis(fx, make_prediction(), ctx)
    for key in ("headline", "verdict", "edge_thesis", "tactical", "risks", "why_not",
                "key_battles", "market_read", "research_grade", "confidence_note",
                "model_trace", "narrative", "edge_quality"):
        assert key in a
    assert a["tactical"]["home"]["pros"]
    assert a["tactical"]["away"]["cons"]
    assert len(a["risks"]) >= 2
    assert a["edge_quality"] in ("STRONG", "MODERATE", "THIN", "NONE")


def test_model_only_is_labelled():
    fx = make_fixture()
    ctx = build_context(fx)
    a = build_analysis(fx, make_prediction(), ctx)
    assert a["research_grade"] in ("C", "D")


def test_protocol_sections_are_present():
    fx = make_fixture()
    ctx = build_context(fx, news_home=[{"title": "Home star ruled out", "tags": ["injury"],
                                        "url": "https://example.com", "source": "Test"}],
                        weather={"temperature_c": 12, "wind_kph": 10,
                                 "precip_chance": 10, "description": "Clear"})
    a = build_analysis(fx, make_prediction(), ctx)
    q = a["protocol"]
    for key in ("data_quality", "expected_script", "key_players", "factors",
                "scenarios", "data_gaps", "final_assessment", "market_read",
                "responsible_gambling", "player_correlations"):
        assert key in q
    assert len(q["data_quality"]) >= 8
    assert "market-free" in q["market_read"].lower() or "no odds" in q["market_read"].lower()
    assert "guaranteed" in q["responsible_gambling"].lower()
    assert "No odds provided" in q["market_read"]
