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


def test_football_result_double_chance_and_correct_score_cohere():
    grid = football.score_grid(2.4, 0.5, rho=-0.03)
    summary, markets = football.grid_markets(grid, "Home", "Away", 2.4, 0.5, -0.03)
    by_key = {m["key"]: m for m in markets}

    assert abs(sum(summary[k] for k in ("home_win", "draw", "away_win")) - 1.0) < 1e-4
    assert abs(by_key["dc_1x"]["probability"] - summary["home_win"] - summary["draw"]) < 2e-4
    assert abs(by_key["dc_x2"]["probability"] - summary["away_win"] - summary["draw"]) < 2e-4
    assert abs(by_key["dc_12"]["probability"] - summary["home_win"] - summary["away_win"]) < 2e-4

    scores = [m for m in markets if m["group"] == "correct_score"]
    assert len(scores) == 10
    assert [m["probability"] for m in scores] == sorted(
        (m["probability"] for m in scores), reverse=True
    )
    assert all(0.0 <= m["probability"] <= 1.0 for m in markets)


def test_half_time_full_time_uses_joint_score_distribution():
    lh, la, rho = 2.4, 0.5, -0.03
    _, markets = football.grid_markets(
        football.score_grid(lh, la, rho), "Home", "Away", lh, la, rho
    )
    by_key = {m["key"]: m for m in markets}
    ht = football.score_grid(lh * 0.45, la * 0.45, rho)
    second = football.score_grid(lh * 0.55, la * 0.55, rho)
    expected = {(h, f): 0.0 for h in ("home", "draw", "away")
                for f in ("home", "draw", "away")}
    n = ht.shape[0]
    for hi in range(n):
        for ai in range(n):
            ht_side = "home" if hi > ai else "away" if hi < ai else "draw"
            for si in range(n):
                for sa in range(n):
                    ft_home, ft_away = hi + si, ai + sa
                    ft_side = "home" if ft_home > ft_away else "away" if ft_home < ft_away else "draw"
                    expected[(ht_side, ft_side)] += ht[hi, ai] * second[si, sa]
    norm = sum(expected.values())
    for (ht_side, ft_side), probability in expected.items():
        assert abs(by_key[f"htft_{ht_side}_{ft_side}"]["probability"] - probability / norm) < 1e-4

    half_scores = [m for m in markets if m["key"].startswith("ht_cs_")]
    assert len(half_scores) == 5
    assert [m["probability"] for m in half_scores] == sorted(
        (m["probability"] for m in half_scores), reverse=True
    )
    assert abs(sum(m["probability"] for m in markets if m["key"].startswith("htft_")) - 1.0) < 1e-3
