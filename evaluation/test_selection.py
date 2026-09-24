"""Offline selection tests; no LLM or star-rating-based ranking."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from loguru import logger
from evaluation.run import ROOT, load_case
from llm_pipeline.models import ModificationObject, Review, ReviewAnalysis
from llm_pipeline.pipeline import LLMAnalysisPipeline
from llm_pipeline.review_selector import select_review


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.disable("llm_pipeline")

    @classmethod
    def tearDownClass(cls):
        logger.enable("llm_pipeline")

    def test_featured_precedes_more_popular_regular_review(self):
        featured = Review(text="Featured", source="featured_tweaks", vote_count=1)
        regular = Review(text="Regular", has_modification=True, vote_count=100, rating=5)
        self.assertEqual(select_review([regular, featured]).text, "Featured")

    def test_missing_votes_use_stored_order_never_ratings(self):
        reviews = [Review(text="First", source="featured_tweaks", rating=1),
                   Review(text="Second", source="featured_tweaks", rating=5)]
        for _ in range(5):
            chosen = select_review(reviews)
            self.assertEqual(chosen.text, "First")
            self.assertEqual(chosen.selection.method, "source_order")
            self.assertIn("Highest-voted status is unknown", chosen.selection.reason)
        self.assertIsNone(reviews[0].selection)  # No mutation of source inputs.

    def test_complete_counts_rank_votes_and_break_ties_in_source_order(self):
        reviews = [Review(text="Zero", source="featured_tweaks", vote_count=0, rating=5),
                   Review(text="First winner", source="featured_tweaks", vote_count=9, rating=1),
                   Review(text="Second winner", source="featured_tweaks", vote_count=9, rating=5)]
        chosen = select_review(reviews)
        self.assertEqual(chosen.text, "First winner")
        self.assertEqual(chosen.selection.method, "highest_available_vote_count")
        self.assertEqual(chosen.selection.eligible_count, 3)

    def test_partial_vote_coverage_is_not_ranked(self):
        reviews = [Review(text="Unknown", source="featured_tweaks"),
                   Review(text="Known", source="featured_tweaks", vote_count=100)]
        chosen = select_review(reviews)
        self.assertEqual(chosen.text, "Unknown")
        self.assertEqual(chosen.selection.method, "source_order")

    def test_empty_featured_falls_back_to_first_nonblank_flagged_review(self):
        reviews = [Review(text="  ", source="featured_tweaks"), Review(text="Praise", rating=5),
                   Review(text="First tweak", has_modification=True, rating=2),
                   Review(text="Later tweak", has_modification=True, rating=5)]
        chosen = select_review(reviews)
        self.assertEqual(chosen.text, "First tweak")
        self.assertEqual(chosen.selection.source, "reviews")
        self.assertIn("falling back", chosen.selection.reason)
        self.assertIsNone(select_review(reviews[:2]))

    def test_invalid_vote_values_are_missing_and_original_indices_survive(self):
        raw = {"featured_tweaks": [{"text": " "}] + [
            {"text": f"Tweak {i}", "vote_count": v} for i, v in enumerate([True, -1, "20", 3.5, None, 0])
        ]}
        with TemporaryDirectory() as directory:
            pipeline = LLMAnalysisPipeline(openai_api_key="offline", output_dir=directory)
            reviews = pipeline.parse_reviews_data(raw)
        self.assertEqual([r.vote_count for r in reviews], [None, None, None, None, None, 0])
        chosen = select_review(reviews)
        self.assertEqual(chosen.selection.source_index, 1)
        self.assertEqual(chosen.selection.method, "source_order")

    def test_featured_only_recipe_reaches_extraction_and_keeps_selection_on_deferral(self):
        raw = {"recipe_id": "test", "title": "Test", "ingredients": ["1 cup milk"],
               "instructions": ["Heat milk."], "featured_tweaks": [{"text": "Used oat milk."}]}
        modification = ModificationObject(modification_type="ingredient_substitution", reasoning="No amount supplied", edits=[],
            analysis=ReviewAnalysis(changes=[{"id": "milk", "modification_type": "ingredient_substitution",
                "summary": "Used oat milk", "evidence": "Used oat milk.", "disposition": "needs_clarification",
                "clarification": "How much?"}]))
        with TemporaryDirectory() as directory:
            pipeline = LLMAnalysisPipeline(openai_api_key="offline", output_dir=directory)
            with patch.object(pipeline, "load_recipe_data", return_value=raw), patch.object(
                pipeline.tweak_extractor, "extract_modification", return_value=modification,
            ) as extract:
                result = pipeline.process_single_recipe("unused", save_output=False)
        extract.assert_called_once()
        self.assertEqual(result.enhancement_status, "needs_clarification")
        self.assertEqual(result.review_selection.review_text, "Used oat milk.")
        self.assertEqual(result.review_selection.source, "featured_tweaks")
        self.assertEqual(result.modifications_applied, [])

    def test_supplied_recipes_use_first_featured_without_claiming_votes(self):
        with TemporaryDirectory() as directory:
            pipeline = LLMAnalysisPipeline(openai_api_key="offline", output_dir=directory)
            for path in sorted((ROOT / "data").glob("recipe_*.json")):
                raw = json.loads(path.read_text())
                selected = select_review(pipeline.parse_reviews_data(raw))
                with self.subTest(recipe=path.name):
                    if raw["featured_tweaks"]:
                        self.assertEqual(selected.text, raw["featured_tweaks"][0]["text"])
                        self.assertEqual(selected.selection.method, "source_order")
                        self.assertIsNone(selected.selection.vote_count)
                    else:
                        self.assertIsNone(selected)

    def test_evaluation_pins_both_sources_instead_of_changing_its_review(self):
        cases = json.loads((ROOT / "evaluation/cases.json").read_text())["cases"]
        for case in cases[:2]:
            raw = load_case(case)
            for source in ("reviews", "featured_tweaks"):
                self.assertTrue(all(r["text"] == case["review_text"] for r in raw[source]))


if __name__ == "__main__":
    unittest.main()
