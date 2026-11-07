import json
from pathlib import Path

def main():
    input_path = Path("data/processed/thesis_50_requirements.json")
    output_path = Path("data/processed/thesis_50_ground_truth.json")

    if not input_path.exists():
        print(f"Error: {input_path} not found. Please ensure your 50 requirements dataset is in place.")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        requirements = json.load(f)

    ground_truth_template = []
    for req in requirements:
        req_id = req.get("requirement_id", req.get("id", "UNKNOWN"))
        text = req.get("text_clean", req.get("text", ""))

        ground_truth_template.append({
            "requirement_id": req_id,
            "text": text,
            "ground_truth_invest": {
                "independent": {"passed": True},
                "negotiable": {"passed": True},
                "valuable": {"passed": True},
                "estimable": {"passed": True},
                "small": {"passed": True},
                "testable": {"passed": True}
            }
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ground_truth_template, f, indent=2)

    print(f"Successfully created ground truth template at: {output_path}")

if __name__ == "__main__":
    main()
