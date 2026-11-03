import pytest

from oracle.analysis.benchmark import build_benchmark


def test_benchmark_math_and_labels():
    d = build_benchmark("fb:5868129", stake=100)
    if not d.get("available"):
        pytest.skip("benchmark odds not cached and network unavailable")
    assert d["market_free_core"] is True
    assert d["rows"]
    assert d["best_return"] and d["best_balanced"] and d["highest_odds"]
    ml = [r for r in d["rows"] if r["market"] == "Moneyline"]
    assert abs(sum(r["devig"] for r in ml) - 1.0) < 1e-3
    for r in d["rows"]:
        assert 0 < r["decimal"] < 1000
        assert 0 <= r["model_prob"] <= 1
        assert r["value"] in ("HIGH VALUE", "MODERATE VALUE", "LOW VALUE", "NO VALUE", "INSUFFICIENT DATA")
        assert r["potential_return"] == round(r["stake"] * r["decimal"], 2)
    if d.get("slip"):
        assert d["slip"]["combined_odds"] == d["slip"]["legs"][0]["decimal"]
        assert d["slip"]["potential_return"] == round(100 * d["slip"]["combined_odds"], 2)


def test_market_odds_are_deduplicated():
    from oracle import db
    with db.db() as conn:
        rows = db.rows(conn, "SELECT * FROM market_odds WHERE fixture_id='fb:5868129'")
    if not rows:
        pytest.skip("benchmark odds not cached")
    keys = {(r["market"], r["selection"], r["line"]) for r in rows}
    assert len(keys) == len(rows)
