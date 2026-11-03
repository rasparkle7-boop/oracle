"""Runtime configuration for ORACLE."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ORACLE_DATA_DIR", ROOT / "data"))
WEB_DIR = Path(__file__).resolve().parent / "web"
DB_PATH = Path(os.getenv("ORACLE_DB", DATA_DIR / "oracle.sqlite3"))
CACHE_DIR = DATA_DIR / "cache"
LOG_PATH = DATA_DIR / "oracle.log"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


@dataclass
class Settings:
    app_name: str = "ORACLE // Sports Intelligence Engine"
    version: str = "2.0.0"
    model_version: str = "oracle-dc-mc-2.0"
    host: str = os.getenv("ORACLE_HOST", "0.0.0.0")
    port: int = _env_int("PORT", _env_int("ORACLE_PORT", 8787))
    db_path: Path = DB_PATH
    data_dir: Path = DATA_DIR
    cache_dir: Path = CACHE_DIR
    window_days: int = _env_int("ORACLE_WINDOW_DAYS", 7)
    history_days: int = _env_int("ORACLE_HISTORY_DAYS", 120)
    scheduler_enabled: bool = os.getenv("ORACLE_SCHEDULER", "1") not in ("0", "false", "False")
    tick_seconds: int = _env_int("ORACLE_TICK_SECONDS", 45)
    fixtures_refresh_minutes: int = _env_int("ORACLE_FIXTURE_REFRESH_MIN", 30)
    results_refresh_minutes: int = _env_int("ORACLE_RESULTS_REFRESH_MIN", 10)
    research_refresh_minutes: int = _env_int("ORACLE_RESEARCH_REFRESH_MIN", 90)
    research_budget: int = _env_int("ORACLE_RESEARCH_BUDGET", 420)
    news_ttl_minutes: int = _env_int("ORACLE_NEWS_TTL_MIN", 360)
    request_timeout: int = _env_int("ORACLE_HTTP_TIMEOUT", 25)
    football_workers: int = _env_int("ORACLE_FOOTBALL_WORKERS", 6)
    cricket_workers: int = _env_int("ORACLE_CRICKET_WORKERS", 5)
    min_history_matches: int = _env_int("ORACLE_MIN_HISTORY", 6)
    monte_carlo_runs: int = _env_int("ORACLE_MC_RUNS", 6000)
    max_fixtures: int = _env_int("ORACLE_MAX_FIXTURES", 5000)
    optional_llm_key: str = os.getenv("ORACLE_LLM_KEY", "")
    optional_llm_model: str = os.getenv("ORACLE_LLM_MODEL", "deepseek-chat")
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    )
    sources: dict = field(default_factory=lambda: {
        "football_fixtures": "FotMob public match feed",
        "football_results": "FotMob historical results (rolling 400 days)",
        "cricket_fixtures": "Cricbuzz public schedules",
        "cricket_results": "Cricsheet open data + Cricbuzz",
        "news": "Google News RSS + ESPN newsroom feeds",
        "weather": "Open-Meteo (open data)",
    })


settings = Settings()
for _p in (settings.data_dir, settings.cache_dir):
    _p.mkdir(parents=True, exist_ok=True)
