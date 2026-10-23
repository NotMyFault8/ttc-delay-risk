import tempfile
import unittest
from pathlib import Path
from ttc_delay_risk.pipeline import archive, audit, local_timestamp, require_training_evidence

HEADER = 'Date,Line,Time,Code,Min Delay\n'
ROW = '2025-01-01,102 MARKHAM ROAD,02:15,MFESA,20\n'


class PipelineTests(unittest.TestCase):
    def test_duplicate_ingestion_and_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            first = archive(b'a', 'https://example.org/data', directory)
            manifest = (Path(directory) / 'bronze' / first / 'manifest.json').read_bytes()
            self.assertEqual(first, archive(b'a', 'https://example.org/data', directory))
            self.assertEqual(manifest, (Path(directory) / 'bronze' / first / 'manifest.json').read_bytes())
            self.assertNotEqual(first, archive(b'b', 'https://example.org/data', directory))

    def test_dst_quarantine(self):
        for day, clock in [('2025-11-02', '01:30'), ('2025-03-09', '02:30')]:
            with self.assertRaises(ValueError):
                local_timestamp(day, clock)

    def test_midnight(self):
        self.assertEqual(local_timestamp('2025-01-01', '00:00').hour, 5)

    def test_normalization_and_duplicate_retention(self):
        report, events, quarantine = audit((HEADER + ROW * 2).encode(), 'hash')
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['route_id'], '102')
        self.assertEqual(report['exact_duplicate_candidates'], 1)
        self.assertEqual(quarantine, [])
        self.assertIsNone(events[0]['available_at'])
        self.assertFalse(report['training_ready'])

    def test_invalid_values_and_lineage(self):
        payload = HEADER + ROW.replace(',20', ',-1')
        report, events, quarantine = audit(payload.encode(), 'hash')
        self.assertEqual(events, [])
        self.assertEqual(quarantine[0]['source_row'], 2)
        self.assertEqual(report['quarantined_rows'], 1)

    def test_schema_change(self):
        with self.assertRaisesRegex(ValueError, 'Schema'):
            audit(b'Date,Line\n2025-01-01,102\n', 'hash')

    def test_training_gate(self):
        with self.assertRaisesRegex(ValueError, 'coverage'):
            require_training_evidence(None, None, None)


if __name__ == '__main__':
    unittest.main()
