# NFL model evaluation

_Generated 2026-10-30 06:09 UTC by `python -m model.us_evaluate nfl`._

Walk-forward by season: each season is predicted by models trained only on earlier seasons.
Settings were chosen on the validation seasons; the test seasons were scored once. All rows
are games with a bookmaker moneyline; ties are excluded.

## Test seasons (2021 to 2025, n = 1420)

| Model | Log loss | Brier | Accuracy |
|---|---:|---:|---:|
| Always home team (base rate) | 0.6896 | 0.2482 | 54.6% |
| Elo (logistic on rating gap) | 0.6404 | 0.2248 | 63.1% |
| Margin model (ridge regression) | 0.6345 | 0.2222 | 63.5% |
| Gradient boosting | 0.6347 | 0.2222 | 63.5% |
| Ensemble (final model) | 0.6341 | 0.2220 | 63.9% |
| Bookmaker moneyline (margin removed) | 0.6103 | 0.2115 | 66.3% |

* Margin error (MAE, points): model 10.13 vs bookmaker spread 9.77 (n = 1420)
* Total points error (MAE): model 10.51 vs bookmaker total 10.31 (n = 1420)

## Validation seasons (2016 to 2020, n = 1330)

| Model | Log loss | Brier | Accuracy |
|---|---:|---:|---:|
| Always home team (base rate) | 0.6880 | 0.2474 | 55.4% |
| Elo (logistic on rating gap) | 0.6287 | 0.2194 | 64.7% |
| Margin model (ridge regression) | 0.6244 | 0.2177 | 65.0% |
| Gradient boosting | 0.6267 | 0.2186 | 64.3% |
| Ensemble (final model) | 0.6242 | 0.2175 | 65.0% |
| Bookmaker moneyline (margin removed) | 0.6069 | 0.2097 | 66.6% |

## 2026 so far (n = 106)

| Model | Log loss | Brier | Accuracy |
|---|---:|---:|---:|
| Always home team (base rate) | 0.7036 | 0.2552 | 49.1% |
| Elo (logistic on rating gap) | 0.6642 | 0.2366 | 58.5% |
| Margin model (ridge regression) | 0.6733 | 0.2407 | 58.5% |
| Gradient boosting | 0.6765 | 0.2424 | 58.5% |
| Ensemble (final model) | 0.6717 | 0.2400 | 57.5% |
| Bookmaker moneyline (margin removed) | 0.6616 | 0.2331 | 63.2% |

## Chosen settings

* Elo: K = 20, home advantage = 35, off-season regression = 0.5
* Ridge alpha = 100.0; gradient boosting {'learning_rate': 0.05, 'max_iter': 300, 'max_depth': 1, 'min_samples_leaf': 100, 'l2_regularization': 1.0}
* Ensemble weights: elo 0.10, margin 0.75, gbm 0.15

## Per season (log loss)

| Season | n | Elo | Margin | GBM | Ensemble | Market |
|---|---:|---:|---:|---:|---:|---:|
| 2016 | 265 | 0.6224 | 0.6260 | 0.6328 | 0.6256 | 0.6216 |
| 2017 | 266 | 0.6233 | 0.6176 | 0.6215 | 0.6179 | 0.5932 |
| 2018 | 265 | 0.6305 | 0.6181 | 0.6242 | 0.6195 | 0.6135 |
| 2019 | 266 | 0.6417 | 0.6360 | 0.6377 | 0.6357 | 0.6163 |
| 2020 | 268 | 0.6257 | 0.6243 | 0.6177 | 0.6224 | 0.5900 |
| 2021 | 284 | 0.6639 | 0.6506 | 0.6390 | 0.6490 | 0.6232 |
| 2022 | 282 | 0.6311 | 0.6280 | 0.6371 | 0.6287 | 0.6050 |
| 2023 | 285 | 0.6598 | 0.6514 | 0.6583 | 0.6523 | 0.6270 |
| 2024 | 285 | 0.6145 | 0.6156 | 0.6135 | 0.6142 | 0.5892 |
| 2025 | 284 | 0.6327 | 0.6271 | 0.6257 | 0.6265 | 0.6070 |
| 2026 | 106 | 0.6642 | 0.6733 | 0.6765 | 0.6717 | 0.6616 |
