# ORACLE v2 — Codebase Audit & Evidence-First Implementation

Audit date: 2026-11-03 · Auditor: engineering pass over the live local codebase

## 1. Framework and page structure

| Layer | What exists |
|---|---|
| Backend | FastAPI, Python 3.11, SQLite (WAL), SQLAlchemy-free SQL helpers |
| Frontend | No-build SPA: `oracle/web/index.html`, `styles.css`, `app.js` |
| Routes | Mission, Fixtures, Research, Model Lab, Slip Lab, Automation, Review, Watchlist, Team profile, Match dossier |
| Match dossier tabs | Verdict, Teams, Lineups, Markets, Odds Bench, Tactical, Research, Protocol/Data, Model Trace |
| Automation | Daemon scheduler: 45s tick, 30-min full cycle, 5-min research sweep, settlement every 5 min |

The interface never calls a bookmaker API for core probabilities. Odds are isolated in the optional Odds Bench.

## 2. Data provenance

| Category | Provider | Storage | Status |
|---|---|---|---|
| Fixtures / results | FotMob public feed | `fixtures` | Live/cached; 30-min refresh |
| Cricket fixtures/results | Cricbuzz public schedules | `fixtures` | Live/cached; parsed RSC |
| Cricket history | Cricsheet | `historical_results` | Cached open data |
| Availability / injuries | FotMob match centre | `research.raw.injuries`, `fixture_research` | Structured when published |
| Lineups | FotMob match centre | `research.raw.lineups` | Confirmed only when published; expected XI unavailable |
| Team form / rest | Local results warehouse | computed on request | Real, calculated from finished fixtures |
| News | Google News RSS / ESPN newsroom | `news_cache`, `research.raw.news` | Cached 6h; headlines + links |
| Weather | Open-Meteo / FotMob | `research.raw.weather` | Forecast; timestamped |
| Referee | FotMob match centre | `research.raw.referee` | Partial; only when published |
| Odds (optional) | ESPN public odds / DraftKings | `market_odds` | Benchmark only; 15-min cache |
| Prediction revisions | ORACLE | `prediction_history` | Append-only; no overwrite |
| Settlements | ORACLE | `settlements` | Finished results; history-guarded |

**Mock data:** none in the live path. The old v1 demo generator is not used by the current UI. Synthetic rows would be labelled `synthetic_demo` if present.

**Missing data:** historical xG, shot volume, expected lineups, player-level minutes/usage logs, full player-prop odds, full referee profiles. These are shown as unavailable, never substituted.

## 3. Prediction pipeline

- Football: per-competition Dixon–Coles, time decay (180-day half-life), home advantage, low-score rho, Poisson 11×11 score grid, shrinkage.
- Cricket: vectorised T20/ODI Monte Carlo; Test session-level model with draw mass.
- Context adjustments: structured availability and fatigue multipliers, weather goal effect, cricket dew/toss/venue. Bounded.
- Calibration: thin-sample 1X2 probabilities blend toward the competition base rate.
- **Odds are not an input** to any of the above. Grep confirms no odds read in `models/` or `pipeline` prediction path.
- Prediction version: `oracle-dc-mc-2.0`, timestamped in `predictions.generated_at` and `prediction_history.created_at`.

## 4. Explanation layer

- `analysis/analyst.py` produces the verdict, edge thesis, tactical pros/cons, risks, odds-free market read, data-quality audit, model-usage trace and scenarios.
- `protocol.model_usage` separates **used by model** (ratings, home advantage, rho, availability/fatigue/weather multipliers, venue for cricket) from **context only** (news headlines, referee, H2H, bookmaker odds).
- No feature importance is invented. The trace lists the actual inputs and values stored with the prediction.

## 5. Odds Bench calculations

- Source: ESPN public odds, provider record (DraftKings for the audited fixture), timestamped; isolated `market_odds` table.
- Raw implied = `1 / decimal`.
- De-vig = implied / sum(implied) within the market group (1X2, spread, total).
- Edge = model probability − de-vig probability.
- EV = `p × (stake × (decimal − 1)) − (1 − p) × stake`.
- Return = `stake × decimal`; profit = return − stake.
- Odds stored to 4dp; UI displays 2dp; calculations use unrounded prices (disclosed in the tab).
- “Best balanced” rule: highest EV among selections with model probability ≥35%; if none, highest model probability. Documented in the tab.
- “Most likely 1X2” is the highest model probability in the moneyline group, distinct from “best return” (highest decimal).

## 6. History and evaluation

- `prediction_history` now stores revisions with model version, probabilities, pick, lineup status, input snapshot and analysis snapshot. Duplicate identical revisions are skipped.
- `settlements` stores actual outcome, pick correctness, Brier, log loss and (for new rows) pick probability.
- Settlement uses the **latest prediction revision created at or before kickoff**, not the current row. Legacy settlements without a pre-kickoff revision are marked `LEGACY` and excluded from headline metrics/calibration.
- Review page reports sample size, date range, accuracy, Brier, log loss, home baseline, by sport/confidence/competition and calibration bins once guarded settlements exist.
- Model Lab retains the walk-forward 8,004-match football backtest and its calibration chart.
- Current live ledger: 24 settled rows, all legacy/unguarded → 0 headline evaluation rows. This is deliberate: no genuine snapshots existed, so they are not presented as validated performance.

## 7. Known limits

- Expected lineups and player-level projections are not available; no player-log provider is connected.
- Historical xG and shots are not in the fixture feed; goals are not substituted.
- Referee data is partial; not used by the model.
- Cricket has no walk-forward backtest yet.
- Odds are optional benchmark only; no odds are used in core probabilities.
- The live sample is too small for a reliability claim. Treat the walk-forward backtest as the current evidence, not the live ledger.
