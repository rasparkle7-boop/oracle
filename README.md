# ORACLE // Sports Intelligence Engine v2

ORACLE is a locally-run, **market-free** sports intelligence engine for football and cricket. It discovers the global fixture grid, researches availability and conditions, fits its own statistical models, simulates outcomes, and writes an auditable dossier for every match in a rolling 7-day window.

![ORACLE mission control](docs/mission.png)

> **Not a betting service. Not financial advice.** A probability is a calibrated belief, not a guarantee. If gambling is harming you, stop and seek support.

---

## Screens

| Mission Control | Fixture Grid |
|---|---|
| ![Mission](docs/mission.png) | ![Fixtures](docs/fixtures.png) |

| Dossier | Model Lab |
|---|---|
| ![Dossier](docs/dossier.png) | ![Model Lab](docs/model-lab.png) |

| Cricket dossier | Mobile |
|---|---|
| ![Cricket](docs/cricket-dossier.png) | ![Mobile](docs/mobile.png) |

| Protocol / data audit | Post-match review |
|---|---|
| ![Protocol](docs/protocol.png) | ![Review](docs/review.png) |

| Global search | Team profile |
|---|---|
| ![Search](docs/search.png) | ![Team](docs/team.png) |

| Model Slip Lab | Mobile search |
|---|---|
| ![Slip](docs/slip.png) | ![Mobile search](docs/mobile-search.png) |

| Optional Odds Bench (real bookmaker odds) | Data status / provenance |
|---|---|
| ![Odds Bench](docs/benchmark.png) | ![Data status](docs/data-status.png) |

| Team comparison | Lineups / availability |
|---|---|
| ![Teams](docs/teams.png) | ![Lineups](docs/lineups.png) |

## What changed from v1

v1 was a poster with six demo fixtures and a preserved model file. v2 is a working engine:

| v1 | v2 |
|---|---|
| 6 synthetic demo fixtures | **1,800+ real fixtures** in the 7-day window |
| 5 competitions | **245 competitions** in-window; 970 in the warehouse |
| Demo-only predictions | **Every scheduled fixture** receives an independent model prediction |
| No research | Live news, structured injuries/suspensions, weather, venue, fatigue |
| No automation | Background scheduler + CLI + cron/launchd |
| No real UI | Full mission-control UI with working filters, dossiers, watchlist, model lab |
| No evaluation | Walk-forward Brier / log loss / accuracy / calibration + post-match settlement ledger |

The numbers above are from a real local run on 2 November 2026. They move as the fixture calendar changes.

---

## Zero market reliance

ORACLE's **core forecast never reads a bookmaker price** as an input. It does not scrape 1xBet, Bet365, Pinnacle or any sportsbook. The core prediction tables contain no odds column, no implied-probability prior, and no "market consensus" feature. Bookmaker prices exist only in a separate, optional **Odds Bench** table used for comparison and are never read by the model.

The core numbers are derived from:

- historical results and goal/run data
- fitted attack/defence/Elo ratings
- venue, toss, weather and pitch context
- verified availability and news signals
- Monte Carlo simulation

**Fair odds** in the UI are `1 / P(ORACLE)`. They are a probability translation, not a market quote. The optional **Odds Bench** labels real bookmaker prices separately and shows implied, de-vig, edge and EV without feeding them back into the forecast.

Why not scrape 1xBet for "all games"? Two reasons:

1. It violates the platform's terms and is legally/operationally fragile.
2. A bookmaker's fixture list is still a bookmaker surface; using it as a discovery layer would blur the zero-market claim.

