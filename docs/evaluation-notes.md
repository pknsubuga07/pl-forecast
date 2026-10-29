# What the evaluation taught us

Companion to [`evaluation.md`](evaluation.md) (the generated tables). Numbers below are from the
run of 29 October 2026. Test = 2021-22 to 2025-26, 1,900 matches, all scored walk-forward.

## Results in one table (test seasons)

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Always home win (base rates) | 1.0686 | 0.6465 | 0.2323 | 44.2% |
| Elo | 0.9843 | 0.5863 | 0.2029 | 52.6% |
| Dixon-Coles (goals + shots on target) | 0.9748 | 0.5796 | 0.1999 | 54.0% |
| Logistic regression | 0.9728 | 0.5785 | 0.1991 | 53.4% |
| Gradient boosting | 0.9885 | 0.5881 | 0.2026 | 52.5% |
| **Ensemble (final: 50% Dixon-Coles, 50% boosting)** | **0.9783** | **0.5820** | **0.2006** | **53.0%** |
| Bookmakers, pre-match average | 0.9594 | 0.5699 | 0.1949 | 55.3% |
| Bookmakers, closing average | 0.9556 | 0.5670 | 0.1936 | 55.9% |

## Takeaways

1. **The market wins.** Bookmaker odds beat every model on every metric, in every test season. A
   log-loss gap of about 0.019 is typical for models built on public results and shot data; the
   market also prices injuries, line-ups and team news that this model never sees. The dashboard
   flags big model-vs-market disagreements, but those are more often the model missing something
   than a mispriced market.
2. **All the real models land within 0.014 log loss of each other** (Elo 0.984, ensemble 0.978,
   Dixon-Coles 0.975, logistic 0.973). Most of the signal is "how good is each team"; the
   model families mostly disagree about noise.
3. **The validation pick was not the test winner.** On validation (2016-21) the ensemble was best
   (0.9505 vs Dixon-Coles 0.9547 and boosting 0.9545). On test, boosting degraded (0.9885) and
   dragged the ensemble below plain Dixon-Coles and logistic regression. We kept the
   pre-registered choice rather than switching after seeing the test set. A reasonable future
   change, decided on *new* data, would be to drop or shrink the boosting component.
4. **Shots on target help.** Blending 30% "shots on target x league conversion rate" into the
   Dixon-Coles target improved validation log loss from 0.9572 to 0.9547. This is the closest
   free, long-history stand-in for xG; real xG is shown on the dashboard but only exists from
   2026-27 in football-data.co.uk, so it cannot be trained on yet.
5. **Calibration is good.** Pooled over home, draw and away forecasts, the ensemble's bins sit
   within about 1.5 points of the diagonal up to 75%. It is slightly under-confident at the
   very top (forecasts around 84% won 87% of the time, n = 62).
6. **Accuracy is a poor guide.** The ensemble and Dixon-Coles differ by 1 point of accuracy but
   only 0.0035 of log loss; picking the most likely outcome throws away most of the forecast.
   Draws are almost never the single most likely result, so accuracy tops out in the mid 50s.

## Honesty notes

* **Two evaluation runs.** The first run ([`evaluation_run1.md`](evaluation_run1.md)) used a narrower
  search grid. Several validation optima sat on the edge of that grid, so a second run widened
  the grids and added the shots-on-target option, again choosing only on validation seasons.
  I had seen the first run's test numbers when making that change, which is a mild form of test
  peeking; the test result barely moved (ensemble 0.9768 then 0.9783, worse, not better).
* **Backtest rows on the history page** (2026-27 matches before 29 Oct 2026) come from models
  trained on seasons before 2026-27, but they were not published in advance. Live, frozen
  predictions start with gameweek 9.
* **Which odds count as "the market"**: the headline benchmark uses football-data.co.uk's
  pre-match average (collected a few days before each round), because that is roughly when the
  model's prediction is made. Closing odds (from 2019-20, covering all test seasons) are sharper
  and are reported alongside.

## Known limitations

* No team news, injuries, suspensions or line-ups. This is the biggest gap to the market.
* xG history is not available from a free, legally usable source (Understat disallows crawling;
  FBref no longer carries Opta xG), so shots on target stand in for it during training.
* Promoted clubs: Elo carries Championship form across, but the shared rating scale only
  connects through promoted and relegated clubs; early-season predictions for promoted sides are
  the least reliable.
* Rest days use ESPN's unofficial schedule data; if ESPN changes format, rest days fall back to
  Premier League matches only (the pipeline records the source failure).
* Score distributions come from Dixon-Coles and are rescaled to the ensemble's 1X2 totals, so
  scoreline probabilities are approximate.
* Home advantage has changed over time (it collapsed in the 2020-21 no-crowd season); the models
  learn an average over their training window.
