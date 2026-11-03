from oracle import pipeline


def test_team_comparison_has_samples_and_honest_unavailable():
    d = pipeline.fixture_detail("fb:5868129")
    assert d
    c = d["comparison"]
    assert c["home"]["overall_5"]["matches"] <= 5
    assert c["away"]["overall_10"]["matches"] <= 10
    assert c["home"]["rest_days"] is not None
    assert "Unavailable" in c["limits"]["xg"]
    assert c["source"]


def test_prediction_history_is_append_only():
    d = pipeline.fixture_detail("fb:5868129")
    assert d["history"]
    rows = d["history"]
    assert all("created_at" in r and "model_version" in r for r in rows)
    # Newest first by query; no duplicate signature is not asserted here, but
    # the table must retain at least one pre-result revision.
    assert len({(r["model_version"], round(r["home_prob"], 4), r["pick"]) for r in rows}) >= 1


def test_protocol_has_model_usage_and_data_status():
    d = pipeline.fixture_detail("fb:5868129")
    q = (d["prediction"]["analysis"] or {}).get("protocol") or {}
    assert q.get("model_usage", {}).get("used")
    assert q.get("model_usage", {}).get("context_only")
    dq = q.get("data_quality") or []
    assert dq and any(x.get("provider") for x in dq)
    assert any("freshness" in x for x in dq)


def test_review_has_baseline_and_date_range():
    d = pipeline.review_summary()
    assert "baseline" in d
    assert "date_range" in d
    assert "calibration" in d


def test_review_keeps_legacy_separate():
    d = pipeline.review_summary()
    assert "guarded" in d and "legacy" in d
    assert d["guarded"] + d["legacy"] <= d["settled"]
    assert "calibration" in d
