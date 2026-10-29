# NBA model evaluation

_Generated 2026-10-29 20:42 UTC by `python -m model.us_evaluate nba`._

Walk-forward by season: each season is predicted by models trained only on earlier seasons.
Settings were chosen on the validation seasons; the test seasons were scored once. All rows
are games with a bookmaker moneyline; ties are excluded.

## Test seasons (2021-22 to 2025-26, n = 6575)

| Model | Log loss | Brier | Accuracy |
|---|---:|---:|---:|
| Always home team (base rate) | 0.6877 | 0.2473 | 55.5% |
| Elo (logistic on rating gap) | 0.6224 | 0.2166 | 65.6% |
| Margin model (ridge regression) | 0.6186 | 0.2148 | 65.7% |
| Gradient boosting | 0.6220 | 0.2163 | 65.2% |
| Ensemble (final model) | 0.6190 | 0.2150 | 65.7% |
| Bookmaker moneyline (margin removed) | 0.5943 | 0.2045 | 68.1% |

* Margin error (MAE, points): model 10.97 vs bookmaker spread 10.54 (n = 6567)
* Total points error (MAE): model 14.94 vs bookmaker total 14.79 (n = 6573)

## Validation seasons (2016-17 to 2020-21, n = 6240)

| Model | Log loss | Brier | Accuracy |
|---|---:|---:|---:|
| Always home team (base rate) | 0.6831 | 0.2450 | 57.2% |
| Elo (logistic on rating gap) | 0.6266 | 0.2186 | 64.4% |
| Margin model (ridge regression) | 0.6255 | 0.2181 | 64.7% |
| Gradient boosting | 0.6269 | 0.2187 | 64.7% |
| Ensemble (final model) | 0.6244 | 0.2176 | 64.8% |
| Bookmaker moneyline | (no stored odds for these seasons) | | |

## 2026-27 so far (n = 68)

| Model | Log loss | Brier | Accuracy |
|---|---:|---:|---:|
| Always home team (base rate) | 0.7061 | 0.2564 | 48.5% |
| Elo (logistic on rating gap) | 0.6257 | 0.2192 | 60.3% |
| Margin model (ridge regression) | 0.6404 | 0.2258 | 60.3% |
| Gradient boosting | 0.6171 | 0.2147 | 64.7% |
| Ensemble (final model) | 0.6288 | 0.2203 | 63.2% |
| Bookmaker moneyline (margin removed) | 0.5531 | 0.1873 | 70.6% |

## Chosen settings

* Elo: K = 8, home advantage = 40, off-season regression = 0.4
* Ridge alpha = 100.0; gradient boosting {'learning_rate': 0.03, 'max_iter': 200, 'max_depth': 2, 'min_samples_leaf': 100, 'l2_regularization': 1.0}
* Ensemble weights: elo 0.35, margin 0.50, gbm 0.15

## Per season (log loss)

| Season | n | Elo | Margin | GBM | Ensemble | Market |
|---|---:|---:|---:|---:|---:|---:|
| 2016-17 | 1309 | 0.6247 | 0.6233 | 0.6264 | 0.6220 | – |
| 2017-18 | 1312 | 0.6156 | 0.6203 | 0.6193 | 0.6169 | – |
| 2018-19 | 1312 | 0.6161 | 0.6133 | 0.6154 | 0.6130 | – |
| 2019-20 | 1142 | 0.6319 | 0.6299 | 0.6317 | 0.6294 | – |
| 2020-21 | 1165 | 0.6479 | 0.6432 | 0.6444 | 0.6435 | – |
| 2021-22 | 1317 | 0.6365 | 0.6333 | 0.6375 | 0.6334 | 0.6104 |
| 2022-23 | 1314 | 0.6471 | 0.6437 | 0.6447 | 0.6438 | 0.6265 |
| 2023-24 | 1313 | 0.6132 | 0.6088 | 0.6159 | 0.6101 | 0.5751 |
| 2024-25 | 1315 | 0.6127 | 0.6057 | 0.6100 | 0.6074 | 0.5857 |
| 2025-26 | 1316 | 0.6026 | 0.6017 | 0.6019 | 0.6006 | 0.5738 |
| 2026-27 | 68 | 0.6257 | 0.6404 | 0.6171 | 0.6288 | 0.5531 |
