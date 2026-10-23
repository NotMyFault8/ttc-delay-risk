import json
import tempfile
import unittest
from pathlib import Path
from ttc_delay_risk.demo import generate
from ttc_delay_risk.model import train, predict
from ttc_delay_risk.store import Store


class MLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.rows = generate()
        cls.report = train(cls.rows, cls.root, demo=True)
        cls.targets = [r for r in cls.rows if r["date"] == "2025-07-01"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_three_models_and_sealed_test(self):
        self.assertEqual(
            set(self.report["final_test"]), {"baseline", "logistic", "catboost"}
        )
        self.assertLess(self.report["train_end"], self.report["test_start"])
        self.assertEqual(len(self.report["rolling_validation"]), 3)

    def test_inference_and_replay(self):
        result = predict(self.targets, self.rows, self.root, self.report["version"])
        self.assertEqual(
            result, predict(self.targets, self.rows, self.root, self.report["version"])
        )
        self.assertTrue(
            all(
                r["mode"] == "synthetic_demo" and 0 <= r["probability"] <= 1
                for r in result
            )
        )
        store = Store("sqlite:///" + str(self.root / "test.db"))
        self.assertEqual(store.publish(result, True), store.publish(result, True))
        self.assertEqual(len(store.predictions("2025-07-01")), 12)

    def test_model_corruption_falls_back(self):
        model = self.root / self.report["version"] / "model.pkl"
        original = model.read_bytes()
        try:
            model.write_bytes(b"corrupt")
            result = predict(self.targets, self.rows, self.root, self.report["version"])
            self.assertTrue(all(r["status"] == "degraded" for r in result))
        finally:
            model.write_bytes(original)

    def test_historical_model_leakage_rejected(self):
        with self.assertRaisesRegex(ValueError, "training period"):
            predict(self.rows[:12], self.rows, self.root, self.report["version"])
