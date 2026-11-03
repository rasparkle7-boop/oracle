# ORACLE — Master Build Prompt

Paste the block below into an elite coding agent (Claude Code, Codex, DeepSeek, Cursor, etc.). It is written as a production brief, not a mood board. It encodes the non-negotiables, the data contract, the math, the UI, the automation, and the acceptance tests.

---

## The prompt

```text
You are an elite quantitative sports modeller, AI architect, and senior full-stack engineer.

Build a production-grade, locally runnable sports intelligence engine called ORACLE.

MISSION
ORACLE must predict football and cricket matches from first principles. It must never use
bookmaker odds, market-implied probabilities, or "consensus" as an input. It must cover every
fixture it can discover in a rolling 7-day window, research each high-priority fixture, explain
its reasoning, and automate the whole cycle.

NON-NEGOTIABLES
1. ZERO MARKET RELIANCE.
   - No odds columns, no bookmaker scrape, no implied-probability priors.
   - "Fair odds" may only be 1 / P(model).
   - If a data source mixes odds with fixtures, ignore the odds.
2. NO FAKE DATA.
   - Never invent fixtures, injuries, lineups, players, weather, or xG.
   - Every claim must be traceable to a stored source or explicitly labelled "model-only".
   - If availability is unknown, say so. Do not hallucinate a player absence.
3. EVERY SCHEDULED FIXTURE GETS A PREDICTION.
   - No "only 6 games". Discover the global feed and predict all of it.
   - Deduplicate by stable provider fixture ID.
   - Add new fixtures automatically on every cycle.
4. EVERY FIXTURE GETS AN EXPLANATION.
   - Pick, probability, fair odds, edge vs a stated baseline.
   - Why this side, tactical pros/cons, key battles, risk factors, adversarial "why not".
   - A research grade (A/B/C/D) and a confidence score.
5. WORKING UI, NOT A POSTER.
   - Every button must do something: filters, search, sort, tabs, watchlist, sync,
     re-analyze, copy, export, command palette, close modal.
   - Verify with a headless browser click test. No dead controls, no overlays
     intercepting clicks.
6. AUTONOMY.
   - A background scheduler runs discovery + research + prediction on a cadence.
   - Also expose a CLI and cron/launchd templates.
   - Persist jobs, progress, logs and last/next sync so the UI can show real state.

DATA SOURCES (free/public first)
- Football fixtures/results: FotMob public match feed (`/api/data/matches?date=YYYYMMDD`).
  Enrich priority matches with `/api/data/matchDetails?matchId=...` for venue, weather,
  formations, H2H, form, and structured unavailable players (injury/suspension).
- Cricket fixtures/results: Cricbuzz public schedules. Parse the React Server Component
  payload embedded in series pages; extract full match objects (matchInfo + matchScore).
- Cricket history/venues: Cricsheet open data (`recently_played_30_json.zip`; optional
  t20s/odis/tests archives for deeper backtests).
- News: Google News RSS per team and ESPN league newsroom feeds. Cache 6h.
- Weather: Open-Meteo geocoding + hourly forecast (no key).
- Do NOT scrape 1xBet/Bet365/Pinnacle. If the user asks for "all 1xBet games", explain
  that bookmaker scraping is out of contract and build a pluggable adapter for a
  licensed global fixture feed instead.

ARCHITECTURE
- Python 3.11+, FastAPI, SQLite (WAL), numpy/scipy, httpx.
- No frontend build step required: serve a static SPA (HTML/CSS/JS) from FastAPI.
- Modules:
  ingest/ (fotmob, cricbuzz, cricsheet, news, weather, http cache)
  models/ (football Dixon-Coles, cricket Monte Carlo, ratings/Elo/form)
  analysis/ (research context, deterministic reasoning core)
  pipeline.py (orchestration), scheduler.py, api.py, cli.py, db.py, schema.sql
- Background scheduler thread started by FastAPI lifespan.
- SQLite tables: competitions, teams, fixtures, team_ratings, predictions, research,
  news_cache, historical_results, sync_jobs, model_runs, watchlist, sync_state, event_log.

FOOTBALL MODEL (Dixon-Coles)
- Fit per competition: attack_i, defence_i, home advantage gamma, low-score rho.
- lambda_home = exp(mu + attack_home - defence_away + gamma)
- lambda_away = exp(mu + attack_away - defence_home)
- mu = log(weighted mean away goals); time decay half-life 180 days.
- Dixon-Coles tau correction for 0-0, 0-1, 1-0, 1-1.
- L2 / empirical-Bayes shrinkage for thin samples. Centre attack and defence.
- 11x11 score grid. Markets: 1X2, double chance, BTTS, O/U 0.5-4.5, Asian handicap
  (push-adjusted), team totals, clean sheets, correct scores, win to nil.
- Calibrate 1X2 toward the competition base rate until each side has ~24 matches:
  w = 0.40 + 0.60 * min(1, (home_matches+away_matches)/24); p = w*model + (1-w)*base.
  This prevents fake 95% certainties from three matches.
- Confidence = weighted blend of sample size, entropy, separation and research depth.

CRICKET MODEL (Monte Carlo)
- Build team strength by format: recent runs for/against + Elo + ICC-style priors.
- Venue stats from Cricsheet: average first innings, chase rate, toss-bat rate, draw rate.
- T20/ODI: vectorised ball-by-ball simulation (numpy), 4,000-8,000 sims.
  - Phase-dependent outcome probabilities [dot,1,2,3,4,6,W,extra].
  - Adjust boundaries by batting strength, wickets by bowling strength.
  - Track runs/wickets/balls; 10 wickets or overs; chase target logic.
  - Average both toss orientations; apply dew boost to the chase.
  - Output win/tie probabilities, projected score bands, total-runs markets.
- Test: session-level result model with explicit draw mass; label it as such.
- Calibrate thin-sample win probabilities toward a neutral prior.

RESEARCH SUBSYSTEM
For each priority fixture (importance-ranked, budgeted):
- Structured availability from match centre: player, injury/suspension, expected return,
  market value. Convert to bounded impact (0-0.30) and attack/defence multipliers.
- News: last 7 days, per team, query injury/suspension/lineup/manager. Classify tags,
  keep headline/source/url/time, cite it.
- Weather: temperature, wind, rain, humidity. Football: goal effect. Cricket: dew risk.
- Fatigue: rest days and matches in last 21 days from the fixture warehouse.
- H2H and recent form from the warehouse.
- Venue/pitch stats for cricket.
- Research depth: full (details+news), enhanced (one), model (none), partial (sparse).
- Store every citation. Unverified news must be down-weighted and labelled.

REASONING CORE
For every fixture emit JSON with:
- headline, verdict, edge_thesis[] (with numbers), tactical {home:{pros,cons}, away:{...}},
  key_battles[], risks[], why_not, market_read,
  research_grade, edge_quality (STRONG/MODERATE/THIN/NONE), confidence_note,
  model_trace[{label,value}], narrative[].
- The verdict must state the pick, probability, fair odds, projected score/xG or run bands,
  conviction, and research grade.
- The edge thesis must explain WHY with model values and context, not adjectives.
- The risk list must include variance, data thinness, availability uncertainty and
  draw/tie mass where relevant.
- The adversarial check must describe the underdog's realistic path.
- Never promise a win. Never say "guaranteed", "banker", "lock".

UI / UX
- Dark "mission control" aesthetic: deep navy/black, cyan/lime/magenta signal colors,
  glass panels, HUD corners, mono labels, display typography, animated canvas globe,
  scanlines, signal wire ticker. No stock photos, no generic dashboard template.
- Views: Mission Control, Fixture Grid, Research Signals, Model Lab, Automation, Watchlist.
- Fixture card: competition, kickoff, teams (logos), 1X2 split bar, pick chip, edge,
  confidence, research depth, flags, watch star.
- Dossier modal/page: header, tabs (Verdict, Markets, Tactical, Research, Model Trace),
  probability split, scoreline heatmap (canvas), pick card, risks, citations, re-analyze.
- Filters: sport, day window, search, sort, min confidence, depth, watchlist.
- Command palette (Cmd/Ctrl+K), toasts, skeleton loaders, empty states, responsive layout.
- Every interactive control must have an event handler. Test that overlays with [hidden]
  do not intercept pointer events.
- Show honesty: model-only banner, research grade, source citations, "no market inputs".

AUTOMATION
- Scheduler tick every 45s; full cycle every 30 min.
- Cycle: fetch fixtures (-7..+7), cricket series, Cricsheet recent, train models,
  enrich priority fixtures, research news, predict all scheduled fixtures, persist.
- Job records with progress, message, stats. Event log. Last/next sync state.
- CLI: serve, sync [--history], analyze <fixture>, backtest --days N, status.
- Provide run.command, cron script, launchd plist.

EVALUATION
- Walk-forward football backtest: train strictly before the hold-out window.
- Report Brier, log loss, accuracy, home baseline, calibration buckets, by-competition error.
- Surface it in Model Lab. Do not hide poor results.

ACCEPTANCE CRITERIA
1. Fresh machine: `pip install -r requirements.txt`, `python -m oracle.cli sync --history`,
   `python -m oracle.cli serve` → UI at http://127.0.0.1:8787 with 1,000+ real fixtures.
2. At least 200 competitions and both sports present in the 7-day window.
3. Every scheduled fixture in the window has a prediction row with probabilities, pick,
   fair odds, confidence, analysis.
4. At least 100 fixtures have full/enhanced research with citations; the rest are clearly
   labelled model-only.
5. No odds/market fields anywhere in schema or code. Grep for "odds" should only find
   fair-odds output and explanatory text.
6. Buttons verified with headless browser: filter, search, open dossier, switch tabs,
   watch, re-analyze, copy, export, palette, close.
7. Scheduler runs and updates last/next sync; jobs/logs visible.
8. Backtest endpoint returns out-of-sample metrics.
9. Tests pass: score grid sums to 1, probabilities bounded, markets coherent, calibration
   shrinks thin samples, analyst output has all required fields.
10. README documents data sources, legal limits, responsible-use warning, and how to add
    a licensed feed.

STYLE
- Production code, typed where useful, no notebooks, no placeholder TODO logic.
- Errors are handled and logged; external calls cached and retried.
- Keep the math honest; keep the UI alive.
```

---

## Short version (if you only have one paragraph)

> Build ORACLE: a market-free football + cricket intelligence engine that discovers every fixture in a 7-day window from public global feeds, researches injuries/news/weather/venue, fits Dixon–Coles and Monte Carlo models, predicts every match with confidence and calibration, explains the edge and the risks with citations, automates the cycle, and ships a futuristic mission-control UI where every button works. No bookmaker odds. No fabricated data. No guarantees.

---

## How to use this prompt well

1. **Give it a real workspace**, not a chat window. The agent must run the ingestion, inspect the data, and screenshot the UI.
2. **Ask for a vertical slice first**: one football league + one cricket series → DB → model → dossier → UI. Then scale discovery.
3. **Demand honesty tests**: kill the network and verify the app shows an empty state rather than fake fixtures.
4. **Demand a click test**: headless browser opens the page, clicks every control, and reports console errors.
5. **Do not let it add odds** "for comparison". That is how market contamination starts.
6. **Check calibration**, not just accuracy. A confident 95% model that is right 60% of the time is worse than a humble 55% model.
7. **Re-run after line-ups**. Injuries and toss are the highest-value late information in sport.
