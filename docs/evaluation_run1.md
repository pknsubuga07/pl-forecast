# Model evaluation report

_Generated 2026-10-29 19:10 UTC by `python -m model.evaluate`._

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
| Elo (logistic on rating gap) | 0.9795 | 0.5833 | 0.2013 | 53.3% |
| Dixon-Coles goals model | 0.9771 | 0.5814 | 0.2006 | 53.3% |
| Multinomial logistic regression | 0.9725 | 0.5784 | 0.1990 | 53.8% |
| Gradient boosting (HistGradientBoosting) | 0.9890 | 0.5883 | 0.2028 | 52.6% |
| Ensemble (final model) | 0.9768 | 0.5811 | 0.2003 | 53.3% |
| Bookmaker average, pre-match (margin removed) | 0.9594 | 0.5699 | 0.1949 | 55.3% |

Against **closing** odds (sharper; available from 2019-20, n = 1900):

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Ensemble (final model) | 0.9768 | 0.5811 | 0.2003 | 53.3% |
| Bookmaker average, pre-match (margin removed) | 0.9594 | 0.5699 | 0.1949 | 55.3% |
| Bookmaker average, closing (margin removed) | 0.9556 | 0.5670 | 0.1936 | 55.9% |

## Validation seasons (2016-17 to 2020-21)

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Always home win (base-rate probabilities) | 1.0640 | 0.6433 | 0.2339 | 45.1% |
| Elo (logistic on rating gap) | 0.9651 | 0.5703 | 0.1985 | 55.5% |
| Dixon-Coles goals model | 0.9572 | 0.5664 | 0.1968 | 55.2% |
| Multinomial logistic regression | 0.9591 | 0.5669 | 0.1967 | 55.2% |
| Gradient boosting (HistGradientBoosting) | 0.9626 | 0.5697 | 0.1986 | 54.4% |
| Ensemble (final model) | 0.9548 | 0.5648 | 0.1963 | 55.5% |
| Bookmaker average, pre-match (margin removed) | 0.9447 | 0.5574 | 0.1930 | 55.9% |

## 2026-27 so far (n = 80, out-of-sample, models trained before the season)

| Model | Log loss | Brier | RPS | Accuracy |
|---|---:|---:|---:|---:|
| Always home win (base-rate probabilities) | 1.1001 | 0.6680 | 0.2307 | 38.8% |
| Elo (logistic on rating gap) | 1.0343 | 0.6229 | 0.2097 | 46.2% |
| Dixon-Coles goals model | 1.0298 | 0.6126 | 0.2077 | 48.8% |
| Multinomial logistic regression | 1.0164 | 0.6075 | 0.2041 | 42.5% |
| Gradient boosting (HistGradientBoosting) | 1.0227 | 0.6097 | 0.2044 | 46.2% |
| Ensemble (final model) | 1.0234 | 0.6091 | 0.2055 | 47.5% |
| Bookmaker average, pre-match (margin removed) | 1.0200 | 0.6114 | 0.2041 | 47.5% |

Small sample: one unusual weekend moves these numbers a lot.

## Chosen settings

* Elo: K = 15, home advantage = 80, off-season regression = 0.1
* Dixon-Coles: time decay xi = 0.0028 per day, ridge = 3.0, promoted-club prior = -0.2
* Gradient boosting: {'learning_rate': 0.03, 'max_iter': 200, 'max_depth': 2, 'min_samples_leaf': 80, 'l2_regularization': 1.0}
* Logistic regression: C = 0.003
* Ensemble weights: dc 0.60, gbm 0.30, logreg 0.10, elo -0.00

## Per season

| Season | n | Elo | Dixon-Coles | GBM | Ensemble | Market |
|---|---:|---:|---:|---:|---:|---:|
| 2016-17 | 380 | 0.9304 | 0.9407 | 0.9283 | 0.9328 | 0.9086 |
| 2017-18 | 380 | 0.9604 | 0.9581 | 0.9544 | 0.9517 | 0.9444 |
| 2018-19 | 380 | 0.9109 | 0.8970 | 0.8992 | 0.8942 | 0.8936 |
| 2019-20 | 380 | 0.9803 | 0.9734 | 0.9820 | 0.9722 | 0.9726 |
| 2020-21 | 380 | 1.0437 | 1.0167 | 1.0488 | 1.0232 | 1.0042 |
| 2021-22 | 380 | 0.9601 | 0.9553 | 0.9772 | 0.9576 | 0.9360 |
| 2022-23 | 380 | 0.9773 | 0.9957 | 0.9971 | 0.9910 | 0.9658 |
| 2023-24 | 380 | 0.9283 | 0.9282 | 0.9356 | 0.9264 | 0.9093 |
| 2024-25 | 380 | 0.9914 | 0.9780 | 0.9966 | 0.9810 | 0.9706 |
| 2025-26 | 380 | 1.0403 | 1.0281 | 1.0388 | 1.0279 | 1.0153 |
| 2026-27 | 80 | 1.0343 | 1.0298 | 1.0227 | 1.0234 | 1.0200 |

_(log loss)_

## What we learned

See README section "How the model was evaluated".
