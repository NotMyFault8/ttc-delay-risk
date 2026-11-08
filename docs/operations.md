# Operations and reproducibility

## Verified locally

- 26 application and Compose tests passed with numerical runtime warnings treated as errors; five additional DAG tests passed inside the Airflow 3.1.5 image.
- Signed scheduler-log requests returned HTTP 200 before and after scheduler replacement; unsigned requests were rejected, and the marker remained in the shared log volume.
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

`Dockerfile.airflow`, `compose.airflow.yaml` and `dags/` form one Airflow **3.1.5** deployment. The existing `ttc_delay_risk_pipeline` DAG retains its 03:30 Toronto ingestion schedule and explicit training/prediction operations, including conditional severity. `ttc_demo` remains a manual synthetic demonstration. The separate `ttc_delay_risk_daily` DAG publishes the legacy service-window model; conditional-severity scenarios are not published as incidence probabilities.

Copy `.env.example` to `.env` if it does not exist. Set `AIRFLOW_POSTGRES_PASSWORD` to a local alphanumeric password. Generate two independent random values with `openssl rand -hex 32`, and set `AIRFLOW_API_SECRET_KEY` and `AIRFLOW_JWT_SECRET`. Keep these values stable across container replacements and supply the same `.env` to all Airflow services. Compose rejects missing or empty secrets. The API secret signs log requests; the JWT secret authenticates Airflow 3 execution API requests. Neither value belongs in Git or an image.

```sh
docker compose -f compose.airflow.yaml config --quiet
docker compose -f compose.airflow.yaml up -d --build
docker compose -f compose.airflow.yaml exec airflow-apiserver \
  airflow users create --username admin --firstname Air --lastname Flow \
  --role Admin --email admin@example.com
# The user-creation command prompts for a password; no default admin password is configured.
```

The UI binds to `127.0.0.1:8080`. Initialization must complete its database migration successfully before services start. The `airflow-data` volume retains inputs and artifacts. All Airflow services share the `airflow-logs` volume at `/opt/airflow/logs`, so completed-task logs survive scheduler replacement. Keep host clocks synchronized for signed log requests. These settings support the documented single-machine deployment, not a high-availability production service.

When upgrading an existing Airflow 3 deployment, retain its Compose project name and metadata database password (changing `POSTGRES_PASSWORD` does not rotate a password in an existing database volume). Replace the former local signing-key placeholders and reset any previously created `admin`/`admin` UI credential. When moving from the old PR's Airflow 2 stack, start a separate Compose project and fresh metadata volume, or follow Airflow's reviewed database upgrade procedure; do not silently reuse the same `airflow-postgres` volume across major versions. Rename the old `.env` variable `AIRFLOW_WEBSERVER_SECRET_KEY` to `AIRFLOW_API_SECRET_KEY` and add the independent JWT secret. The old `airflow/Dockerfile` and `airflow/dags/` layout is no longer used.

### Enable daily publication

The daily DAG is initially **paused**, disables catchup, permits one active run, retries twice and limits each task to two hours. It checks the executable, dataset, release pointer and publication database URL before invoking the existing atomic `ttc-pipeline predict --publish` path. The CLI run ledger remains the batch result record.

Before unpausing, place the reviewed rolling dataset at `/opt/airflow/project/data/runtime/production-windows.json` in the shared `airflow-data` volume, and train/review/release the real service-window model under `/opt/airflow/project/data/runtime/registry`. Explicitly set `TTC_PUBLISH_DATABASE_URL` in `.env`. For the application PostgreSQL service from `compose.yaml`, use `postgresql+psycopg2://ttc:YOUR_POSTGRES_PASSWORD@db:5432/ttc` and start the combined deployment:

```sh
docker compose -f compose.yaml -f compose.airflow.yaml up -d --build
# After verifying the dataset, release and publication database:
docker compose -f compose.yaml -f compose.airflow.yaml exec airflow-scheduler \
  airflow dags unpause ttc_delay_risk_daily
```

`TTC_PUBLISH_DATABASE_URL` is used only by the daily publisher; ingestion, demo and existing manual workflows retain their own storage behavior. Stop the systemd publication timer before enabling this DAG, and avoid manual publishers for the same database/date. The ingestion DAG does not generate the reviewed service-window dataset or release a model automatically.

Scheduled publications select the Toronto date of `data_interval_end`, including DST transitions. For a manual historical run, supply midnight Toronto time as its logical date; the manual path uses that date instead of the inferred interval end:

```sh
docker compose -f compose.airflow.yaml exec airflow-scheduler \
  airflow dags trigger --logical-date '2025-07-01T00:00:00-04:00' ttc_delay_risk_daily
```

A manual run without a logical date fails instead of silently selecting another service date. The model must predate the historical target, and triggering this DAG explicitly publishes the selected date.

### Airflow verification

Run `python -m unittest discover -s tests -p test_airflow_compose.py -v` for required-secret, inheritance and persistent-volume checks. The `airflow` CI job builds the actual image, imports all DAGs, verifies scheduled/manual dates across DST, executes the publisher command against a recording stub, and checks signed log reads before and after scheduler replacement. It also verifies that unsigned requests are rejected. The tests run in an isolated Compose project and never trigger publication against real data.

For the log checks in an isolated local test project after startup:

```sh
docker compose -f compose.airflow.yaml exec -T airflow-scheduler python - write < scripts/check_airflow_logs.py
docker compose -f compose.airflow.yaml exec -T airflow-apiserver python - read < scripts/check_airflow_logs.py
docker compose -f compose.airflow.yaml up -d --no-deps --force-recreate airflow-scheduler
docker compose -f compose.airflow.yaml exec -T airflow-apiserver python - read < scripts/check_airflow_logs.py
```

The templates under `deploy/` remain a lightweight systemd alternative. They require a service user, project installation, reviewed dataset and released model, and do not fetch coverage evidence automatically.

The `runs` table stores success/failure, elapsed time and error type. Inspect it alongside `batches` and `current_batches`. Monitor `/health` for the process and `/ready` for current production predictions. The source audit reports schema, blank counts, duplicate candidates and quarantine reasons. Model reports contain daily performance, calibration bins and per-route breakdowns. Automated drift alarms and a hosted monitoring service are not implemented.

Historical observations older than 60 days at prediction time produce `unavailable` status; no route history produces `degraded`; corrupt/missing model bytes fall back to the historical-frequency baseline. Demo mode remains visible even when fallback occurs. Tune freshness policy only with documented source cadence evidence.

## Recovery and rollback

- Failed ingestion: retain Bronze and retry. Schema failures require an adapter fix and regression test.
- Failed batch validation: current publication remains intact; fix inputs and rerun.
- Corrupt model artifact: predictions expose `degraded` fallback. Restore the trusted artifact or release an earlier version.
- Roll back: `ttc-pipeline rollback --version PREVIOUS_VERSION`, then explicitly republish the required dates. Changing the model pointer alone does not rewrite predictions.
- Stop the combined deployment: `docker compose -f compose.yaml -f compose.airflow.yaml down` (use only the Airflow file for the standalone stack). Keep the same project name. Do not add `--volumes` unless intentionally removing stored databases, artifacts and task logs.

## API

`/health`, `/ready`, `/predictions?date=...&route=...&limit=...&offset=...`, `/risk-ranking?date=...&top_k=...`, `/model-info?date=...`, and `/docs`.

Prediction responses include UTC target boundaries, probability, risk level, version, prediction/feature cutoff, status and mode. Query sizes are bounded; internal errors return a generic dependency-unavailable response. Public cloud deployment requires an explicitly chosen host, access policy and operational configuration.
