"""Local source-verified search over invented documents. No network or model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXAMPLE_DOCUMENTS = Path(__file__).parent / "examples" / "documents.json"


class SourceCheckError(ValueError):
    """A result cannot be trusted against the current source set."""


@dataclass(frozen=True)
class Document:
    source_id: str
    title: str
    version: str
    allowed_groups: frozenset[str]
    body: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    @property
    def lines(self) -> list[str]:
        return self.body.splitlines()


def load_documents(path: Path = EXAMPLE_DOCUMENTS) -> list[Document]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SourceCheckError("document set must be a list")

    required = {"source_id", "title", "version", "allowed_groups", "body"}
    documents = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != required:
            raise SourceCheckError(f"invalid document fields at index {index}")
        if any(not isinstance(row[key], str) or not row[key].strip()
               for key in ("source_id", "title", "version", "body")):
            raise SourceCheckError(f"invalid document text at index {index}")
        groups = row["allowed_groups"]
        if (not isinstance(groups, list) or not groups
                or any(not isinstance(group, str) or not group.strip() for group in groups)
                or len(groups) != len(set(groups))):
            raise SourceCheckError(f"invalid access groups at index {index}")
        documents.append(Document(
            source_id=row["source_id"],
            title=row["title"],
            version=row["version"],
            allowed_groups=frozenset(groups),
            body=row["body"],
        ))
    ids = [document.source_id for document in documents]
    if len(ids) != len(set(ids)):
        raise SourceCheckError("duplicate source ID")
    return documents


def terms(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


def search(
    query: str, group: str, documents: list[Document], limit: int = 3
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    query_terms = terms(query)
    if not query_terms:
        return []

    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for document in documents:
        if group not in document.allowed_groups:
            continue
        for line_number, line in enumerate(document.lines, start=1):
            overlap = len(query_terms & terms(line))
            if overlap == 0:
                continue
            result = {
                "source_id": document.source_id,
                "title": document.title,
                "version": document.version,
                "line": line_number,
                "excerpt": line,
                "body_sha256": document.sha256,
            }
            candidates.append((overlap, document.source_id, result))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]["line"]))
    return [item[2] for item in candidates[:limit]]


def resolve_result(
    result: dict[str, Any], group: str, documents: list[Document]
) -> str:
    expected_fields = {"source_id", "title", "version", "line", "excerpt", "body_sha256"}
    if not isinstance(result, dict) or set(result) != expected_fields:
        raise SourceCheckError("invalid result fields")
    matches = [doc for doc in documents if doc.source_id == result.get("source_id")]
    if len(matches) != 1:
        raise SourceCheckError("source ID is missing or ambiguous")
    document = matches[0]
    if group not in document.allowed_groups:
        raise SourceCheckError("source access denied")
    if result.get("title") != document.title:
        raise SourceCheckError("source title changed")
    if result.get("version") != document.version:
        raise SourceCheckError("source version changed")
    if result.get("body_sha256") != document.sha256:
        raise SourceCheckError("source content changed")
    line_number = result.get("line")
    if not isinstance(line_number, int) or isinstance(line_number, bool):
        raise SourceCheckError("invalid source line")
    if line_number < 1 or line_number > len(document.lines):
        raise SourceCheckError("source line is missing")
    line = document.lines[line_number - 1]
    if result.get("excerpt") != line:
        raise SourceCheckError("excerpt does not match source")
    return line


def review_packet(
    query: str, group: str, documents: list[Document]
) -> dict[str, Any]:
    results = search(query, group, documents)
    for result in results:
        resolve_result(result, group, documents)
    return {
        "status": "review_required" if results else "no_source_found",
        "query": query,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Words to find in the fictional documents")
    parser.add_argument("--group", required=True, help="Caller's access group")
    parser.add_argument("--documents", type=Path, default=EXAMPLE_DOCUMENTS)
    args = parser.parse_args()
    print(json.dumps(review_packet(args.query, args.group, load_documents(args.documents)), indent=2))


if __name__ == "__main__":
    main()
