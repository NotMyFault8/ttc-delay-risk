import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from ttc_delay_risk.gtfs import windows


class GTFSTests(unittest.TestCase):
    def test_calendar_exception_and_next_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(
                    "routes.txt", "route_id,route_short_name,route_type\nr1,102,3\n"
                )
                z.writestr("trips.txt", "route_id,service_id,trip_id\nr1,s1,t1\n")
                z.writestr(
                    "calendar_dates.txt",
                    "service_id,date,exception_type\ns1,20250101,1\n",
                )
                z.writestr(
                    "stop_times.txt",
                    "trip_id,arrival_time,departure_time\nt1,25:00:00,25:00:00\nt1,25:40:00,25:40:00\n",
                )
            rows = windows(
                path,
                date(2025, 1, 1),
                "2024-12-01T00:00:00+00:00",
                "2025-01-01T09:00:00+00:00",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["date"], "2025-01-02")
            self.assertEqual(rows[0]["hour"], 1)
            self.assertEqual(
                windows(
                    path,
                    date(2025, 1, 2),
                    "2024-12-01T00:00:00+00:00",
                    "2025-01-02T09:00:00+00:00",
                ),
                [],
            )
