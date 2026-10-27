"""Ingest TTC delays daily; run severity scenarios or legacy batches on demand.

Trigger with DAG run configuration. Example prediction run:
{"operation":"predict","dataset":"/opt/airflow/project/data/windows.json",
 "root":"/opt/airflow/project/data/runtime","date":"2026-10-26"}

Candidate training additionally requires an evidence JSON file with reviewed,
verified coverage, schedule, and availability references. Training creates a
candidate only; release remains a separate, explicit operator action.

Incident-conditional severity uses train_severity/predict_severity operations,
raw inputs, and a separate research registry under ROOT/severity. It does not
claim service-hour incidence probability or publish to the legacy API.
"""

import json
import logging
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pendulum
from airflow.sdk import dag, task


PROJECT_ROOT = Path("/opt/airflow/project")
PIPELINE = "/home/airflow/ttc-venv/bin/ttc-pipeline"
DEFAULT_ROOT = PROJECT_ROOT / "data/runtime"
TTC_DATASET_API = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?"
    + urllib.parse.urlencode({"id": "ttc-bus-delay-data"})
)
TTC_DELAY_RESOURCE_ID = "b5725365-9252-4bfe-b6f4-cda7ddf74341"


def _run(command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
    )
    if completed.stdout:
        logging.info("Project command output:\n%s", completed.stdout.rstrip())
    if completed.returncode:
        if completed.stderr:
            logging.error("Project command error:\n%s", completed.stderr.rstrip())
        raise RuntimeError(
            f"{Path(command[0]).name} exited with status {completed.returncode}"
        )
    try:
        return json.loads(completed.stdout.strip())
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("ttc-pipeline did not return a JSON summary") from exc


