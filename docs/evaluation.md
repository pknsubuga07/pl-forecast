# Model evaluation report

_Generated 2026-10-30 06:10 UTC by `python -m model.evaluate`._

## Protocol

* **Walk-forward by season.** For each evaluated season every learner is trained only on
  earlier seasons (from 2007-08). Dixon-Coles ratings are refit every Monday and
  Thursday using only matches before that date. Features use only pre-kickoff information.
* **Validation** (2016-17 to 2020-21, 1900 matches) was used for all choices:
  Elo K / home advantage / off-season regression, Dixon-Coles time decay / shrinkage /
  promoted-club prior, the gradient boosting and logistic regression settings, and the
  ensemble weights.
* **Test** (2021-22 to 2025-26, 1900 matches) was scored once with those fixed choices.
* Bookmaker baseline: market-average decimal odds collected by football-data.co.uk before
  the round (not closing odds), margin removed by proportional normalisation. All models are
  scored on the same matches (those with market odds).

Lower is better for log loss, Brier (multi-class, 0-2) and RPS (0-1).

## Test seasons (2021-22 to 2025-26)

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Always home win (base-rate probabilities) | 1.0686 | 0.6465 | 0.2323 | 44.2% |
| Elo (logistic on rating gap) | 0.9843 | 0.5863 | 0.2029 | 52.6% |
| Dixon-Coles goals model | 0.9748 | 0.5796 | 0.1999 | 54.0% |
| Multinomial logistic regression | 0.9728 | 0.5785 | 0.1991 | 53.4% |
| Gradient boosting (HistGradientBoosting) | 0.9885 | 0.5881 | 0.2026 | 52.5% |
| Ensemble (final model) | 0.9783 | 0.5820 | 0.2006 | 53.1% |
| Bookmaker average, pre-match (margin removed) | 0.9594 | 0.5699 | 0.1949 | 55.3% |

Against **closing** odds (sharper; available from 2019-20, n = 1900):

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Ensemble (final model) | 0.9783 | 0.5820 | 0.2006 | 53.1% |
| Bookmaker average, pre-match (margin removed) | 0.9594 | 0.5699 | 0.1949 | 55.3% |
| Bookmaker average, closing (margin removed) | 0.9556 | 0.5670 | 0.1936 | 55.9% |

## Validation seasons (2016-17 to 2020-21)

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Always home win (base-rate probabilities) | 1.0640 | 0.6433 | 0.2339 | 45.1% |
| Elo (logistic on rating gap) | 0.9635 | 0.5693 | 0.1980 | 55.7% |
| Dixon-Coles goals model | 0.9547 | 0.5647 | 0.1960 | 55.4% |
| Multinomial logistic regression | 0.9570 | 0.5653 | 0.1960 | 55.3% |
| Gradient boosting (HistGradientBoosting) | 0.9545 | 0.5644 | 0.1963 | 54.6% |
| Ensemble (final model) | 0.9505 | 0.5619 | 0.1952 | 55.4% |
| Bookmaker average, pre-match (margin removed) | 0.9447 | 0.5574 | 0.1930 | 55.9% |

## 2026-27 so far (n = 80, out-of-sample, models trained before the season)

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Always home win (base-rate probabilities) | 1.1001 | 0.6680 | 0.2307 | 38.8% |
| Elo (logistic on rating gap) | 1.0198 | 0.6139 | 0.2052 | 50.0% |
| Dixon-Coles goals model | 1.0262 | 0.6118 | 0.2068 | 50.0% |
| Multinomial logistic regression | 1.0129 | 0.6052 | 0.2032 | 45.0% |
| Gradient boosting (HistGradientBoosting) | 1.0248 | 0.6116 | 0.2065 | 47.5% |
| Ensemble (final model) | 1.0226 | 0.6096 | 0.2058 | 50.0% |
| Bookmaker average, pre-match (margin removed) | 1.0200 | 0.6114 | 0.2041 | 47.5% |

Small sample: one unusual weekend moves these numbers a lot.

## Chosen settings

* Elo: K = 10, home advantage = 95, off-season regression = 0.05
* Dixon-Coles: time decay xi = 0.0028 per day, ridge = 1.5, promoted-club prior = -0.2
* Gradient boosting: {'learning_rate': 0.05, 'max_iter': 300, 'max_depth': 1, 'min_samples_leaf': 100, 'l2_regularization': 1.0}
* Logistic regression: C = 0.003
* Ensemble weights: dc 0.50, gbm 0.50, logreg 0.00, elo 0.00

## Per season

| Season | n | Elo | Dixon-Coles | GBM | Ensemble | Market |
|---|---:|---:|---:|---:|---:|---:|
| 2016-17 | 380 | 0.9227 | 0.9363 | 0.9226 | 0.9259 | 0.9086 |
| 2017-18 | 380 | 0.9589 | 0.9575 | 0.9486 | 0.9485 | 0.9444 |
| 2018-19 | 380 | 0.9104 | 0.8956 | 0.8889 | 0.8887 | 0.8936 |
| 2019-20 | 380 | 0.9838 | 0.9731 | 0.9814 | 0.9728 | 0.9726 |
| 2020-21 | 380 | 1.0419 | 1.0110 | 1.0310 | 1.0163 | 1.0042 |
| 2021-22 | 380 | 0.9583 | 0.9549 | 0.9797 | 0.9629 | 0.9360 |
| 2022-23 | 380 | 0.9867 | 0.9933 | 1.0018 | 0.9943 | 0.9658 |
| 2023-24 | 380 | 0.9282 | 0.9245 | 0.9305 | 0.9248 | 0.9093 |
| 2024-25 | 380 | 1.0059 | 0.9775 | 0.9967 | 0.9839 | 0.9706 |
| 2025-26 | 380 | 1.0424 | 1.0238 | 1.0337 | 1.0258 | 1.0153 |
| 2026-27 | 80 | 1.0198 | 1.0262 | 1.0248 | 1.0226 | 1.0200 |

_(log loss)_

## What we learned

See [evaluation-notes.md](evaluation-notes.md) for the discussion, honesty notes and limitations.
