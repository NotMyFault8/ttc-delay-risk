# Engineering decisions and milestones

## Implemented foundation

The small standard-library implementation keeps data semantics inspectable before introducing orchestration and database services. `archive` stores immutable source bytes keyed by SHA-256. Reports and normalized outputs are namespaced by source hash, so revisions cannot replace an earlier snapshot. Writes use temporary files and rename. Run one writer per output directory; concurrent writers and multi-file transactional publication are not implemented.

The first-observation manifest is stable on repeat ingestion. It is not a full retrieval history or historical release record. A revised file creates a new partition; there is no current-version pointer yet. Schema failures retain Bronze inputs and raise an error without producing Silver outputs. Unknown fields remain in Bronze; required missing fields stop processing. Output JSON is intended for this modest snapshot size, not unbounded streams.

## Verification

Seven unit tests cover identical ingestion, revised input retention, DST fall-back and spring-forward boundaries, midnight conversion, duplicate retention, invalid-value quarantine, schema rejection and training evidence rejection. The real-source audit also ran successfully. CI is configured for Python 3.10 and 3.12. Container execution, network-failure injection, deployment and API latency are not yet verified.

## Recovery

Re-run the same command after an interruption. The source hash determines the partition and completed JSON outputs are atomically replaced. Preserve Bronze; generated Silver outputs can be regenerated. For a source schema change, retain the rejected bytes, update a versioned adapter and add a regression fixture before retrying. Do not manually modify archived source bytes.

## Remaining implementation

1. **Evidence:** archived GTFS, service validity and publication/coverage ledger; inspect code taxonomy and route mappings.
2. **Gold:** GTFS service dates including times beyond 24:00, UTC windows across DST, unknown labels, mature-label availability and partitioned snapshots.
3. **Features:** one shared training/inference implementation; point-in-time historical counts; calendar and scheduled service features.
4. **Evaluation:** smoothed frequency, logistic regression, LightGBM or CatBoost; temporal folds; Average Precision, daily Precision/Recall@K, Brier and group errors. Select K and thresholds on validation only.
5. **Serving:** versioned model registry, explicit release gate and rollback; PostgreSQL atomic batch publication; FastAPI health, readiness, predictions, ranking and model metadata.
6. **Operations:** retries and run ledger, Airflow/dbt where justified, degradation and freshness checks, Docker integration tests, deployment configuration and 14-day operation record.

A planned component is not an implemented capability. Do not describe the project as production-ready until these acceptance gates have measured evidence.