@dag(
    dag_id="ttc_delay_risk_pipeline",
    description=(
        "Ingest the official TTC delay feed daily at 03:30 Toronto time; build "
        "candidate models or predict from prepared datasets on demand."
    ),
    schedule="30 3 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="America/Toronto"),
    catchup=False,
    max_active_runs=1,
    params={
        "operation": "ingest",
        "dataset": "",
        "root": str(DEFAULT_ROOT),
        "date": "",
        "end_date": "",
        "publish": False,
        "evidence": "",
        "inputs": [],
        "threshold": 15,
        "version": "",
    },
    tags=["ttc-delay-risk", "batch-ml"],
)
def ttc_delay_risk_pipeline():
    @task
    def validate_run_config(**context) -> dict:
        params = context["params"]
        operation = params.get("operation", "ingest")
        if operation not in {"ingest", "predict", "train_candidate", "train_severity", "predict_severity"}:
            raise ValueError(
                "operation must be ingest, predict, train_candidate, train_severity, or predict_severity"
            )
        root = Path(params.get("root") or DEFAULT_ROOT)
        config = {
            "operation": operation,
            "root": str(root),
            "publish": bool(params.get("publish", False)),
        }

        if operation == "ingest":
            return config

        if operation in {"train_severity", "predict_severity"}:
            if config["publish"]:
                raise ValueError("Conditional severity outputs are research scenarios, not published incidence risk")
            if operation == "train_severity":
                inputs = params.get("inputs", [])
                if not isinstance(inputs, list) or not inputs or not all(isinstance(p, str) and Path(p).is_file() for p in inputs):
                    raise ValueError("inputs must list existing CSV or XLSX files in the shared volume")
                config.update(inputs=inputs, threshold=float(params.get("threshold", 15)))
            else:
                target_date = params.get("date", "")
                date.fromisoformat(target_date)
                config.update(date=target_date, version=params.get("version", ""))
            return config

        dataset = Path(params.get("dataset", ""))
        if not dataset.is_file():
            raise FileNotFoundError(
                f"Prepared dataset JSON does not exist: {dataset}. "
                "Place it in the shared Airflow data volume."
            )
        config["dataset"] = str(dataset)

        if operation == "predict":
            target_date = params.get("date", "")
            end_date = params.get("end_date", "") or target_date
            if not target_date:
                raise ValueError("date is required for prediction")
            date.fromisoformat(target_date)
            date.fromisoformat(end_date)
            if end_date < target_date:
                raise ValueError("end_date must be on or after date")
            if not (root / "registry/release.json").is_file():
                raise FileNotFoundError(
                    f"No released model at {root / 'registry/release.json'}. "
                    "Train and explicitly release a model before prediction."
                )
            config.update({"date": target_date, "end_date": end_date})
        else:
            evidence = Path(params.get("evidence", ""))
            if not evidence.is_file():
                raise FileNotFoundError(
                    "evidence is required for candidate training and must point "
                    "to a reviewed evidence JSON in the shared data volume"
                )
            evidence_doc = json.loads(evidence.read_text())
            for name in ("coverage", "schedule", "availability"):
                item = evidence_doc.get(name, {})
                if not item.get("verified") or not item.get("reference"):
                    raise ValueError(
                        f"Training evidence {name} must be verified and cite a reference"
                    )
            config["evidence"] = str(evidence)

        return config

    @task.branch
    def choose_workflow(config: dict) -> str:
        if config["operation"] == "ingest":
            return "ingest_ttc_delays"
        if config["operation"] == "train_candidate":
            return "train_candidate"
        if config["operation"] in {"train_severity", "predict_severity"}:
            return "conditional_severity"
        return "predict_batch"

    @task
    def conditional_severity(config: dict) -> dict:
        operation = "train" if config["operation"] == "train_severity" else "predict"
        command = ["/home/airflow/ttc-venv/bin/python", "-m", "ttc_delay_risk.severity",
                   operation, "--root", str(Path(config["root"]) / "severity")]
        if operation == "train":
            command += ["--threshold", str(config["threshold"]), "--inputs", *config["inputs"]]
        else:
            command += ["--date", config["date"]]
            if config.get("version"):
                command += ["--version", config["version"]]
        return _run(command)

    @task
    def train_candidate(config: dict) -> dict:
        return _run(
            [
                PIPELINE,
                "train",
                "--root",
                config["root"],
                "--dataset",
                config["dataset"],
                "--evidence",
                config["evidence"],
            ]
        )

    @task
    def predict_batch(config: dict) -> dict:
        command = [
            PIPELINE,
            "predict",
            "--root",
            config["root"],
            "--dataset",
            config["dataset"],
            "--date",
            config["date"],
            "--end-date",
            config["end_date"],
        ]
        if config["publish"]:
            command.append("--publish")
        return _run(command)

    @task
    def ingest_ttc_delays(config: dict) -> dict:
        request = urllib.request.Request(
            TTC_DATASET_API, headers={"User-Agent": "ttc-delay-risk/0.1"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            metadata = json.load(response)
        if not metadata.get("success"):
            raise RuntimeError("Toronto Open Data CKAN metadata lookup failed")
        resources = metadata["result"].get("resources", [])
        resource = next(
            (item for item in resources if item.get("id") == TTC_DELAY_RESOURCE_ID),
            None,
        )
        if resource is None:
            resource = next(
                (
                    item for item in resources
                    if item.get("format", "").lower() == "csv"
                    and "delay" in (item.get("name", "") + item.get("url", "")).lower()
                ),
                None,
            )
        if not resource or not resource.get("url", "").startswith("https://"):
            raise RuntimeError("Could not find the official TTC delay CSV resource")
        logging.info(
            "Ingesting official TTC resource %s (%s)",
            resource.get("id"), resource.get("name"),
        )
        return _run(
            [
                "/home/airflow/ttc-venv/bin/ttc-risk",
                "--url", resource["url"],
                "--output", config["root"],
            ]
        )

    run_config = validate_run_config()
    branch = choose_workflow(run_config)
    training = train_candidate(run_config)
    prediction = predict_batch(run_config)
    ingestion = ingest_ttc_delays(run_config)
    severity = conditional_severity(run_config)
    branch >> [ingestion, training, prediction, severity]


ttc_delay_risk_pipeline()

