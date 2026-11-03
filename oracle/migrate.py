"""Non-destructive SQLite to Neon PostgreSQL migration."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path

from . import db

TABLES = [
    "competitions", "teams", "fixtures", "team_ratings",
    "predictions", "research", "news_cache", "sync_jobs",
    "model_runs", "watchlist", "sync_state", "event_log",
    "historical_results", "settlements", "match_reviews",
    "market_odds", "prediction_history",
]
IDENTITY_TABLES = {"event_log", "prediction_history"}
KEY_COLUMNS = {
    "competitions": ("id",), "teams": ("id",), "fixtures": ("id",),
    "team_ratings": ("team_id",), "predictions": ("fixture_id",),
    "research": ("fixture_id",), "news_cache": ("cache_key",),
    "sync_jobs": ("id",), "model_runs": ("id",),
    "watchlist": ("fixture_id",), "sync_state": ("key",),
    "event_log": ("id",), "historical_results": ("id",),
    "settlements": ("fixture_id",), "match_reviews": ("fixture_id",),
    "market_odds": ("fixture_id", "source", "provider", "market", "selection", "line"),
    "prediction_history": ("id",),
}

def main():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is missing. Add it to .env.local first.")

    source = Path(os.getenv("ORACLE_DB", Path(__file__).resolve().parent.parent / "data/oracle.sqlite3"))
    if not source.exists():
        raise SystemExit(f"SQLite source database not found: {source}")

    sqlite = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    sqlite.row_factory = sqlite3.Row
    if sqlite.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("SQLite integrity check failed; migration cancelled.")

    db.init_db()
    with db.db() as target:
        for table in TABLES:
            source_count = sqlite.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if not source_count:
                print(f"{table}: 0 rows")
                continue

            columns = [r[1] for r in sqlite.execute(f'PRAGMA table_info("{table}")')]
            col_sql = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            insert_sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
            cursor = sqlite.execute(f'SELECT {col_sql} FROM "{table}"')
            batch = []
            copied = 0
            while True:
                rows = cursor.fetchmany(500)
                if not rows:
                    break
                batch = [tuple(row) for row in rows]
                target.raw.cursor().executemany(insert_sql, batch)
                copied += len(batch)
            if copied != source_count:
                raise RuntimeError(f"{table}: copied {copied}, expected {source_count}")
            print(f"{table}: migrated {copied} rows")

        # Keep identity sequences above imported IDs.
        for table in IDENTITY_TABLES:
            target.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                f"EXISTS(SELECT 1 FROM {table}))",
                (table,)
            )

        # Verify every source key exists in Neon. Existing Neon rows win on conflicts.
        for table in TABLES:
            expected = sqlite.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            actual = target.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
            key_cols = KEY_COLUMNS[table]
            key_sql = ", ".join(f'"{c}"' for c in key_cols)
            source_keys = {tuple(r) for r in sqlite.execute(f'SELECT {key_sql} FROM "{table}"')}
            target_keys = {
                tuple(r[c] for c in key_cols)
                for r in target.execute(f'SELECT {key_sql} FROM "{table}"').fetchall()
            }
            missing = len(source_keys - target_keys)
            if actual < expected or missing:
                raise RuntimeError(
                    f"Verification failed for {table}: SQLite={expected}, Neon={actual}, missing_keys={missing}"
                )

    sqlite.close()
    print("\nSUCCESS: every SQLite key is present in Neon; existing Neon rows were preserved.")

if __name__ == "__main__":
    main()
