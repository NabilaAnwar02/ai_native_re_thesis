# CLAUDE.md

Master's thesis project: **AI-Native Requirements Engineering via a Multi-Agent Framework**.

## Project Goals

1. Build a multi-agent pipeline that performs core RE activities — elicitation, classification, decomposition, ambiguity/conflict detection, and traceability — on real requirement datasets.
2. Treat agent output as *revisable*, not authoritative. Every automated judgment is logged so it can be audited, corrected, and measured (see Corrections Logs below).
3. Produce reproducible experimental evidence: fixed inputs in `data/raw_requirements/`, versioned runs in `data/logs/`, deterministic scripts in `src/`.
4. Feed those findings directly into the manuscript chapters in `thesis_drafts/`.

## Folder Layout

```
ai_native_re_thesis/
├── CLAUDE.md                   # this file — project conventions
├── data/
│   ├── raw_requirements/       # initial requirement datasets (read-only inputs)
│   └── logs/                   # experimental tracking + Corrections Logs
├── src/                        # Python micro-agent scripts + execution pipelines
└── thesis_drafts/              # manuscript chapters
```

- **`data/raw_requirements/`** — Source datasets, untouched. Never edit in place; derived artifacts belong in `data/logs/` or a new subfolder.
- **`data/logs/`** — Two kinds of records: (a) *experiment logs* — per-run metadata (timestamp, model ID, prompt version, token usage, outputs); (b) *Corrections Logs* — cases where an agent's output was wrong or incomplete, what the correct answer was, and why. The Corrections Logs are primary research data, not debug output.
- **`src/`** — One file per micro-agent (single, narrow responsibility), plus pipeline scripts that compose them. Agents should be independently runnable and testable.
- **`thesis_drafts/`** — Chapter drafts. Keep prose and code separate; pull numbers from `data/logs/`, don't retype them.

## Python Stack

Assumed unless you tell me otherwise — say the word and I'll swap any of these.

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| LLM access | `anthropic` (official Anthropic SDK) |
| Default model | `claude-opus-5` |
| Structured agent output | `pydantic` v2 (schemas per agent, validated via the SDK's structured outputs) |
| Data handling | `pandas` for tabular requirement sets, stdlib `json` / `jsonl` for logs |
| Config / secrets | `python-dotenv`, `ANTHROPIC_API_KEY` from `.env` (never committed) |
| Tests | `pytest` |
| Env | `venv` + `requirements.txt` |

## Conventions

- **Model IDs:** use the exact string `claude-opus-5`. Never append a date suffix.
- **Thinking:** adaptive thinking is on by default on Opus 5 — no `thinking` parameter needed. Control depth with `output_config={"effort": "..."}` (`low`–`max`).
- **Sampling params:** `temperature`, `top_p`, and `top_k` are rejected on Opus 5. Steer behavior with prompts.
- **Structured output:** prefer `client.messages.parse(..., output_format=MyPydanticModel)` over parsing free text, so agent output is schema-validated at the boundary.
- **Refusals:** check `response.stop_reason == "refusal"` before reading `response.content` — a refusal returns HTTP 200 with empty or partial content.
- **Reproducibility:** every pipeline run writes one log entry to `data/logs/` recording model ID, effort level, prompt version/hash, input file, and token usage. A result without a log entry doesn't count as evidence.
- **Prompt versioning:** prompts live in `src/` as named constants or files, not inline string literals scattered across call sites — the manuscript needs to cite exactly which prompt produced which result.

## Notes

- Not currently a git repository. Initializing one is recommended before the first experimental run so log entries and prompt versions are anchored to commits.
- `data/logs/`, `src/`, and `thesis_drafts/` each hold a `.gitkeep` so they survive the first commit. `data/raw_requirements/` already contains inputs (`Sw_project_req.txt`, `requirements-xml.zip`).
