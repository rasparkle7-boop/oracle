from oracle.pipeline import _actual_result


def test_football_result_mapping():
    fx = {"sport": "football", "home_score_num": 2, "away_score_num": 1}
    pred = {"home_prob": 0.6, "draw_prob": 0.2, "away_prob": 0.2}
    label, idx, prob, excluded = _actual_result(fx, pred)
    assert label == "home"
    assert idx == 0
    assert prob == 0.6
    assert excluded is False


def test_cricket_no_result_is_excluded():
    fx = {"sport": "cricket", "winner_team_id": None, "home_team_id": "a", "away_team_id": "b",
          "score_detail": "Match abandoned", "raw": {"format": "ODI"}}
    pred = {"home_prob": 0.5, "draw_prob": 0.0, "away_prob": 0.5}
    label, idx, prob, excluded = _actual_result(fx, pred)
    assert label == "no_result"
    assert excluded is True
