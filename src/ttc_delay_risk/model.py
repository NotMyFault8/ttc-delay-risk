"""Temporal model comparison, sealed final test, and versioned artifacts."""

import hashlib
import json
import pickle
from pathlib import Path
import numpy as np
from catboost import CatBoostClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, brier_score_loss
from .features import build, validate, stamp, FEATURE_NAMES
from .pipeline import atomic_json


def metrics(rows, y, probabilities, k=5):
    daily = []
    for day in sorted({r["date"] for r in rows}):
        indices = [i for i, r in enumerate(rows) if r["date"] == day]
        top = sorted(
            indices,
            key=lambda i: (-probabilities[i], rows[i]["route_id"], rows[i]["start"]),
        )[:k]
        positives = sum(y[i] for i in indices)
        daily.append(
            {
                "date": day,
                "precision_at_k": float(sum(y[i] for i in top) / len(top)),
                "recall_at_k": (
                    float(sum(y[i] for i in top) / positives) if positives else None
                ),
            }
        )
    calibration = []
    for lo in np.linspace(0, 0.9, 10):
        idx = [
            i
            for i, p in enumerate(probabilities)
            if lo <= p < lo + 0.1 or (lo > 0.89 and p == 1)
        ]
        if idx:
            calibration.append(
                {
                    "lower": float(lo),
                    "count": len(idx),
                    "predicted": float(np.mean(probabilities[idx])),
                    "observed": float(np.mean(y[idx])),
                }
            )
    return {
        "average_precision": (
            float(average_precision_score(y, probabilities)) if sum(y) else None
        ),
        "brier": float(brier_score_loss(y, probabilities)),
        "k": k,
        "precision_at_k": float(np.mean([d["precision_at_k"] for d in daily])),
        "recall_at_k": (
            float(
                np.mean(
                    [d["recall_at_k"] for d in daily if d["recall_at_k"] is not None]
                )
            )
            if sum(y)
            else None
        ),
        "daily": daily,
        "calibration": calibration,
    }


def train(rows, directory, demo=False):
    validate(rows)
    rows = sorted(
        [r for r in rows if r["label"] is not None],
        key=lambda r: (r["date"], r["route_id"], r["start"]),
    )
    if len({r["date"] for r in rows}) < 60:
        raise ValueError("At least 60 service dates required")
    days = sorted({r["date"] for r in rows})
    cut1, cut2 = days[int(len(days) * 0.6)], days[int(len(days) * 0.8)]
    candidates = {
        "logistic": lambda: make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=1000, random_state=42, solver="liblinear"),
        ),
        "catboost": lambda: CatBoostClassifier(
            iterations=80,
            depth=4,
            learning_rate=0.05,
            random_seed=42,
            verbose=False,
            allow_writing_files=False,
            thread_count=2,
        ),
    }
    X = build(rows, rows)
    y = np.array([r["label"] for r in rows])

    def evaluate_window(start, end):
        validation = [i for i, r in enumerate(rows) if start <= r["date"] < end]
        cutoff = min(stamp(rows[i]["prediction_time"]) for i in validation)
        training = [
            i
            for i, r in enumerate(rows)
            if r["date"] < start and stamp(r["available_at"]) <= cutoff
        ]
        if len(set(y[training])) < 2:
            raise ValueError("Training needs both classes")
        predictions, fitted = {"baseline": X[validation, 6]}, {}
        for name, factory in candidates.items():
            fitted[name] = factory().fit(X[training], y[training])
            predictions[name] = fitted[name].predict_proba(X[validation])[:, 1]
        results = {
            name: metrics([rows[i] for i in validation], y[validation], p)
            for name, p in predictions.items()
        }
        return results, fitted, validation, predictions, training

    folds = []
    for a, b in [(0.4, 0.5), (0.5, 0.6), (0.6, 0.8)]:
        result, _, _, _, _ = evaluate_window(
            days[int(len(days) * a)], days[int(len(days) * b)]
        )
        folds.append(result)
    # Model choice uses validation only. Final-test performance never changes this decision.
    validation = folds[-1]
    chosen = min(validation, key=lambda name: validation[name]["brier"])
    if (validation[chosen]["average_precision"] or 0) < (
        validation["baseline"]["average_precision"] or 0
    ):
        chosen = "baseline"
    _, _, validation_indices, validation_probabilities, _ = evaluate_window(cut1, cut2)
    for route in {rows[i]["route_id"] for i in validation_indices}:
        group = [
            j for j, i in enumerate(validation_indices) if rows[i]["route_id"] == route
        ]
        if len(group) >= 20:
            labels = y[[validation_indices[j] for j in group]]
            candidate_brier = brier_score_loss(
                labels, validation_probabilities[chosen][group]
            )
            baseline_brier = brier_score_loss(
                labels, validation_probabilities["baseline"][group]
            )
            if candidate_brier > baseline_brier + 0.05:
                chosen = "baseline"
    final, fitted, indices, predictions, training = evaluate_window(cut2, "9999-12-31")
    # Thresholds set on validation baseline/model probability quantiles, before test publication.
    _, _, _, vp, _ = evaluate_window(cut1, cut2)
    thresholds = np.quantile(vp[chosen], [0.5, 0.8]).tolist()
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    code_hash = hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
    ).hexdigest()
    version = digest[:8] + "-" + code_hash[:6] + ("-demo" if demo else "-real")
    report = {
        "mode": "synthetic_demo" if demo else "real_data",
        "rows": len(rows),
        "positive_rate": float(y.mean()),
        "feature_version": "v1",
        "features": FEATURE_NAMES,
        "dependencies": {
            name: __import__("importlib.metadata", fromlist=["version"]).version(name)
            for name in ["numpy", "scikit-learn", "catboost"]
        },
        "seed": 42,
        "code_sha256": code_hash,
        "data_sha256": digest,
        "version": version,
        "selected": chosen,
        "train_start": days[0],
        "train_end": max(rows[i]["date"] for i in training),
        "validation_start": cut1,
        "test_start": cut2,
        "test_end": days[-1],
        "thresholds": thresholds,
        "rolling_validation": folds,
        "final_test": final,
        "release_policy": "Minimum validation Brier with AP at least baseline and route Brier regression <= 0.05 (n>=20); no final-test selection",
        "group_results": {},
    }
    for route in sorted({rows[i]["route_id"] for i in indices}):
        ix = [j for j, i in enumerate(indices) if rows[i]["route_id"] == route]
        report["group_results"][route] = metrics(
            [rows[indices[j]] for j in ix],
            y[[indices[j] for j in ix]],
            predictions[chosen][ix],
        )
    destination = Path(directory) / version
    destination.mkdir(parents=True, exist_ok=True)
    atomic_json(destination / "report.json", report)
    artifact = {
        "model": None if chosen == "baseline" else fitted[chosen],
        "metadata": report,
    }
    data = pickle.dumps(artifact)
    (destination / "model.tmp").write_bytes(data)
    (destination / "model.tmp").replace(destination / "model.pkl")
    atomic_json(
        destination / "checksum.json", {"sha256": hashlib.sha256(data).hexdigest()}
    )
    return report


