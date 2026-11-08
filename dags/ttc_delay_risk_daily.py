"""Opt-in daily publication of the reviewed legacy service-window risk model."""

from datetime import timedelta

import pendulum
from airflow.sdk import DAG
from airflow.providers.standard.operators.bash import BashOperator


# Manual runs must supply a logical date; interval inference can select the prior day.
TARGET_DATE = (
    "{{ (dag_run.logical_date if dag_run.run_type == 'manual' else "
    "data_interval_end).in_timezone('America/Toronto').strftime('%Y-%m-%d') }}"
)
PREAMBLE = """
set -euo pipefail
pipeline="${TTC_PIPELINE:-/home/airflow/ttc-venv/bin/ttc-pipeline}"
data_root="${TTC_DATA_ROOT:-/opt/airflow/project/data/runtime}"
dataset="${TTC_DATASET:-$data_root/production-windows.json}"
export DATABASE_URL="${TTC_PUBLISH_DATABASE_URL:?Set TTC_PUBLISH_DATABASE_URL before enabling daily publication}"
"""

with DAG(
    dag_id="ttc_delay_risk_daily",
    description="Validate reviewed inputs and atomically publish the daily service-window risk batch",
    schedule="30 3 * * *",
    start_date=pendulum.datetime(2025, 1, 1, tz="America/Toronto"),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    default_args={
        "owner": "ttc-risk",
        "depends_on_past": False,
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(hours=2),
    },
    tags=["ttc", "batch-ml", "publication"],
) as dag:
    preflight = BashOperator(
        task_id="preflight",
        append_env=True,
        bash_command=PREAMBLE + """
test -x "$pipeline"
test -r "$dataset"
test -r "$data_root/registry/release.json"
""",
    )

    publish = BashOperator(
        task_id="predict_and_publish",
        append_env=True,
        env={"TTC_TARGET_DATE": TARGET_DATE},
        bash_command=PREAMBLE + """
"$pipeline" predict \
  --root "$data_root" \
  --dataset "$dataset" \
  --date "$TTC_TARGET_DATE" \
  --publish
""",
    )

    preflight >> publish
