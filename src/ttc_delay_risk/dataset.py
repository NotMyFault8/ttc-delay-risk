"""Build dated service windows and labels from reviewed source manifests."""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .gtfs import windows, label_windows
from .features import validate, stamp
from .pipeline import atomic_json


def assemble(manifest, events, coverage, start, end):
    result = []
    day = start
    while day <= end:
        cutoff = (
            datetime.combine(day, datetime.min.time())
            .replace(hour=4, tzinfo=ZoneInfo("America/Toronto"))
            .astimezone(timezone.utc)
        )
        merged = {}
        for service_day in [day - timedelta(days=1), day]:
            eligible = [
                s
                for s in manifest
                if s["start_date"] <= str(service_day) <= s["end_date"]
                and stamp(s["available_at"]) <= cutoff
                and s.get("reference")
            ]
            if not eligible:
                raise ValueError("No verified as-of schedule for " + str(service_day))
            schedule = max(eligible, key=lambda s: stamp(s["available_at"]))
            for row in windows(
                schedule["path"],
                service_day,
                schedule["available_at"],
                cutoff.isoformat(),
            ):
                if row["date"] != str(day):
                    continue
                key = row["route_id"], row["start"]
                if key in merged:
                    merged[key]["scheduled_trips"] += row["scheduled_trips"]
                else:
                    merged[key] = row
        result.extend(label_windows(list(merged.values()), events, coverage))
        day += timedelta(days=1)
    validate(result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["schedules", "events", "coverage", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument(
        "--codes",
        nargs="+",
        required=True,
        help="Reviewed incident codes included in labels",
    )
    a = p.parse_args()
    events = [r for r in json.loads(a.events.read_text()) if r["code"] in a.codes]
    rows = assemble(
        json.loads(a.schedules.read_text()),
        events,
        json.loads(a.coverage.read_text()),
        a.start,
        a.end,
    )
    atomic_json(a.output, rows)
    print(
        json.dumps(
            {
                "windows": len(rows),
                "unknown_labels": sum(r["label"] is None for r in rows),
            }
        )
    )


if __name__ == "__main__":
    main()
