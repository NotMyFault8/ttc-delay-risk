"""Airflow orchestration for the atomic TTC bus risk prediction batch."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from airflow import DAG
from airflow.operators.bash import BashOperator


PROJECT_ROOT = "/opt/ttc-delay-risk"
TORONTO = ZoneInfo("America/Toronto")
TARGET_DATE = (
    "{{ (dag_run.logical_date if dag_run.external_trigger else "
    "data_interval_end).in_timezone('America/Toronto').strftime('%Y-%m-%d') }}"
)

default_args = {
    "owner": "ttc-risk",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(hours=2),
}

with DAG(
    dag_id="ttc_delay_risk_daily",
    description="Validate inputs and atomically publish the daily TTC bus risk batch",
    schedule="30 3 * * *",
    start_date=datetime(2025, 1, 1, tzinfo=TORONTO),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["ttc", "batch-ml", "production"],
) as dag:
    preflight = BashOperator(
        task_id="preflight",
        append_env=True,
        bash_command=f"""
set -euo pipefail
project_root="${{TTC_PROJECT_ROOT:-{PROJECT_ROOT}}}"
data_root="${{TTC_DATA_ROOT:-$project_root/data}}"
dataset="${{TTC_DATASET:-$data_root/production-windows.json}}"
test -x "$project_root/.venv/bin/ttc-pipeline"
test -r "$dataset"
test -r "$data_root/registry/release.json"
test -n "${{DATABASE_URL:-}}"
""",
    )

    publish = BashOperator(
        task_id="predict_and_publish",
        append_env=True,
        bash_command=f"""
set -euo pipefail
project_root="${{TTC_PROJECT_ROOT:-{PROJECT_ROOT}}}"
data_root="${{TTC_DATA_ROOT:-$project_root/data}}"
dataset="${{TTC_DATASET:-$data_root/production-windows.json}}"
"$project_root/.venv/bin/ttc-pipeline" predict \
  --root "$data_root" \
  --dataset "$dataset" \
  --date "{TARGET_DATE}" \
  --publish
""",
    )

    preflight >> publish

