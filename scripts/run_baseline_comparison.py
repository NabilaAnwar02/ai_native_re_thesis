"""One-shot baseline (RQ1 control): a single call per requirement.

The system prompt and user prompt are unchanged from the first baseline run.
Infrastructure is shared with the multi-agent pipeline (llm_common.py), so both
conditions use the same model settings, retries, verdict parsing and run log.

Usage
    python scripts/run_baseline_comparison.py --output data/processed/thesis_50_baseline.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from llm_common import (CRITERIA, LLMClient, append_run_log, load_json, parse_verdicts,
                        prompt_hash, save_json)

SCRIPT_VERSION = "2.0.0"

ONE_SHOT_SYSTEM_PROMPT = """You are an Expert Requirements Engineering Quality Auditor.
Your task is to conduct a rigorous audit of a given software requirement against the 6 INVEST criteria:
1. Independent: Can the requirement be developed separately?
2. Negotiable: Is it flexible and open to discussion on details?
3. Valuable: Does it deliver clear value to the user or customer?
4. Estimable: Is it clear enough to estimate its implementation effort?
5. Small: Is it small enough to fit within a single iteration/sprint?
6. Testable: Can its success be objectively verified through tests?

You MUST output strictly formatted JSON conforming to the requested schema. Ensure every dimension includes a boolean passed flag, a rationale, and a recommendation if failed.
"""

USER_TEMPLATE = """Requirement ID: {req_id}
Requirement Text: {text}

Evaluate this requirement against all 6 INVEST criteria in a single-shot assessment.
Respond ONLY with a valid JSON object matching this schema structure:
{{
  "requirement_id": "{req_id}",
  "independent": {{"passed": true, "rationale": "...", "recommendation": "..."}},
  "negotiable": {{"passed": true, "rationale": "...", "recommendation": "..."}},
  "valuable": {{"passed": true, "rationale": "...", "recommendation": "..."}},
  "estimable": {{"passed": true, "rationale": "...", "recommendation": "..."}},
  "small": {{"passed": true, "rationale": "...", "recommendation": "..."}},
  "testable": {{"passed": true, "rationale": "...", "recommendation": "..."}}
}}
"""


def main() -> None:
    p = argparse.ArgumentParser(description="One-shot baseline INVEST review")
    p.add_argument("--input", default="data/processed/thesis_50_requirements.json")
    p.add_argument("--output", default="data/processed/thesis_50_baseline.json")
    p.add_argument("--model", default="claude-sonnet-5")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    in_path, out_path = Path(args.input), Path(args.output)
    if in_path.resolve() == out_path.resolve():
        raise SystemExit("--output must differ from --input.")
    data = load_json(in_path)[: args.limit] if args.limit else load_json(in_path)
    llm = LLMClient(args.model, args.temperature)

    print(f"Condition: one_shot | model {args.model} | temperature {args.temperature} | {len(data)} requirements")
    results, failed = [], []
    for i, req in enumerate(data, 1):
        rid = req.get("id", f"REQ_{i}")
        text = req.get("text_clean", req.get("text", ""))
        print(f"[{i}/{len(data)}] {rid} ...", end=" ", flush=True)
        out = dict(req)
        try:
            r = llm.ask(ONE_SHOT_SYSTEM_PROMPT, USER_TEMPLATE.format(req_id=rid, text=text), 4096)
            parsed = parse_verdicts(r["text"], rid)
            out["invest_validation"] = parsed["verdicts"]
            out["raw_response"] = r["text"]
            out["run_meta"] = {"status": "ok" if not parsed["missing_criteria"] else "incomplete",
                               "missing_criteria": parsed["missing_criteria"], "stop_reason": r["stop_reason"]}
            print(out["run_meta"]["status"])
        except Exception as exc:
            print(f"FAILED: {exc}")
            failed.append(rid)
            out["invest_validation"] = {c: None for c in CRITERIA}
            out["run_meta"] = {"status": "failed", "error": str(exc)}
        results.append(out)
        save_json(out_path, results)

    incomplete = [r["id"] for r in results if r["run_meta"]["status"] == "incomplete"]
    append_run_log({
        "script": "run_baseline_comparison", "script_version": SCRIPT_VERSION, "condition": "one_shot",
        "model": args.model, "temperature": args.temperature,
        "prompt_hash": prompt_hash(ONE_SHOT_SYSTEM_PROMPT, USER_TEMPLATE),
        "input": str(in_path), "output": str(out_path), "records": len(results),
        "failed": failed, "incomplete": incomplete, "api_calls": llm.calls,
        "input_tokens": llm.input_tokens, "output_tokens": llm.output_tokens,
    })
    print(f"\nSaved {out_path} | failed {len(failed)} | incomplete {len(incomplete)} | "
          f"tokens in {llm.input_tokens:,} / out {llm.output_tokens:,}")


if __name__ == "__main__":
    main()
