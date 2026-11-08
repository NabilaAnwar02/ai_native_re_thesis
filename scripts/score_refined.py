"""RQ3: did refinement improve INVEST quality? Compares refined vs. original labels.

Run after the original ground truth is frozen and both annotators have labelled
the refined sheet (copies of labelling/refined_labelling_sheet.csv).

Step 1 - agreement on the refined sheet:
    python scripts/score_refined.py agree labelling/refined_A.csv labelling/refined_B.csv
  -> results/refined_agreement.json, refined_disagreements.csv

Step 2 - after filling final_label and reason in refined_disagreements.csv:
    python scripts/score_refined.py compare labelling/refined_A.csv labelling/refined_B.csv refined_disagreements.csv
  -> results/refinement_effect.json and results/refinement_effect.md
     (pass rate per criterion before vs. after refinement, on the same requirements)
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from build_ground_truth import CRITERIA, cohen_kappa, read_sheet

GT = Path("data/processed/thesis_50_ground_truth.json")
REFINED = Path("data/processed/thesis_50_refined.json")


def refined_ids() -> set:
    with open(REFINED, encoding="utf-8") as fh:
        return {r["id"] for r in json.load(fh)}


def agree(args) -> None:
    ids = refined_ids()
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
    Path("results").mkdir(exist_ok=True)
    Path("results/refined_agreement.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    fields = ["id", "criterion", "text", "A", "B", "A_notes", "B_notes", "final_label", "reason"]
    with open("refined_disagreements.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(dis)
    for c, r in report["per_criterion"].items():
        print(f"{c:<12} agreement {r['agreement']:.3f}  kappa {r['kappa']}")
    print(f"{len(dis)} disagreements -> refined_disagreements.csv")


def compare(args) -> None:
    if not GT.exists():
        raise SystemExit("Freeze the original ground truth first.")
    ids = refined_ids()
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

    result = {"n_requirements": len(ids), "per_criterion": {}}
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
    Path("results/refinement_effect.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    n = len(ids)
    lines = ["# Effect of refinement (human labels, same requirements)", "",
             f"{n} refined requirements.", "",
             "| Criterion | Pass before | Pass after | Fail -> pass | Pass -> fail |", "|---|---|---|---|---|"]
    for c, r in result["per_criterion"].items():
        lines.append(f"| {c} | {r['pass_before']}/{n} | {r['pass_after']}/{n} | {r['fail_to_pass']} | {r['pass_to_fail']} |")
    lines.append(f"| **Total** | {tot['pass_before']}/{6 * n} | {tot['pass_after']}/{6 * n} | "
                 f"{tot['fail_to_pass']} | {tot['pass_to_fail']} |")
    Path("results/refinement_effect.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    args.func(args)


if __name__ == "__main__":
    main()
