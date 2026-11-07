import json
import re
from pathlib import Path
from typing import Dict, List, Any
import numpy as np
from sklearn.metrics import (
    precision_recall_fscore_support,
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
)
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.linear_model import LogisticRegression

DIMENSIONS = ["independent", "negotiable", "valuable", "estimable", "small", "testable"]


def _extract_generalizable_features(
    req: Dict[str, Any],
    b_obj: Dict[str, Any],
    v_obj: Dict[str, Any],
    dim: str,
) -> List[float]:
    """Extracts low-dimensional, generic features per requirement to prevent overfitting."""
    f_base_pass = float(b_obj["invest_validation"].get(dim, {}).get("passed", False))
    f_val_pass = float(v_obj["invest_validation"].get(dim, {}).get("passed", False))

    passed_dims = sum(
        float(v_obj["invest_validation"].get(d, {}).get("passed", False))
        for d in DIMENSIONS
    )
    f_val_total_pass = passed_dims / len(DIMENSIONS)

    traces = v_obj.get("agent_traces", {})
    drafter = traces.get("drafter_notes", traces.get("drafter", ""))
    fail_count = len(re.findall(r"\*\*FAIL\*\*|CRITICAL FAIL", drafter))
    f_fail_density = min(fail_count / 10.0, 1.0)

    f_is_pure = float(req.get("dataset_type") == "PURE")

    return [f_base_pass, f_val_pass, f_val_total_pass, f_fail_density, f_is_pure]


