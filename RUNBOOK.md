# Thesis re-run runbook

Run every command from the repository root (`~/ai_native_re_thesis`).

## 0. Clean up (once)

1. Copy the new files into the repository:
   - `scripts/llm_common.py`
   - `scripts/run_invest_validation.py` (replaces the old one)
   - `scripts/run_baseline_comparison.py` (replaces the old one)
   - `scripts/build_ground_truth.py`
   - `scripts/evaluate.py`
   - `scripts/corrections_log.py`
2. Move the old outputs to an archive folder rather than deleting them. They are the pilot run and can be mentioned as such in Chapter 4.
   ```
   mkdir -p data/archive/pilot
   git mv data/processed/thesis_50_validated.json data/processed/thesis_50_baseline.json data/processed/thesis_50_ground_truth.json data/archive/pilot/
   git mv results/metrics_summary.json data/archive/pilot/
   ```
3. Delete these scripts. Their numbers must not be used:
   - `results/calculate_metrics.py`
   - `create_ground_truth.py`
   - `init_ground_truth.py`
   - `prompts.py` (unused; its INVEST definitions now live in `STATIC_GUARDRAILS`)
4. Commit: `git commit -m "Replace evaluation; archive pilot run"`.

## 1. Labels (you and the second annotator, no model output open)

1. Each annotator copies `labelling_sheet.csv` to `annotator_A.csv` or `annotator_B.csv`. Fill in `P`/`F` and notes, following the INVEST Annotation Guideline.
2. Measure agreement before any discussion:
   `python scripts/build_ground_truth.py agree annotator_A.csv annotator_B.csv`
3. Resolve the disagreements together. Fill in `final_label` and `reason` in `disagreements.csv`.
4. Freeze the labels:
   `python scripts/build_ground_truth.py freeze annotator_A.csv annotator_B.csv disagreements.csv`
5. Commit the sheets, `disagreements.csv`, the frozen ground truth and its `.meta.json`. Write the SHA-256 hash into Chapter 4.

## 2. Model runs (can run while labelling is in progress; prompts are unchanged)

1. Smoke test:
   `python scripts/run_invest_validation.py --limit 1 --temperature 0 --output data/processed/smoke.json`
   If the API rejects `temperature`, drop the flag everywhere below and say so in Chapter 4.
2. Run the three conditions:
   ```
   python scripts/run_baseline_comparison.py --temperature 0 --output data/processed/thesis_50_baseline.json
   python scripts/run_invest_validation.py --temperature 0 --output data/processed/thesis_50_multiagent.json
   python scripts/run_invest_validation.py --temperature 0 --no-meta-prompter --output data/processed/thesis_50_multiagent_nomp.json
   ```
3. Check the last lines of `data/logs/runs.jsonl`. Re-run any requirement listed as `failed` or `incomplete` before evaluating, or report it as missing.

## 2b. Refinement (RQ3, after the multi-agent run)

```
python scripts/refine_requirements.py --review data/processed/thesis_50_multiagent.json --only SWPROJ
```

This rewrites the failed course requirements and writes a blank `labelling/refined_labelling_sheet.csv`. Both annotators label it with the same guideline, after freezing the original labels. Compare the pass rates of the original and refined versions in Chapter 5. Remove `--only SWPROJ` to refine all 50 if time allows.

## 3. Evaluation (only after the labels are frozen)

```
python scripts/evaluate.py \
  --system one_shot=data/processed/thesis_50_baseline.json \
  --system multi_agent=data/processed/thesis_50_multiagent.json \
  --system multi_agent_no_mp=data/processed/thesis_50_multiagent_nomp.json \
  --agreement results/annotation_agreement.json

python scripts/corrections_log.py \
  --baseline data/processed/thesis_50_baseline.json \
  --multi-agent data/processed/thesis_50_multiagent.json
```

Outputs:
- `results/metrics_summary.json`
- `results/metrics_tables.md` (tables ready for Chapter 5)
- `results/corrections_log.csv`
- `results/corrections_summary.json`

Commit them.

## Rules that keep the results valid

- Do not change any prompt after seeing results. If a change is unavoidable, it becomes a new, separately reported condition.
- Do not edit labels after the freeze.
- Report every condition you ran, including ones that did badly.
