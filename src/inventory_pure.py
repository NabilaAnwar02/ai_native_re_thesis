"""Inventory the PURE requirements corpus (XML subset).

Parses every ``*.xml`` document under the PURE XML directory and reports, per
document: title, version, explicitly tagged ``<req>`` elements with their IDs
and enclosing section path, structural element counts, and a word count. Emits
a machine-readable manifest plus a run-log entry so the numbers can be cited in
the manuscript rather than retyped from a terminal.

Section paths
-------------
``<req>`` elements carry an ``id`` attribute that restarts per section, so it is
not a document-unique key (in ``2008 - peering``, 24 requirements share 5 IDs).
Each requirement therefore records the chain of enclosing ``<p>`` sections as
both numbers (``"3 > 3.1 > 3.1.1"``) and titles
(``"Specific Requirements > Functional > Login"``), plus two keys:

``uid``        ``<stem>::r0001`` — guaranteed unique, safe as a join key.
``trace_key``  ``<stem>::<section path>::<id>`` — human-readable; collisions are
               counted in the summary rather than silently deduplicated.

Dataset
-------
PURE: A Dataset of Public Requirements Documents.
Ferrari, A., Spagnolo, G. O., & Gnesi, S. (2017). IEEE RE'17.
https://doi.org/10.5281/zenodo.1414117

Only a subset of PURE was manually ported to the common XML schema, and within
that subset only some documents carry ``<req>`` markup at all. Documents with
zero ``<req>`` elements are NOT empty -- their requirements live unmarked in
``<text_body>`` and ``<item>`` prose. See ``untagged_documents`` in the summary.

Usage
-----
    python src/inventory_pure.py
    python src/inventory_pure.py --input-dir data/interim/requirements-xml --pretty
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Bump when the extraction logic changes, so log entries stay attributable.
# 1.1.0 — record the enclosing <p> section path (ids + titles) per requirement.
SCRIPT_VERSION = "1.1.0"
SCRIPT_NAME = "inventory_pure"

# Repo root, assuming this file lives at <root>/src/inventory_pure.py
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = REPO_ROOT / "data" / "interim" / "requirements-xml"
DEFAULT_LOGS_DIR = REPO_ROOT / "data" / "logs"

# Structural elements of the PURE req_document schema worth counting.
COUNTED_ELEMENTS = (
    "req",
    "item",
    "itemize",
    "text_body",
    "p",
    "title",
    "glossary_item",
    "enum",
    "crossref",
)

# Inline requirement labels the authors typed into the text, e.g. "REQ-1:",
# "R 2.4.1", "3.1.2.1". Captured separately from the XML ``id`` attribute
# because the two do not always agree.
INLINE_ID_RE = re.compile(
    r"^\s*((?:REQ|R|FR|NFR)[\s\-_.]*\d+(?:\.\d+)*|\d+(?:\.\d+){1,})\s*[:.\)\-]",
    re.IGNORECASE,
)

WHITESPACE_RE = re.compile(r"\s+")


def local_name(tag: str) -> str:
    """Strip the ``{namespace}`` prefix ElementTree prepends to every tag."""
    return tag.rpartition("}")[2]


def normalize(text: str | None) -> str:
    """Collapse all runs of whitespace to single spaces and trim."""
    return WHITESPACE_RE.sub(" ", text or "").strip()


def element_text(element: ET.Element) -> str:
    """Full text content of an element, including all descendants."""
    return normalize("".join(element.itertext()))


def direct_child_text(root: ET.Element, name: str) -> str:
    """Text of the first direct child named ``name``.

    Deliberately not a recursive search: ``<title>`` appears on every nested
    ``<p>`` section, so a ``//title`` lookup would return a section heading
    instead of the document title.
    """
    for child in root:
        if local_name(child.tag) == name:
            return element_text(child)
    return ""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _build_requirement(
    element: ET.Element,
    sections: list[dict[str, str | None]],
    ordinal: int,
    stem: str,
) -> dict[str, Any]:
    """Assemble one requirement record from its element and ancestor sections."""
    text = element_text(element)
    match = INLINE_ID_RE.match(text)
    xml_id = element.get("id")
    inline_id = match.group(1).strip() if match else None

    path_ids = [s["id"] for s in sections if s["id"]]
    path_titles = [s["title"] for s in sections if s["title"]]
    section_path_ids = " > ".join(path_ids)

    return {
        "ordinal": ordinal,
        # Guaranteed unique within the document; use this to join tables.
        "uid": f"{stem}::r{ordinal:04d}",
        # Readable but NOT guaranteed unique — collisions are counted, not hidden.
        "trace_key": f"{stem}::{section_path_ids or '-'}::{xml_id or inline_id or ordinal}",
        "xml_id": xml_id,
        "inline_id": inline_id,
        "section_path_ids": section_path_ids,
        "section_path_titles": " > ".join(path_titles),
        "section_id": path_ids[-1] if path_ids else None,
        "section_title": path_titles[-1] if path_titles else None,
        "section_depth": len(sections),
        "text": text,
        "char_length": len(text),
    }


def extract_requirements(root: ET.Element, stem: str) -> list[dict[str, Any]]:
    """Depth-first walk collecting every ``<req>`` with its section ancestry.

    ElementTree elements hold no parent reference, so ``root.iter()`` cannot
    reconstruct where a requirement sits in the document. This walk threads a
    stack of enclosing ``<p>`` sections instead. Only ``<p>`` contributes to the
    path; ``<itemize>``/``<item>`` wrappers are traversed but not recorded, so a
    requirement inside a bulleted list still reports its owning section.
    """
    requirements: list[dict[str, Any]] = []

    def walk(element: ET.Element, sections: list[dict[str, str | None]]) -> None:
        for child in element:
            name = local_name(child.tag)
            if name == "req":
                requirements.append(
                    _build_requirement(child, sections, len(requirements) + 1, stem)
                )
            elif name == "p":
                section = {
                    "id": child.get("id"),
                    "title": direct_child_text(child, "title") or None,
                }
                walk(child, sections + [section])
            elif name == "title":
                continue  # section heading, never contains requirements
            else:
                walk(child, sections)

    walk(root, [])
    return requirements


def inventory_document(path: Path) -> dict[str, Any]:
    """Parse one PURE XML document into a manifest record."""
    record: dict[str, Any] = {
        "file": path.name,
        "stem": path.stem,
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
    }

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        record["parse_error"] = str(exc)
        return record

    counts = dict.fromkeys(COUNTED_ELEMENTS, 0)
    for element in root.iter():
        name = local_name(element.tag)
        if name in counts:
            counts[name] += 1

    requirements = extract_requirements(root, path.stem)
    full_text = element_text(root)

    raw_ids = [r["xml_id"] or r["inline_id"] for r in requirements]
    trace_keys = [r["trace_key"] for r in requirements]
    sections_used = {r["section_path_ids"] for r in requirements if r["section_path_ids"]}

    record.update(
        {
            "title": direct_child_text(root, "title"),
            "version": direct_child_text(root, "version"),
            "root_element": local_name(root.tag),
            "element_counts": counts,
            "requirement_count": len(requirements),
            "requirement_ids": raw_ids,
            "unique_requirement_ids": len(set(raw_ids)),
            "duplicate_requirement_ids": len(raw_ids) - len(set(raw_ids)),
            # If this is 0, section path + id is a valid composite key here.
            "trace_key_collisions": len(trace_keys) - len(set(trace_keys)),
            "sections_with_requirements": len(sections_used),
            "max_section_depth": max(
                (r["section_depth"] for r in requirements), default=0
            ),
            "requirements_with_xml_id": sum(
                1 for r in requirements if r["xml_id"]
            ),
            "requirements_with_inline_id": sum(
                1 for r in requirements if r["inline_id"]
            ),
            "requirements": requirements,
            "word_count": len(full_text.split()),
            "char_count": len(full_text),
        }
    )
    return record


def summarize(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Corpus-level rollup across all parsed documents."""
    parsed = [d for d in documents if "parse_error" not in d]
    tagged = [d for d in parsed if d["requirement_count"] > 0]
    untagged = [d for d in parsed if d["requirement_count"] == 0]
    total_reqs = sum(d["requirement_count"] for d in parsed)

    return {
        "document_count": len(documents),
        "parsed_count": len(parsed),
        "failed_count": len(documents) - len(parsed),
        "total_requirements": total_reqs,
        "total_words": sum(d["word_count"] for d in parsed),
        "total_items": sum(d["element_counts"]["item"] for d in parsed),
        "total_text_bodies": sum(d["element_counts"]["text_body"] for d in parsed),
        "documents_with_req_tags": len(tagged),
        "documents_without_req_tags": len(untagged),
        # Named explicitly: these are the documents where requirements must be
        # elicited from unmarked prose, not read off <req> tags.
        "untagged_documents": sorted(d["stem"] for d in untagged),
        "requirements_by_document": {
            d["stem"]: d["requirement_count"]
            for d in sorted(parsed, key=lambda x: -x["requirement_count"])
        },
        # Bare <req id> is not document-unique; section path + id resolves it.
        "total_duplicate_requirement_ids": sum(
            d["duplicate_requirement_ids"] for d in tagged
        ),
        "total_trace_key_collisions": sum(d["trace_key_collisions"] for d in tagged),
        "documents_with_trace_key_collisions": sorted(
            d["stem"] for d in tagged if d["trace_key_collisions"] > 0
        ),
        "max_section_depth": max((d["max_section_depth"] for d in parsed), default=0),
        "max_share_single_document": (
            round(
                max((d["requirement_count"] for d in parsed), default=0)
                / total_reqs,
                4,
            )
            if total_reqs
            else 0.0
        ),
    }


