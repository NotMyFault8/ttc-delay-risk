"""Incident-conditional severity research model; never service-hour incidence risk.

python -m ttc_delay_risk.severity train --inputs FILE... --root data/severity
python -m ttc_delay_risk.severity predict --root data/severity --date YYYY-MM-DD
"""

import argparse
import hashlib
import json
import pickle
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from importlib.metadata import version as dependency_version
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from catboost import CatBoostClassifier
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

from .pipeline import atomic_json
from .severity_data import load_events

TARGET = "P(recorded Min Delay >= threshold | a TTC incident record, route, local calendar)"
FEATURES = ["route_id", "hour", "weekday", "month", "hour_sin", "hour_cos"]
TORONTO = ZoneInfo("America/Toronto")


def design(rows):
    # No observed duration, incident reason, vehicle or outcome-derived feature.
    return np.array([
        [r["route_id"], str(r["hour"]), str(date.fromisoformat(r["business_date"]).weekday()),
         str(date.fromisoformat(r["business_date"]).month),
         np.sin(2 * np.pi * r["hour"] / 24), np.cos(2 * np.pi * r["hour"] / 24)]
        for r in rows
    ], dtype=object)


def labels(rows, threshold):
    return np.array([int(r["delay_minutes"] >= threshold) for r in rows])


class FrequencyBaseline:
    """Training-only route/hour counts, shrunk toward route and global means."""

    def fit(self, X, y):
        self.prior = float(np.mean(y))
        self.route, self.window = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        for row, value in zip(X, y):
            for table, key in ((self.route, row[0]), (self.window, (row[0], row[1]))):
                table[key][0] += int(value)
                table[key][1] += 1
        self.route, self.window = dict(self.route), dict(self.window)
        return self

    def predict_proba(self, X):
        probabilities = []
        for row in X:
            positives, count = self.route.get(row[0], (0, 0))
            route_p = (positives + 50 * self.prior) / (count + 50)
            positives, count = self.window.get((row[0], row[1]), (0, 0))
            probabilities.append((positives + 30 * route_p) / (count + 30))
        p = np.array(probabilities)
        return np.column_stack([1 - p, p])


def factory(kind):
    if kind == "baseline":
        return FrequencyBaseline()
    if kind == "logistic":
        return make_pipeline(
            ColumnTransformer([("calendar", OneHotEncoder(handle_unknown="ignore"), [0, 1, 2, 3])]),
            LogisticRegression(max_iter=500, solver="liblinear", random_state=42),
        )
    return CatBoostClassifier(iterations=150, depth=5, learning_rate=0.05, random_seed=42,
                              cat_features=[0, 1, 2, 3], verbose=False,
                              allow_writing_files=False, thread_count=2)


def evaluate(y, p):
    if not len(y) or not np.isfinite(p).all():
        raise ValueError("Empty or nonfinite evaluation")
    bins = []
    for i in range(10):
        mask = (p >= i / 10) & ((p < (i + 1) / 10) if i < 9 else (p <= 1))
        if mask.any():
            bins.append({"lower": i / 10, "count": int(mask.sum()),
                         "predicted": float(p[mask].mean()), "observed": float(y[mask].mean())})
    return {"rows": len(y), "positive_rate": float(y.mean()),
            "brier": float(brier_score_loss(y, p)),
            "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "average_precision": float(average_precision_score(y, p)) if y.sum() else None,
            "roc_auc": float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
            "calibration": bins}


