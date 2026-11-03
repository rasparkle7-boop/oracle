from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from . import db, pipeline, scheduler
from .config import settings


def cmd_serve(args) -> None:
    import uvicorn
    uvicorn.run("oracle.api:app", host=args.host or settings.host, port=args.port or settings.port,
                reload=False, log_level="info")


def cmd_sync(args) -> None:
    result = pipeline.run_full_sync(force_models=args.force_models, include_history=args.history)
    print(json.dumps(result, indent=2, default=str))


def cmd_analyze(args) -> None:
    print(json.dumps(pipeline.analyze_fixture(args.fixture), indent=2, default=str))


def cmd_backtest(args) -> None:
    print(json.dumps(pipeline.backtest_football(args.days), indent=2, default=str))


def cmd_status(args) -> None:
    print(json.dumps({"overview": pipeline.overview(), "automation": scheduler.status()},
                     indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="oracle", description="ORACLE sports intelligence engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="start the API and mission-control UI")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("sync", help="run one full autonomous cycle")
    p.add_argument("--force-models", action="store_true")
    p.add_argument("--history", action="store_true", help="backfill the full history window")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("analyze", help="deep-dive one fixture")
    p.add_argument("fixture")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("repredict", help="re-run models from cached research context")
    p.set_defaults(func=lambda args: print(json.dumps(pipeline.repredict_all(), indent=2)))

    p = sub.add_parser("sweep", help="deepen the least-researched in-window fixtures")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=lambda args: print(json.dumps(pipeline.research_sweep(args.limit), indent=2)))

    p = sub.add_parser("settle", help="settle finished fixtures against predictions")
    p.set_defaults(func=lambda args: print(json.dumps(pipeline.settle_predictions(), indent=2)))

    p = sub.add_parser("review", help="post-match calibration ledger")
    p.set_defaults(func=lambda args: print(json.dumps(pipeline.review_summary(), indent=2, default=str)))

    p = sub.add_parser("backtest", help="walk-forward football backtest")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("status", help="print engine status")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    db.init_db()
    args.func(args)


if __name__ == "__main__":
    main()
