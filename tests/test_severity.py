import csv
import io
import hashlib
import json
import pickle
import tempfile
import unittest
import zipfile
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

from ttc_delay_risk.severity import FrequencyBaseline, design, labels, split_dates, predict_scenarios
from ttc_delay_risk.severity_data import load_events, workbook_rows


class SeverityTests(unittest.TestCase):
    def test_missing_hours_never_become_negative_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incidents.csv"
            with path.open("w") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Date", "Line", "Time", "Code", "Min Delay"])
                writer.writerows([
                    ["2025-01-01", "35 JANE", "08:00", "X", "15"],
                    ["2025-01-01", "35 JANE", "08:00", "X", "15"],
                    ["2025-01-02", "35 JANE", "08:00", "X", "0"],
                    ["2025-01-03", "", "08:00", "X", "20"],
                    ["2025-03-09", "35", "02:30", "X", "20"],
                ])
            rows, audit = load_events([path])
            self.assertEqual(len(rows), 2)
            self.assertEqual(labels(rows, 15).tolist(), [1, 0])
            self.assertEqual(audit[0]["duplicates"], 1)
            self.assertEqual(sum(audit[0]["quarantine_reasons"].values()), 2)
            self.assertTrue(all(r["available_at"] is None for r in rows))

    def test_features_ignore_outcomes_and_incident_reason(self):
        row = {"route_id": "35", "hour": 8, "business_date": "2026-01-02", "delay_minutes": 10, "code": "X"}
        changed = {**row, "delay_minutes": 999, "code": "Y", "available_at": "2030-01-01"}
        np.testing.assert_array_equal(design([row]), design([changed]))

    def test_baseline_does_not_update_on_inference(self):
        X = np.array([["35", "8"], ["35", "9"]], dtype=object)
        model = FrequencyBaseline().fit(X, np.array([1, 0]))
        original = model.predict_proba(X)
        unknown = model.predict_proba(np.array([["unknown", "0"]], dtype=object))
        self.assertEqual(unknown[0, 1], 0.5)
        np.testing.assert_array_equal(original, model.predict_proba(X))

    def test_calendar_splits(self):
        self.assertEqual(split_dates("2026-09-30"), ("2026-01-01", "2026-04-01"))

    def test_prospective_guard_and_conditional_output(self):
        model = FrequencyBaseline().fit(np.array([["35", "8"], ["35", "9"]], dtype=object), np.array([1, 0]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "registry/v1"
            folder.mkdir(parents=True)
            (root / "latest.json").write_text(json.dumps({"version": "v1"}))
            payload = pickle.dumps({"model": model, "report": {
                "created_at": "2026-10-27T07:00:00+00:00", "event_date_end": "2026-09-30", "threshold_minutes": 15},
                "route_counts": {"35": 2}, "route_hour_counts": {("35", 8): 1}, "recent_routes": ["35"]})
            (folder / "model.pkl").write_bytes(payload)
            (folder / "checksum.json").write_text(json.dumps({"sha256": hashlib.sha256(payload).hexdigest()}))
            now = datetime(2026, 10, 27, 8, tzinfo=timezone.utc)
            result = predict_scenarios(root, "2026-10-28", ["35", "999999"], now=now)
            self.assertEqual(len(result), 48)
            self.assertTrue(all(r["route_service_verified"] is False for r in result))
            self.assertTrue(all("probability" not in r and 0 <= r["conditional_severe_delay_probability"] <= 1 for r in result))
            self.assertEqual({r["status"] for r in result}, {"low_support", "unknown_route"})
            with self.assertRaisesRegex(ValueError, "future"):
                predict_scenarios(root, "2026-09-01", now=now)
            with self.assertRaisesRegex(ValueError, "did not exist"):
                predict_scenarios(root, "2026-10-28", now=datetime(2026, 10, 26, tzinfo=timezone.utc))
            (folder / "model.pkl").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checksum"):
                predict_scenarios(root, "2026-10-28", now=now)

    def test_xlsx_sparse_cells_and_serial_date(self):
        payload = io.BytesIO()
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with zipfile.ZipFile(payload, "w") as book:
            book.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="2023" r:id="rId1"/></sheets></workbook>')
            book.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            header = ''.join(f'<c r="{col}1" t="inlineStr"><is><t>{name}</t></is></c>' for col, name in zip('ABCDF', ['Date', 'Route', 'Time', 'Incident', 'Min Delay']))
            book.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData><row>{header}</row><row><c r="A2"><v>44927</v></c><c r="B2"><v>35</v></c><c r="C2"><v>0.5</v></c><c r="F2"><v>15</v></c></row></sheetData></worksheet>')
        row = list(workbook_rows(payload.getvalue()))[0]
        self.assertEqual(row["Date"], "2023-01-01")
        self.assertEqual(row["Time"], "12:00:00")
        self.assertEqual(row["Incident"], "")
        self.assertEqual(row["Min Delay"], "15")


if __name__ == "__main__":
    unittest.main()
