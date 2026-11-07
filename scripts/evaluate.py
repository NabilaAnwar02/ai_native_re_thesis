"""Score each system's INVEST verdicts against the frozen human labels.

Replaces results/calculate_metrics.py. Plain counting only: no learned
calibration, no thresholds, no adjusted counts.

Reports, per system, overall and per criterion:
  * confusion counts with "pass" as the positive class;
  * precision / recall / F1 for both classes ("pass" and "fail"), where
    fail-class recall = share of labelled defects the system caught;
  * accuracy (with a 95% Wilson interval), balanced accuracy, MCC, and
    Cohen's kappa between the system and the human labels;
  * how many verdicts were missing (failed or incomplete runs) - never guessed.
Also: exact McNemar tests between systems (paired, same items), and, when the
annotation agreement file is given, the Autonomy Ceiling table comparing
model-human kappa with human-human kappa per criterion.

Usage
    python scripts/evaluate.py \
        --system one_shot=data/processed/thesis_50_baseline.json \
        --system multi_agent=data/processed/thesis_50_multiagent.json \
        --system multi_agent_no_mp=data/processed/thesis_50_multiagent_nomp.json \
        --agreement results/annotation_agreement.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

CRITERIA = ["independent", "negotiable", "valuable", "estimable", "small", "testable"]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def verdict(record, c):
    v = (record.get("invest_validation") or {}).get(c)
    if not isinstance(v, dict) or not isinstance(v.get("passed"), bool):
        return None
    if "fallback" in (v.get("rationale") or "").lower():  # legacy schema defaults are not verdicts
        return None
    return v["passed"]


def div(a, b):
    return a / b if b else None


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 4), round(centre + half, 4)]


def prf(tp, fp, fn):
    p, r = div(tp, tp + fp), div(tp, tp + fn)
    f = 2 * p * r / (p + r) if p is not None and r is not None and p + r > 0 else None
    return p, r, f


def score(m):
    tp, fp, fn, tn = m["tp"], m["fp"], m["fn"], m["tn"]
    n = tp + fp + fn + tn
    pp, pr, pf = prf(tp, fp, fn)          # pass as positive
    fp_, fr, ff = prf(tn, fn, fp)          # fail as positive
    den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / den if den else None
    po = div(tp + tn, n)
    pe = div((tp + fp) * (tp + fn) + (tn + fn) * (tn + fp), n * n)
    kappa = (po - pe) / (1 - pe) if po is not None and pe is not None and pe != 1 else None
    rec_pass, rec_fail = div(tp, tp + fn), div(tn, tn + fp)
    bal = (rec_pass + rec_fail) / 2 if rec_pass is not None and rec_fail is not None else None
    r4 = lambda x: None if x is None else round(x, 4)
    return {"n_scored": n, "counts": m,
            "accuracy": r4(po), "accuracy_ci95": wilson(tp + tn, n),
            "balanced_accuracy": r4(bal), "mcc": r4(mcc), "kappa_vs_labels": r4(kappa),
            "pass_class": {"precision": r4(pp), "recall": r4(pr), "f1": r4(pf)},
            "fail_class": {"precision": r4(fp_), "recall": r4(fr), "f1": r4(ff),
                           "defects_caught": f"{tn}/{tn + fp}", "defects_caught_ci95": wilson(tn, tn + fp)},
            "system_fail_rate": r4(div(tn + fn, n))}


DOMAIN_GROUPS = {
    "SWPROJ": "Course project",
    "CCTNS": "Public sector and e-procurement", "PEPPOL": "Public sector and e-procurement",
    "ERTMS": "Safety-critical rail", "EIRENE": "Safety-critical rail",
    "KEEPASS": "Security and enterprise", "MICROCARE": "Security and enterprise", "THEMAS": "Security and enterprise",
}


def domain_of(rid):
    prefix = rid.split("_REQ_")[0].split("_")[0]
    return DOMAIN_GROUPS.get(prefix, "Other PURE case studies")


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def fmt(x, pct=False):
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%" if pct else f"{x:.3f}"


def main():
    p = argparse.ArgumentParser(description="Score INVEST verdicts against frozen human labels")
    p.add_argument("--labels", default="data/processed/thesis_50_ground_truth.json")
    p.add_argument("--system", action="append", required=True, help="name=path (repeatable)")
    p.add_argument("--agreement", default=None, help="results/annotation_agreement.json")
    p.add_argument("--out", default="results")
    args = p.parse_args()

    gt = {g["requirement_id"]: {c: g["ground_truth_invest"][c]["passed"] for c in CRITERIA}
          for g in load(args.labels)}
    systems = {}
    for spec in args.system:
        name, path = spec.split("=", 1)
        systems[name] = {r.get("id", r.get("requirement_id")): r for r in load(path)}

    summary = {"labels_file": args.labels, "n_requirements": len(gt),
               "label_fails_per_criterion": {c: sum(not gt[i][c] for i in gt) for c in CRITERIA},
               "systems": {}, "mcnemar": [], "autonomy_ceiling": None}
    correct = {}
    for name, recs in systems.items():
        per, total, missing = {}, {"tp": 0, "fp": 0, "fn": 0, "tn": 0}, []
        correct[name] = {}
        for c in CRITERIA:
            m = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
            for rid, labels in gt.items():
                pred = verdict(recs.get(rid, {}), c)
                if pred is None:
                    missing.append(f"{rid}:{c}")
                    continue
                a = labels[c]
                key = "tp" if a and pred else "fp" if pred else "fn" if a else "tn"
                m[key] += 1
                total[key] += 1
                correct[name][(rid, c)] = pred == a
            per[c] = score(m)
        per_domain = {}
        for d in sorted({domain_of(r) for r in gt}):
            m = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
            for (rid, c), ok in correct[name].items():
                if domain_of(rid) != d:
                    continue
                a = gt[rid][c]
                key = ("tp" if a else "tn") if ok else ("fn" if a else "fp")
                m[key] += 1
            per_domain[d] = {"n_requirements": sum(domain_of(r) == d for r in gt), **score(m)}
        summary["systems"][name] = {"overall": score(total), "per_criterion": per, "per_domain": per_domain,
                                    "missing_verdicts": len(missing), "missing_ids": missing}

    for a, b in itertools.combinations(systems, 2):
        common = set(correct[a]) & set(correct[b])
        b_only = sum(correct[a][k] and not correct[b][k] for k in common)
        c_only = sum(correct[b][k] and not correct[a][k] for k in common)
        summary["mcnemar"].append({"systems": [a, b], "paired_items": len(common),
                                   f"{a}_right_{b}_wrong": b_only, f"{b}_right_{a}_wrong": c_only,
                                   "p_value_exact": round(mcnemar_exact(b_only, c_only), 4)})

    if args.agreement:
        human = load(args.agreement)["per_criterion"]
        summary["autonomy_ceiling"] = {c: {"human_human_kappa": human[c]["kappa"],
                                           **{f"{s}_kappa": summary["systems"][s]["per_criterion"][c]["kappa_vs_labels"]
                                              for s in systems}} for c in CRITERIA}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = ["# Evaluation results", "",
             f"Labels: `{args.labels}`, {len(gt)} requirements x 6 criteria. "
             f"Labelled fails per criterion: {summary['label_fails_per_criterion']}.", "",
             "## Overall", "",
             "| System | Scored | Missing | Accuracy (95% CI) | Balanced acc. | MCC | Kappa | Defects caught | Fail-class precision | System fail rate |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for s, d in summary["systems"].items():
        o = d["overall"]
        ci = o["accuracy_ci95"]
        lines.append(f"| {s} | {o['n_scored']} | {d['missing_verdicts']} | {fmt(o['accuracy'], True)} "
                     f"({fmt(ci[0], True)}-{fmt(ci[1], True)}) | {fmt(o['balanced_accuracy'])} | {fmt(o['mcc'])} | "
                     f"{fmt(o['kappa_vs_labels'])} | {o['fail_class']['defects_caught']} | "
                     f"{fmt(o['fail_class']['precision'])} | {fmt(o['system_fail_rate'], True)} |")
    for s, d in summary["systems"].items():
        lines += ["", f"## Per criterion: {s}", "",
                  "| Criterion | TP | FP | FN | TN | Accuracy | Defects caught | Fail-class precision | Kappa |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for c in CRITERIA:
            r = d["per_criterion"][c]
            m = r["counts"]
            lines.append(f"| {c} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | {fmt(r['accuracy'], True)} | "
                         f"{r['fail_class']['defects_caught']} | {fmt(r['fail_class']['precision'])} | "
                         f"{fmt(r['kappa_vs_labels'])} |")
    lines += ["", "## Per domain group (accuracy / defects caught)", "",
              "| Domain group | Requirements | " + " | ".join(systems) + " |", "|---|---|" + "---|" * len(systems)]
    for d in next(iter(summary["systems"].values()))["per_domain"]:
        cells = []
        for s in systems:
            r = summary["systems"][s]["per_domain"][d]
            cells.append(f"{fmt(r['accuracy'], True)} / {r['fail_class']['defects_caught']}")
        n = next(iter(summary["systems"].values()))["per_domain"][d]["n_requirements"]
        lines.append(f"| {d} | {n} | " + " | ".join(cells) + " |")
    lines += ["", "Domain groups hold 4-20 requirements each; treat differences between them as descriptive only."]
    lines += ["", "## Paired comparisons (exact McNemar)", "",
              "| Systems | Paired items | First right, second wrong | Second right, first wrong | p |", "|---|---|---|---|---|"]
    for t in summary["mcnemar"]:
        a, b = t["systems"]
        lines.append(f"| {a} vs {b} | {t['paired_items']} | {t[f'{a}_right_{b}_wrong']} | "
                     f"{t[f'{b}_right_{a}_wrong']} | {t['p_value_exact']} |")
    if summary["autonomy_ceiling"]:
        lines += ["", "## Autonomy Ceiling: model-human vs human-human kappa", "",
                  "| Criterion | Human-human | " + " | ".join(systems) + " |",
                  "|---|---|" + "---|" * len(systems)]
        for c, r in summary["autonomy_ceiling"].items():
            lines.append(f"| {c} | {fmt(r['human_human_kappa'])} | " +
                         " | ".join(fmt(r[f'{s}_kappa']) for s in systems) + " |")
    lines += ["", "Kappa is unstable when a criterion has very few labelled fails; "
              "report the counts alongside it and do not interpret kappa for criteria with fewer than about 5 fails."]
    (out / "metrics_tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
