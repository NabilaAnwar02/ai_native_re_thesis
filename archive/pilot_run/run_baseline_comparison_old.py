import os
import json
import argparse
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import anthropic
from json_repair import repair_json

# ---------------------------------------------------------------------------
# Pydantic Schema Definitions (Shared with Multi-Agent Pipeline)
# ---------------------------------------------------------------------------
class InvestCriterionResult(BaseModel):
    passed: bool = Field(default=False, description="True if requirement satisfies criterion, False if violated.")
    rationale: str = Field(default="Not evaluated.", description="Detailed explanation of the verdict.")
    recommendation: Optional[str] = Field(None, description="Actionable suggestion for improvement if failed.")

class InvestValidationResult(BaseModel):
    requirement_id: str
    independent: Optional[InvestCriterionResult] = Field(default_factory=lambda: InvestCriterionResult(passed=False))
    negotiable: Optional[InvestCriterionResult] = Field(default_factory=lambda: InvestCriterionResult(passed=False))
    valuable: Optional[InvestCriterionResult] = Field(default_factory=lambda: InvestCriterionResult(passed=False))
    estimable: Optional[InvestCriterionResult] = Field(default_factory=lambda: InvestCriterionResult(passed=False))
    small: Optional[InvestCriterionResult] = Field(default_factory=lambda: InvestCriterionResult(passed=False))
    testable: Optional[InvestCriterionResult] = Field(default_factory=lambda: InvestCriterionResult(passed=False))

# ---------------------------------------------------------------------------
# One-Shot Baseline System Prompt
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# One-Shot Pipeline Execution
# ---------------------------------------------------------------------------
class OneShotBaselinePipeline:
    def __init__(self, api_key: Optional[str] = None, model_name: str = "claude-sonnet-5"):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model_name = model_name

    def _extract_text(self, response) -> str:
        extracted_texts = []
        for block in response.content:
            if hasattr(block, "text") and block.text:
                extracted_texts.append(block.text)
        return "\n".join(extracted_texts) if extracted_texts else str(response.content)

    def validate_requirement(self, req: Dict[str, Any]) -> Dict[str, Any]:
        req_id = req.get("requirement_id", req.get("id", "UNKNOWN"))
        text = req.get("text_clean", req.get("text", ""))

        prompt = f"""Requirement ID: {req_id}
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
        response = self.client.messages.create(
            model=self.model_name,
            max_tokens=2048,
            system=ONE_SHOT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )

        raw_json_str = self._extract_text(response)
        if "```" in raw_json_str:
            raw_json_str = raw_json_str.split("```json")[-1].split("```")[0].strip()
            if not raw_json_str.startswith("{"):
                parts = raw_json_str.split("```")
                for p in parts:
                    if "{" in p and "}" in p:
                        raw_json_str = p.strip()
                        break

        repaired_json_str = repair_json(raw_json_str, return_objects=False)
        parsed_dict = json.loads(repaired_json_str)

        validated_schema = InvestValidationResult(**parsed_dict)
        
        req_copy = dict(req)
        req_copy["invest_validation"] = validated_schema.model_dump()
        return req_copy

def main():
    parser = argparse.ArgumentParser(description="One-Shot Baseline INVEST Requirements Evaluation")
    parser.add_argument("--input", default="data/processed/thesis_50_requirements.json", help="Path to input requirements JSON file")
    parser.add_argument("--output", default="data/processed/thesis_50_baseline.json", help="Path to save baseline results")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file {input_path} not found.")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("==================================================")
    print("  ONE-SHOT PROMPTING BASELINE EVALUATION (RQ1)    ")
    print("==================================================")
    print(f"Processing {len(data)} requirements using model 'claude-sonnet-5' (One-shot)...\n")

    pipeline = OneShotBaselinePipeline()
    baseline_dataset = []

    for idx, req in enumerate(data, 1):
        req_id = req.get("requirement_id", req.get("id", f"REQ_{idx}"))
        print(f"[{idx}/{len(data)}] Evaluating one-shot baseline for {req_id}...")
        try:
            result = pipeline.validate_requirement(req)
            baseline_dataset.append(result)
            print(f"   └─ SUCCESS: One-shot evaluation complete.")
        except Exception as e:
            print(f"   └─ ERROR processing {req_id}: {str(e)}")
            baseline_dataset.append(req)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(baseline_dataset, f, indent=2)

    print("\n==================================================")
    print(f" One-Shot Baseline processing complete!")
    print(f" Saved serialized baseline results to {output_path}")
    print("==================================================")

if __name__ == "__main__":
    main()
