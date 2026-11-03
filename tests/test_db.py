from oracle import db


def test_schema_initialises_and_has_core_tables():
    db.init_db()
    with db.db() as conn:
        tables = {r["name"] for r in db.rows(conn, "select name from sqlite_master where type='table'")}
    for table in ("fixtures", "teams", "competitions", "predictions", "research",
                  "historical_results", "sync_jobs", "watchlist", "news_cache"):
        assert table in tables


def test_no_market_odds_columns():
    db.init_db()
    with db.db() as conn:
        cols = db.rows(conn, "pragma table_info(predictions)")
        names = {c["name"] for c in cols}
    banned = {"odds", "bookmaker_odds", "implied_prob", "market_prob", "b365h", "b365a", "b365d"}
    assert not (names & banned)
