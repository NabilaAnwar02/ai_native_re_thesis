"""RQ3: did refinement improve INVEST quality? Compares refined vs. original labels.

Run after the original ground truth is frozen and both annotators have labelled
a refined sheet. Works for both refinement rounds:

  round 1 (placeholder Refiner, default):
    python scripts/score_refined.py agree   labelling/refined_A.csv labelling/refined_B.csv
    python scripts/score_refined.py compare labelling/refined_A.csv labelling/refined_B.csv refined_disagreements.csv

  round 2 (assume Refiner, exploratory):
    python scripts/score_refined.py --round assume agree   labelling/refined_assume_A.csv labelling/refined_assume_B.csv
    python scripts/score_refined.py --round assume compare labelling/refined_assume_A.csv labelling/refined_assume_B.csv refined_assume_disagreements.csv

Outputs (round 1 / round 2):
  results/refined_agreement.json      / results/refined_assume_agreement.json
  refined_disagreements.csv           / refined_assume_disagreements.csv
  results/refinement_effect.{json,md} / results/refinement_assume_effect.{json,md}
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from build_ground_truth import CRITERIA, cohen_kappa, read_sheet

GT = Path("data/processed/thesis_50_ground_truth.json")
ROUNDS = {
    "placeholder": {"refined": "data/processed/thesis_50_refined.json", "tag": "refined",
                    "effect": "refinement_effect"},
    "assume": {"refined": "data/processed/thesis_50_refined_assume.json", "tag": "refined_assume",
               "effect": "refinement_assume_effect"},
}


def refined_ids(path: str) -> set:
    with open(path, encoding="utf-8") as fh:
        return {r["id"] for r in json.load(fh)}


def plausibility(path: str) -> dict:
    """Count Y/N in the optional assumed_values_plausible column (round 2 only)."""
    counts = {"Y": 0, "N": 0, "NA": 0, "blank": 0}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if "assumed_values_plausible" not in row:
                return {}
            v = (row["assumed_values_plausible"] or "").strip().upper()
            counts[v if v in counts else "blank"] += 1
    return counts


def agree(args, cfg) -> None:
    ids = refined_ids(cfg["refined"])
    A, B = read_sheet(args.a, ids), read_sheet(args.b, ids)
    report, dis = {"n_requirements": len(ids), "per_criterion": {}}, []
    for c in CRITERIA:
        a = [A[i]["labels"][c] for i in sorted(ids)]
        b = [B[i]["labels"][c] for i in sorted(ids)]
        po, k = cohen_kappa(a, b)
        report["per_criterion"][c] = {"agreement": round(po, 4), "kappa": None if k is None else round(k, 4)}
        for i in sorted(ids):
            if A[i]["labels"][c] != B[i]["labels"][c]:
                dis.append({"id": i, "criterion": c, "text": A[i]["text"],
                            "A": "P" if A[i]["labels"][c] else "F", "B": "P" if B[i]["labels"][c] else "F",
                            "A_notes": A[i]["notes"], "B_notes": B[i]["notes"], "final_label": "", "reason": ""})
    pa, pb = plausibility(args.a), plausibility(args.b)
    if pa:
        report["assumed_values_plausible"] = {"A": pa, "B": pb}
    Path("results").mkdir(exist_ok=True)
    Path(f"results/{cfg['tag']}_agreement.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    fields = ["id", "criterion", "text", "A", "B", "A_notes", "B_notes", "final_label", "reason"]
    with open(f"{cfg['tag']}_disagreements.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(dis)
    for c, r in report["per_criterion"].items():
        print(f"{c:<12} agreement {r['agreement']:.3f}  kappa {r['kappa']}")
    if pa:
        print(f"assumed values plausible  A: {pa}  B: {pb}")
    print(f"{len(dis)} disagreements -> {cfg['tag']}_disagreements.csv")


def compare(args, cfg) -> None:
    if not GT.exists():
        raise SystemExit("Freeze the original ground truth first.")
    ids = refined_ids(cfg["refined"])
    A, B = read_sheet(args.a, ids), read_sheet(args.b, ids)
    final = {}
    with open(args.disagreements, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            v = (row.get("final_label") or "").strip().upper()
            if v not in ("P", "F") or not (row.get("reason") or "").strip():
                raise SystemExit(f"{row['id']}/{row['criterion']} needs final_label and reason.")
            final[(row["id"], row["criterion"])] = v == "P"
    with open(GT, encoding="utf-8") as fh:
        orig = {g["requirement_id"]: {c: g["ground_truth_invest"][c]["passed"] for c in CRITERIA}
                for g in json.load(fh)}

    result = {"round": args.round, "n_requirements": len(ids), "per_criterion": {}}
    for c in CRITERIA:
        before = after = fixed = broken = 0
        for i in ids:
            a, b = A[i]["labels"][c], B[i]["labels"][c]
            ref = a if a == b else final[(i, c)]
            before += orig[i][c]
            after += ref
            fixed += (not orig[i][c]) and ref
            broken += orig[i][c] and not ref
        result["per_criterion"][c] = {"pass_before": before, "pass_after": after,
                                      "fail_to_pass": fixed, "pass_to_fail": broken}
    tot = {k: sum(r[k] for r in result["per_criterion"].values())
           for k in ("pass_before", "pass_after", "fail_to_pass", "pass_to_fail")}
    result["total"] = tot
    pa, pb = plausibility(args.a), plausibility(args.b)
    if pa:
        result["assumed_values_plausible"] = {"A": pa, "B": pb}
    Path(f"results/{cfg['effect']}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    n = len(ids)
    lines = [f"# Effect of refinement ({args.round} Refiner, human labels, same requirements)", "",
             f"{n} refined requirements.", "",
             "| Criterion | Pass before | Pass after | Fail -> pass | Pass -> fail |", "|---|---|---|---|---|"]
    for c, r in result["per_criterion"].items():
        lines.append(f"| {c} | {r['pass_before']}/{n} | {r['pass_after']}/{n} | {r['fail_to_pass']} | {r['pass_to_fail']} |")
    lines.append(f"| **Total** | {tot['pass_before']}/{6 * n} | {tot['pass_after']}/{6 * n} | "
                 f"{tot['fail_to_pass']} | {tot['pass_to_fail']} |")
    if pa:
        lines += ["", f"Assumed values judged plausible: annotator A {pa}, annotator B {pb}."]
    Path(f"results/{cfg['effect']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--round", choices=list(ROUNDS), default="placeholder")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("agree")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(func=agree)
    s = sub.add_parser("compare")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("disagreements")
    s.set_defaults(func=compare)
    args = p.parse_args()
    args.func(args, ROUNDS[args.round])


if __name__ == "__main__":
    main()
