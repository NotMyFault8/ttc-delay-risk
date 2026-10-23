# Evaluation — synthetic contract demonstration

These are **synthetic results**, not evidence of TTC forecasting performance. The generator uses seed 42, three fictitious routes, four hours per day and a seven-day publication lag.

Windows: 2184. Positive rate: 0.268. Final period: 2025-05-26 to 2025-07-01. Selected model: **baseline**, chosen before final-test evaluation.

| Model | Average Precision | Brier | Precision@5 | Recall@5 |
|---|---:|---:|---:|---:|
| baseline | 0.4137 | 0.1880 | 0.3405 | 0.5365 |
| catboost | 0.4222 | 0.1888 | 0.3838 | 0.5901 |
| logistic | 0.3448 | 0.1946 | 0.3459 | 0.5423 |

Average Precision is scikit-learn average_precision_score, not trapezoidal PR area. Precision and recall are averaged per date; recall excludes dates without positive labels. Ties use route and window order. Calibration bins, daily fluctuations and route results are retained in the JSON report.

The baseline remained selected. A candidate looking better on the final test does not justify retroactively choosing it. This experiment validates software paths; its controlled generator does not reproduce TTC reporting patterns, route changes, rare incidents or operational drift. Real-model evaluation remains blocked on reviewed coverage, historical schedules and release-time evidence.
