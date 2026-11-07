"""Refiner agent: rewrite each requirement that failed one or more INVEST criteria.

This is the third stage of the Draft -> Review -> Refine SOP. It runs AFTER the
multi-agent review and does not change the review verdicts, so the RQ1/RQ2
results are unaffected. Its output is judged by the human annotators: they
label the refined versions with the same INVEST guideline, and the change in
pass rate (original vs. refined) is the RQ3 measure of quality impact.

Usage
    python scripts/refine_requirements.py \
        --review data/processed/thesis_50_multiagent.json \
        --output data/processed/thesis_50_refined.json
  -> also writes labelling/refined_labelling_sheet.csv (blank, for annotators)
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from llm_common import CRITERIA, LLMClient, append_run_log, load_json, prompt_hash, save_json

SCRIPT_VERSION = "1.0.0"

REFINER_SYSTEM = """You are a Requirements Refiner Agent.
You receive a software requirement and the review findings for the INVEST criteria it failed.
Rewrite the requirement so that it addresses those findings while keeping its original intent.
Do not invent business facts: where a value is unknown, use a clearly marked placeholder such as [TBD: maximum response time].
If the requirement bundles several capabilities, you may split it into at most three numbered requirements.
Respond with the rewritten requirement text only."""

USER_TEMPLATE = """Requirement ID: {req_id}
Original requirement: {text}

Failed criteria and review findings:
{findings}

Rewrite the requirement."""


def findings_of(record) -> str:
    lines = []
    for c in CRITERIA:
        v = (record.get("invest_validation") or {}).get(c)
        if isinstance(v, dict) and v.get("passed") is False:
            rec = v.get("recommendation") or ""
            lines.append(f"- {c.capitalize()}: {v.get('rationale', '')} Recommendation: {rec}".strip())
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Refine requirements that failed the multi-agent review")
    p.add_argument("--review", default="data/processed/thesis_50_multiagent.json")
    p.add_argument("--output", default="data/processed/thesis_50_refined.json")
    p.add_argument("--sheet", default="labelling/refined_labelling_sheet.csv")
    p.add_argument("--model", default="claude-sonnet-5")
    p.add_argument("--only", default=None, help="restrict to ids starting with this prefix, e.g. SWPROJ")
    args = p.parse_args()

    records = load_json(Path(args.review))
    if args.only:
        records = [r for r in records if r["id"].startswith(args.only)]
    llm = LLMClient(args.model)
    out, failed = [], []
    for i, rec in enumerate(records, 1):
        findings = findings_of(rec)
        print(f"[{i}/{len(records)}] {rec['id']} ...", end=" ", flush=True)
        if not findings:
            print("passed all criteria, not refined")
            continue
        try:
            r = llm.ask(REFINER_SYSTEM, USER_TEMPLATE.format(req_id=rec["id"], text=rec["text_clean"],
                                                             findings=findings), 2048)
            out.append({"id": rec["id"], "original_text": rec["text_clean"], "refined_text": r["text"],
                        "findings_used": findings})
            print("ok")
        except Exception as exc:
            print(f"FAILED: {exc}")
            failed.append(rec["id"])
        save_json(Path(args.output), out)

    sheet = Path(args.sheet)
    sheet.parent.mkdir(parents=True, exist_ok=True)
    rows = list(out)
    random.Random(2027).shuffle(rows)
    with open(sheet, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["order", "id", "text", *CRITERIA, "notes"])
        for n, r in enumerate(rows, 1):
            w.writerow([n, r["id"], r["refined_text"], *[""] * len(CRITERIA), ""])

    append_run_log({"script": "refine_requirements", "script_version": SCRIPT_VERSION, "model": args.model,
                    "prompt_hash": prompt_hash(REFINER_SYSTEM, USER_TEMPLATE), "input": args.review,
                    "output": args.output, "refined": len(out), "failed": failed,
                    "input_tokens": llm.input_tokens, "output_tokens": llm.output_tokens})
    print(f"\nRefined {len(out)} | failed {len(failed)} | saved {args.output} and {sheet}")


if __name__ == "__main__":
    main()
