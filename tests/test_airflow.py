import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeDAG:
    latest = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeDAG.latest = self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeBashOperator:
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.downstream = None
        self.created.append(self)

    def __rshift__(self, other):
        self.downstream = other
        return other


class AirflowDagTests(unittest.TestCase):
    def test_daily_dag_contract(self):
        FakeBashOperator.created = []
        airflow = types.ModuleType("airflow")
        airflow.DAG = FakeDAG
        operators = types.ModuleType("airflow.operators")
        bash = types.ModuleType("airflow.operators.bash")
        bash.BashOperator = FakeBashOperator
        modules = {
            "airflow": airflow,
            "airflow.operators": operators,
            "airflow.operators.bash": bash,
        }
        dag_path = (
            Path(__file__).parents[1]
            / "airflow"
            / "dags"
            / "ttc_delay_risk_daily.py"
        )
        with patch.dict(sys.modules, modules):
            namespace = runpy.run_path(str(dag_path))

        self.assertEqual(FakeDAG.latest.kwargs["schedule"], "30 3 * * *")
        self.assertFalse(FakeDAG.latest.kwargs["catchup"])
        self.assertEqual(FakeDAG.latest.kwargs["max_active_runs"], 1)
        self.assertEqual(
            [task.kwargs["task_id"] for task in FakeBashOperator.created],
            ["preflight", "predict_and_publish"],
        )
        command = FakeBashOperator.created[1].kwargs["bash_command"]
        self.assertIn("America/Toronto", command)
        self.assertIn("data_interval_end", command)
        self.assertIn("--publish", command)
        self.assertIs(FakeBashOperator.created[0].downstream, FakeBashOperator.created[1])
        self.assertIs(namespace["dag"], FakeDAG.latest)


if __name__ == "__main__":
    unittest.main()

