"""Deterministic synthetic contract fixture. Never presented as observed TTC data."""

import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def generate():
    rng = random.Random(42)
    rows = []
    for day_index in range(182):
        day = date(2025, 1, 1) + timedelta(days=day_index)
        cutoff = datetime.combine(day, datetime.min.time()).replace(
            hour=4, tzinfo=ZoneInfo("America/Toronto")
        )
        for route in ["DEMO-A", "DEMO-B", "DEMO-C"]:
            for hour in [7, 8, 12, 17]:
                start = cutoff.replace(hour=hour).astimezone(timezone.utc)
                risk = (
                    0.07
                    + 0.18 * (hour in [7, 8, 17])
                    + 0.13 * (route == "DEMO-A")
                    + 0.04 * (day.weekday() < 5)
                )
                rows.append(
                    {
                        "route_id": route,
                        "date": str(day),
                        "hour": hour,
                        "start": start.isoformat(),
                        "end": (start + timedelta(hours=1)).isoformat(),
                        "prediction_time": cutoff.astimezone(timezone.utc).isoformat(),
                        "schedule_available_at": (
                            cutoff - timedelta(days=30)
                        ).isoformat(),
                        "scheduled_trips": 6 if hour == 12 else 12,
                        "coverage_verified": True,
                        "label": int(rng.random() < risk),
                        "available_at": (start + timedelta(days=7)).isoformat(),
                    }
                )
    return rows