def build_inventory(input_dir: Path) -> dict[str, Any]:
    xml_files = sorted(
        p
        for p in input_dir.rglob("*.xml")
        # macOS archives carry AppleDouble resource forks; they are not documents.
        if not p.name.startswith("._") and "__MACOSX" not in p.parts
    )
    if not xml_files:
        raise SystemExit(f"No XML documents found under {input_dir}")

    documents = [inventory_document(p) for p in xml_files]
    return {
        "script": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_dir": str(input_dir.relative_to(REPO_ROOT)),
        "dataset": "PURE (Ferrari, Spagnolo & Gnesi, RE'17) — XML subset",
        "summary": summarize(documents),
        "documents": documents,
    }


def print_report(inventory: dict[str, Any]) -> None:
    summary = inventory["summary"]
    print(f"PURE XML inventory — {inventory['generated_utc']}")
    print(f"input: {inventory['input_dir']}\n")

    header = f"{'document':<24} {'reqs':>5} {'items':>6} {'words':>7}  title"
    print(header)
    print("-" * len(header))
    for doc in inventory["documents"]:
        if "parse_error" in doc:
            print(f"{doc['stem']:<24} {'ERR':>5}  {doc['parse_error']}")
            continue
        title = doc["title"][:48] + ("…" if len(doc["title"]) > 48 else "")
        print(
            f"{doc['stem']:<24} {doc['requirement_count']:>5} "
            f"{doc['element_counts']['item']:>6} {doc['word_count']:>7}  {title}"
        )

    print()
    print(f"documents            : {summary['document_count']}")
    print(f"parsed / failed      : {summary['parsed_count']} / {summary['failed_count']}")
    print(f"total <req> elements : {summary['total_requirements']}")
    print(f"total words          : {summary['total_words']:,}")
    print(
        f"with / without <req> : {summary['documents_with_req_tags']} / "
        f"{summary['documents_without_req_tags']}"
    )
    print(
        f"largest doc's share  : {summary['max_share_single_document']:.1%} "
        "of all tagged requirements"
    )
    print(
        f"duplicate <req> ids  : {summary['total_duplicate_requirement_ids']} "
        f"(collisions after adding section path: "
        f"{summary['total_trace_key_collisions']})"
    )
    print(f"max section depth    : {summary['max_section_depth']}")

    print("\nSection-path coverage (documents with <req> markup):")
    print(
        f"  {'document':<22} {'reqs':>5} {'sections':>9} {'uniq ids':>9} {'collisions':>11}"
    )
    for doc in inventory["documents"]:
        if doc.get("requirement_count"):
            print(
                f"  {doc['stem']:<22} {doc['requirement_count']:>5} "
                f"{doc['sections_with_requirements']:>9} "
                f"{doc['unique_requirement_ids']:>9} "
                f"{doc['trace_key_collisions']:>11}"
            )

    print("\nExample requirement records:")
    for doc in inventory["documents"]:
        if not doc.get("requirement_count"):
            continue
        sample = doc["requirements"][len(doc["requirements"]) // 2]
        text = sample["text"][:70] + ("…" if len(sample["text"]) > 70 else "")
        print(f"  [{sample['uid']}]")
        print(f"    path  : {sample['section_path_ids'] or '(root)'}")
        print(f"    titles: {sample['section_path_titles'] or '(untitled)'}")
        print(f"    text  : {text}")

    if summary["untagged_documents"]:
        print("\nNo <req> markup (requirements are embedded in prose):")
        for stem in summary["untagged_documents"]:
            print(f"  - {stem}")


def write_outputs(inventory: dict[str, Any], logs_dir: Path, pretty: bool) -> tuple[Path, Path]:
    """Write the full manifest and append a one-line run-log entry."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = inventory["generated_utc"].replace(":", "").replace("-", "")
    manifest_path = logs_dir / f"pure_inventory_{stamp}.json"

    manifest_path.write_text(
        json.dumps(inventory, indent=2 if pretty else None, ensure_ascii=False),
        encoding="utf-8",
    )

    # Per CLAUDE.md: every run leaves a log entry. No model/token fields here --
    # this script is deterministic and makes no LLM calls.
    runs_path = logs_dir / "runs.jsonl"
    entry = {
        "timestamp_utc": inventory["generated_utc"],
        "script": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "run_type": "deterministic_inventory",
        "model": None,
        "input_dir": inventory["input_dir"],
        "output_file": str(manifest_path.relative_to(REPO_ROOT)),
        "summary": inventory["summary"],
    }
    with runs_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return manifest_path, runs_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"directory of PURE XML files (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_LOGS_DIR,
        help=f"where to write the manifest and run log (default: {DEFAULT_LOGS_DIR})",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="indent the JSON manifest (larger file, readable diffs)",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="print the report without writing any files",
    )
    args = parser.parse_args()

    inventory = build_inventory(args.input_dir.resolve())
    print_report(inventory)

    if args.no_write:
        print("\n[--no-write] no files written.")
        return

    manifest_path, runs_path = write_outputs(inventory, args.logs_dir, args.pretty)
    print(f"\nmanifest  -> {manifest_path.relative_to(REPO_ROOT)}")
    print(f"run log   -> {runs_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
