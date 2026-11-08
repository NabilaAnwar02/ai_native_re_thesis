# Evaluation results

Labels: `data/processed/thesis_50_ground_truth.json`, 50 requirements x 6 criteria. Labelled fails per criterion: {'independent': 4, 'negotiable': 5, 'valuable': 4, 'estimable': 12, 'small': 6, 'testable': 17}.

## Overall

| System | Scored | Missing | Accuracy (95% CI) | Balanced acc. | MCC | Kappa | Defects caught | Fail-class precision | System fail rate |
|---|---|---|---|---|---|---|---|---|---|
| one_shot_run1 | 300 | 0 | 48.0% (42.4%-53.6%) | 0.665 | 0.256 | 0.146 | 45/48 | 0.227 | 66.0% |
| one_shot_run2 | 295 | 5 | 49.8% (44.2%-55.5%) | 0.667 | 0.252 | 0.149 | 42/46 | 0.226 | 63.0% |

## Per criterion: one_shot_run1

| Criterion | TP | FP | FN | TN | Accuracy | Defects caught | Fail-class precision | Kappa |
|---|---|---|---|---|---|---|---|---|
| independent | 29 | 0 | 17 | 4 | 66.0% | 4/4 | 0.191 | 0.214 |
| negotiable | 6 | 1 | 39 | 4 | 20.0% | 4/5 | 0.093 | -0.015 |
| valuable | 32 | 2 | 14 | 2 | 68.0% | 2/4 | 0.125 | 0.083 |
| estimable | 2 | 0 | 36 | 12 | 28.0% | 12/12 | 0.250 | 0.026 |
| small | 21 | 0 | 23 | 6 | 54.0% | 6/6 | 0.207 | 0.180 |
| testable | 9 | 0 | 24 | 17 | 52.0% | 17/17 | 0.415 | 0.203 |

## Per criterion: one_shot_run2

| Criterion | TP | FP | FN | TN | Accuracy | Defects caught | Fail-class precision | Kappa |
|---|---|---|---|---|---|---|---|---|
| independent | 29 | 0 | 17 | 4 | 66.0% | 4/4 | 0.191 | 0.214 |
| negotiable | 8 | 1 | 37 | 4 | 24.0% | 4/5 | 0.098 | -0.005 |
| valuable | 34 | 2 | 12 | 1 | 71.4% | 1/3 | 0.077 | 0.028 |
| estimable | 3 | 0 | 34 | 11 | 29.2% | 11/11 | 0.244 | 0.039 |
| small | 20 | 0 | 23 | 6 | 53.1% | 6/6 | 0.207 | 0.176 |
| testable | 11 | 1 | 21 | 16 | 55.1% | 16/17 | 0.432 | 0.223 |

## Per domain group (accuracy / defects caught)

| Domain group | Requirements | one_shot_run1 | one_shot_run2 |
|---|---|---|---|
| Course project | 11 | 47.0% / 3/4 | 50.0% / 2/4 |
| Other PURE case studies | 20 | 43.3% / 28/30 | 44.2% / 28/30 |
| Public sector and e-procurement | 4 | 37.5% / 3/3 | 34.8% / 2/2 |
| Safety-critical rail | 9 | 57.4% / 6/6 | 63.0% / 6/6 |
| Security and enterprise | 6 | 58.3% / 5/5 | 59.4% / 4/4 |

Domain groups hold 4-20 requirements each; treat differences between them as descriptive only.

## Paired comparisons (exact McNemar)

| Systems | Paired items | First right, second wrong | Second right, first wrong | p |
|---|---|---|---|---|
| one_shot_run1 vs one_shot_run2 | 295 | 6 | 12 | 0.2379 |

Kappa is unstable when a criterion has very few labelled fails; report the counts alongside it and do not interpret kappa for criteria with fewer than about 5 fails.
