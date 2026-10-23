import json
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from ttc_delay_risk.demo import generate
from ttc_delay_risk.features import build, validate
from ttc_delay_risk.gtfs import seconds, label_windows
from ttc_delay_risk.store import Store
from ttc_delay_risk.api import create_app


class SystemTests(unittest.TestCase):
    def test_future_labels_do_not_change_features(self):
        rows = generate()[:120]
        target = rows[-1]
        first = build([target], rows)
        changed = [
            (
                dict(r, label=1 - r["label"])
                if r["available_at"] > target["prediction_time"]
                else r
            )
            for r in rows
        ]
        self.assertTrue((first == build([target], changed)).all())

    def test_schedule_leakage_rejected(self):
        row = generate()[0]
        row["schedule_available_at"] = "2030-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "Schedule"):
            validate([row])

    def test_unknown_coverage_rejected(self):
        row = generate()[0]
        row["coverage_verified"] = False
        with self.assertRaisesRegex(ValueError, "coverage"):
            validate([row])

    def test_gtfs_after_midnight(self):
        self.assertEqual(seconds("25:30:00"), 91800)
        with self.assertRaises(ValueError):
            seconds("24:61:00")

    def test_unknown_label_and_start_boundary(self):
        row = generate()[0]
        row["label"] = None
        self.assertIsNone(label_windows([row], [], {})[0]["label"])
        evidence = {
            row["date"]: {
                "verified": True,
                "reference": "test fixture",
                "available_at": row["available_at"],
            }
        }
        event = {"route_id": row["route_id"], "event_time": row["end"]}
        self.assertEqual(label_windows([row], [event], evidence)[0]["label"], 0)
        event["event_time"] = row["start"]
        self.assertEqual(label_windows([row], [event], evidence)[0]["label"], 1)

    def test_staging_idempotency_and_api(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + str(Path(directory) / "db.sqlite")
            store = Store(url)
            row = {
                "route_id": "DEMO-A",
                "date": "2025-07-01",
                "start": "2025-07-01T12:00:00+00:00",
                "probability": 0.4,
                "status": "demo",
                "mode": "synthetic_demo",
                "model_version": "test",
            }
            first = store.publish([row])
            self.assertEqual(store.predictions(row["date"]), [])
            self.assertEqual(first, store.publish([row], activate=True))
            client = TestClient(create_app(url))
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 503)
            self.assertEqual(
                client.get("/predictions?date=2025-07-01").json()["total"], 1
            )
            self.assertEqual(
                client.get("/risk-ranking?date=2025-07-01&top_k=0").status_code, 422
            )
            with self.assertRaises(ValueError):
                store.publish([dict(row, probability=2)], activate=True)
            self.assertEqual(store.predictions(row["date"]), [row])
