# Evaluation results

Labels: `data/processed/thesis_50_ground_truth.json`, 50 requirements x 6 criteria. Labelled fails per criterion: {'independent': 4, 'negotiable': 5, 'valuable': 4, 'estimable': 12, 'small': 6, 'testable': 17}.

## Overall

| System | Scored | Missing | Accuracy (95% CI) | Balanced acc. | MCC | Kappa | Defects caught | Fail-class precision | System fail rate |
|---|---|---|---|---|---|---|---|---|---|
| one_shot | 300 | 0 | 48.0% (42.4%-53.6%) | 0.665 | 0.256 | 0.146 | 45/48 | 0.227 | 66.0% |
| multi_agent | 295 | 5 | 40.0% (34.6%-45.7%) | 0.617 | 0.197 | 0.096 | 45/48 | 0.205 | 74.2% |
| multi_agent_no_mp | 298 | 2 | 39.6% (34.2%-45.2%) | 0.623 | 0.210 | 0.099 | 46/48 | 0.205 | 75.2% |

## Per criterion: one_shot

| Criterion | TP | FP | FN | TN | Accuracy | Defects caught | Fail-class precision | Kappa |
|---|---|---|---|---|---|---|---|---|
| independent | 29 | 0 | 17 | 4 | 66.0% | 4/4 | 0.191 | 0.214 |
| negotiable | 6 | 1 | 39 | 4 | 20.0% | 4/5 | 0.093 | -0.015 |
| valuable | 32 | 2 | 14 | 2 | 68.0% | 2/4 | 0.125 | 0.083 |
| estimable | 2 | 0 | 36 | 12 | 28.0% | 12/12 | 0.250 | 0.026 |
| small | 21 | 0 | 23 | 6 | 54.0% | 6/6 | 0.207 | 0.180 |
| testable | 9 | 0 | 24 | 17 | 52.0% | 17/17 | 0.415 | 0.203 |

## Per criterion: multi_agent

| Criterion | TP | FP | FN | TN | Accuracy | Defects caught | Fail-class precision | Kappa |
|---|---|---|---|---|---|---|---|---|
| independent | 23 | 1 | 23 | 3 | 52.0% | 3/4 | 0.115 | 0.071 |
| negotiable | 24 | 1 | 20 | 4 | 57.1% | 4/5 | 0.167 | 0.129 |
| valuable | 16 | 1 | 29 | 3 | 38.8% | 3/4 | 0.094 | 0.025 |
| estimable | 1 | 0 | 37 | 12 | 26.0% | 12/12 | 0.245 | 0.013 |
| small | 9 | 0 | 34 | 6 | 30.6% | 6/6 | 0.150 | 0.061 |
| testable | 0 | 0 | 31 | 17 | 35.4% | 17/17 | 0.354 | 0.000 |

## Per criterion: multi_agent_no_mp

| Criterion | TP | FP | FN | TN | Accuracy | Defects caught | Fail-class precision | Kappa |
|---|---|---|---|---|---|---|---|---|
| independent | 18 | 0 | 28 | 4 | 44.0% | 4/4 | 0.125 | 0.093 |
| negotiable | 23 | 0 | 22 | 5 | 56.0% | 5/5 | 0.185 | 0.173 |
| valuable | 21 | 2 | 24 | 2 | 46.9% | 2/4 | 0.077 | -0.009 |
| estimable | 1 | 0 | 36 | 12 | 26.5% | 12/12 | 0.250 | 0.013 |
| small | 9 | 0 | 35 | 6 | 30.0% | 6/6 | 0.146 | 0.058 |
| testable | 0 | 0 | 33 | 17 | 34.0% | 17/17 | 0.340 | 0.000 |

## Per domain group (accuracy / defects caught)

| Domain group | Requirements | one_shot | multi_agent | multi_agent_no_mp |
|---|---|---|---|---|
| Course project | 11 | 47.0% / 3/4 | 33.9% / 3/4 | 40.0% / 4/4 |
| Other PURE case studies | 20 | 43.3% / 28/30 | 45.0% / 28/30 | 36.7% / 28/30 |
| Public sector and e-procurement | 4 | 37.5% / 3/3 | 25.0% / 3/3 | 37.5% / 3/3 |
| Safety-critical rail | 9 | 57.4% / 6/6 | 52.8% / 6/6 | 52.8% / 6/6 |
| Security and enterprise | 6 | 58.3% / 5/5 | 25.0% / 5/5 | 30.6% / 5/5 |

Domain groups hold 4-20 requirements each; treat differences between them as descriptive only.

## Paired comparisons (exact McNemar)

| Systems | Paired items | First right, second wrong | Second right, first wrong | p |
|---|---|---|---|---|
| one_shot vs multi_agent | 295 | 57 | 33 | 0.0149 |
| one_shot vs multi_agent_no_mp | 298 | 54 | 29 | 0.008 |
| multi_agent vs multi_agent_no_mp | 293 | 36 | 35 | 1.0 |

## Autonomy Ceiling: model-human vs human-human kappa

| Criterion | Human-human | one_shot | multi_agent | multi_agent_no_mp |
|---|---|---|---|---|
| independent | 1.000 | 0.214 | 0.071 | 0.093 |
| negotiable | 0.556 | -0.015 | 0.129 | 0.173 |
| valuable | 0.645 | 0.083 | 0.025 | -0.009 |
| estimable | 0.819 | 0.026 | 0.013 | 0.013 |
| small | 0.490 | 0.180 | 0.061 | 0.058 |
| testable | 0.908 | 0.203 | 0.000 | 0.000 |

Kappa is unstable when a criterion has very few labelled fails; report the counts alongside it and do not interpret kappa for criteria with fewer than about 5 fails.
