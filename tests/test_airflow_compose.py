"""Exercise Compose interpolation and inheritance without starting containers."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is required")
class AirflowComposeTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("AIRFLOW_", "COMPOSE_", "TTC_"))
        }
        self.env.update(
            POSTGRES_PASSWORD="testApplicationPassword",
            AIRFLOW_POSTGRES_PASSWORD="testMetadataPassword",
            AIRFLOW_API_SECRET_KEY="testApiSecret" * 8,
            AIRFLOW_JWT_SECRET="testJwtSecret" * 8,
        )

    def compose(self, env=None, combined=False):
        command = ["docker", "compose", "--env-file", os.devnull]
        if combined:
            command += ["-f", "compose.yaml"]
        command += ["-f", "compose.airflow.yaml", "config", "--format", "json"]
        return subprocess.run(command, cwd=ROOT, env=env or self.env,
                              text=True, capture_output=True, check=False)

    def test_shared_secrets_and_persistent_logs_in_both_deployments(self):
        for combined in (False, True):
            with self.subTest(combined=combined):
                result = self.compose(combined=combined)
                self.assertEqual(result.returncode, 0, result.stderr)
                services = json.loads(result.stdout)["services"]
                for name in ("airflow-init", "airflow-apiserver", "airflow-scheduler",
                             "airflow-dag-processor", "airflow-triggerer"):
                    service = services[name]
                    for option, variable in (
                        ("AIRFLOW__API__SECRET_KEY", "AIRFLOW_API_SECRET_KEY"),
                        ("AIRFLOW__API_AUTH__JWT_SECRET", "AIRFLOW_JWT_SECRET"),
                    ):
                        self.assertEqual(service["environment"][option], self.env[variable])
                    logs = [v for v in service["volumes"] if v["target"] == "/opt/airflow/logs"]
                    self.assertEqual(len(logs), 1)
                    self.assertEqual(logs[0]["type"], "volume")
                    self.assertEqual(logs[0]["source"], "airflow-logs")
                self.assertEqual(services["airflow-init"]["command"], ["db", "migrate"])
                self.assertEqual(services["airflow-init"]["restart"], "no")
                self.assertNotIn("airflow-webserver", services)

    def test_missing_and_empty_secrets_fail_before_startup(self):
        for variable in ("AIRFLOW_API_SECRET_KEY", "AIRFLOW_JWT_SECRET", "AIRFLOW_POSTGRES_PASSWORD"):
            for value in (None, ""):
                with self.subTest(variable=variable, value=value):
                    env = dict(self.env)
                    if value is None:
                        del env[variable]
                    else:
                        env[variable] = value
                    result = self.compose(env=env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(variable, result.stderr)