def predict(targets, history, directory, version):
    folder = Path(directory) / version
    metadata = json.loads((folder / "report.json").read_text())
    validate(targets)
    if any(r["date"] <= metadata["train_end"] for r in targets):
        raise ValueError("Model cannot predict within its training period")
    X = build(targets, history)
    status = "demo" if metadata["mode"] == "synthetic_demo" else "ok"
    try:
        data = (folder / "model.pkl").read_bytes()
        if (
            hashlib.sha256(data).hexdigest()
            != json.loads((folder / "checksum.json").read_text())["sha256"]
        ):
            raise ValueError("Artifact checksum mismatch")
        # Only load locally trained, trusted artifacts. Pickle is not an upload format.
        artifact = pickle.loads(data)
        p = (
            X[:, 6]
            if artifact["model"] is None
            else artifact["model"].predict_proba(X)[:, 1]
        )
    except (OSError, ValueError, pickle.UnpicklingError, EOFError):
        p, status = X[:, 6], "degraded"
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Invalid model probabilities")
    output = []
    for row, probability in zip(targets, p):
        item = {
            k: row[k] for k in ("route_id", "date", "start", "end", "prediction_time")
        }
        known = [
            r
            for r in history
            if r["label"] is not None
            and stamp(r["available_at"]) <= stamp(row["prediction_time"])
            and stamp(r["end"]) <= stamp(row["prediction_time"])
        ]
        row_status = status
        if (
            not known
            or (
                stamp(row["prediction_time"]) - max(stamp(r["end"]) for r in known)
            ).days
            > 60
        ):
            row_status = "unavailable"
        elif not any(r["route_id"] == row["route_id"] for r in known):
            row_status = "degraded"
        item.update(
            target_window_start=row["start"],
            target_window_end=row["end"],
            probability=float(probability),
            model_version=version,
            status=row_status,
            mode=metadata["mode"],
            feature_cutoff_time=row["prediction_time"],
            risk_level=(
                "high"
                if probability >= metadata["thresholds"][1]
                else "medium" if probability >= metadata["thresholds"][0] else "low"
            ),
        )
        output.append(item)
    return output