def split_dates(last_day):
    last = date.fromisoformat(last_day)
    # Last six calendar months are test, previous three validation.
    def first(months_back):
        ordinal = last.year * 12 + last.month - 1 - months_back
        return date(ordinal // 12, ordinal % 12 + 1, 1).isoformat()
    return first(8), first(5)


def fit_model(inputs, root, threshold=15.0, validation_start=None, test_start=None):
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("Threshold must be finite and positive")
    rows, sources = load_events(inputs)
    last = max(r["business_date"] for r in rows)
    default_val, default_test = split_dates(last)
    validation_start, test_start = validation_start or default_val, test_start or default_test
    if not min(r["business_date"] for r in rows) < validation_start < test_start <= last:
        raise ValueError("Invalid chronological boundaries")
    training = [r for r in rows if r["business_date"] < validation_start]
    validation = [r for r in rows if validation_start <= r["business_date"] < test_start]
    test = [r for r in rows if r["business_date"] >= test_start]
    for name, subset in [("train", training), ("validation", validation), ("test", test)]:
        if len(subset) < 100 or len({r["business_date"] for r in subset}) < 30 or len(set(labels(subset, threshold))) < 2:
            raise ValueError(f"{name} needs 100 incidents, 30 dates and both classes")
    Xv, yv = design(validation), labels(validation, threshold)
    # Compare inclusion of 2023 using validation only; schema changed in 2025.
    cohorts = {"combined": training}
    recent = [r for r in training if r["business_date"] >= "2025-01-01"]
    if len(recent) >= 100 and len(set(labels(recent, threshold))) == 2 and len(recent) < len(training):
        cohorts["since2025"] = recent
    validation_results = {}
    for cohort, sample in cohorts.items():
        for kind in ["baseline", "logistic", "catboost"]:
            model = factory(kind).fit(design(sample), labels(sample, threshold))
            validation_results[f"{kind}:{cohort}"] = evaluate(yv, model.predict_proba(Xv)[:, 1])
    selected = min(validation_results, key=lambda k: (validation_results[k]["brier"], k))
    kind, cohort = selected.split(":")
    # Seal choice before using test outcomes. Refit on train + validation for testing.
    fit_rows = [r for r in rows if r["business_date"] < test_start
                and (cohort == "combined" or r["business_date"] >= "2025-01-01")]
    heldout_model = factory(kind).fit(design(fit_rows), labels(fit_rows, threshold))
    ptest = heldout_model.predict_proba(design(test))[:, 1]
    ytest = labels(test, threshold)
    baseline = FrequencyBaseline().fit(design(fit_rows), labels(fit_rows, threshold))
    pbaseline = baseline.predict_proba(design(test))[:, 1]
    groups = {}
    for month in sorted({r["business_date"][:7] for r in test}):
        mask = np.array([r["business_date"].startswith(month) for r in test])
        groups[month] = evaluate(ytest[mask], ptest[mask])
    # Fixed selection is refitted on the snapshot for prospective scenario scores.
    prospective = [r for r in rows if cohort == "combined" or r["business_date"] >= "2025-01-01"]
    final_model = factory(kind).fit(design(prospective), labels(prospective, threshold))
    now = datetime.now(timezone.utc).isoformat()
    data_hash = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    code_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    spec = {"threshold_minutes": threshold, "validation_start": validation_start, "test_start": test_start,
            "data_sha256": data_hash, "code_sha256": code_hash}
    version = "severity-" + hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16] + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    report = {**spec, "version": version, "target": TARGET, "mode": "real_data_conditional_severity_research",
              "created_at": now, "features": FEATURES, "selected": selected, "sources": sources,
              "rows": len(rows), "by_year": dict(Counter(r["business_date"][:4] for r in rows)),
              "train_rows": len(training), "validation_rows": len(validation), "test_rows": len(test),
              "event_date_start": min(r["business_date"] for r in rows), "event_date_end": last,
              "validation": validation_results, "test": evaluate(ytest, ptest),
              "test_baseline": evaluate(ytest, pbaseline), "test_by_month": groups,
              "prospective_fit_rows": len(prospective), "seed": 42,
              "dependencies": {n: dependency_version(n) for n in ["numpy", "scikit-learn", "catboost"]},
              "selection_policy": "Minimum validation Brier across model/cohort candidates; test never selects a model",
              "evaluation_scope": "Retrospective event-date holdout on current snapshots; historical publication times unknown, not an as-of operational backtest",
              "limitations": ["Conditional on a reported incident; not incident occurrence, punctuality or passenger risk",
                              "Historical route validity and schedule exposure are unknown",
                              "2023 lacks December; 2024 absent; source schemas and reporting mix changed",
                              "Zero recorded delay is below threshold, not proof of on-time service",
                              "Exact duplicate context is collapsed; indistinguishable genuine reports may be merged",
                              "No realtime inputs; no external calibration or prospective validation yet"]}
    folder = Path(root) / "registry" / version
    folder.mkdir(parents=True, exist_ok=False)
    artifact = {"model": final_model, "report": report,
                "route_counts": dict(Counter(r["route_id"] for r in prospective)),
                "route_hour_counts": dict(Counter((r["route_id"], r["hour"]) for r in prospective)),
                "recent_routes": sorted({r["route_id"] for r in prospective if r["business_date"] >= (date.fromisoformat(last) - timedelta(days=89)).isoformat()})}
    payload = pickle.dumps(artifact)
    (folder / "model.pkl").write_bytes(payload)
    atomic_json(folder / "checksum.json", {"sha256": hashlib.sha256(payload).hexdigest()})
    atomic_json(folder / "report.json", report)
    atomic_json(Path(root) / "latest.json", {"version": version, "status": "research_candidate"})
    return report


