"""Reproducible train, inference, staging, release and rollback entry points."""

import argparse
import os
import json
import time
import uuid
from pathlib import Path
from .pipeline import atomic_json, require_training_evidence
from .features import validate, stamp
from .model import train, predict
from .store import Store
from .demo import generate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command", choices=["demo", "train", "predict", "release", "rollback"]
    )
    p.add_argument("--root", type=Path, default=Path("data"))
    p.add_argument("--dataset", type=Path)
    p.add_argument("--evidence", type=Path)
    p.add_argument("--version")
    p.add_argument("--date")
    p.add_argument("--end-date")
    p.add_argument("--database-url")
    p.add_argument("--publish", action="store_true")
    args = p.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    store = Store(
        args.database_url
        or os.getenv("DATABASE_URL")
        or "sqlite:///" + str(args.root / "predictions.db")
    )
    run_id = str(uuid.uuid4())
    begin = time.monotonic()
    registry = args.root / "registry"
    pointer = registry / "release.json"
    try:
        if args.command in ["release", "rollback"]:
            if not args.version:
                raise ValueError("--version is required")
            report = json.loads((registry / args.version / "report.json").read_text())
            previous = (
                json.loads(pointer.read_text()).get("current")
                if pointer.exists()
                else None
            )
            atomic_json(
                pointer,
                {"current": args.version, "previous": previous, "mode": report["mode"]},
            )
            print(json.dumps({"released": args.version, "previous": previous}))
            return
        if args.command == "demo":
            rows = generate()
            atomic_json(args.root / "demo.json", rows)
            report = train(rows, registry, demo=True)
            atomic_json(
                pointer,
                {
                    "current": report["version"],
                    "previous": None,
                    "mode": "synthetic_demo",
                },
            )
            targets = [r for r in rows if r["date"] == "2025-07-01"]
            output = predict(targets, rows, registry, report["version"])
            batch = store.publish(output, activate=True)
            print(
                json.dumps(
                    {
                        "mode": "synthetic_demo",
                        "batch": batch,
                        "version": report["version"],
                        "report": str(registry / report["version"] / "report.json"),
                    }
                )
            )
        elif args.command == "train":
            if not args.dataset or not args.evidence:
                raise ValueError("--dataset and --evidence required")
            evidence = json.loads(args.evidence.read_text())
            require_training_evidence(
                evidence.get("coverage"),
                evidence.get("schedule"),
                evidence.get("availability"),
            )
            rows = json.loads(args.dataset.read_text())
            report = train(rows, registry)
            print(json.dumps({"candidate": report["version"], "published": False}))
        else:
            if not args.dataset or not args.date:
                raise ValueError("--dataset and --date required")
            rows = json.loads(args.dataset.read_text())
            validate(rows)
            targets = [
                r
                for r in rows
                if args.date <= r["date"] <= (args.end_date or args.date)
            ]
            if not targets:
                raise ValueError("No service windows for target date")
            version = args.version or json.loads(pointer.read_text())["current"]
            output = predict(targets, rows, registry, version)
            store.publish(output, activate=args.publish)
            print(json.dumps({"count": len(output), "published": args.publish}))
        store.log(
            run_id, {"status": "success", "elapsed_seconds": time.monotonic() - begin}
        )
    except Exception as exc:
        store.log(
            run_id,
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "elapsed_seconds": time.monotonic() - begin,
            },
        )
        raise


if __name__ == "__main__":
    main()
