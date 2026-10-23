# Engineering decisions

## Time and labels

The prediction unit is route × local operating date × hour, published at 04:00 Toronto for later windows. UTC window starts distinguish repeated local hours. GTFS uses service-day noon minus twelve hours and supports times beyond 24:00, following the [official specification](https://gtfs.org/documentation/schedule/reference/). Calendar exceptions override weekly service. Both the preceding and current service date are considered when building an operating day.

A reviewed coverage ledger controls labels. Unknown coverage yields null labels. Event-start membership is half-open: start <= event < end. The dataset builder requires an explicit incident-code allowlist. Scheduled trip counts represent trips intersecting an hour, not passenger exposure or ridership.

## Leakage control

Training and inference call the same feature builder. A chronological sweep admits each label only after both its event window ends and its availability timestamp is reached. Schedule publication must precede prediction time. Model fitting also excludes labels unavailable at each fold's starting cutoff. Scalers are fitted only on training rows. A model cannot score dates within its training period through the batch prediction entry point.

Features are hour sine/cosine, weekday, month, scheduled trips, smoothed route frequency, smoothed route-hour frequency and history size. No incident cause or realized duration is used. Holidays and weather are intentionally absent. Unknown routes inherit the smoothed global prior and receive degraded status.

## Model selection

Three expanding temporal folds use 40–50%, 50–60% and 60–80% of service dates for validation. The last 20% is the final test. Candidates are a smoothed historical-frequency baseline, standardized logistic regression and CatBoost. Choose minimum validation Brier subject to AP at least the baseline and no route Brier regression greater than 0.05 for groups with at least 20 validation rows. Otherwise retain baseline. Daily attention budget K=5 is fixed in advance; risk thresholds are validation probability quantiles, not operationally calibrated intervention thresholds.

Registry versions include data and source-code hashes. Reports retain dependencies, seed, feature names, windows, metrics and thresholds. The artifacts are Python pickle files from local training only: never load untrusted uploads. SHA-256 detects accidental corruption, not malicious replacement by someone with filesystem write access.

## Reliability and scope

Source snapshots are content-addressed and immutable. Repeated batch payloads share an ID. A transaction inserts a staged batch and optionally changes the current-date pointers; readers cannot observe a partially activated batch. Revisions create new snapshots. Explicit publication can replace a date's current batch, while older batches remain retained.

Run one publisher per database/date and one writer per artifact directory. This is a single-node research deployment; concurrent writers, distributed leases, database migrations and high-availability failover are not implemented. PostgreSQL and SQLite share the same SQLAlchemy repository interface. JSON batch payloads keep the prototype small; a normalized indexed prediction table is a next step for larger workloads.

Python replaces dbt for the current transformation scope; a systemd timer replaces Airflow; the local registry replaces MLflow. These are deliberate scope choices, not claims that those named tools are present. No Terraform/cloud resources are provisioned.