Instead, ORACLE uses broad public discovery feeds and a pluggable adapter interface, so a **licensed** global fixture feed can be added without changing the model or UI. See [Extending coverage](#extending-coverage).

---

## Coverage

Current public feeds give:

- **Football:** every fixture in the next 7 days across ~250 active competitions from the global FotMob public match feed — top-five European leagues, lower divisions, cups, UEFA/CONMEBOL/AFC/CAF competitions, women's football, youth, and minor leagues.
- **Cricket:** every match in active international, franchise and domestic series from Cricbuzz schedules — international tours, WBBL, Nepal Premier League, CSA T20, Ranji Trophy, Sheffield Shield, Ford Trophy, Abu Dhabi T10, and more.
- **History:** 34,000+ finished football matches (up to 400 days) fitted for ratings; 400+ recent cricket results plus Cricsheet open data for venue and form context.

The rolling window automatically adds new fixtures on every cycle and deduplicates by provider fixture ID.

---

## Quickstart (macOS / Linux)

```bash
cd oracle
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# First bootstrap: 7-day window + history (2-5 minutes)
python -m oracle.cli sync --history

# Start API + UI
python -m oracle.cli serve
```

Open **http://127.0.0.1:8787**.

On macOS you can also double-click [`run.command`](run.command) or [`START_ORACLE_MAC.command`](START_ORACLE_MAC.command).

### Live editing (VS Code)

The project ships with `.vscode/settings.json`:

- **Auto-save** after 500 ms, so editor changes hit the real file without `Cmd+S`.
- **Backend auto-reload**: `./dev.command` runs uvicorn with `--reload`; Python edits restart the API automatically.
- **Browser live reload**: the dev server watches `oracle/web/*` and reloads the open page when CSS/JS/HTML changes.
- **No manual refresh** is needed while `./dev.command` is running.

If VS Code was already open before these settings were added, run **Developer: Reload Window** once.

### Bundled snapshot

The downloadable zip ships with a pre-synced `data/oracle.sqlite3` (1,817 in-window fixtures and dossiers as of 2 Nov 2026, 18:19 UTC), so the UI has real data on first launch. Delete the database file and run `python -m oracle.cli sync --history` if you want to rebuild from scratch.

### First run without history

```bash
python -m oracle.cli sync          # 7-day window, ~90 seconds after warm cache
python -m oracle.cli serve
```

### Useful CLI

```bash
python -m oracle.cli status
python -m oracle.cli analyze fb:5795505
python -m oracle.cli backtest --days 30
python -m oracle.cli sync --force-models
```

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | engine heartbeat |
| `GET /api/overview` | counts, depth, model status, top signals |
| `GET /api/fixtures?days=7&sport=football&sort=confidence` | filterable fixture grid |
| `GET /api/benchmark/{id}?stake=100` | optional bookmaker benchmark: odds, implied, de-vig, edge, EV, best return/balanced, one-leg fair slip |
| `GET /api/search?q=Arsenal` | exact, partial, alias and fuzzy team/competition/fixture search |
| `GET /api/teams/{id}` | team profile, form, rating and upcoming fixtures |
| `GET /api/slip?stake=100&threshold=90` | model-fair-odds slip builder (no bookmaker odds) |
| `GET /api/fixtures/{id}` | full dossier: prediction + research + analysis |
| `POST /api/fixtures/{id}/analyze` | re-run research + model for one fixture |
| `POST /api/sync` | queue an autonomous cycle |
| `GET /api/jobs/{id}` | cycle progress |
| `GET /api/automation` | scheduler, jobs, event log, sources |
| `GET /api/backtest?days=30` | walk-forward football evaluation |
| `GET /api/review` | post-match settlement ledger |
| `POST /api/settle` | settle finished matches against stored predictions |
| `GET /api/export?sport=football&days=7` | CSV of the window |
| `GET /api/stream` | SSE status stream |

FastAPI docs are at **/docs**.

---

## Architecture

```
oracle/
├── oracle/
│   ├── api.py               FastAPI + SSE + static UI
│   ├── pipeline.py          discover → research → model → reason → persist
│   ├── scheduler.py         autonomous loop
│   ├── db.py                SQLite access, upserts, jobs, cache
│   ├── schema.sql           canonical schema
│   ├── config.py            runtime settings
│   ├── ingest/
│   │   ├── fotmob.py        global football fixtures, venues, weather, injuries
│   │   ├── cricbuzz.py      active cricket series and scores
│   │   ├── cricsheet.py     open cricket history / venue stats
│   │   ├── news.py          Google News RSS + ESPN newsroom
│   │   ├── weather.py       Open-Meteo geocoding + forecast
│   │   └── http.py          cached, retrying, bounded-concurrency HTTP
│   ├── models/
│   │   ├── football.py      Dixon–Coles + Poisson grid + markets
│   │   ├── cricket.py       vectorised ball-by-ball Monte Carlo + Test model
│   │   └── ratings.py       Elo, form, rest, congestion, H2H
│   ├── analysis/
│   │   ├── research.py      bounded context → model adjustments
│   │   └── analyst.py       deterministic reasoning core
│   └── web/                 mission-control SPA (no build step)
├── scripts/                 cron + launchd templates
├── tests/                   math and honesty tests
├── PROMPT_ORACLE.md         reusable master build prompt
└── data/                    SQLite warehouse + HTTP cache
```

### Data flow

1. **Discover** football fixtures for `today-7 … today+7` and all active cricket series.
2. **Deduplicate/upsert** competitions, teams and fixtures into SQLite.
3. **Enrich** the highest-priority fixtures with venue, weather, structured unavailable players, H2H and form.
4. **Research** team news (cached 6h), classify injury/suspension/manager/lineup signals.
5. **Fit** Dixon–Coles per competition with time decay and shrinkage; fit cricket Elo and batting/bowling indices.
6. **Adjust** expected goals / run rates with bounded context multipliers.
7. **Predict** all scheduled fixtures; simulate T20/ODI ball-by-ball; run Test draw model.
8. **Reason**: thesis, pros/cons, risks, adversarial check, confidence, research grade.
9. **Persist** prediction + research + analysis; expose to UI.
10. **Repeat** on a 30-minute scheduler, with new fixtures auto-added.

---

## Evidence-first match page

The match dossier is now organized as **Verdict → Teams → Lineups → Markets → Odds Bench → Tactical → Research → Protocol/Data → Model Trace**:

- **Teams** — last 5/10 form, home/away splits, goals for/against per match, rest days, sample sizes and date ranges. Historical xG and shots are explicitly unavailable.
- **Lineups** — confirmed starters when published; otherwise “Lineups not confirmed — prediction may change.” Expected XIs are not invented.
- **Verdict** — model probabilities, goal-total probabilities, model inputs actually used, context-only evidence and generation timestamp.
- **Protocol/Data** — provider, freshness, missing fields and market-free policy for every data category.
- **Model Trace** — append-only prediction revisions with model version and lineup status.
- **Review** — history-guarded settlement ledger, Brier/log loss, home baseline, calibration bins and clear legacy-sample warnings.

See [AUDIT.md](AUDIT.md) for the full audit.

## Forecast protocol

Every analysis follows [FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md): event identification, timestamped data audit, opponent-adjusted team strength, player projections where real data exists, correlations, scenarios, factor attribution, confidence scoring, market read only when odds are provided, data gaps and responsible-gambling notice. ORACLE's default forecast remains market-free; market data can only run as a separately labelled benchmark layer.

## The models

### Football — Dixon–Coles

- Per-competition attack/defence parameters, home advantage, low-score `rho`.
- Time decay (180-day half-life) and L2/empirical-Bayes shrinkage.
- 11×11 Poisson score grid with Dixon–Coles correction.
- Markets: 1X2, double chance, BTTS, over/under 0.5–4.5, Asian handicap, team totals, clean sheets, correct scores.
- Thin-sample calibration: the 1X2 distribution is blended toward the competition base rate until each side has ~24 matches of evidence.

### Cricket — Monte Carlo

- T20: 120-ball vectorised innings simulation, phase-dependent outcome distributions (powerplay/middle/death), wicket pressure, extras, chase logic, toss orientation and dew boost.
- ODI: 300-ball equivalent.
- Test: session-level result model with explicit draw mass, labelled as such in the dossier.
- Team strength blends recent runs-for/against with format Elo and ICC-style priors.
- Venue stats: average first innings, chase rate, toss-bat rate, draw rate from Cricsheet.

### Context (bounded, auditable)

| Signal | Football effect | Cricket effect |
|---|---|---|
| Confirmed injuries/suspensions | attack/defence multipliers from market-value-weighted availability | batting/bowling multipliers |
| Unverified news injury | capped small deduction, labelled weaker | capped small deduction |
| Congestion/rest | attack and defence fatigue penalty | rest-day flag |
| Rain/wind/heat | goals multiplier | dew / interruption flag |
| Venue | home advantage in DC | first-innings runs, chase rate |
| Manager change | uncertainty flag | — |

Every adjustment is bounded and included in the dossier's **Model Trace** tab.

### Evaluation

`/api/backtest?days=30` trains strictly before a hold-out window and reports:

- Brier score (multi-class)
- log loss
- 1X2 accuracy vs. "always home" baseline
- calibration buckets
- per-competition error

A model that cannot beat the home baseline is not ready for money. ORACLE reports that openly.

---

## The UI

A no-build, dependency-free SPA served by FastAPI:

- **Mission Control** — live canvas globe, KPI strip, highest-confidence signals, coverage matrix, engine status, research depth.
- **Fixture Grid** — all 1,800+ fixtures, sport/day/confidence/depth/sort/search filters, infinite load, watchlist.
- **Dossier** — verdict, independent probabilities, scoreline heatmap, market table, tactical pros/cons, injury/news/weather research, model trace, adversarial check.
- **Research Signals** — enriched fixtures and their flags/citations.
- **Model Lab** — run walk-forward backtest, calibration, per-competition error, architecture and data contract.
- **Review** — post-match settlement ledger: stored pre-match pick vs actual, accuracy, Brier, log loss, by sport/confidence/competition, with an honest small-sample warning.
- **Protocol tab** — data-quality audit, expected game script, key player availability, factor attribution, scenarios, data gaps and responsible-gambling notice for every dossier.
- **Odds Bench tab** — optional benchmark layer: timestamped ESPN/DraftKings odds, implied probability, de-vig probability, AI edge, EV, best return, best balanced, highest odds and a one-leg fair slip. The core forecast is never changed by these prices.
- **Automation** — scheduler state, job history, live event log, sources, CLI reference.
- **Command palette** — `⌘K` / `Ctrl+K`.
- **Working buttons** — sync, re-analyze, watch, copy, export, filters, tabs, palette, responsive rail.

The design is deliberately "mission control": dark glass panels, cyan/lime/magenta signal colors, HUD typography, animated globe, scanlines, no stock-photo poster.

---

## Automation

The FastAPI process starts a daemon scheduler (`ORACLE_SCHEDULER=1`). Every 45 seconds it checks:

- whether the 30-minute cycle is due;
- whether more than 50 in-window fixtures lack predictions;
- whether a manual cycle is queued.

Each cycle refreshes fixtures, results, research, models and predictions. `data/oracle.sqlite3` is the only state.

Optional OS-level scheduling:

```bash
# every 30 minutes
*/30 * * * * /path/to/oracle/scripts/oracle_sync.sh >> /tmp/oracle_cron.log 2>&1
```

macOS launchd template: [`scripts/com.oracle.engine.plist`](scripts/com.oracle.engine.plist).

### Environment

Copy [`.env.example`](.env.example) or export variables:

```bash
ORACLE_PORT=8787
ORACLE_WINDOW_DAYS=7
ORACLE_FIXTURE_REFRESH_MIN=30
ORACLE_RESEARCH_BUDGET=420
ORACLE_MC_RUNS=6000
ORACLE_SCHEDULER=1
```

---

## Data sources and provenance

| Layer | Source | Notes |
|---|---|---|
| Football fixtures/results | FotMob public feed | no key; global; includes venue/weather/unavailable players on enriched matches |
| Cricket fixtures/results | Cricbuzz public schedules | active international, franchise, domestic series |
| Cricket history/venues | Cricsheet | open data, CC-friendly attribution |
| News/injuries | Google News RSS, ESPN newsroom | headlines + links; classification is heuristic, not a medical source |
| Weather | Open-Meteo | open data, no key |
| Odds benchmark (optional) | ESPN public odds / DraftKings | only in the labelled Odds Bench layer; never a core model input |

Every dossier exposes citations and a research grade (A/B/C/D). Structured availability outranks news. When nothing verified exists, the dossier says **model-only** instead of inventing a story.

---

## Extending coverage

The discovery layer is intentionally pluggable:

1. Add an adapter under `oracle/ingest/` returning normalized `competitions`, `teams`, `fixtures` dicts.
2. Call it from `pipeline.run_full_sync()`.
3. Keep the provider fixture ID stable for deduplication.
4. Do **not** add odds columns or market-implied features.

For true 1xBet-level depth, use a licensed global fixture API and add it as another adapter. Do not scrape the bookmaker.

---

## Tests

```bash
source .venv/bin/activate
pytest -q
```

The suite checks score-grid normalization, market coherence, probability bounds, calibration behavior, fixture normalization, research honesty, and analyst output.

---

## Known limits

- Public feeds can rate-limit or change shape; the cache and retry layer absorb most of it.
- Cricket playing XIs and toss are often unknown until close to start; re-analyze after they land.
- Injury data is only as good as the public match-centre feed; unverified news is deliberately down-weighted.
- Test cricket is modelled at session level, not ball-by-ball.
- Bookmaker-free does **not** mean edge-free or risk-free. Evaluate calibration before using any output.
- SQLite is appropriate for a local single-user engine. For multi-user hosting, move to PostgreSQL and a queue.

---

## Responsible use

ORACLE is a research and analytics project. It does not accept bets, hold funds, or promise profit. If you choose to use probabilities in a wagering context, you are responsible for local law, bankroll limits, and your own decisions. Never chase losses. If gambling stops being fun, seek help.
