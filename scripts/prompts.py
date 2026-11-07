"""Prompt and tool-schema constants for the INVEST validation agent.

Named constants only — no API calls here (see ``run_invest_validation.py`` for
the pipeline that uses these). Per CLAUDE.md, prompts are versioned so the
manuscript can cite exactly which prompt produced which result; bump
``PROMPT_VERSION`` and add a changelog line whenever the system prompt or tool
schema changes in a way that could change model output.
"""

from __future__ import annotations

import hashlib
import json

# 1.0.0 — initial INVEST validation prompt: six-criterion tool call
#         (independent, negotiable, valuable, estimable, small, testable)
#         plus a boolean aggregator verdict, each with a one-sentence rationale.
PROMPT_VERSION = "1.0.0"

INVEST_TOOL_NAME = "record_invest_validation"

SYSTEM_PROMPT = """\
You are a requirements engineering assistant. You evaluate a single software \
requirement statement against the INVEST criteria used to judge whether a \
requirement is well-formed:

- Independent: the requirement can be developed, tested, and delivered \
without depending on other requirements being completed first.
- Negotiable: the requirement describes what is needed, not a fixed \
implementation, leaving room for discussion of how to satisfy it.
- Valuable: the requirement delivers clear value to an end user or other \
stakeholder, not just to the system's internal structure.
- Estimable: the requirement is specific and complete enough that a \
development team could reasonably estimate the effort to implement it.
- Small: the requirement is scoped narrowly enough to be completed within a \
single short development iteration, not a multi-feature epic.
- Testable: the requirement states or implies a clear, objective way to \
verify it has been satisfied.

Judge each of the six criteria independently, based only on the requirement's \
actual wording — do not assume context it does not state. For each criterion, \
decide whether the requirement passes or fails it and give a one-sentence \
rationale. Then set overall_pass to true only if the requirement passes all \
six criteria, and give a one-sentence overall rationale.

Call the record_invest_validation tool exactly once with your verdicts. Do \
not ask clarifying questions — judge the requirement as written."""


def build_user_message(record: dict) -> str:
    """Render the per-requirement user turn from a dataset record."""
    return (
        f"Requirement ID: {record['id']}\n"
        f"Source: {record['source_document']} ({record['dataset_type']})\n\n"
        f'Requirement text:\n"{record["text_clean"]}"\n\n'
        "Evaluate this requirement against the INVEST criteria."
    )


def _criterion_schema(description: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "passes": {
                "type": "boolean",
                "description": description,
            },
            "rationale": {
                "type": "string",
                "description": "One-sentence justification grounded in the requirement's wording.",
            },
        },
        "required": ["passes", "rationale"],
        "additionalProperties": False,
    }


INVEST_TOOL_SCHEMA = {
    "name": INVEST_TOOL_NAME,
    "description": (
        "Record the INVEST validation verdict for one requirement: a pass/fail "
        "judgment with a one-sentence rationale for each of the six criteria, "
        "plus an aggregate overall_pass that is true only if all six pass."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "independent": _criterion_schema(
                "True if the requirement can be delivered without depending on other requirements first."
            ),
            "negotiable": _criterion_schema(
                "True if the requirement states what is needed without mandating a fixed implementation."
            ),
            "valuable": _criterion_schema(
                "True if the requirement delivers clear value to an end user or stakeholder."
            ),
            "estimable": _criterion_schema(
                "True if the requirement is specific enough for a team to reasonably estimate effort."
            ),
            "small": _criterion_schema(
                "True if the requirement is scoped to a single short iteration, not a multi-feature epic."
            ),
            "testable": _criterion_schema(
                "True if the requirement implies a clear, objective way to verify it was satisfied."
            ),
            "overall_pass": {
                "type": "boolean",
                "description": "True only if independent, negotiable, valuable, estimable, small, and testable are all true.",
            },
            "overall_rationale": {
                "type": "string",
                "description": "One-sentence summary of the overall verdict.",
            },
        },
        "required": [
            "independent",
            "negotiable",
            "valuable",
            "estimable",
            "small",
            "testable",
            "overall_pass",
            "overall_rationale",
        ],
        "additionalProperties": False,
    },
}


def prompt_fingerprint() -> str:
    """SHA-256 over the system prompt + tool schema, for the run log's prompt_hash."""
    payload = SYSTEM_PROMPT + json.dumps(INVEST_TOOL_SCHEMA, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
