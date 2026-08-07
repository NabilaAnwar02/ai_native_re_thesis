"""Build the unified 50-requirement thesis dataset for INVEST validation.

Composes two sources into one publication-ready JSON file:

* 11 requirements from the Software Engineering Project 2 course spec
  (``data/raw_requirements/Sw_project_req.txt``).
* 39 requirements sampled from the PURE XML subset
  (``data/interim/requirements-xml/XMLZIPFile/``).

Why the PURE half is *hybrid*
-----------------------------
Only 6 of the 18 PURE XML documents carry explicit ``<req>`` markup, and one of
them (``2007-eirene_fun_7-2``) holds 58% of all tagged requirements. Sampling
``<req>`` elements alone would therefore cover 6 domains, not 18. For the 12
untagged documents the requirements live in unmarked ``<text_body>``/``<item>``
prose, so those are mined with a modal-verb heuristic ("shall", "must",
"should", ...). Extraction method is recorded per item in the provenance
sidecar, so prose-mined entries can be audited separately in the manuscript.

Determinism
-----------
No RNG. Within a document, items are picked at evenly spaced indices across the
filtered candidate list, so the selection spreads across sections and reruns
byte-identically. Timestamps are confined to the log/sidecar; the dataset file
itself is stable across runs.

Usage
-----
    python scripts/build_thesis_dataset.py
    python scripts/build_thesis_dataset.py --no-write
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Reused rather than reimplemented: one parsing contract for the whole corpus.
from inventory_pure import (  # noqa: E402
    direct_child_text,
    element_text,
    extract_requirements,
    local_name,
    normalize,
)

# Bump when selection or cleaning logic changes, so dataset files stay attributable.
# 1.0.0 — initial build: 11 course + 39 PURE (hybrid <req> / modal-prose).
# 1.1.0 — reject non-atomic elements and modals confined to subordinate clauses,
#         after manual review of the v1.0.0 prose-mined sample (3 defects).
# 1.2.0 — treat a trailing "[SSS563]" as notation rather than a merge signal
#         (it had cut the TCS pool from 92 to 4); drop restatements sharing an
#         opening phrase or >=50% content words with an already-selected item.
SCRIPT_VERSION = "1.2.0"
SCRIPT_NAME = "build_thesis_dataset"

COURSE_FILE = REPO_ROOT / "data" / "raw_requirements" / "Sw_project_req.txt"
XML_DIR = REPO_ROOT / "data" / "interim" / "requirements-xml" / "XMLZIPFile"
OUTPUT_FILE = REPO_ROOT / "data" / "processed" / "thesis_50_requirements.json"
LOGS_DIR = REPO_ROOT / "data" / "logs"

TARGET_TOTAL = 50
TARGET_PURE = 39

# Hard floor from the dataset spec: anything shorter is a parsing artifact.
MIN_CHARS = 10
# Sampling window: below this a "requirement" is a fragment or heading; above it
# the element is a multi-requirement wall of prose that INVEST cannot score.
CANDIDATE_MIN_CHARS = 30
CANDIDATE_MAX_CHARS = 600

# Any residual markup that survived XML text extraction (escaped HTML in prose).
TAG_RE = re.compile(r"<[^>]+>")
# Leading enumeration the authors typed into the text, e.g. "3.1.2 " or "R-4:".
COURSE_LINE_RE = re.compile(r"^\s*(\d+)\.\s*\[([A-Za-z]+-\d+)\]\s*(.+?)\s*$")
# Requirement-bearing modality; the discriminator for untagged prose.
MODAL_RE = re.compile(
    r"\b(shall|must|should|will be able to|is required to|are required to)\b",
    re.IGNORECASE,
)
# Prose elements that can hold a requirement statement.
PROSE_ELEMENTS = ("text_body", "item")
# A candidate must read as a sentence, not a heading or a table cell.
SENTENCE_RE = re.compile(r"[a-z]{3}.*[a-z]{3}", re.DOTALL)

# Prose that talks *about* the document rather than stating an obligation. A
# modal verb inside one of these is incidental ("This section presents the
# commands that all systems must respond to"), so they are rejected outright.
META_OPENER_RE = re.compile(
    r"^\s*(this (section|document|chapter|specification|subsection|paragraph|annex|appendix|part)"
    r"|the (following|above|table|figure|purpose of this)"
    r"|(figure|table|note|notes|description|definition|example|abbreviation)s?\b"
    r"|\d+(\.\d+)*\s+(introduction|scope|overview|purpose|references|definitions)\b)",
    re.IGNORECASE,
)
# A prescriptive statement names an actor before its modal verb.
ACTOR_RE = re.compile(
    r"^\s*(the\s+\w+|each\s+\w+|all\s+\w+|every\s+\w+|no\s+\w+|any\s+\w+|[A-Z][\w-]*(\s+[\w-]+){0,3})"
    r"[^.;:]{0,120}?\b(shall|must|should|will)\b",
    re.IGNORECASE,
)
STRONG_MODAL_RE = re.compile(r"\b(shall|must)\b", re.IGNORECASE)
# Narrative / definitional tells that a sentence describes rather than requires.
NARRATIVE_RE = re.compile(
    r"\b(we|our|this is|these are|is a special|is intended|are conditions|is defined as"
    r"|presented here|for example|e\.g\.|i\.e\.)\b",
    re.IGNORECASE,
)
# Cross-references and inline requirement tags signal a fragment lifted out of a
# numbered list — usually more than one requirement in a single element.
CROSSREF_RE = re.compile(r"(see\s+(sub)?section|as defined in|\[[A-Z]{2,}\d+\]|refer to)", re.IGNORECASE)
# The document's own numbering, typed into the requirement text ("3.2.4 The land-
# based part shall...", "REQ-5: ..."). Lifted into provenance so it neither
# inflates the word count nor hides the actor from ACTOR_RE.
LEADING_LABEL_RE = re.compile(
    r"^\s*((?:REQ|FR|NFR|SSS|R)[\s\-_.]*\d+(?:\.\d+)*|\d+(?:\.\d+)+)\s*[:.)\-–]?\s+",
    re.IGNORECASE,
)
# A list stem whose items live in sibling elements — "shall be as follows:" on
# its own states no obligation that INVEST can score.
DANGLING_STEM_RE = re.compile(r"(the following|as follows)[^.]{0,12}$", re.IGNORECASE)
# EIRENE/ERTMS mark each requirement Mandatory/Optional with a trailing "(M)",
# "(O)" or bare "M". Notation, not prose — and it hides the ":" of a list stem.
NOTATION_MARKER_RE = re.compile(r"[\s.]*[(\[]?(M|O|MI)[)\]]?[\s.]*$")
# The source element cut a statement short: "...at speeds from 0 km/h to".
TRUNCATED_RE = re.compile(
    r"\b(and|or|to|of|the|a|an|for|with|from|in|on|at|by|than|between|into|that|which|is|are|be)"
    r"[\s,;]*$",
    re.IGNORECASE,
)
# Words that open a subordinate clause. A modal inside one obligates nothing on
# its own: "...to determine when a unit shall be turned on" is a description.
SUBORDINATOR_RE = re.compile(
    r"\b(where|wherein|whereby|which|when|whenever|while|whilst|that|who|whom|whose"
    r"|after|before|until|unless|because|although|though|since|if)\b",
    re.IGNORECASE,
)
# Finite verbs that signal the sentence has returned to its main clause, so a
# later modal is a real obligation: "If acknowledgement IS specified, the driver
# shall..." states a requirement; "when a unit shall..." does not.
FINITE_VERB_RE = re.compile(
    r"\b(is|are|was|were|has|have|had|does|do|did|can|could|may|might|will|would"
    r"|shall|should|must|occurs|exists|applies|fails|becomes)\b",
    re.IGNORECASE,
)
# TCS tags every requirement with a trailing "[SSS563]". At the end it is
# notation (stripped); followed by more prose it means the element merged
# several numbered requirements — "...integrate with AMPS.[SSS563] The..."
TRAILING_TAG_RE = re.compile(r"\s*\[[A-Z]{2,}\s*\d+\]\s*\.?\s*$")
EMBEDDED_TAG_RE = re.compile(r"\[[A-Z]{2,}\s*\d+\]\s*\S")

BLANK_INVEST = {
    "independent": None,
    "negotiable": None,
    "valuable": None,
    "estimable": None,
    "small": None,
    "testable": None,
    "overall_pass": None,
}


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def clean_text(raw: str) -> str:
    """Strip residual markup, decode entities, collapse whitespace."""
    text = TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    # Non-breaking spaces and friends survive \s in some Python builds' inputs.
    text = text.replace(" ", " ").replace("​", "")
    return normalize(text)


def split_label(text: str) -> tuple[str, str | None]:
    """Separate a leading document number/tag from the requirement prose."""
    match = LEADING_LABEL_RE.match(text)
    if not match:
        return text, None
    remainder = text[match.end() :].strip()
    # Only strip if real prose follows; otherwise the "label" was the content.
    if len(remainder) < CANDIDATE_MIN_CHARS:
        return text, None
    return remainder, match.group(1).strip()


def strip_notation(text: str) -> str:
    """Drop trailing document notation: a TCS "[SSS563]" tag, an EIRENE "(M)"."""
    stripped = TRAILING_TAG_RE.sub("", text).strip()
    stripped = NOTATION_MARKER_RE.sub("", stripped).strip()
    # Guard against eating the whole statement if the marker *was* the content.
    return stripped if len(stripped) >= CANDIDATE_MIN_CHARS else text


def states_obligation(text: str) -> bool:
    """True if at least one modal sits in a main clause, not a subordinate one.

    For each modal, look back to the start of its clause (the last comma or
    semicolon). If a subordinator opens that span and no finite verb closes it
    off before the modal, the modal is still inside the subordinate clause and
    obligates nothing. Text with no modal at all is left to other checks — the
    ``<req>``-tagged half of the corpus includes declarative requirements.
    """
    modals = list(MODAL_RE.finditer(text))
    if not modals:
        return True

    for modal in modals:
        clause = re.split(r"[,;:]", text[: modal.start()])[-1]
        subordinators = list(SUBORDINATOR_RE.finditer(clause))
        if not subordinators:
            return True  # plain "<subject> shall ..." — an obligation
        tail = clause[subordinators[-1].end() :]
        if FINITE_VERB_RE.search(tail):
            return True  # subordinate clause resolved; back in the main clause
    return False


def is_atomic(text: str) -> bool:
    """Reject elements that merged several requirements into one record."""
    if EMBEDDED_TAG_RE.search(text):
        return False
    sentences = len([s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()])
    return not (sentences > 1 and len(MODAL_RE.findall(text)) > 1)


def is_usable(text: str) -> bool:
    """Reject artifacts: fragments, headings, meta-prose, dangling list stems."""
    if not (CANDIDATE_MIN_CHARS <= len(text) <= CANDIDATE_MAX_CHARS):
        return False
    if not SENTENCE_RE.search(text):
        return False
    if META_OPENER_RE.match(text):
        return False
    # Starts mid-sentence: the element split a statement that began elsewhere.
    if text[:1].islower():
        return False
    if text.rstrip().endswith(":"):
        return False
    if TRUNCATED_RE.search(text.rstrip(" .")):
        return False
    if DANGLING_STEM_RE.search(text):
        return False
    if not is_atomic(text):
        return False
    return states_obligation(text)


def quality_score(text: str) -> int:
    """Rank how much a candidate reads as one atomic, testable obligation.

    Used only to order candidates within a document — the count per document is
    fixed by the stratification quota. Deterministic and cheap by design: this
    is a corpus-preparation filter, not the INVEST judgment itself, which is the
    multi-agent framework's job and must not be pre-empted here.
    """
    score = 0
    if ACTOR_RE.match(text):
        score += 4  # names who is obliged, before saying what is obliged
    if STRONG_MODAL_RE.search(text):
        score += 3  # "shall"/"must" over the weaker "should"/"will"
    modal_hits = len(MODAL_RE.findall(text))
    if modal_hits > 1:
        score -= 2 * (modal_hits - 1)  # likely several requirements in one blob
    sentences = len([s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()])
    if sentences == 1:
        score += 2
    else:
        score -= sentences - 1
    if NARRATIVE_RE.search(text):
        score -= 3
    if CROSSREF_RE.search(text):
        score -= 2
    if 40 <= len(text) <= 300:
        score += 1  # a statement, not a fragment or a wall of prose
    if re.search(r"\b(\d+(\.\d+)*\s*(ms|s|km|m|kg|%|hz|khz|mhz|db|seconds|minutes|hours))\b", text, re.I):
        score += 1  # a measurable threshold — directly relevant to Testable
    return score


def metrics_for(text: str) -> dict[str, int]:
    return {"word_count": len(text.split()), "char_count": len(text)}


# --------------------------------------------------------------------------- #
# ID schema
# --------------------------------------------------------------------------- #
def file_prefix(stem: str) -> str:
    """Deterministic uppercase prefix from a PURE filename stem.

    ``"0000 - cctns"`` -> ``CCTNS``; ``"2007-eirene_fun_7-2"`` -> ``EIRENE_FUN``.
    Year prefixes and trailing version tokens are dropped; the two EIRENE
    documents stay distinguishable (``EIRENE_FUN`` vs ``EIRENE_SYS``).
    """
    name = re.sub(r"^\s*\d{4}\s*-\s*", "", stem.lower())
    tokens = [t for t in re.split(r"[^a-z0-9]+", name) if t]
    while tokens and re.fullmatch(r"v?\d+", tokens[-1]):
        tokens.pop()
    return "_".join(tokens).upper() or re.sub(r"[^A-Z0-9]+", "_", stem.upper())


# --------------------------------------------------------------------------- #
# Source 1 — course requirements
# --------------------------------------------------------------------------- #
def load_course_requirements(path: Path) -> list[dict[str, Any]]:
    """Parse the numbered ``N. [FR-0X] ...`` lines of the course spec.

    The ordinal and the ``[FR-01]`` label are provenance, not requirement
    prose, so they are lifted out of ``text_clean`` and kept in the sidecar.
    """
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = COURSE_LINE_RE.match(line)
        if not match:
            raise ValueError(f"{path.name}:{lineno}: unrecognized requirement line: {line!r}")
        _ordinal, label, body = match.groups()
        text = clean_text(body)
        if len(text) < MIN_CHARS:
            continue
        index = len(records) + 1
        records.append(
            {
                "record": {
                    "id": f"SWPROJ_REQ_{index:03d}",
                    "source_document": path.name,
                    "dataset_type": "Course_Project",
                    "text_clean": text,
                    "metrics": metrics_for(text),
                    "invest_validation": dict(BLANK_INVEST),
                },
                "provenance": {
                    "extraction_method": "course_line",
                    "source_line": lineno,
                    "original_label": label,
                    "requirement_class": "NFR" if label.upper().startswith("NFR") else "FR",
                },
            }
        )
    return records


# --------------------------------------------------------------------------- #
# Source 2 — PURE XML candidates
# --------------------------------------------------------------------------- #
def prose_candidates(root: ET.Element) -> list[dict[str, Any]]:
    """Mine modal requirement statements from unmarked ``<text_body>``/``<item>``.

    Only leaf prose elements are taken: a ``<text_body>`` wrapping an
    ``<itemize>`` would otherwise be harvested alongside each of its ``<item>``
    children, duplicating the same sentences at two granularities.
    """
    found: list[dict[str, Any]] = []

    def has_nested_prose(element: ET.Element) -> bool:
        return any(local_name(d.tag) in PROSE_ELEMENTS for d in element.iter() if d is not element)

    def walk(element: ET.Element, sections: list[dict[str, str | None]]) -> None:
        for child in element:
            name = local_name(child.tag)
            if name == "title":
                continue
            if name == "p":
                section = {"id": child.get("id"), "title": direct_child_text(child, "title") or None}
                walk(child, sections + [section])
                continue
            if name in PROSE_ELEMENTS and not has_nested_prose(child):
                text, label = split_label(clean_text(element_text(child)))
                text = strip_notation(text)
                if MODAL_RE.search(text):
                    ids = [s["id"] for s in sections if s["id"]]
                    titles = [s["title"] for s in sections if s["title"]]
                    found.append(
                        {
                            "text": text,
                            "section_path_ids": " > ".join(ids),
                            "section_path_titles": " > ".join(titles),
                            "xml_id": None,
                            "inline_id": label,
                            "element": name,
                        }
                    )
                continue
            walk(child, sections)

    walk(root, [])
    return found


def document_candidates(path: Path) -> dict[str, Any]:
    """All usable candidates for one XML document, plus how they were obtained."""
    root = ET.parse(path).getroot()
    tagged = extract_requirements(root, path.stem)

    if tagged:
        method = "req_tag"
        raw = []
        for r in tagged:
            text, label = split_label(clean_text(r["text"]))
            raw.append(
                {
                    "text": strip_notation(text),
                    "section_path_ids": r["section_path_ids"],
                    "section_path_titles": r["section_path_titles"],
                    "xml_id": r["xml_id"],
                    "inline_id": r["inline_id"] or label,
                    "element": "req",
                }
            )
    else:
        method = "modal_prose"
        raw = prose_candidates(root)

    seen: set[str] = set()
    candidates = []
    for item in raw:
        key = item["text"].lower()
        if key in seen or not is_usable(item["text"]):
            continue
        seen.add(key)
        candidates.append(item)

    return {
        "stem": path.stem,
        "file": path.name,
        "prefix": file_prefix(path.stem),
        "extraction_method": method,
        "pool_total": len(raw),
        "candidates": candidates,
    }


def allocate(docs: list[dict[str, Any]], target: int) -> dict[str, int]:
    """Spread ``target`` items across documents, capped by each pool's size.

    Base quota is an even split. Leftovers (from the split remainder and from
    pools too small to meet their quota) go to the largest pools first, ties
    broken by stem, so the allocation is reproducible.
    """
    by_size = sorted(docs, key=lambda d: (-len(d["candidates"]), d["stem"]))
    base = target // len(docs)
    quota = {d["stem"]: min(base, len(d["candidates"])) for d in docs}

    remaining = target - sum(quota.values())
    while remaining > 0:
        progressed = False
        for doc in by_size:
            if remaining == 0:
                break
            if quota[doc["stem"]] < len(doc["candidates"]):
                quota[doc["stem"]] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            raise ValueError(f"corpus cannot supply {target} requirements; short by {remaining}")
    return quota


NEAR_DUPLICATE_THRESHOLD = 0.8
# Two statements opening with the same six words are the same requirement
# restated for another section — Jaccard misses them when the tails diverge.
RESTATEMENT_PREFIX_TOKENS = 6


def tokens_of(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def prefix_of(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower())[:RESTATEMENT_PREFIX_TOKENS])


# Function words and modals carry no topic, so they inflate whole-text overlap
# between two requirements that merely share a sentence frame.
STOPWORDS = frozenset(
    """a an the of to in for and or be is are was were shall must should will may can
    that this these those with by on at as it its each any all from not no which when
    if so such other than their they there have has had do does did within into per
    between used use only more most such same both one two three""".split()
)
# Topical redundancy: looser than NEAR_DUPLICATE_THRESHOLD because it compares
# only content words, of which two related requirements share proportionally more.
CONTENT_OVERLAP_THRESHOLD = 0.5


def content_tokens_of(text: str) -> frozenset[str]:
    return frozenset(t for t in tokens_of(text) if t not in STOPWORDS and not t.isdigit())


def is_near_duplicate(text: str, existing: list[frozenset[str]]) -> bool:
    """Jaccard overlap test — catches boilerplate restated with one word changed.

    PURE documents repeat clauses across sections ("a visual and audible
    *indication* / *alarm* shall be given when..."). Exact-match dedup misses
    those, and a 50-item dataset cannot afford to spend two slots on one idea.
    """
    candidate = tokens_of(text)
    if not candidate:
        return True
    return any(
        len(candidate & other) / len(candidate | other) >= NEAR_DUPLICATE_THRESHOLD
        for other in existing
        if other
    )


def select_indices(candidates: list[dict[str, Any]], count: int) -> list[int]:
    """Pick ``count`` candidate indices: best-scoring first, one per section.

    The section constraint stops all picks from a large document landing in the
    same chapter; it is relaxed only if the document has fewer distinct sections
    than the quota. Ties break on document order, so the result is stable.
    """
    ranked = sorted(range(len(candidates)), key=lambda i: (-quality_score(candidates[i]["text"]), i))
    chosen: list[int] = []
    picked_tokens: list[frozenset[str]] = []
    picked_content: list[frozenset[str]] = []
    picked_prefixes: set[tuple[str, ...]] = set()
    used_sections: set[str] = set()

    def take(index: int) -> None:
        chosen.append(index)
        picked_tokens.append(tokens_of(candidates[index]["text"]))
        picked_content.append(content_tokens_of(candidates[index]["text"]))
        picked_prefixes.add(prefix_of(candidates[index]["text"]))

    def redundant(index: int) -> bool:
        text = candidates[index]["text"]
        if prefix_of(text) in picked_prefixes or is_near_duplicate(text, picked_tokens):
            return True
        content = content_tokens_of(text)
        if not content:
            return True
        return any(
            len(content & other) / len(content | other) >= CONTENT_OVERLAP_THRESHOLD
            for other in picked_content
            if other
        )

    for index in ranked:
        if len(chosen) == count:
            break
        section = candidates[index]["section_path_ids"] or f"#{index}"
        if section in used_sections or redundant(index):
            continue
        used_sections.add(section)
        take(index)

    for index in ranked:  # relax the one-per-section rule if still short
        if len(chosen) == count:
            break
        if index not in chosen and not redundant(index):
            take(index)

    for index in ranked:  # last resort: quota outranks the diversity heuristics
        if len(chosen) == count:
            break
        if index not in chosen:
            take(index)

    return sorted(chosen)


def build_pure_records(docs: list[dict[str, Any]], quota: dict[str, int]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for doc in docs:
        picks = select_indices(doc["candidates"], quota[doc["stem"]])
        for index, position in enumerate(picks, 1):
            candidate = doc["candidates"][position]
            text = candidate["text"]
            req_id = f"{doc['prefix']}_REQ_{index:03d}"
            records.append(
                {
                    "record": {
                        "id": req_id,
                        "source_document": doc["file"],
                        "dataset_type": "PURE",
                        "text_clean": text,
                        "metrics": metrics_for(text),
                        "invest_validation": dict(BLANK_INVEST),
                    },
                    "provenance": {
                        "extraction_method": doc["extraction_method"],
                        "source_element": candidate["element"],
                        "xml_id": candidate["xml_id"],
                        "inline_id": candidate["inline_id"],
                        "section_path_ids": candidate["section_path_ids"] or None,
                        "section_path_titles": candidate["section_path_titles"] or None,
                        "candidate_index": position,
                        "candidate_pool_size": len(doc["candidates"]),
                        "selection_score": quality_score(text),
                        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    },
                }
            )
    return records


# --------------------------------------------------------------------------- #
# Validation, reporting, output
# --------------------------------------------------------------------------- #
def validate(records: list[dict[str, Any]]) -> None:
    dataset = [r["record"] for r in records]
    course = [r for r in dataset if r["dataset_type"] == "Course_Project"]
    pure = [r for r in dataset if r["dataset_type"] == "PURE"]

    problems = []
    if len(dataset) != TARGET_TOTAL:
        problems.append(f"expected {TARGET_TOTAL} records, got {len(dataset)}")
    if len(course) != TARGET_TOTAL - TARGET_PURE:
        problems.append(f"expected {TARGET_TOTAL - TARGET_PURE} course records, got {len(course)}")
    if len(pure) != TARGET_PURE:
        problems.append(f"expected {TARGET_PURE} PURE records, got {len(pure)}")

    ids = [r["id"] for r in dataset]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        problems.append(f"duplicate ids: {dupes}")

    # Cross-document check: select_indices only dedups within one document.
    seen: list[tuple[str, frozenset[str]]] = []
    for r in dataset:
        current = tokens_of(r["text_clean"])
        for other_id, other in seen:
            if current and other and len(current & other) / len(current | other) >= NEAR_DUPLICATE_THRESHOLD:
                problems.append(f"{r['id']}: near-duplicate of {other_id}")
        seen.append((r["id"], current))

    for r in dataset:
        if len(r["text_clean"]) < MIN_CHARS:
            problems.append(f"{r['id']}: text below {MIN_CHARS} chars")
        if r["text_clean"] != normalize(r["text_clean"]) or TAG_RE.search(r["text_clean"]):
            problems.append(f"{r['id']}: text not clean")
        if r["metrics"] != metrics_for(r["text_clean"]):
            problems.append(f"{r['id']}: metrics disagree with text")
        if set(r["invest_validation"]) != set(BLANK_INVEST):
            problems.append(f"{r['id']}: invest_validation schema mismatch")

    if problems:
        raise SystemExit("VALIDATION FAILED:\n  - " + "\n  - ".join(problems))


def print_report(records: list[dict[str, Any]], docs: list[dict[str, Any]]) -> None:
    pools = {d["file"]: d for d in docs}
    per_file: dict[str, list[dict[str, Any]]] = {}
    for entry in records:
        per_file.setdefault(entry["record"]["source_document"], []).append(entry)

    header = f"{'source document':<26} {'type':<14} {'method':<12} {'n':>3} {'pool':>6} {'id prefix':<16}"
    print("\nCount distribution per source file")
    print(header)
    print("-" * len(header))
    for name, entries in per_file.items():
        first = entries[0]
        prefix = first["record"]["id"].rsplit("_REQ_", 1)[0]
        pool = pools[name]["candidates"] if name in pools else []
        print(
            f"{name[:26]:<26} {first['record']['dataset_type']:<14} "
            f"{first['provenance']['extraction_method']:<12} {len(entries):>3} "
            f"{len(pool) if pool else '-':>6} {prefix:<16}"
        )
    print("-" * len(header))

    dataset = [r["record"] for r in records]
    course_n = sum(1 for r in dataset if r["dataset_type"] == "Course_Project")
    pure_n = len(dataset) - course_n
    req_tag_n = sum(1 for r in records if r["provenance"]["extraction_method"] == "req_tag")
    prose_n = sum(1 for r in records if r["provenance"]["extraction_method"] == "modal_prose")
    words = [r["metrics"]["word_count"] for r in dataset]

    print(f"{'TOTAL':<26} {'':<14} {'':<12} {len(dataset):>3}")
    print(f"\ncourse / PURE        : {course_n} / {pure_n}")
    print(f"PURE source documents: {len({r['source_document'] for r in dataset if r['dataset_type'] == 'PURE'})}")
    print(f"PURE <req> / prose   : {req_tag_n} / {prose_n}")
    print(f"unique ids           : {len({r['id'] for r in dataset})}")
    print(f"word count min/med/max: {min(words)} / {sorted(words)[len(words) // 2]} / {max(words)}")

    def show(entry: dict[str, Any], heading: str) -> None:
        record, prov = entry["record"], entry["provenance"]
        print(f"\n{heading}")
        print(json.dumps(record, indent=2, ensure_ascii=False))
        print(f"  provenance: {json.dumps(prov, ensure_ascii=False)}")

    show(next(r for r in records if r["record"]["dataset_type"] == "Course_Project"), "Sample — course requirement")
    show(next(r for r in records if r["record"]["dataset_type"] == "PURE"), "Sample — PURE requirement")


def write_outputs(records: list[dict[str, Any]], docs: list[dict[str, Any]]) -> tuple[Path, Path, Path]:
    """Write the dataset, a provenance sidecar, and one ``runs.jsonl`` entry."""
    dataset = [r["record"] for r in records]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    file_stamp = stamp.replace(":", "").replace("-", "")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    OUTPUT_FILE.write_text(
        json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Kept out of the dataset file so it matches the thesis schema exactly;
    # join back on "id" when auditing where an item came from.
    sidecar = LOGS_DIR / f"thesis_50_provenance_{file_stamp}.json"
    sidecar.write_text(
        json.dumps(
            {
                "script": SCRIPT_NAME,
                "script_version": SCRIPT_VERSION,
                "generated_utc": stamp,
                "dataset_file": str(OUTPUT_FILE.relative_to(REPO_ROOT)),
                "candidate_pools": {
                    d["file"]: {
                        "extraction_method": d["extraction_method"],
                        "raw_elements": d["pool_total"],
                        "usable_candidates": len(d["candidates"]),
                        "id_prefix": d["prefix"],
                    }
                    for d in docs
                },
                "items": {r["record"]["id"]: r["provenance"] for r in records},
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # Per CLAUDE.md: no run without a log entry. Deterministic — no LLM calls.
    runs_path = LOGS_DIR / "runs.jsonl"
    entry = {
        "timestamp_utc": stamp,
        "script": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "run_type": "deterministic_dataset_build",
        "model": None,
        "inputs": [
            str(COURSE_FILE.relative_to(REPO_ROOT)),
            str(XML_DIR.relative_to(REPO_ROOT)),
        ],
        "output_file": str(OUTPUT_FILE.relative_to(REPO_ROOT)),
        "provenance_file": str(sidecar.relative_to(REPO_ROOT)),
        "summary": {
            "total": len(dataset),
            "course": sum(1 for r in dataset if r["dataset_type"] == "Course_Project"),
            "pure": sum(1 for r in dataset if r["dataset_type"] == "PURE"),
            "pure_documents": len({r["source_document"] for r in dataset if r["dataset_type"] == "PURE"}),
            "by_extraction_method": {
                method: sum(1 for r in records if r["provenance"]["extraction_method"] == method)
                for method in ("course_line", "req_tag", "modal_prose")
            },
            "per_source_document": {
                name: sum(1 for r in dataset if r["source_document"] == name)
                for name in sorted({r["source_document"] for r in dataset})
            },
        },
    }
    with runs_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return OUTPUT_FILE, sidecar, runs_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course-file", type=Path, default=COURSE_FILE)
    parser.add_argument("--xml-dir", type=Path, default=XML_DIR)
    parser.add_argument("--no-write", action="store_true", help="report only, write nothing")
    args = parser.parse_args()

    course = load_course_requirements(args.course_file)
    expected_course = TARGET_TOTAL - TARGET_PURE
    if len(course) != expected_course:
        raise SystemExit(f"expected {expected_course} course requirements, parsed {len(course)}")

    xml_files = sorted(
        p
        for p in args.xml_dir.glob("*.xml")
        if not p.name.startswith("._") and "__MACOSX" not in p.parts
    )
    if not xml_files:
        raise SystemExit(f"No XML documents found under {args.xml_dir}")

    docs = [document_candidates(p) for p in xml_files]
    docs = [d for d in docs if d["candidates"]]

    prefixes = [d["prefix"] for d in docs]
    if len(set(prefixes)) != len(prefixes):
        raise SystemExit(f"id prefix collision across documents: {sorted(prefixes)}")

    quota = allocate(docs, TARGET_PURE)
    records = course + build_pure_records(docs, quota)

    validate(records)
    print_report(records, docs)

    if args.no_write:
        print("\n[--no-write] no files written.")
        return

    dataset_path, sidecar, runs_path = write_outputs(records, docs)
    print(f"\ndataset    -> {dataset_path.relative_to(REPO_ROOT)}")
    print(f"provenance -> {sidecar.relative_to(REPO_ROOT)}")
    print(f"run log    -> {runs_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
