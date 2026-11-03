import math

import numpy as np

from oracle.models import cricket, football


def test_score_grid_normalises_and_has_shape():
    grid = football.score_grid(1.65, 1.05, rho=-0.04)
    assert grid.shape == (11, 11)
    assert abs(float(grid.sum()) - 1.0) < 1e-9
    assert np.all(grid >= 0)


def test_markets_are_coherent():
    grid = football.score_grid(1.7, 1.2, rho=-0.03)
    summary, markets = football.grid_markets(grid, "Home", "Away")
    assert abs(summary["home_win"] + summary["draw"] + summary["away_win"] - 1.0) < 1e-6
    over = next(m for m in markets if m["key"] == "over_2_5")
    under = next(m for m in markets if m["key"] == "under_2_5")
    assert abs(over["probability"] + under["probability"] - 1.0) < 1e-6
    assert all(0 < m["probability"] < 1 for m in markets)
    assert all(m["fair_odds"] > 1 for m in markets)
    # Asian handicap pair should be complementary after push adjustment
    home = next(m for m in markets if m["key"] == "ah_home_-0.5")
    away = next(m for m in markets if m["key"] == "ah_away_+0.5")
    assert abs(home["probability"] + away["probability"] - 1.0) < 1e-6


def test_dixon_coles_recovers_direction_of_strength():
    # Team A dominates at home; team B is weak.
    fitted = football.fit_dixon_coles(
        home_goals=[3, 2, 4, 2, 3, 1, 2, 3],
        away_goals=[0, 1, 0, 1, 0, 0, 1, 0],
        home_ids=["A"] * 8,
        away_ids=["B"] * 8,
        days_ago=[10, 20, 30, 40, 50, 60, 70, 80],
    )
    assert fitted["attack"]["A"] > fitted["attack"]["B"]
    assert fitted["home_adv"] > 0


def test_cricket_simulation_bounds():
    rng = np.random.default_rng(7)
    runs, wkts, balls = cricket.simulate_innings(rng, 800, "T20", 1.0, 1.0, 1.0)
    assert runs.shape == (800,)
    assert np.all(runs >= 0)
    assert np.all(wkts <= 10)
    assert np.all(balls <= 120)
    mean = float(runs.mean())
    assert 110 < mean < 210, mean


def test_cricket_lookup_handles_unknown_team():
    book = cricket.CricketBook(teams={}, venues={}, trained_at="now", matches=0, elo_index={})
    strength = cricket.team_strength(book, "Unknown XI", "T20")
    assert strength["bat"] == 1.0
    assert strength["elo"] == 1500.0


def test_football_calibration_does_not_emit_fake_certainty(monkeypatch):
    # A prediction on a thin sample must be pulled toward the prior.
    class C:
        competition_id = "test"
        mu = math.log(1.2)
        home_adv = 0.22
        rho = -0.03
        attack = {"H": 1.2, "A": -0.8}
        defence = {"H": 0.9, "A": -0.9}
        matches = {"H": 1, "A": 1}
        base_rates = {"home": 0.45, "draw": 0.26, "away": 0.29}
        n_matches = 2
        goals_avg = 1.3

    book = football.FootballModelBook(
        competitions={"test": C()}, fallback=C(), team_prior={},
        global_home_adv=0.22, global_rho=-0.03, global_mu=math.log(1.2),
        trained_at="now", training_matches=2,
    )
    fx = {"competition_id": "test", "home_team_id": "H", "away_team_id": "A",
          "home_name": "Home", "away_name": "Away"}
    p = football.predict(book, fx)
    assert p["pick_prob"] < 0.80
    assert abs(p["home_prob"] + p["draw_prob"] + p["away_prob"] - 1.0) < 1e-6
