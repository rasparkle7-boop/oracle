from oracle import pipeline


def test_search_exact_partial_and_fuzzy():
    exact = pipeline.search_all("Arsenal")
    assert exact["teams"]
    assert exact["teams"][0]["name"] == "Arsenal"
    partial = pipeline.search_all("Arse")
    assert any("Arsenal" in t["name"] for t in partial["teams"])
    fuzzy = pipeline.search_all("Arsnal")
    assert any(t["name"] == "Arsenal" for t in fuzzy["teams"])
    assert pipeline.search_all("x")["teams"] == []


def test_alias_search():
    r = pipeline.search_all("man utd")
    assert any(t["name"] == "Manchester United" for t in r["teams"])


def test_team_detail_has_form_and_fixtures():
    d = pipeline.team_detail("fb:t9825")
    assert d and d["team"]["name"] == "Arsenal"
    assert "form" in d["card"]
    assert isinstance(d["upcoming"], list)


def test_model_slip_math_is_consistent():
    s = pipeline.build_model_slip(stake=100, threshold=0.90)
    assert s["policy"] == "model-fair-odds"
    assert "correlation_adjustment" in s and "market_types" in s
    if s["legs"]:
        p = 1.0
        odds = 1.0
        for leg in s["legs"]:
            p *= leg["probability"]
            odds *= leg["fair_odds"]
        assert abs(p - s["combined_probability"]) < 1e-5
        assert abs(odds - s["combined_fair_odds"]) < 1e-2
        assert abs(s["potential_return"] - round(100 * odds, 2)) < 0.05
        assert "bookmaker" in s["market_note"].lower()
        assert s["meets_threshold"] == (s["combined_probability"] >= 0.90)