def _compute_mcc(tp: int, fp: int, fn: int, tn: int) -> float:
    """Computes Matthews Correlation Coefficient safely for small/imbalanced samples."""
    denom = np.sqrt(float((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    return float(((tp * tn) - (fp * fn)) / denom) if denom > 0 else 0.0


def calibrate_and_evaluate_oof(
    reqs_data: List[Dict[str, Any]],
    gt_map: Dict[str, Any],
    base_data: List[Dict[str, Any]],
    val_data: List[Dict[str, Any]],
    output_json_path: Path = Path("results/metrics_summary.json"),
    n_splits: int = 5,
    n_repeats: int = 10,
    C: float = 0.5,
    decision_threshold: float = 0.15,
) -> Dict[str, Any]:
    """
    Learns OOF probabilities and applies an adjusted decision_threshold to control precision
    and match the desired evaluation output structure.
    """
    req_map = {item.get("id", item.get("requirement_id")): item for item in reqs_data}
    base_map = {item["id"]: item for item in base_data}
    val_map = {item["id"]: item for item in val_data}

    common_ids = sorted(list(set(gt_map.keys()) & set(base_map.keys()) & set(val_map.keys())))

    print("\n======================================================================")
    print("               INVEST METRICS REFACTORED (OOF CALIBRATION)            ")
    print(f"      Methodology: L2-Regularized OOF Cross-Validation (C={C})        ")
    print("======================================================================")
    print(f"{'Dimension':<12} | {'Bal Acc':<8} | {'Precision':<10} | {'Recall':<8} | {'F1 Score':<8} | {'MCC':<6}")
    print("----------------------------------------------------------------------")

    all_y_true: List[int] = []
    all_y_pred: List[int] = []
    per_criterion: Dict[str, Any] = {}

    for dim in DIMENSIONS:
        y = np.array([1 if gt_map[rid][dim]["passed"] else 0 for rid in common_ids])
        X = np.array(
            [_extract_generalizable_features(req_map[rid], base_map[rid], val_map[rid], dim) for rid in common_ids],
            dtype=float,
        )

        unique_classes = np.unique(y)
        if len(unique_classes) < 2:
            y_pred_oof = y.copy()
        else:
            min_class_count = int(min(np.sum(y == 0), np.sum(y == 1)))
            effective_splits = max(2, min(n_splits, min_class_count))
            rskf = RepeatedStratifiedKFold(
                n_splits=effective_splits, n_repeats=n_repeats, random_state=42
            )

            oof_probs = np.zeros((n_repeats, len(y)))
            for split_idx, (train_idx, test_idx) in enumerate(rskf.split(X, y)):
                repeat_idx = split_idx // effective_splits

                if len(np.unique(y[train_idx])) < 2:
                    oof_probs[repeat_idx, test_idx] = float(y[train_idx][0])
                    continue

                clf = LogisticRegression(
                    C=C,
                    class_weight={0: 1.0, 1: 4.0},
                    solver="lbfgs",
                    max_iter=500,
                    random_state=42,
                )
                clf.fit(X[train_idx], y[train_idx])
                oof_probs[repeat_idx, test_idx] = clf.predict_proba(X[test_idx])[:, 1]

            mean_oof_prob = oof_probs.mean(axis=0)
            y_pred_oof = (mean_oof_prob >= decision_threshold).astype(int)

        all_y_true.extend(y.tolist())
        all_y_pred.extend(y_pred_oof.tolist())

        prec, rec, f1, _ = precision_recall_fscore_support(
            y, y_pred_oof, average="binary", zero_division=0
        )
        acc = accuracy_score(y, y_pred_oof)
        bal_acc = balanced_accuracy_score(y, y_pred_oof)
        tn, fp, fn, tp = confusion_matrix(y, y_pred_oof, labels=[0, 1]).ravel()
        mcc = _compute_mcc(int(tp), int(fp), int(fn), int(tn))

        print(
            f"{dim.capitalize():<12} | {bal_acc * 100.0:5.1f}%   | {prec:10.3f} | {rec:8.3f} | {f1:8.3f} | {mcc:6.3f}"
        )

        per_criterion[dim] = {
            "precision": round(float(prec), 4),
            "recall": round(float(rec), 4),
            "f1_score": round(float(f1), 4),
            "accuracy": round(float(acc), 4),
            "balanced_accuracy": round(float(bal_acc), 4),
            "mcc": round(float(mcc), 4),
            "counts": {
                "tp": int(tp),
                "fp": int(fp),
                "fn": int(fn),
                "tn": int(tn),
            },
        }

    y_true_arr = np.array(all_y_true)
    y_pred_arr = np.array(all_y_pred)
    o_prec, o_rec, o_f1, _ = precision_recall_fscore_support(
        y_true_arr, y_pred_arr, average="binary", zero_division=0
    )
    o_acc = accuracy_score(y_true_arr, y_pred_arr)
    o_bal_acc = balanced_accuracy_score(y_true_arr, y_pred_arr)
    o_tn, o_fp, o_fn, o_tp = confusion_matrix(
        y_true_arr, y_pred_arr, labels=[0, 1]
    ).ravel()
    o_mcc = _compute_mcc(int(o_tp), int(o_fp), int(o_fn), int(o_tn))

    print("----------------------------------------------------------------------")
    print(
        f"{'OVERALL':<12} | {o_bal_acc * 100.0:5.1f}%   | {o_prec:10.3f} | {o_rec:8.3f} | {o_f1:8.3f} | {o_mcc:6.3f}"
    )
    print("======================================================================")

    summary = {
        "methodology": {
            "calibration": "L2-Regularized Out-of-Fold Cross-Validation with Lowered Threshold",
            "regularization_C": C,
            "decision_threshold": decision_threshold,
            "n_splits": n_splits,
            "n_repeats": n_repeats,
            "total_requirements": len(common_ids),
            "total_checks": len(all_y_true),
        },
        "overall": {
            "precision": round(float(o_prec), 4),
            "recall": round(float(o_rec), 4),
            "f1_score": round(float(o_f1), 4),
            "accuracy": round(float(o_acc), 4),
            "balanced_accuracy": round(float(o_bal_acc), 4),
            "mcc": round(float(o_mcc), 4),
            "counts": {
                "tp": int(o_tp),
                "fp": int(o_fp),
                "fn": int(o_fn),
                "tn": int(o_tn),
            },
        },
        "per_criterion": per_criterion,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved calibrated summary JSON to: {output_json_path}\n")

    return summary


def evaluate_predictions_legacy(gt_path: Path, pred_path: Path, label: str):
    """Original raw (uncalibrated) evaluation function for baseline comparison output structure."""
    if not pred_path.exists():
        print(f"[{label}] Prediction file not found at {pred_path}. Skipping.")
        return

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)
    with open(pred_path, "r", encoding="utf-8") as f:
        pred_data = json.load(f)

    gt_map = {item["requirement_id"]: item["ground_truth_invest"] for item in gt_data}
    y_true = []
    y_pred = []

    for item in pred_data:
        req_id = item.get("requirement_id", item.get("id"))
        if req_id not in gt_map:
            continue

        pred_invest = item.get("invest_validation", {})
        gt_invest = gt_map[req_id]

        for dim in DIMENSIONS:
            gt_val = gt_invest.get(dim, {}).get("passed", True)
            pred_dim_obj = pred_invest.get(dim, {})
            if isinstance(pred_dim_obj, dict):
                pred_val = pred_dim_obj.get("passed", False)
            else:
                pred_val = bool(pred_dim_obj)

            y_true.append(1 if gt_val else 0)
            y_pred.append(1 if pred_val else 0)

    if not y_true:
        print(f"[{label}] No matching requirement IDs found between ground truth and predictions.")
        return

    accuracy = accuracy_score(y_true, y_pred)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )

    print("\n==================================================")
    print(f"  RAW UNCALIBRATED RESULTS: {label.upper()}")
    print("==================================================")
    print(f"Total Evaluated Checks : {len(y_true)}")
    print(f"Accuracy               : {accuracy * 100:.2f}%")
    print(f"Precision              : {precision:.4f}")
    print(f"Recall                 : {recall:.4f}")
    print(f"F1 Score               : {f1:.4f}")
    print("--------------------------------------------------")

    for i, dim in enumerate(DIMENSIONS):
        dim_true = [y_true[j] for j in range(len(y_true)) if j % len(DIMENSIONS) == i]
        dim_pred = [y_pred[j] for j in range(len(y_pred)) if j % len(DIMENSIONS) == i]
        d_acc = accuracy_score(dim_true, dim_pred)
        d_prec, d_rec, d_f1, _ = precision_recall_fscore_support(
            dim_true, dim_pred, average="binary", zero_division=0
        )
        print(
            f"  - {dim.capitalize():<11} : F1: {d_f1:.4f} (Precision: {d_prec:.4f}, Recall: {d_rec:.4f}, Acc: {d_acc * 100.0:.1f}%)"
        )
    print("==================================================")


def main():
    data_dir = Path("data/processed/")
    gt_path = data_dir / "thesis_50_ground_truth.json"
    reqs_path = data_dir / "thesis_50_requirements.json"
    val_path = data_dir / "thesis_50_validated.json"
    base_path = data_dir / "thesis_50_baseline.json"

    for p in [gt_path, reqs_path, val_path, base_path]:
        if not p.exists():
            print(f"Error: Required file not found at {p}.")
            return

    with open(gt_path, "r", encoding="utf-8") as f:
        gt_data = json.load(f)
    gt_map = {item["requirement_id"]: item["ground_truth_invest"] for item in gt_data}

    with open(reqs_path, "r", encoding="utf-8") as f:
        reqs_data = json.load(f)
    with open(base_path, "r", encoding="utf-8") as f:
        base_data = json.load(f)
    with open(val_path, "r", encoding="utf-8") as f:
        val_data = json.load(f)

    # 1. Run OOF Calibrated Evaluation with adjusted threshold
    calibrate_and_evaluate_oof(
        reqs_data=reqs_data,
        gt_map=gt_map,
        base_data=base_data,
        val_data=val_data,
        output_json_path=Path("results/metrics_summary.json"),
        decision_threshold=0.15,
    )

    # 2. Match baseline/raw output structure exactly
    evaluate_predictions_legacy(gt_path, base_path, "One-Shot Baseline (Raw)")
    evaluate_predictions_legacy(gt_path, val_path, "Multi-Agent Pipeline (Raw)")


if __name__ == "__main__":
    main()