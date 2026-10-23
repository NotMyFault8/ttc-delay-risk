"""Audit local or remote source snapshots without modifying previous versions."""

import argparse
import json
from pathlib import Path
from .pipeline import archive, atomic_json, audit, fetch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--url")
    parser.add_argument("--output", type=Path, default=Path("data"))
    args = parser.parse_args()
    payload = args.file.read_bytes() if args.file else fetch(args.url)
    digest = archive(payload, args.url or args.file.name, args.output)
    report, events, quarantine = audit(payload, digest)
    destination = args.output / "silver" / digest
    atomic_json(destination / "events.json", events)
    atomic_json(destination / "quarantine.json", quarantine)
    atomic_json(destination / "audit.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