def predict_scenarios(root, target_date, routes=None, version=None, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Prediction time must be timezone-aware")
    version = version or json.loads((Path(root) / "latest.json").read_text())["version"]
    if Path(version).name != version:
        raise ValueError("Invalid version")
    folder = Path(root) / "registry" / version
    payload = (folder / "model.pkl").read_bytes()
    if hashlib.sha256(payload).hexdigest() != json.loads((folder / "checksum.json").read_text())["sha256"]:
        raise ValueError("Model checksum mismatch")
    # Local training artifacts only. Pickle is never an upload API.
    artifact = pickle.loads(payload)
    report = artifact["report"]
    if now < datetime.fromisoformat(report["created_at"]):
        raise ValueError("Model did not exist at prediction time")
    day = date.fromisoformat(target_date)
    if target_date <= report["event_date_end"] or datetime.combine(day, time(), TORONTO) <= now:
        raise ValueError("Scenario date must be wholly in the future and after training data")
    targets = [{"route_id": str(route), "hour": hour, "business_date": target_date}
               for route in sorted(set(routes or artifact["recent_routes"])) for hour in range(24)]
    probabilities = artifact["model"].predict_proba(design(targets))[:, 1]
    result = []
    for row, probability in zip(targets, probabilities):
        count = artifact["route_counts"].get(row["route_id"], 0)
        result.append({**row, "conditional_severe_delay_probability": float(probability),
                       "threshold_minutes": report["threshold_minutes"], "condition": "a TTC incident is recorded",
                       "prediction_time": now.isoformat(), "model_version": version,
                       "training_event_end": report["event_date_end"], "route_training_records": count,
                       "route_hour_training_records": artifact["route_hour_counts"].get((row["route_id"], row["hour"]), 0),
                       "route_service_verified": False,
                       "status": "unknown_route" if not count else "low_support" if count < 100 else "research_scenario"})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["train", "predict"])
    parser.add_argument("--root", type=Path, default=Path("data/severity"))
    parser.add_argument("--inputs", nargs="+", type=Path)
    parser.add_argument("--threshold", type=float, default=15)
    parser.add_argument("--validation-start")
    parser.add_argument("--test-start")
    parser.add_argument("--date")
    parser.add_argument("--routes", nargs="+")
    parser.add_argument("--version")
    args = parser.parse_args()
    if args.operation == "train":
        if not args.inputs:
            parser.error("--inputs is required")
        report = fit_model(args.inputs, args.root, args.threshold, args.validation_start, args.test_start)
        print(json.dumps({"candidate": report["version"], "selected": report["selected"], "rows": report["rows"],
                          "test": report["test"], "report": str(args.root / "registry" / report["version"] / "report.json")}))
    else:
        if not args.date:
            parser.error("--date is required")
        result = predict_scenarios(args.root, args.date, args.routes, args.version)
        output = args.root / "predictions" / f"{args.date}-{result[0]['model_version']}.json"
        atomic_json(output, result)
        print(json.dumps({"count": len(result), "output": str(output), "target": TARGET}))


if __name__ == "__main__":
    # Stable pickle module name when invoked with python -m.
    from ttc_delay_risk.severity import main as entrypoint
    entrypoint()
