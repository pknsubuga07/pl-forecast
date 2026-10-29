# Forecast: Premier League, NBA and NFL predictions

A personal, educational project that predicts upcoming Premier League, NBA and NFL games from real
data, explains each prediction, compares it with bookmaker odds, and keeps an honest, frozen record
of how it did. **Not a betting tool.**

The Premier League section is described first; [NBA and NFL](#nba-and-nfl) follow the same design
and have their own section below.

**Live dashboard: https://pl-forecast.vercel.app/** (updated automatically by GitHub Actions)

| Fixtures | Match detail | Model performance |
|---|---|---|
| ![Fixtures](docs/screenshots/fixtures.jpg) | ![Match](docs/screenshots/match.jpg) | ![Performance](docs/screenshots/performance.jpg) |

What the dashboard shows:

* **Fixtures** for the next three gameweeks with a home / draw / away bar, confidence level, the
  bookmaker view and a flag where model and market differ by 10+ points; filter by gameweek, team
  or big disagreements.
* **Match page** for any upcoming fixture: probabilities (always summing to 100%), predicted
  outcome and confidence, a plain-English explanation, most likely scorelines with a score grid,
  expected goals, model vs bookmaker table, last-5 form with goals, league position / points /
  goal difference / points per game, home record of the home side and away record of the away side
  (this season and last, including Championship for promoted clubs), head-to-head (last 10 league
  meetings), xG / shots / shots on target / clean sheets, rest days since each team's last match in
  any competition, the model components and their weights, kickoff in New York time and venue.
* **Performance**: walk-forward log loss, Brier score, RPS and accuracy for every model and
  baseline and for the bookmakers, a calibration chart and per-season results.
* **History**: every finished 2026-27 match with the prediction on record before kickoff, the
  result, and a running record against the market.
* **Table** and **team pages** (Elo history, form trend, upcoming fixtures, per-game stats).
* "Data last updated" timestamp, source-failure banner, dark mode, mobile layout.

## Architecture

```
 football-data.co.uk ─┐  results, shots, odds (CSV)          GitHub Actions (cron)
 FPL public API ──────┼─► pipeline/ingest.py ─► SQLite ─► model/features.py ─► model/predict.py
 ESPN public API ─────┘  fixtures, kickoffs,   data/epl.sqlite   (leakage-safe)   (ensemble, scorelines,
                         venues, cups/Europe,                                      explanations)
                         DraftKings odds                                               │
                                                                                       ▼
                   data/ledger/predictions.csv ◄── freeze at kickoff ── model/ledger.py
                   (committed, append/lock only)                               │
                                                                               ▼
                               pipeline/export.py ─► web/public/data/*.json ─► git push
                                                                               │
                                     Vercel builds web/ (Next.js static export) ◄┘
```

* The **database** is SQLite (`data/epl.sqlite`). It can always be rebuilt from the sources, so it
  is cached between CI runs rather than committed. Tables: `teams`, `team_aliases` (the single
  name-mapping table), `matches` (Premier League and Championship, unique per division / season /
  home / away), `odds`, `other_matches` (cups and Europe, for rest days), `elo_history`,
  `predictions`, `pipeline_runs`, `source_status`. Every write is an upsert on a natural key, so
  re-running never duplicates anything. The schema is in [`pipeline/db.py`](pipeline/db.py).
* **Frozen predictions** live in `data/ledger/predictions.csv`, which is committed. A row can be
  refreshed until kickoff, then it is locked forever; git history is the audit trail.
* **Model versions** are saved in `model/artifacts/<version>/` (pickled model, manifest with
  hyper-parameters, training-data fingerprint and library versions). Each ledger row records the
  version that made it.
* The **site** is a static Next.js export built from `web/public/data/*.json`. If a pipeline run
  fails, nothing is committed and the live site keeps serving the last good data.

```
pipeline/   sources (football_data, fpl, espn), ingest, team mapping, db, export, CLI
            us_ingest.py, us_export.py (NBA / NFL)
model/      elo, dixon_coles, features, learners, evaluate, train, predict, explain, ledger
            us_features.py, us_models.py, us_evaluate.py, us_predict.py (NBA / NFL)
web/        Next.js 16 + TypeScript + Tailwind 4 dashboard
data/       teams.csv, us_teams.csv, team_aliases.csv, point_deductions.csv, ledger/  (raw/ + sqlite are ignored)
docs/       evaluation.md, evaluation_nba.md, evaluation_nfl.md (generated), evaluation-notes.md, screenshots
tests/      pytest suite
.github/    workflows: update.yml (scheduled pipeline), ci.yml (tests + web build)
```

## Data sources, terms and limits

| Source | Used for | Key? | Terms / limits | How we use it |
|---|---|---|---|---|
| [football-data.co.uk](https://www.football-data.co.uk/data.php) | Premier League and Championship results 2004-05 to now, shots, cards, odds from many bookmakers (opening and closing), xG for 2026-27, odds for the next round (`fixtures.csv`) | No | Free for personal / research use; please don't hammer it | Finished seasons downloaded once; only the current season and `fixtures.csv` are refreshed, ≥1 s between requests |
| [Fantasy Premier League API](https://fantasy.premierleague.com/api/bootstrap-static/) | Fixture list, gameweeks, UTC kickoff times, postponements, live/final scores, club codes for crests | No | Unofficial, undocumented; personal use | 2 requests per run |
| ESPN site API (`site.api.espn.com`) | Venues, every club's cup and European fixtures (rest days), DraftKings moneyline odds for the next ~10 days | No | Unofficial, undocumented; may change without notice | ~50 requests per run (0.4 s apart); one-off ~400-request historical backfill. **Optional**: if it fails the pipeline continues and the banner shows the issue |
| Club crests (`resources.premierleague.com`) | Images on the dashboard | No | Crests are the clubs' trademarks; hot-linked for personal, non-commercial use | Loaded by the browser |
| [nflverse `games.csv`](https://github.com/nflverse/nfldata) | NFL: every game since 1999 with kickoff, scores, rest days, stadium, starting QBs, closing moneyline / spread / total | No | Openly published by the nflverse project for public analysis (no explicit licence file on the repo; attribute nflverse) | One ~1.5 MB request per run |
| ESPN site + core APIs | NBA: schedules and results since 2012-13, arenas, DraftKings odds for upcoming games; historical NBA odds (core API) for the evaluation seasons; NFL live status and venues; NBA/NFL logos | No | Unofficial, undocumented | NBA: ~40 requests per run; one-off ~900 schedule requests and ~6,600 odds requests (cached) |

Sources I considered and did not use:
* **football-data.org** needs an API key and adds nothing the sources above do not already
  provide.
* **Understat** has free xG, but its `robots.txt` disallows all crawling.
* **FBref** no longer carries Opta xG, and its terms forbid scraping.

The consequence is that historical xG is not available. The model is trained on shots and shots
on target instead, and the dashboard shows real xG for 2026-27 from football-data.co.uk.

## Running it locally

Requirements: Python 3.14 (CI uses the same version, because saved models are pickled) and Node 20+. No API keys are
needed.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python -m pipeline bootstrap
```

`bootstrap` downloads every season, backfills cup and European dates from ESPN, trains the model
(re-using the committed `model/artifacts/hyperparams.json`) and writes the dashboard data. It
takes about 5 minutes on a first run. Add `--evaluate` to also re-run the full walk-forward
evaluation, which takes about 10 more minutes.

Then build and preview the dashboard:

```bash
cd web && npm install && npm run build && npx serve out
```

Or use `npm run dev` in `web/` for live reload while editing the UI.

Day-to-day commands:

```bash
.venv/bin/python -m pipeline update
```

```bash
.venv/bin/python -m pipeline update --retrain
```

```bash
.venv/bin/python -m model.evaluate
```

```bash
.venv/bin/python -m model.us_evaluate nfl
```

```bash
.venv/bin/python -m pipeline backfill-nba-odds && .venv/bin/python -m model.us_evaluate nba
```

```bash
.venv/bin/python -m pytest -q
```

## How the model works

1. **Elo** ratings run over the Premier League *and* Championship since 2004-05 (K = 10, goal
   difference multiplier, home advantage 95, 5% regression to the division mean each summer). This
   is how **promoted clubs** are handled: they arrive with the rating earned in the Championship,
   and points flow between divisions through promoted and relegated clubs. A promoted-club prior is
   also applied in Dixon-Coles.
2. **Dixon-Coles** goals model, refit twice a week on the last three seasons. Matches are weighted
   by recency (half-life about 8 months), ratings are shrunk towards a prior, and the target is 70%
   goals and 30% shots-on-target-implied goals. It gives expected goals and the full scoreline
   distribution.
3. **Gradient boosting** (scikit-learn `HistGradientBoostingClassifier`, depth-1 trees) uses 32
   pre-match features:
   * Elo ratings and the Dixon-Coles outputs
   * last-5 points per game, plus 10-match goal, shot and shots-on-target differences
   * home form of the home side and away form of the away side
   * season points per game, goal difference per game and league position
   * days of rest since the last match in any competition, and whether the club played in Europe
     within the last 5 days
   * promoted-club flags

   Missing values (for example, a promoted club's PL form) are handled natively.
4. **Final forecast** = 50% Dixon-Coles + 50% boosting. The weights and every hyper-parameter
   were chosen on the 2016-17 to 2020-21 validation seasons. **Bookmaker odds are never a model
   input**, so comparing the model with the market is fair.
5. **Explanations**: for each group of inputs (ratings, form, shots, home/away form, table, rest,
   promotion) the two teams are made equal on that group and the change in the predicted outcome's
   probability is measured. The biggest effects become the sentence on the match page.
6. **Confidence**:
   * high: the top outcome is at least 60%, or 30+ points clear of the next
   * medium: the top outcome is at least 45%, or 15+ points clear
   * otherwise low

**Leakage control.** Every feature is built from "state after match" rows joined to each fixture
with a strict *before kickoff* as-of join. League-table snapshots only count once a matchday's
games are over. Dixon-Coles only sees matches before its fit date. `tests/test_leakage.py`
checks this: it scrambles a match's own result and every later result, then asserts that the
match's features do not change.

## How it was evaluated

Walk-forward by season, no random splits. Each season is predicted by models trained only on
earlier seasons. Full tables are in [`docs/evaluation.md`](docs/evaluation.md) and the discussion
is in [`docs/evaluation-notes.md`](docs/evaluation-notes.md).

Test seasons 2021-22 to 2025-26 (1,900 matches):

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Always home win (base rates) | 1.069 | 0.647 | 0.232 | 44.2% |
| Elo | 0.984 | 0.586 | 0.203 | 52.6% |
| Dixon-Coles | 0.975 | 0.580 | 0.200 | 54.0% |
| **Final ensemble** | **0.978** | **0.582** | **0.201** | **53.0%** |
| Bookmakers (pre-match average) | 0.959 | 0.570 | 0.195 | 55.3% |

* The model clearly beats the naive baselines and is well calibrated.
* It does **not** beat the bookmakers. That is the expected result for a model that sees no team
  news.
* On the test seasons the plain Dixon-Coles model was slightly better than the ensemble that
  validation picked. That is reported, not tuned away.

**Known limitations:**
* No injuries, line-ups or team news.
* No historical xG for training.
* Early-season predictions for promoted clubs are the least reliable.
* ESPN's data is unofficial.
* Scoreline probabilities are approximate.

More detail is in the notes.

## NBA and NFL

The **NBA** (`/nba`) and **NFL** (`/nfl`) sections reuse the Premier League design: a games list,
game pages, standings, history, performance and team pages. Each sport has its own frozen ledger
(`data/ledger/nba_predictions.csv`, `data/ledger/nfl_predictions.csv`) and its own versioned
models (`model/artifacts/nba/`, `model/artifacts/nfl/`).

**What a game page shows:**
* home and away win probability, the predicted winner and a confidence level
  (high ≥ 75%, medium ≥ 62%, otherwise low)
* a projected score, plus the model's spread and total next to the betting line and moneyline
* a plain-English explanation and the factor bars behind it
* last-5 form, season record and conference rank, last 10 games, streak, points for and against
* the home team's home record and the away team's road record (this season and last)
* head-to-head (last 10 meetings, playoffs marked)
* rest days and back-to-backs (NBA), and starting quarterbacks (NFL)
* tip-off or kickoff in ET, and the venue

**Data:**
* **NFL:** nflverse `games.csv` has every game since 1999, with closing lines from 2006. ESPN adds
  live status and logos.
* **NBA:** ESPN team schedules, 2012-13 onward. Historical NBA odds come from ESPN's core API for
  2021-22 onward, used only to evaluate against the market. Upcoming odds are DraftKings via ESPN.

Teams are mapped in the same `data/team_aliases.csv`; NFL relocations keep one id
(STL→LA Rams, SD→LA Chargers, OAK→Las Vegas).

**Model, per sport:**
1. **Elo** with a margin-of-victory multiplier and an off-season pull back to average.
2. A **margin model**: ridge regression on the final point margin, converted to a win
   probability through a normal distribution with the residual spread. A matching model predicts
   total points, which gives the projected score.
3. A **gradient-boosted** win classifier.
4. **Inputs to all three:** Elo, short- and long-window point differential, points scored and
   allowed, home and road form, season win % and margin, rest days, neutral site and playoffs,
   plus back-to-backs (NBA) or starting-quarterback changes (NFL).
5. The final probability is a weighted average with weights chosen on validation seasons; the
   projected margin is derived from it.
6. **Evaluation:** the same walk-forward protocol: validation 2016–2020, test 2021–2025, betting
   lines never an input. Ties (NFL, about 0.2%) are excluded from the win-probability metrics.

**NFL, test seasons 2021–2025 (1,420 games with a closing moneyline):**

| Model | Log loss | Brier | Winner picked |
|---|---:|---:|---:|
| Always home team | 0.690 | 0.248 | 54.6% |
| Elo | 0.640 | 0.225 | 63.1% |
| Margin model | 0.635 | 0.222 | 63.5% |
| **Final ensemble** | **0.634** | **0.222** | **63.9%** |
| Closing moneyline | 0.610 | 0.212 | 66.3% |

* The average miss on the final margin is 10.1 points, against 9.8 for the closing spread. On
  total points it's 10.5 against 10.3 for the closing total.
* The market is clearly better. Closing lines include injury and weather news, and the model
  sees none of that.
* Calibration is good in the middle. Heavy home underdogs win a bit more often than the model
  says (forecasts around 26% won 34%, n = 77).
* The NFL Elo settings sit at the edge of their search grid (home advantage 35, 50% off-season
  regression). I didn't re-tune after seeing the test results.

**NBA, test seasons 2021-22 to 2025-26 (6,575 games with a pre-game moneyline):**

| Model | Log loss | Brier | Winner picked |
|---|---:|---:|---:|
| Always home team | 0.688 | 0.247 | 55.5% |
| Elo | 0.622 | 0.217 | 65.6% |
| Margin model | 0.619 | 0.215 | 65.7% |
| **Final ensemble** | **0.619** | **0.215** | **65.7%** |
| Pre-game moneyline | 0.594 | 0.205 | 68.1% |

* The average miss on the final margin is 11.0 points, against 10.5 for the betting spread. On
  total points it's 14.9 against 14.8 for the betting total.
* Calibration is good: every 10% bin is within about 5 points of the diagonal.
* The market's lead is bigger in the NBA. That fits the biggest gap in the model: it doesn't know
  who is resting or injured on a given night.
* The validation seasons have no stored odds, so validation is scored on all games, without a
  market comparison.
* The NBA test seasons were scored only once, after every setting had been fixed on 2016-17 to
  2020-21. Elo still landed on the edge of its widened grid (K = 8, home advantage 40); it was
  left there.

**Limits:**
* No injuries, rest decisions, lineups or trades. This matters most in the NBA, where stars sit
  out regularly.
* The NFL QB-change flag only knows the listed starter from nflverse.
* NBA standings are ordered by win % and point differential, not the league's official
  tie-breakers.

## Scheduled updates

[`.github/workflows/update.yml`](.github/workflows/update.yml) runs on GitHub Actions on this
schedule:

| When (UTC) | What |
|---|---|
| Every 3 hours (`17 */3 * * *`) | Fetch results, fixtures, odds and cup dates. Update Elo and features. Refresh predictions for the next 3 gameweeks. Lock predictions whose match has kicked off. Log finished matches. Export JSON. Commit. |
| Hourly 10:47–20:47 on Saturdays and Sundays | The same, more often on match days, so the frozen prediction is close to kickoff. |
| Hourly 22:47–01:47 every day | Evening runs for NBA tip-offs and NFL night games. |
| Tuesdays 06:05 | The same plus `--retrain`: the production model is refit on all finished matches and saved as a new version. |

Each commit to `main` triggers a Vercel deploy of `web/`.

**Failure handling:**
* Each sport runs independently: `python -m pipeline update` covers the Premier League, NBA and
  NFL. If one sport's required source fails, the other sports still publish, that sport keeps its
  last good data, and the workflow is marked failed at the end. The exit code is 0 if all
  succeeded, 2 if some failed, 1 if all failed.
* The required sources are football-data.co.uk and FPL for the Premier League, nflverse for the
  NFL, and ESPN schedules for the NBA. If one is down or changes format (HTML instead of CSV,
  missing columns, unknown team names), that sport fails with a clear error.
* On a failed run nothing is committed, so the site keeps the last good data, and GitHub emails
  the repository owner.
* ESPN failures are recorded but don't stop the run. The dashboard banner names any failing
  source.
* Commits that would only bump the "last updated" time are limited to one every 12 hours, to keep
  the git history small.

To trigger a run manually, open GitHub → Actions → "Update data and predictions" → Run workflow.
Tick "retrain" or "evaluate" if you want those too. Locally, run
`python -m pipeline update [--retrain]`.

Note: GitHub disables scheduled workflows after 60 days with no repository activity. The bot's
own commits count as activity, so this should not happen while matches are being played.

**Edge cases the pipeline handles:**
* **Postponed matches**: FPL clears the kickoff, so the match shows as postponed and an unlocked
  prediction is kept for the new date.
* **Rescheduled matches**: predictions are keyed by match, not date.
* **Season rollover**: the current season comes from FPL's fixture list. The new season's CSV
  may 404 for a while, and pre-season ratings regression is applied.
* **Off-season**: an empty fixture list renders an empty state.
* **Missing stats**: NaN-tolerant features.
* **Results before football-data updates**: FPL scores fill the gap.

## Environment variables and secrets

**No API keys or secrets are required.** [`.env.example`](.env.example) lists optional overrides:
`EPL_DB_PATH`, `EPL_DATA_DIR`, `EPL_WEB_DATA_DIR` and `EPL_USER_AGENT`. `.env` files are
git-ignored.

Deployment needs only the Vercel ↔ GitHub connection:
* import the repo in Vercel
* set the Root Directory to `web`
* use the default framework settings (Next.js)

The workflow pushes with the built-in `GITHUB_TOKEN`, which needs "Read and write permissions"
under Settings → Actions → General.

## Disclaimer

For personal and educational use only. Not betting advice. Data belongs to its respective
providers; club crests are trademarks of their clubs.
