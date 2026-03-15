"""
Tests for utils.py — call_dynbench response normalisation.
"""
import sys
import unittest
from unittest.mock import MagicMock, patch


def _make_response(status_code: int, body: dict) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    mock.text = str(body)
    return mock


# ---------------------------------------------------------------------------
# call_dynbench — import with Streamlit mocked out
# ---------------------------------------------------------------------------

with patch.dict(sys.modules, {"streamlit": MagicMock()}):
    import utils as _utils


class TestCallDynbenchNormalisation(unittest.TestCase):
    """Verify that call_dynbench normalises various backend response shapes."""

    _URL = "http://mock-backend/transform"
    _ARGS = ("question text", "SELECT ?x WHERE {}", "gpt-4o")

    def _call(self, body: dict):
        resp = _make_response(200, body)
        with patch.object(_utils.requests, "post", return_value=resp):
            return _utils.call_dynbench(self._URL, *self._ARGS)

    # --- top-level snake_case keys (original format) ---

    def test_top_level_keys_returned_unchanged(self):
        body = {"transformed_question": "Q?", "transformed_query": "SELECT ?x {}"}
        result, error = self._call(body)
        self.assertIsNone(error)
        self.assertEqual(result["transformed_question"], "Q?")
        self.assertEqual(result["transformed_query"], "SELECT ?x {}")

    # --- attempts-based format (new backend response) ---

    def test_extracts_from_successful_attempt(self):
        body = {
            "attempts": [
                {
                    "Status": "failure",
                    "Transformed question": "wrong",
                    "Transformed query": "wrong",
                },
                {
                    "Status": "success",
                    "Transformed question": "Who was the father of King Trajan?",
                    "Transformed query": "SELECT ?uri WHERE { wd:Q1425 wdt:P22 ?uri }",
                },
            ],
            "selected_replace": {
                "old_entity": "wd:Q9682",
                "new_entity": "wd:Q1425",
                "old_label": "Elizabeth II",
                "new_label": "Trajan",
                "old_pagerank": 757.1678,
                "new_pagerank": 235.1549,
            },
        }
        result, error = self._call(body)
        self.assertIsNone(error)
        self.assertEqual(result["transformed_question"], "Who was the father of King Trajan?")
        self.assertEqual(result["transformed_query"], "SELECT ?uri WHERE { wd:Q1425 wdt:P22 ?uri }")

    def test_falls_back_to_last_attempt_when_no_success_status(self):
        body = {
            "attempts": [
                {
                    "Transformed question": "Last Q?",
                    "Transformed query": "SELECT ?last {}",
                },
            ],
        }
        result, error = self._call(body)
        self.assertIsNone(error)
        self.assertEqual(result["transformed_question"], "Last Q?")

    def test_builds_selected_replace_from_attempt_when_absent_at_top_level(self):
        body = {
            "attempts": [{
                "Status": "success",
                "Transformed question": "Q?",
                "Transformed query": "SELECT ?x {}",
                "Original entity": "wd:Q9682",
                "New entity": "wd:Q1425",
                "Label for original entity": "Elizabeth II",
                "Label for new entity": "Trajan",
                "Original entity PageRank": 757.1678,
                "New entity PageRank": 235.1549,
            }],
            # no top-level "selected_replace"
        }
        result, error = self._call(body)
        self.assertIsNone(error)
        sr = result.get("selected_replace")
        self.assertIsNotNone(sr)
        self.assertEqual(sr["old_entity"], "wd:Q9682")
        self.assertEqual(sr["new_entity"], "wd:Q1425")
        self.assertEqual(sr["old_label"], "Elizabeth II")
        self.assertEqual(sr["new_label"], "Trajan")
        self.assertEqual(sr["old_pagerank"], 757.1678)
        self.assertEqual(sr["new_pagerank"], 235.1549)

    def test_top_level_selected_replace_takes_precedence_over_attempt(self):
        sr_top = {"old_entity": "top", "new_entity": "top", "old_label": "Top",
                  "new_label": "Top", "old_pagerank": 1, "new_pagerank": 2}
        body = {
            "attempts": [{
                "Status": "success",
                "Transformed question": "Q?",
                "Transformed query": "SELECT ?x {}",
                "Original entity": "wd:Q_attempt",
                "Label for original entity": "Attempt entity",
            }],
            "selected_replace": sr_top,
        }
        result, error = self._call(body)
        self.assertIsNone(error)
        self.assertEqual(result["selected_replace"], sr_top)

    def test_selected_replace_preserved_in_result(self):
        sr = {
            "old_entity": "wd:Q9682",
            "new_entity": "wd:Q1425",
            "old_label": "Elizabeth II",
            "new_label": "Trajan",
            "old_pagerank": 757.1678,
            "new_pagerank": 235.1549,
        }
        body = {
            "attempts": [{
                "Status": "success",
                "Transformed question": "Q?",
                "Transformed query": "SELECT ?x {}",
            }],
            "selected_replace": sr,
        }
        result, error = self._call(body)
        self.assertIsNone(error)
        self.assertEqual(result["selected_replace"], sr)

    def test_returns_error_when_no_question_anywhere(self):
        body = {"attempts": [{"Transformed query": "SELECT ?x {}"}]}
        result, error = self._call(body)
        self.assertIsNone(result)
        self.assertIn("transformed_question", error)

    def test_returns_error_when_attempts_empty(self):
        body = {"attempts": []}
        result, error = self._call(body)
        self.assertIsNone(result)
        self.assertIsNotNone(error)

    # --- HTTP error ---

    def test_returns_error_on_http_failure(self):
        resp = _make_response(500, {})
        resp.text = "Internal Server Error"
        with patch.object(_utils.requests, "post", return_value=resp):
            result, error = _utils.call_dynbench(self._URL, *self._ARGS)
        self.assertIsNone(result)
        self.assertIn("500", error)


if __name__ == "__main__":
    unittest.main()
