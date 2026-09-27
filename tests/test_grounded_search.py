import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grounded_search import (  # noqa: E402
    SourceCheckError,
    load_documents,
    resolve_result,
    review_packet,
    search,
)


class SourceLinkedSearchTests(unittest.TestCase):
    def setUp(self):
        self.documents = load_documents()

    def test_result_points_to_exact_current_source_line(self):
        result = search("expense approval limit", "staff", self.documents)[0]
        self.assertEqual(result["source_id"], "POL-101")
        self.assertEqual(
            resolve_result(result, "staff", self.documents),
            result["excerpt"],
        )

    def test_access_is_filtered_before_ranking(self):
        packet = review_packet("board-only strategy", "staff", self.documents)
        self.assertEqual(packet["status"], "no_source_found")
        self.assertEqual(packet["results"], [])

    def test_access_is_checked_again_when_opening_source(self):
        result = search("board-only strategy", "board", self.documents)[0]
        with self.assertRaisesRegex(SourceCheckError, "access denied"):
            resolve_result(result, "staff", self.documents)

    def test_changed_source_cannot_support_old_result(self):
        result = search("expense approval limit", "staff", self.documents)[0]
        changed = dataclasses.replace(self.documents[0], body="The approval rule changed.")
        with self.assertRaisesRegex(SourceCheckError, "content changed"):
            resolve_result(result, "staff", [changed, *self.documents[1:]])

    def test_fabricated_excerpt_is_rejected(self):
        result = search("expense approval limit", "staff", self.documents)[0]
        result["excerpt"] = "The system approves everything automatically."
        with self.assertRaisesRegex(SourceCheckError, "does not match"):
            resolve_result(result, "staff", self.documents)

    def test_missing_source_is_rejected(self):
        result = search("expense approval limit", "staff", self.documents)[0]
        with self.assertRaisesRegex(SourceCheckError, "missing or ambiguous"):
            resolve_result(result, "staff", self.documents[1:])

    def test_changed_version_is_rejected_even_when_text_is_unchanged(self):
        result = search("expense approval limit", "staff", self.documents)[0]
        changed = dataclasses.replace(self.documents[0], version="2026-02")
        with self.assertRaisesRegex(SourceCheckError, "version changed"):
            resolve_result(result, "staff", [changed, *self.documents[1:]])

    def test_changed_title_is_rejected(self):
        result = search("expense approval limit", "staff", self.documents)[0]
        changed = dataclasses.replace(self.documents[0], title="A different document")
        with self.assertRaisesRegex(SourceCheckError, "title changed"):
            resolve_result(result, "staff", [changed, *self.documents[1:]])

    def test_extra_result_field_is_rejected(self):
        result = search("expense approval limit", "staff", self.documents)[0]
        result["approved"] = True
        with self.assertRaisesRegex(SourceCheckError, "invalid result fields"):
            resolve_result(result, "staff", self.documents)

    def test_unknown_group_sees_no_results(self):
        packet = review_packet("expense approval limit", "unknown", self.documents)
        self.assertEqual(packet["status"], "no_source_found")
        self.assertEqual(packet["results"], [])

    def test_tie_order_is_stable(self):
        first = search("expenses approval", "staff", self.documents)
        second = search("expenses approval", "staff", list(reversed(self.documents)))
        self.assertEqual(first, second)

    def test_invalid_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "limit must be positive"):
            search("expense", "staff", self.documents, limit=0)

    def test_duplicate_source_ids_are_rejected_at_load(self):
        rows = json.loads((Path(__file__).resolve().parents[1] / "examples" / "documents.json").read_text())
        rows[1]["source_id"] = rows[0]["source_id"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            with self.assertRaisesRegex(SourceCheckError, "duplicate source ID"):
                load_documents(path)

    def test_malformed_access_groups_are_rejected_at_load(self):
        rows = json.loads((Path(__file__).resolve().parents[1] / "examples" / "documents.json").read_text())
        rows[0]["allowed_groups"] = "staff"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            with self.assertRaisesRegex(SourceCheckError, "invalid access groups"):
                load_documents(path)


if __name__ == "__main__":
    unittest.main()
