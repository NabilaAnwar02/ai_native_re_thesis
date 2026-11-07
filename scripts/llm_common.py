"""Shared helpers for the LLM pipelines (multi-agent and one-shot baseline).

Changes from the earlier scripts, all aimed at honest, reproducible runs:
  * No silent fallbacks: a criterion the model did not return is stored as
    null and flagged, never recorded as "failed".
  * Retries: API errors are retried with back-off; a reply that contains no
    text (e.g. only a thinking block, or cut off at max_tokens) is retried
    once with a larger token budget and then raises.
  * Run log: every run appends one line to data/logs/runs.jsonl with the
    model, temperature, prompt hash, token totals and success counts.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

try:  # json_repair fixes small JSON syntax slips; plain json is the fallback.
    from json_repair import repair_json
except ImportError:  # pragma: no cover
    repair_json = None

CRITERIA = ["independent", "negotiable", "valuable", "estimable", "small", "testable"]
LOG_FILE = Path("data/logs/runs.jsonl")


class InvestCriterionResult(BaseModel):
    passed: bool
    rationale: str = ""
    recommendation: Optional[str] = None


class EmptyResponseError(RuntimeError):
    """The model returned no usable text."""


def prompt_hash(*parts: str) -> str:
    return hashlib.sha256("\n\x1e\n".join(parts).encode("utf-8")).hexdigest()


class LLMClient:
    """Thin wrapper around anthropic.Anthropic with retries and token tracking."""

    def __init__(self, model: str, temperature: Optional[float] = None,
                 max_retries: int = 3, api_key: Optional[str] = None):
        import os
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    @staticmethod
    def _text_of(response) -> str:
        parts = [b.text for b in response.content
                 if getattr(b, "type", None) == "text" and getattr(b, "text", "")]
        return "\n".join(parts).strip()

    def _create(self, system: str, user: str, max_tokens: int):
        kwargs: Dict[str, Any] = dict(model=self.model, max_tokens=max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}])
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        delay = 5.0
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.messages.create(**kwargs)
                self.calls += 1
                usage = getattr(response, "usage", None)
                if usage is not None:
                    self.input_tokens += getattr(usage, "input_tokens", 0) or 0
                    self.output_tokens += getattr(usage, "output_tokens", 0) or 0
                return response
            except self._anthropic.APIError as exc:
                status = getattr(exc, "status_code", None)
                transient = (isinstance(exc, (self._anthropic.APIConnectionError, self._anthropic.RateLimitError))
                             or (status is not None and status >= 500))
                if not transient or attempt == self.max_retries:
                    raise  # e.g. 400 bad request: retrying cannot help
                print(f"      API error ({exc.__class__.__name__}); retrying in {delay:.0f}s")
                time.sleep(delay)
                delay *= 2

    def ask(self, system: str, user: str, max_tokens: int) -> Dict[str, Any]:
        """Return {"text", "stop_reason", "retried"}; raise if no text after one retry."""
        response = self._create(system, user, max_tokens)
        text, stop = self._text_of(response), getattr(response, "stop_reason", None)
        retried = False
        if not text or stop == "max_tokens":
            retried = True
            response = self._create(system, user, max_tokens * 2)
            text, stop = self._text_of(response), getattr(response, "stop_reason", None)
        if not text:
            raise EmptyResponseError(f"no text in reply (stop_reason={stop})")
        return {"text": text, "stop_reason": stop, "retried": retried}


def extract_json_object(raw: str) -> Dict[str, Any]:
    """Pull the JSON object out of a reply that may wrap it in prose or fences."""
    text = raw
    if "```" in text:
        for chunk in text.split("```"):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                text = chunk
                break
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    if repair_json is not None:
        text = repair_json(text, return_objects=False)
    return json.loads(text)


def parse_verdicts(raw: str, req_id: str) -> Dict[str, Any]:
    """Validate each criterion separately; missing or malformed ones become null."""
    data = extract_json_object(raw)
    result: Dict[str, Any] = {"requirement_id": req_id}
    missing: List[str] = []
    for c in CRITERIA:
        try:
            result[c] = InvestCriterionResult(**data[c]).model_dump()
        except Exception:
            result[c] = None
            missing.append(c)
    return {"verdicts": result, "missing_criteria": missing}


def append_run_log(entry: Dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
