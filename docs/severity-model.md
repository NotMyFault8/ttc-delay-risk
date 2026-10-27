# Conditional incident severity — 2026-10-27

## Prediction question

For a route, local hour, weekday and month, **if a TTC incident is recorded**, what is the probability that its recorded `Min Delay` is at least 15 minutes?

One incident record is one sample. Duration >=15 gives label 1; a valid duration <15 gives label 0, including recorded zeros. Missing service-hour records never become negative samples. This estimates severity within TTC's reporting process, not delay occurrence, actual punctuality, passenger exposure, or the probability of at least one severe incident in an hour.

The configurable 15-minute threshold is a project definition, not a claimed TTC standard. Features are route, hour, weekday, month and cyclic hour. Incident reason, observed delay, gap, direction, vehicle and realtime observations are excluded. Historical GTFS and complete reporting are not prerequisites for this conditional question; their absence still limits route validity and generalization.

## Data

The parser reads CSV, XLSX and ZIP containing one XLSX, including sparse cells, shared/inline strings, Excel serial dates and numeric times. Formula cells are rejected. `Route`/`Incident` map to `Line`/`Code` for parsing; incident codes remain lineage fields, not an established cross-year taxonomy. No historical availability timestamps are invented.

| Source | Raw | Invalid route/time | Duplicate valid context | Accepted |
| --- | ---: | ---: | ---: | ---: |
| Kaggle 2023 | 50,913 | 702 | 186 | 50,025 |
| Official 2025+ | 107,349 | 1,819 | 302 | 105,228 |
| Total | 158,262 | 2,521 | 488 | 155,253 |

Duplicates use normalized route/time/code/duration plus source location/gap/direction/vehicle. This differs from legacy ingestion; indistinguishable genuine reports may also be collapsed. Ambiguous/nonexistent Toronto DST times are rejected. Numeric route parsing does not verify current bus service. 2023 lacks December, 2024 is absent, and the current snapshot ends 2026-09-30. Missing periods are not filled. Raw data and artifacts remain in ignored storage.

## Selection and results

Train: before 2026-01-01. Validation: 2026-01-01–2026-03-31. Sealed test: 2026-04-01–2026-09-30 (27,613 records, 45.73% positive). Each partition requires 100 events, 30 observed dates and both classes.

Validation compares fixed configurations of smoothed route/hour frequency, logistic regression and CatBoost, with combined history and 2025+ history. Minimum validation Brier selects the model/cohort. The baseline uses only fitted training counts, without incorporating validation/test outcomes.

| Candidate | Combined validation Brier | 2025+ validation Brier |
| --- | ---: | ---: |
| Frequency baseline | 0.16522 | 0.16532 |
| Logistic regression | 0.16962 | 0.16703 |
| CatBoost | 0.16659 | **0.16412** |

2023 was assessed but did not improve the winning configuration. **CatBoost with 2025+ history** was selected before inspecting the test. This configuration was refitted on pre-test records for evaluation. A separate prospective artifact refits the same selected configuration on all 105,228 available 2025+ records; its future performance is unmeasured.

| Test metric | CatBoost | Frequency baseline |
| --- | ---: | ---: |
| Brier (lower is better) | 0.16812 | 0.16988 |
| Average Precision | 0.78897 | 0.78425 |
| ROC-AUC | 0.82916 | 0.82770 |
| Log loss | 0.50946 | 0.51457 |

The improvement is modest, roughly 1% in Brier. Probabilities have calibration error: the 0.20–0.30 test bin averaged 0.246 predicted versus 0.348 observed. No significance or prospective reliability claim is made. Monthly test metrics, calibration bins, source/model/code hashes and dependency versions appear in `reports/severity-evaluation.json`.

This is **retrospective event-date evaluation on downloaded snapshots**, not an historically executable as-of backtest: publication times remain unknown and later revisions may be included. The legacy evidence gate remains in place for its different target. Predictions must use an artifact already fitted at prediction time, and dates wholly in the future and after all training records. Future model improvements require fresh evaluation periods; this test has now been inspected.

## Commands and output

```sh
python -m ttc_delay_risk.severity train \
  --inputs /path/to/ttc-bus-delay-data-2023.xlsx.zip /path/to/source.csv \
  --threshold 15 --validation-start 2026-01-01 --test-start 2026-04-01 \
  --root data/severity
python -m ttc_delay_risk.severity predict \
  --root data/severity --date FUTURE-YYYY-MM-DD --routes 35 36 52
```

Default splits hold out the final six calendar months for test and the preceding three for validation. Artifacts go to `ROOT/registry/VERSION`; `ROOT/latest.json` identifies the latest research candidate. Inference verifies artifact checksums and rejects historical dates. Only load trusted local pickle artifacts.

Output: `ROOT/predictions/DATE-VERSION.json`. Fields include `conditional_severe_delay_probability`, `threshold_minutes`, `condition`, `prediction_time`, `training_event_end`, support counts and `route_service_verified=false`. Default routes appeared in the final 90 source days. The 24 hour scenarios per route do not establish that service operates then. Unseen routes get `unknown_route`; fewer than 100 route records gives `low_support`. Scores are not published to the old incidence-risk API.

## Airflow

The DAG retains `30 3 * * *`, America/Toronto, with ingestion as its scheduled default. New explicit run configurations:

```json
{
  "operation": "train_severity",
  "root": "/opt/airflow/project/data",
  "threshold": 15,
  "inputs": [
    "/opt/airflow/project/data/severity-inputs/2023.xlsx.zip",
    "/opt/airflow/project/data/ttc/bronze/2bc395f3c0db59010daf42bd97dcc6f2c3006c3646f58cf2d2cd42cba6e1b1f3/source.csv"
  ]
}
```

```json
{
  "operation": "predict_severity",
  "root": "/opt/airflow/project/data",
  "date": "2026-10-28"
}
```

The DAG appends `/severity` to its root; the module CLI takes the severity root directly. Replace the date with a future date on later runs. Optional `version` pins prediction to an artifact. `publish=true` is rejected for research scenarios. The legacy branches still require their original evidence and release.

## Execution evidence

The real training run produced `severity-1a2f096613d5a5ba-20261027T075906503244`. Airflow run `severity_preview_20261028` completed its validation, branching and conditional-severity tasks successfully. It generated 5,424 scenarios for 226 recently observed route identifiers × 24 hours on 2026-10-28. JSON and CSV copies are under the ignored workspace directory `data/severity/predictions/`; the artifact remains in the Airflow data volume.

The full 23-test suite passed after implementation. An additional prospective-inference test subsequently passed together with the five original severity tests (24 distinct tests in total). Checks cover sparse Excel cells, absent-hour handling, invalid/DST records, duplicates, outcome-free features, fixed baseline counts, future-only predictions, model creation time, unknown routes and artifact corruption. Airflow reported no DAG import errors. No prospective outcomes were available at execution time.
