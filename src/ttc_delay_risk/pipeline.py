"""Immutable ingestion and conservative normalization of the 2025+ CSV feed.

Source rows retain their lineage. Ambiguous local timestamps are quarantined,
not silently assigned to a daylight-saving fold. No negative labels are inferred.
"""
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
REQUIRED = {"Date", "Line", "Time", "Code", "Min Delay"}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def fetch(url, attempts=3):
    """Bounded network retries; failures leave earlier snapshots intact."""
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS sources are supported")
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def archive(payload, source_url, root):
    """Content addressing makes repeated ingestion idempotent."""
    digest = hashlib.sha256(payload).hexdigest()
    folder = Path(root) / "bronze" / digest
    folder.mkdir(parents=True, exist_ok=True)
    data = folder / "source.csv"
    if not data.exists():
        temporary = folder / "source.tmp"
        temporary.write_bytes(payload)
        temporary.replace(data)
    now = datetime.now(timezone.utc).isoformat()
    manifest = folder / "manifest.json"
    if not manifest.exists():
        atomic_json(manifest, {
            "source_url": source_url, "content_hash": digest,
            "first_seen_at": now, "retrieved_at": now,
            "bytes": len(payload), "historical_available_at": None,
            "parser_version": "csv-2025-v1",
        })
    return digest


def local_timestamp(day, clock):
    naive = datetime.fromisoformat(day[:10] + "T" + clock)
    candidates = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=TORONTO, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(TORONTO).replace(tzinfo=None) == naive:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError("ambiguous_or_nonexistent_local_time")
    return candidates.pop()


def normalize(row, row_number, source_hash):
    match = re.fullmatch(r"\s*(\d+)(?:\s+.*)?", row["Line"])
    if not match or int(match[1]) == 0:
        raise ValueError("invalid_route")
    delay = float(row["Min Delay"])
    if not 0 <= delay < float("inf"):
        raise ValueError("invalid_delay")
    timestamp = local_timestamp(row["Date"], row["Time"])
    if not row["Code"].strip():
        raise ValueError("missing_code")
    return {
        "route_id": str(int(match[1])), "event_time": timestamp.isoformat(),
        "business_date": row["Date"][:10], "code": row["Code"],
        "delay_minutes": delay, "source_hash": source_hash,
        "source_row": row_number, "available_at": None,
    }


def audit(payload, source_hash):
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    columns = reader.fieldnames or []
    missing = REQUIRED - set(columns)
    if missing:
        raise ValueError("Schema missing required fields: " + ", ".join(sorted(missing)))
    valid, quarantine = [], []
    blank = Counter()
    signatures = Counter()
    for number, row in enumerate(reader, start=2):
        for key, value in row.items():
            if not value:
                blank[str(key)] += 1
        # Source-generated IDs are excluded from the duplicate diagnostic.
        signature = tuple((key, value) for key, value in row.items() if key != "_id")
        signatures[signature] += 1
        try:
            valid.append(normalize(row, number, source_hash))
        except (ValueError, TypeError, KeyError) as error:
            quarantine.append({"source_row": number, "reason": str(error), "raw": row})
    dates = [row["business_date"] for row in valid]
    report = {
        "source_hash": source_hash, "columns": columns,
        "rows": len(valid) + len(quarantine), "valid_rows": len(valid),
        "quarantined_rows": len(quarantine), "blank_counts": dict(blank),
        "exact_duplicate_candidates": sum(count - 1 for count in signatures.values()),
        "duplicate_policy": "Retain all source rows; candidates are diagnostics only",
        "date_min": min(dates, default=None), "date_max": max(dates, default=None),
        "routes": len({row["route_id"] for row in valid}),
        "quarantine_reasons": dict(Counter(row["reason"] for row in quarantine)),
        "training_ready": False,
        "blocking_requirements": ["Verified event coverage", "Historical GTFS validity",
                                  "Historical publication availability"],
    }
    return report, valid, quarantine


def require_training_evidence(coverage, schedule, availability):
    """Fail closed until explicitly reviewed source evidence is supplied."""
    for name, evidence in (("coverage", coverage), ("schedule", schedule),
                           ("availability", availability)):
        if not evidence or not evidence.get("verified") or not evidence.get("reference"):
            raise ValueError("Training blocked: missing verified " + name)
