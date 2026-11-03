from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

from oracle import pipeline
from oracle.models import football


def test_training_decay_is_relative_to_the_fold_as_of_time(monkeypatch):
    captured = {}
    row = {
        "id": "fb:test", "competition_id": "c1", "home_team_id": "h",
        "away_team_id": "a", "home_name": "Home", "away_name": "Away",
        "home_score_num": 1, "away_score_num": 0,
        "kickoff_utc": "2025-01-09T00:00:00Z",
    }
    monkeypatch.setattr(football.db, "db", lambda: nullcontext(None))

    def rows(_conn, _sql, params):
        captured["params"] = params
        return [row]

    monkeypatch.setattr(football.db, "rows", rows)
    data = football.load_training_data(
        history_days=30,
        before_iso="2025-01-10T00:00:00Z",
        as_of_iso="2025-01-10T00:00:00Z",
    )

    assert data[0]["days_ago"] == 1.0
    assert captured["params"][1] == "2025-01-10T00:00:00Z"
    assert captured["params"][0] == "2024-12-11T00:00:00Z"


def test_backtest_uses_chronological_seven_day_folds(monkeypatch):
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    fixtures = [
        {"id": "fb:1", "competition_id": "c1", "kickoff_utc": "2026-01-02T00:00:00Z",
         "home_score_num": 1, "away_score_num": 0, "raw": {}},
        {"id": "fb:2", "competition_id": "c1", "kickoff_utc": "2026-01-09T00:00:00Z",
         "home_score_num": 0, "away_score_num": 1, "raw": {}},
    ]
    cutoffs = []
    monkeypatch.setattr(pipeline, "_now", lambda: now)
    monkeypatch.setattr(pipeline.db, "db", lambda: nullcontext(None))

    def rows(_conn, sql, _params=()):
        return fixtures if "FROM fixtures" in sql else []

    monkeypatch.setattr(pipeline.db, "rows", rows)

    def train(**kwargs):
        cutoffs.append((kwargs["before_iso"], kwargs["as_of_iso"]))
        return SimpleNamespace(training_matches=100)

    monkeypatch.setattr(pipeline.football_model, "train", train)
    monkeypatch.setattr(
        pipeline.football_model,
        "predict",
        lambda _book, _fixture: {
            "home_prob": 0.60, "draw_prob": 0.20, "away_prob": 0.20,
            "features": {"base_rates": {"home": 0.45, "draw": 0.26, "away": 0.29}},
        },
    )

    result = pipeline.backtest_football(days=14)

    assert len(result["folds"]) == 2
    assert cutoffs == [
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ("2026-01-08T00:00:00Z", "2026-01-08T00:00:00Z"),
    ]
    assert all(fold["train_before"] == fold["from"] for fold in result["folds"])
    assert result["model_comparison"]["dixon_coles"]["n"] == 2
    assert result["model_comparison"]["competition_base_rate"]["n"] == 2
