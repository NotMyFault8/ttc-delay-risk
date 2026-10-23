"""Point-in-time features shared by evaluation and batch inference."""

from datetime import datetime
import numpy as np

FEATURE_NAMES = [
    "hour_sin",
    "hour_cos",
    "weekday",
    "month",
    "scheduled_trips",
    "route_frequency",
    "route_hour_frequency",
    "history_count",
]


def stamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must have a UTC offset")
    return parsed


def validate(rows):
    keys = set()
    for row in rows:
        key = row["route_id"], row["start"]
        if key in keys:
            raise ValueError("Duplicate service window")
        keys.add(key)
        if not stamp(row["start"]) < stamp(row["end"]):
            raise ValueError("Invalid window")
        if stamp(row["prediction_time"]) > stamp(row["start"]):
            raise ValueError("Prediction occurs after window starts")
        if row["scheduled_trips"] < 0:
            raise ValueError("Negative scheduled trips")
        if row["label"] not in (None, 0, 1):
            raise ValueError("Invalid binary label")
        if row["label"] is not None and not row.get("coverage_verified"):
            raise ValueError("Unknown coverage cannot produce a training label")
        if row["label"] is not None and stamp(row["available_at"]) < stamp(row["end"]):
            raise ValueError("Label cannot be available before window ends")
        if stamp(row["schedule_available_at"]) > stamp(row["prediction_time"]):
            raise ValueError("Schedule not available at prediction time")


def build(targets, history):
    """Sweep availability boundaries once; no future label enters a feature."""
    from collections import defaultdict
    from zoneinfo import ZoneInfo

    known = sorted(
        [
            (max(stamp(r["available_at"]), stamp(r["end"])), i, r)
            for i, r in enumerate(history)
            if r["label"] is not None
        ],
        key=lambda item: (item[0], item[1]),
    )
    counts = defaultdict(lambda: [0, 0])
    total = positives = position = 0
    result = [None] * len(targets)
    for index, target in sorted(
        enumerate(targets), key=lambda item: stamp(item[1]["prediction_time"])
    ):
        cutoff = stamp(target["prediction_time"])
        while position < len(known) and known[position][0] <= cutoff:
            row = known[position][2]
            hour = stamp(row["start"]).astimezone(ZoneInfo("America/Toronto")).hour
            for key in [(row["route_id"],), (row["route_id"], hour)]:
                counts[key][0] += row["label"]
                counts[key][1] += 1
            positives += row["label"]
            total += 1
            position += 1
        prior = (positives + 1) / (total + 2)
        local = stamp(target["start"]).astimezone(ZoneInfo("America/Toronto"))
        route = counts[(target["route_id"],)]
        same_hour = counts[(target["route_id"], local.hour)]
        smooth = lambda value: (value[0] + 10 * prior) / (value[1] + 10)
        result[index] = [
            np.sin(2 * np.pi * local.hour / 24),
            np.cos(2 * np.pi * local.hour / 24),
            local.weekday(),
            local.month,
            target["scheduled_trips"],
            smooth(route),
            smooth(same_hour),
            route[1],
        ]
    return np.asarray(result, dtype=float)
