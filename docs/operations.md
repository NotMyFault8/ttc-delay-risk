# Operations and reproducibility

## Verified locally

- 18 tests passed with numerical runtime warnings treated as errors.
- Docker image built; PostgreSQL 16.6 became healthy; FastAPI served the published demo batch.
- The same synthetic batch ID was produced by Python 3.10 locally and Python 3.12 in the container.
- The dashboard displayed 10 ranked windows from a published batch containing 12 predictions.
- A 200-request HTTP benchmark at concurrency four completed against the local container and PostgreSQL. See `reports/local-benchmark.json` for latency and exact scope.
- Corrupt-artifact fallback, idempotent replay and invalid publication rejection are tested. `/ready` correctly rejects historical demo data.

These checks are not a production SLA. No cloud costs, 14-day run success rate or real TTC forecasting improvement have been measured.

## Source ingestion

`ttc-risk --file SOURCE.csv --output data` creates Bronze and Silver partitions keyed by SHA-256. Use `--url HTTPS_RESOURCE` for network ingestion with bounded retries. Existing files survive source failures. Only the 2025+ CSV adapter is implemented. Re-run after interruption; never edit archived bytes.

## Dataset contracts

A schedule manifest is a JSON list. Each item has `path` (local GTFS ZIP), `start_date`, `end_date`, `available_at` (offset-aware timestamp), and `reference` (evidence URL or document identifier). Validity and historical availability must be reviewed; the pipeline selects the latest available matching snapshot.

Coverage is a JSON object keyed by local date. Values contain `verified`, `reference`, and `available_at`. Only reviewed dates get labels. The event input is the normalized `events.json` from ingestion. Use `--codes` to explicitly identify included incident codes.

`ttc-dataset` writes rows with route, date, UTC start/end, local hour, planned trip count, schedule availability, prediction cutoff, label and label availability. Unknown labels remain null. `ttc-pipeline train` additionally requires an evidence document matching `configs/evidence.example.json`. The document is a manual attestation; its flags cannot establish scientific validity by themselves.

## Training and release

```sh
ttc-pipeline train --dataset data/windows.json --evidence evidence.json
# Inspect data scope, validation selection and held-out results.
ttc-pipeline release --version VERSION
```

Training saves a candidate without changing the release pointer. Release and rollback are explicit operator actions. Baseline is a valid selected model; no improvement is fabricated. Synthetic and real artifacts have different version suffixes.

## Predict and backfill

```sh
ttc-pipeline predict --dataset data/windows.json --date 2025-07-01
# The command above stages only; publishing is explicit.
ttc-pipeline predict --dataset data/windows.json --date 2025-07-01 --publish
ttc-pipeline predict --dataset data/windows.json --date 2025-07-01 --end-date 2025-07-07
```

Backfills must use a model trained before their earliest target date. Recompute daily targets with the shared as-of feature code; no current results change unless `--publish` is present. `DATABASE_URL` or `--database-url` selects PostgreSQL; otherwise the root directory contains a SQLite database.

## Scheduling and monitoring

The production DAG at `airflow/dags/ttc_delay_risk_daily.py` runs at 03:30 America/Toronto, checks the executable, dataset, release pointer and database configuration, then atomically publishes that Toronto service date. It disables catchup and limits concurrency to one active run; historical dates can be run explicitly with an Airflow logical date. The CLI run ledger remains the system of record for the batch result.

For a local deployment, set both passwords in `.env`, place the reviewed rolling dataset at `data/production-windows.json`, and release a real model before starting Airflow:

```sh
docker compose -f compose.yaml -f compose.airflow.yaml up airflow-init
docker compose -f compose.yaml -f compose.airflow.yaml up -d airflow-webserver airflow-scheduler api
```

The Airflow UI binds to `127.0.0.1:8080`. Create the first UI user with the Airflow CLI; credentials are never committed. Worker processes receive the prediction database URL through the environment. The DAG uses Airflow's data interval in `America/Toronto`, including DST transitions, rather than the container clock.

The templates under `deploy/` remain a lightweight systemd alternative. Before installing them, create the service user, install the project in `/opt/ttc-delay-risk`, supply the reviewed rolling dataset and release a real model. Neither scheduler fetches new coverage evidence automatically.

The `runs` table stores success/failure, elapsed time and error type. Inspect it alongside `batches` and `current_batches`. Monitor `/health` for the process and `/ready` for current production predictions. The source audit reports schema, blank counts, duplicate candidates and quarantine reasons. Model reports contain daily performance, calibration bins and per-route breakdowns. Automated drift alarms and a hosted monitoring service are not implemented.

Historical observations older than 60 days at prediction time produce `unavailable` status; no route history produces `degraded`; corrupt/missing model bytes fall back to the historical-frequency baseline. Demo mode remains visible even when fallback occurs. Tune freshness policy only with documented source cadence evidence.

## Recovery and rollback

- Failed ingestion: retain Bronze and retry. Schema failures require an adapter fix and regression test.
- Failed batch validation: current publication remains intact; fix inputs and rerun.
- Corrupt model artifact: predictions expose `degraded` fallback. Restore the trusted artifact or release an earlier version.
- Roll back: `ttc-pipeline rollback --version PREVIOUS_VERSION`, then explicitly republish the required dates. Changing the model pointer alone does not rewrite predictions.
- Stop local services: `docker compose down`. Do not add `--volumes` unless intentionally removing the stored database.

## API

`/health`, `/ready`, `/predictions?date=...&route=...&limit=...&offset=...`, `/risk-ranking?date=...&top_k=...`, `/model-info?date=...`, and `/docs`.

Prediction responses include UTC target boundaries, probability, risk level, version, prediction/feature cutoff, status and mode. Query sizes are bounded; internal errors return a generic dependency-unavailable response. Public cloud deployment requires an explicitly chosen host, access policy and operational configuration.
