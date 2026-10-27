from datetime import timedelta
from pathlib import Path
import subprocess

import pendulum

from airflow.sdk import dag, task

PROJECT_ROOT = Path("/opt/airflow/project")


@dag(
    dag_id="ttc_demo",
    schedule=None,
    start_date=pendulum.datetime(
        2026,10,24, tz="America/Toronto"
    ),
    catchup=False,
    tags=["ttc_demo"]
)
def ttc_demo():

    @task(
        retries=1,
        retry_delay=timedelta(minutes=1),
    )
    def run_demo():

        subprocess.run(
            [
                "/home/airflow/ttc-venv/bin/ttc-pipeline",
                "demo",
                "--root",
                str(PROJECT_ROOT / "data/airflow-demo"),
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )

    run_demo()

ttc_demo()
