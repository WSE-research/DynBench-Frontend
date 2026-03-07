"""Tests for sample_selector.py."""
import unittest
from unittest.mock import patch

from sample_selector import (
    select_sample,
    build_samples_by_id,
    build_samples_by_language,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

EN1 = {"id": "train:1", "language": "en", "question": "Q1-en", "query": "SELECT 1"}
DE1 = {"id": "train:1", "language": "de", "question": "Q1-de", "query": "SELECT 1"}
EN2 = {"id": "train:2", "language": "en", "question": "Q2-en", "query": "SELECT 2"}
RU3 = {"id": "train:3", "language": "ru", "question": "Q3-ru", "query": "SELECT 3"}

SAMPLES = [EN1, DE1, EN2, RU3]

BY_ID = build_samples_by_id(SAMPLES)
BY_LANG = build_samples_by_language(SAMPLES)


# ---------------------------------------------------------------------------
# build_samples_by_id
# ---------------------------------------------------------------------------

class TestBuildSamplesById(unittest.TestCase):

    def test_groups_multiple_language_variants(self):
        result = build_samples_by_id(SAMPLES)
        self.assertEqual(set(result.keys()), {"train:1", "train:2", "train:3"})
        self.assertCountEqual(result["train:1"], [EN1, DE1])

    def test_single_variant_stored_as_list(self):
        result = build_samples_by_id(SAMPLES)
        self.assertEqual(result["train:2"], [EN2])

    def test_empty_input(self):
        self.assertEqual(build_samples_by_id([]), {})


# ---------------------------------------------------------------------------
# build_samples_by_language
# ---------------------------------------------------------------------------

class TestBuildSamplesByLanguage(unittest.TestCase):

    def test_groups_by_language(self):
        result = build_samples_by_language(SAMPLES)
        self.assertCountEqual(result["en"], [EN1, EN2])
        self.assertEqual(result["de"], [DE1])
        self.assertEqual(result["ru"], [RU3])

    def test_empty_input(self):
        self.assertEqual(build_samples_by_language([]), {})


# ---------------------------------------------------------------------------
# select_sample — both params present
# ---------------------------------------------------------------------------

class TestSelectSampleBothParams(unittest.TestCase):

    def test_exact_match_found(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:1", "en")
        self.assertEqual(result, EN1)

    def test_exact_match_other_language(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:1", "de")
        self.assertEqual(result, DE1)

    def test_id_exists_but_language_missing(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:1", "fr")
        self.assertIsNone(result)

    def test_id_missing(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:99", "en")
        self.assertIsNone(result)

    def test_both_missing(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:99", "fr")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# select_sample — only sample_id
# ---------------------------------------------------------------------------

class TestSelectSampleOnlyId(unittest.TestCase):

    def test_returns_one_of_the_language_variants(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:1", None)
        self.assertIn(result, [EN1, DE1])

    def test_single_variant_always_returned(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:2", None)
        self.assertEqual(result, EN2)

    def test_unknown_id_returns_none(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:99", None)
        self.assertIsNone(result)

    def test_randomness_uses_random_choice(self):
        with patch("sample_selector.random.choice", return_value=DE1) as mock_choice:
            result = select_sample(SAMPLES, BY_ID, BY_LANG, "train:1", None)
        mock_choice.assert_called_once_with([EN1, DE1])
        self.assertEqual(result, DE1)


# ---------------------------------------------------------------------------
# select_sample — only sample_language
# ---------------------------------------------------------------------------

class TestSelectSampleOnlyLanguage(unittest.TestCase):

    def test_returns_sample_in_given_language(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, None, "en")
        self.assertIn(result, [EN1, EN2])

    def test_single_item_language(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, None, "ru")
        self.assertEqual(result, RU3)

    def test_unknown_language_returns_none(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, None, "xx")
        self.assertIsNone(result)

    def test_randomness_uses_random_choice(self):
        with patch("sample_selector.random.choice", return_value=EN2) as mock_choice:
            result = select_sample(SAMPLES, BY_ID, BY_LANG, None, "en")
        mock_choice.assert_called_once_with([EN1, EN2])
        self.assertEqual(result, EN2)


# ---------------------------------------------------------------------------
# select_sample — neither param, random_fallback
# ---------------------------------------------------------------------------

class TestSelectSampleNoParams(unittest.TestCase):

    def test_no_params_no_fallback_returns_none(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, None, None, random_fallback=False)
        self.assertIsNone(result)

    def test_no_params_with_fallback_returns_a_sample(self):
        result = select_sample(SAMPLES, BY_ID, BY_LANG, None, None, random_fallback=True)
        self.assertIn(result, SAMPLES)

    def test_no_params_fallback_empty_samples_returns_none(self):
        result = select_sample([], {}, {}, None, None, random_fallback=True)
        self.assertIsNone(result)

    def test_fallback_uses_random_choice(self):
        with patch("sample_selector.random.choice", return_value=RU3) as mock_choice:
            result = select_sample(SAMPLES, BY_ID, BY_LANG, None, None, random_fallback=True)
        mock_choice.assert_called_once_with(SAMPLES)
        self.assertEqual(result, RU3)


if __name__ == "__main__":
    unittest.main()
