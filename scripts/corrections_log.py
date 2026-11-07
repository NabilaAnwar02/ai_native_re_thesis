"""Corrections Log: where the multi-agent review changed the outcome (RQ1, RQ3).

Compares the one-shot baseline and the multi-agent pipeline item by item
(requirement x criterion) against the frozen labels, and classifies each:

  corrected   - baseline wrong, multi-agent right  (the review fixed an error)
  introduced  - baseline right, multi-agent wrong  (the review added an error)
  both_right / both_wrong / missing

Writes results/corrections_log.csv (one row per item, with both rationales)
and results/corrections_summary.json (counts per criterion).

Usage
    python scripts/corrections_log.py \
        --baseline data/processed/thesis_50_baseline.json \
        --multi-agent data/processed/thesis_50_multiagent.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from evaluate import CRITERIA, load, verdict


def rationale(record, c):
    v = (record.get("invest_validation") or {}).get(c)
    return (v or {}).get("rationale", "") if isinstance(v, dict) else ""


def main():
    p = argparse.ArgumentParser(description="Build the Corrections Log")
    p.add_argument("--labels", default="data/processed/thesis_50_ground_truth.json")
    p.add_argument("--baseline", required=True)
    p.add_argument("--multi-agent", required=True)
    p.add_argument("--out", default="results")
    args = p.parse_args()

    gt = {g["requirement_id"]: g for g in load(args.labels)}
    base = {r["id"]: r for r in load(args.baseline)}
    ma = {r["id"]: r for r in load(args.multi_agent)}

    rows = []
    summary = {c: {k: 0 for k in ("corrected", "introduced", "both_right", "both_wrong", "missing")}
               for c in CRITERIA}
    for rid, g in gt.items():
        for c in CRITERIA:
            truth = g["ground_truth_invest"][c]["passed"]
            b, m = verdict(base.get(rid, {}), c), verdict(ma.get(rid, {}), c)
            if b is None or m is None:
                outcome = "missing"
            elif b != truth and m == truth:
                outcome = "corrected"
            elif b == truth and m != truth:
                outcome = "introduced"
            else:
                outcome = "both_right" if b == truth else "both_wrong"
            summary[c][outcome] += 1
            pf = lambda x: "" if x is None else ("P" if x else "F")
            rows.append({"id": rid, "criterion": c, "text": g["text"], "label": pf(truth),
                         "one_shot": pf(b), "multi_agent": pf(m), "outcome": outcome,
                         "one_shot_rationale": rationale(base.get(rid, {}), c),
                         "multi_agent_rationale": rationale(ma.get(rid, {}), c)})

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "corrections_log.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    totals = {k: sum(summary[c][k] for c in CRITERIA) for k in summary[CRITERIA[0]]}
    (out / "corrections_summary.json").write_text(json.dumps({"per_criterion": summary, "total": totals},
                                                             indent=2), encoding="utf-8")
    print(f"{'criterion':<12} corrected introduced both_right both_wrong missing")
    for c in CRITERIA:
        s = summary[c]
        print(f"{c:<12} {s['corrected']:>9} {s['introduced']:>10} {s['both_right']:>10} "
              f"{s['both_wrong']:>10} {s['missing']:>7}")
    print(f"{'TOTAL':<12} {totals['corrected']:>9} {totals['introduced']:>10} {totals['both_right']:>10} "
          f"{totals['both_wrong']:>10} {totals['missing']:>7}")
    print(f"Wrote {out / 'corrections_log.csv'} and {out / 'corrections_summary.json'}")


if __name__ == "__main__":
    main()
