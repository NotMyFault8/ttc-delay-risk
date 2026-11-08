"""Run with the real Airflow installation inside Dockerfile.airflow."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

import pendulum
from airflow.models.dagbag import DagBag
from airflow.timetables.base import TimeRestriction


class AirflowDagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bag = DagBag(dag_folder="/opt/airflow/dags", include_examples=False)

    def test_all_dags_import_and_daily_publication_is_opt_in(self):
        self.assertEqual(self.bag.import_errors, {})
        self.assertTrue({"ttc_delay_risk_pipeline", "ttc_delay_risk_daily", "ttc_demo"} <= self.bag.dags.keys())
        dag = self.bag.dags["ttc_delay_risk_daily"]
        self.assertTrue(dag.is_paused_upon_creation)
        self.assertFalse(dag.catchup)
        self.assertEqual(dag.max_active_runs, 1)
        self.assertEqual(dag.get_task("preflight").downstream_task_ids, {"predict_and_publish"})
        self.assertEqual(dag.get_task("predict_and_publish").retries, 2)

    def render_publish(self, run_type, logical_date, interval_end):
        task = deepcopy(self.bag.dags["ttc_delay_risk_daily"].get_task("predict_and_publish"))
        task.render_template_fields({
            "dag_run": SimpleNamespace(run_type=run_type, logical_date=logical_date),
            "data_interval_end": interval_end,
        })
        return task

    def test_scheduled_and_manual_service_dates_across_dst(self):
        for day in ("2025-03-09", "2025-11-02"):
            midnight = pendulum.parse(day, tz="America/Toronto")
            end = midnight.add(hours=5)
            with self.subTest(day=day):
                scheduled = self.render_publish("scheduled", midnight.subtract(days=1), end)
                manual = self.render_publish("manual", midnight, midnight.subtract(days=1))
                self.assertEqual(scheduled.env["TTC_TARGET_DATE"], day)
                self.assertEqual(manual.env["TTC_TARGET_DATE"], day)

    def test_timetable_stays_at_0330_toronto_across_dst(self):
        dag = self.bag.dags["ttc_delay_risk_daily"]
        for month, day in ((3, 8), (11, 1)):
            start = pendulum.datetime(2025, month, day, 3, 30, tz="America/Toronto")
            restriction = TimeRestriction(earliest=start, latest=None, catchup=True)
            previous = None
            for _ in range(3):
                info = dag.timetable.next_dagrun_info(
                    last_automated_data_interval=previous, restriction=restriction)
                local = info.run_after.in_timezone("America/Toronto")
                self.assertEqual((local.hour, local.minute), (3, 30))
                previous = info.data_interval

    def test_manual_run_without_logical_date_fails_closed(self):
        from jinja2 import UndefinedError
        with self.assertRaises(UndefinedError):
            self.render_publish("manual", None, pendulum.now("UTC"))

    def test_preflight_and_publish_command_with_real_shell(self):
        dag = self.bag.dags["ttc_delay_risk_daily"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data with spaces"
            (root / "registry").mkdir(parents=True)
            (root / "production-windows.json").write_text("[]")
            release = root / "registry/release.json"
            release.write_text("{}")
            capture = root / "arguments.txt"
            pipeline = root / "fake-pipeline"
            pipeline.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TTC_CAPTURE"\n')
            pipeline.chmod(0o755)
            env = {**os.environ, "TTC_PIPELINE": str(pipeline), "TTC_DATA_ROOT": str(root),
                   "TTC_CAPTURE": str(capture), "TTC_PUBLISH_DATABASE_URL": "postgresql://test"}
            env.pop("TTC_DATASET", None)
            command = dag.get_task("preflight").bash_command
            def preflight(environment):
                return subprocess.run(["bash", "-c", command], env=environment, capture_output=True).returncode
            self.assertEqual(preflight(env), 0)
            self.assertNotEqual(preflight({**env, "TTC_PUBLISH_DATABASE_URL": ""}), 0)
            release.unlink()
            self.assertNotEqual(preflight(env), 0)
            release.write_text("{}")
            date = pendulum.datetime(2025, 3, 9, tz="America/Toronto")
            task = self.render_publish("manual", date, date.subtract(days=1))
            subprocess.run(["bash", "-c", task.bash_command], env={**env, **task.env}, check=True)
            self.assertEqual(capture.read_text().splitlines(), [
                "predict", "--root", str(root), "--dataset", str(root / "production-windows.json"),
                "--date", "2025-03-09", "--publish",
            ])
