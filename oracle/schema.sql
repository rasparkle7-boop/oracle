-- ORACLE // Sports Intelligence Engine
-- SQLite schema (Postgres-compatible core types)

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS competitions (
    id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    name TEXT NOT NULL,
    country TEXT,
    tier INTEGER,
    logo TEXT,
    source TEXT,
    metadata TEXT DEFAULT '{}',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT,
    country TEXT,
    logo TEXT,
    metadata TEXT DEFAULT '{}',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS fixtures (
    id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    competition_id TEXT,
    season TEXT,
    round TEXT,
    kickoff_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    home_team_id TEXT,
    away_team_id TEXT,
    home_name TEXT NOT NULL,
    away_name TEXT NOT NULL,
    venue TEXT,
    city TEXT,
    country TEXT,
    home_score TEXT,
    away_score TEXT,
    home_score_num REAL,
    away_score_num REAL,
    score_detail TEXT,
    winner_team_id TEXT,
    source TEXT,
    source_url TEXT,
    importance REAL DEFAULT 0.5,
    raw TEXT DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_fixtures_kickoff ON fixtures (kickoff_utc);
CREATE INDEX IF NOT EXISTS idx_fixtures_sport_kickoff ON fixtures (sport, kickoff_utc);
CREATE INDEX IF NOT EXISTS idx_fixtures_comp ON fixtures (competition_id, kickoff_utc);
CREATE INDEX IF NOT EXISTS idx_fixtures_status ON fixtures (status);

CREATE TABLE IF NOT EXISTS team_ratings (
    team_id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    competition_id TEXT,
    as_of TEXT,
    attack REAL,
    defence REAL,
    elo REAL,
    matches INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    goals_for REAL DEFAULT 0,
    goals_against REAL DEFAULT 0,
    form TEXT DEFAULT '[]',
    home_advantage REAL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS predictions (
    fixture_id TEXT PRIMARY KEY REFERENCES fixtures(id) ON DELETE CASCADE,
    sport TEXT NOT NULL,
    model_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    home_prob REAL,
    draw_prob REAL,
    away_prob REAL,
    pick TEXT,
    pick_side TEXT,
    pick_prob REAL,
    pick_fair REAL,
    edge REAL,
    confidence REAL,
    data_depth TEXT,
    expected_home REAL,
    expected_away REAL,
    markets TEXT DEFAULT '[]',
    score_grid TEXT DEFAULT '{}',
    analysis TEXT DEFAULT '{}',
    features TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_predictions_sport_conf ON predictions (sport, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_generated ON predictions (generated_at);

CREATE TABLE IF NOT EXISTS research (
    fixture_id TEXT PRIMARY KEY REFERENCES fixtures(id) ON DELETE CASCADE,
    generated_at TEXT NOT NULL,
    depth TEXT NOT NULL,
    home_news_count INTEGER DEFAULT 0,
    away_news_count INTEGER DEFAULT 0,
    injury_signals TEXT DEFAULT '[]',
    weather TEXT DEFAULT '{}',
    pitch TEXT DEFAULT '{}',
    fatigue TEXT DEFAULT '{}',
    tactical TEXT DEFAULT '{}',
    citations TEXT DEFAULT '[]',
    summary TEXT,
    raw TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS news_cache (
    cache_key TEXT PRIMARY KEY,
    team_id TEXT,
    team_name TEXT,
    fetched_at TEXT NOT NULL,
    items TEXT DEFAULT '[]',
    source TEXT
);

CREATE TABLE IF NOT EXISTS sync_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    progress REAL DEFAULT 0,
    message TEXT,
    stats TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_jobs_started ON sync_jobs (started_at DESC);

CREATE TABLE IF NOT EXISTS model_runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    metrics TEXT DEFAULT '{}',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS watchlist (
    fixture_id TEXT PRIMARY KEY REFERENCES fixtures(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    scope TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_event_log_ts ON event_log (ts DESC);

CREATE TABLE IF NOT EXISTS historical_results (
    id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    competition TEXT,
    played_on TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score REAL,
    away_score REAL,
    home_wickets REAL,
    away_wickets REAL,
    winner TEXT,
    venue TEXT,
    city TEXT,
    format TEXT,
    neutral INTEGER DEFAULT 0,
    source TEXT,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_history_sport_date ON historical_results (sport, played_on DESC);
CREATE INDEX IF NOT EXISTS idx_history_teams ON historical_results (home_team, away_team);

CREATE TABLE IF NOT EXISTS settlements (
    fixture_id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    competition_id TEXT,
    kickoff_utc TEXT,
    settled_at TEXT NOT NULL,
    actual_outcome TEXT NOT NULL,
    actual_index INTEGER,
    model_prob REAL,
    pick TEXT,
    pick_side TEXT,
    pick_correct INTEGER,
    brier REAL,
    log_loss REAL,
    confidence REAL,
    data_depth TEXT,
    excluded INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    pick_prob REAL
);
CREATE INDEX IF NOT EXISTS idx_settlements_sport ON settlements (sport, settled_at DESC);

CREATE TABLE IF NOT EXISTS match_reviews (
    fixture_id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    competition_id TEXT,
    kickoff_utc TEXT,
    settled_at TEXT NOT NULL,
    verdict TEXT NOT NULL,
    outcome_status TEXT NOT NULL,
    summary TEXT NOT NULL,
    reasons TEXT DEFAULT '[]',
    market_reviews TEXT DEFAULT '[]',
    prediction_dna TEXT DEFAULT '{}',
    raw TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_match_reviews_sport ON match_reviews (sport, settled_at DESC);

CREATE TABLE IF NOT EXISTS market_odds (
    fixture_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT,
    event_id TEXT,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    american REAL,
    decimal REAL NOT NULL,
    implied REAL,
    raw TEXT DEFAULT '{}',
    PRIMARY KEY (fixture_id, source, provider, market, selection, line)
);
CREATE INDEX IF NOT EXISTS idx_market_odds_fixture ON market_odds (fixture_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS prediction_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model_version TEXT,
    home_prob REAL,
    draw_prob REAL,
    away_prob REAL,
    pick TEXT,
    pick_side TEXT,
    pick_prob REAL,
    confidence REAL,
    data_depth TEXT,
    lineups_status TEXT,
    lineups_fingerprint TEXT DEFAULT '',
    input_snapshot TEXT DEFAULT '{}',
    analysis_snapshot TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_prediction_history_fixture ON prediction_history (fixture_id, created_at DESC);
