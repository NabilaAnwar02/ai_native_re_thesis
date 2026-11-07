"""Turn two independent annotation sheets into the frozen ground truth.

Step 1 - agreement (before any discussion):
    python scripts/build_ground_truth.py agree annotator_A.csv annotator_B.csv
  -> results/annotation_agreement.json   per-criterion agreement and Cohen's kappa
  -> disagreements.csv                   one row per disagreement, to adjudicate

Step 2 - freeze (after filling final_label and reason in disagreements.csv):
    python scripts/build_ground_truth.py freeze annotator_A.csv annotator_B.csv disagreements.csv
  -> data/processed/thesis_50_ground_truth.json       (same format as before)
  -> data/processed/thesis_50_ground_truth.meta.json  date, SHA-256, adjudication counts

The frozen file is never overwritten: delete it by hand only if the supervisor
agrees that labelling must be redone.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CRITERIA = ["independent", "negotiable", "valuable", "estimable", "small", "testable"]
REQS = Path("data/processed/thesis_50_requirements.json")
GT_OUT = Path("data/processed/thesis_50_ground_truth.json")
META_OUT = Path("data/processed/thesis_50_ground_truth.meta.json")
AGREE_OUT = Path("results/annotation_agreement.json")


def read_sheet(path: str, expected_ids: set) -> dict:
    rows, problems = {}, []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rid = row["id"].strip()
            labels = {}
            for c in CRITERIA:
                v = (row.get(c) or "").strip().upper()
                if v not in ("P", "F"):
                    problems.append(f"{rid}/{c}: '{row.get(c)}' is not P or F")
                labels[c] = v == "P"
            rows[rid] = {"labels": labels, "notes": (row.get("notes") or "").strip(), "text": row["text"]}
    missing, extra = expected_ids - set(rows), set(rows) - expected_ids
    if missing:
        problems.append(f"missing ids: {sorted(missing)}")
    if extra:
        problems.append(f"unknown ids: {sorted(extra)}")
    if problems:
        raise SystemExit(f"{path} is not complete:\n  " + "\n  ".join(problems[:30]))
    return rows


def cohen_kappa(a: list, b: list):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return po, (None if pe == 1 else (po - pe) / (1 - pe))


def expected_ids() -> set:
    with open(REQS, encoding="utf-8") as fh:
        return {r["id"] for r in json.load(fh)}


def agree(args) -> None:
    ids = expected_ids()
    A, B = read_sheet(args.a, ids), read_sheet(args.b, ids)
    report, dis = {"n_requirements": len(ids), "per_criterion": {}}, []
    allA, allB = [], []
    for c in CRITERIA:
        a = [A[i]["labels"][c] for i in sorted(ids)]
        b = [B[i]["labels"][c] for i in sorted(ids)]
        allA += a
        allB += b
        po, k = cohen_kappa(a, b)
        report["per_criterion"][c] = {"agreement": round(po, 4), "kappa": None if k is None else round(k, 4),
                                      "fails_A": a.count(False), "fails_B": b.count(False)}
        for i in sorted(ids):
            if A[i]["labels"][c] != B[i]["labels"][c]:
                dis.append({"id": i, "criterion": c, "text": A[i]["text"],
                            "A": "P" if A[i]["labels"][c] else "F", "B": "P" if B[i]["labels"][c] else "F",
                            "A_notes": A[i]["notes"], "B_notes": B[i]["notes"], "final_label": "", "reason": ""})
    po, k = cohen_kappa(allA, allB)
    report["overall"] = {"agreement": round(po, 4), "kappa": None if k is None else round(k, 4),
                         "disagreements": len(dis)}
    AGREE_OUT.parent.mkdir(parents=True, exist_ok=True)
    AGREE_OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with open("disagreements.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(dis[0].keys()) if dis else
                           ["id", "criterion", "text", "A", "B", "A_notes", "B_notes", "final_label", "reason"])
        w.writeheader()
        w.writerows(dis)
    print(f"{'criterion':<12} agreement  kappa   fails A/B")
    for c, r in report["per_criterion"].items():
        print(f"{c:<12} {r['agreement']:.3f}     {r['kappa']}   {r['fails_A']}/{r['fails_B']}")
    print(f"overall      {po:.3f}     {report['overall']['kappa']}   disagreements: {len(dis)}")
    print(f"Wrote {AGREE_OUT} and disagreements.csv")


def freeze(args) -> None:
    if GT_OUT.exists():
        raise SystemExit(f"{GT_OUT} already exists and is frozen. Not overwriting.")
    ids = expected_ids()
    A, B = read_sheet(args.a, ids), read_sheet(args.b, ids)
    final = {}
    with open(args.disagreements, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            v = (row.get("final_label") or "").strip().upper()
            if v not in ("P", "F") or not (row.get("reason") or "").strip():
                raise SystemExit(f"Disagreement {row['id']}/{row['criterion']} needs final_label (P/F) and a reason.")
            final[(row["id"], row["criterion"])] = v == "P"
    gt, changed_from_A = [], 0
    for i in sorted(ids):
        labels = {}
        for c in CRITERIA:
            a, b = A[i]["labels"][c], B[i]["labels"][c]
            if a == b:
                labels[c] = a
            else:
                if (i, c) not in final:
                    raise SystemExit(f"No adjudicated label for {i}/{c}.")
                labels[c] = final[(i, c)]
            changed_from_A += labels[c] != a
        gt.append({"requirement_id": i, "text": A[i]["text"],
                   "ground_truth_invest": {c: {"passed": labels[c]} for c in CRITERIA}})
    GT_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(gt, indent=2, ensure_ascii=False)
    GT_OUT.write_text(payload, encoding="utf-8")
    meta = {"frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "adjudicated_labels": len(final),
            "labels_differing_from_annotator_A": changed_from_A,
            "fails_per_criterion": {c: sum(not g["ground_truth_invest"][c]["passed"] for g in gt) for c in CRITERIA},
            "sources": [args.a, args.b, args.disagreements]}
    META_OUT.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("agree")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(func=agree)
    s = sub.add_parser("freeze")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("disagreements")
    s.set_defaults(func=freeze)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
