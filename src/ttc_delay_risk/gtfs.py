"""Generate active bus route-hours from a dated static GTFS snapshot.

GTFS times use noon minus twelve hours on the service date, per specification.
Frequencies-based service is rejected until expanded explicitly.
"""

import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def seconds(value):
    h, m, s = map(int, value.split(":"))
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError("Invalid GTFS time")
    return 3600 * h + 60 * m + s


def windows(path, service_date, available_at, prediction_time):
    with zipfile.ZipFile(path) as archive:

        def table(name):
            if name not in archive.namelist():
                return []
            return list(
                csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig")))
            )

        if table("frequencies.txt"):
            raise ValueError("Frequency-based GTFS requires explicit expansion")
        day = service_date.strftime("%Y%m%d")
        weekday = service_date.strftime("%A").lower()
        active = {
            r["service_id"]
            for r in table("calendar.txt")
            if r["start_date"] <= day <= r["end_date"] and r[weekday] == "1"
        }
        for r in table("calendar_dates.txt"):
            if r["date"] == day:
                if r["exception_type"] == "1":
                    active.add(r["service_id"])
                else:
                    active.discard(r["service_id"])
        routes = {
            r["route_id"]: r["route_short_name"]
            for r in table("routes.txt")
            if r["route_type"] == "3"
        }
        trips = {
            r["trip_id"]: routes[r["route_id"]]
            for r in table("trips.txt")
            if r["service_id"] in active and r["route_id"] in routes
        }
        bounds = {}
        for r in table("stop_times.txt"):
            if r["trip_id"] in trips:
                values = [
                    seconds(r[k]) for k in ("arrival_time", "departure_time") if r[k]
                ]
                if values:
                    lo, hi = bounds.get(r["trip_id"], (min(values), max(values)))
                    bounds[r["trip_id"]] = min(lo, min(values)), max(hi, max(values))
        noon = datetime.combine(service_date, datetime.min.time()).replace(
            hour=12, tzinfo=ZoneInfo("America/Toronto")
        )
        origin = noon.astimezone(timezone.utc) - timedelta(hours=12)
        grouped = {}
        for trip, (lo, hi) in bounds.items():
            start = origin + timedelta(seconds=lo)
            end = origin + timedelta(seconds=max(hi, lo + 1))
            hour = start.replace(minute=0, second=0, microsecond=0)
            while hour < end:
                grouped.setdefault((trips[trip], hour), set()).add(trip)
                hour += timedelta(hours=1)
        return [
            {
                "route_id": route,
                "start": start.isoformat(),
                "end": (start + timedelta(hours=1)).isoformat(),
                "hour": start.astimezone(ZoneInfo("America/Toronto")).hour,
                "date": start.astimezone(ZoneInfo("America/Toronto"))
                .date()
                .isoformat(),
                "scheduled_trips": len(ids),
                "schedule_available_at": available_at,
                "prediction_time": prediction_time,
                "label": None,
                "available_at": None,
                "coverage_verified": False,
            }
            for (route, start), ids in sorted(grouped.items())
            if start >= datetime.fromisoformat(prediction_time)
        ]


def label_windows(candidates, events, coverage):
    """Coverage ledger entries need a reviewed reference and publication cutoff."""
    output = []
    for candidate in candidates:
        row = dict(candidate)
        evidence = coverage.get(row["date"], {})
        if evidence.get("verified") and evidence.get("reference"):
            row["coverage_verified"] = True
            row["available_at"] = evidence["available_at"]
            row["label"] = int(
                any(
                    e["route_id"] == row["route_id"]
                    and datetime.fromisoformat(row["start"])
                    <= datetime.fromisoformat(e["event_time"])
                    < datetime.fromisoformat(row["end"])
                    for e in events
                )
            )
        output.append(row)
    return output
