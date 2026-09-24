"""Offline tests for evidence boundaries, complete plans, and abstention."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from loguru import logger
from evaluation.run import ROOT
from llm_pipeline.enhanced_recipe_generator import EnhancedRecipeGenerator
from llm_pipeline.grounding import normalize_amounts, validate_analysis, validate_plan
from llm_pipeline.models import EditPlan, Recipe, Review, ReviewAnalysis
from llm_pipeline.tweak_extractor import TweakExtractor


def response(value):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=json.dumps(value))
    )])


class ExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.disable("llm_pipeline")

    @classmethod
    def tearDownClass(cls):
        logger.enable("llm_pipeline")

    def setUp(self):
        self.recipe = Recipe(recipe_id="test", title="Vegetable stew",
                             ingredients=["1 cup beans", "1 cup water"],
                             instructions=["Simmer beans in water."])
        self.text = "I used 2 cups beans. I omitted the water. Next time I will add cream."
        self.inventory = {"changes": [
            {"id": "beans", "modification_type": "quantity_adjustment", "summary": "Increase beans",
             "evidence": "I used 2 cups beans.", "disposition": "apply",
             "amount": "2 cups", "amount_evidence": "I used 2 cups beans."},
            {"id": "water", "modification_type": "removal", "summary": "Omit water",
             "evidence": "I omitted the water.", "disposition": "apply"},
            {"id": "cream", "modification_type": "addition", "summary": "Add cream later",
             "evidence": "Next time I will add cream.", "disposition": "future_plan"},
        ]}

    def test_unquoted_evidence_and_benefits_are_rejected(self):
        for field in ("evidence", "outcome_evidence"):
            inventory = json.loads(json.dumps(self.inventory))
            if field == "evidence":
                inventory["changes"][0][field] = "These beans are healthier."
            else:
                inventory[field] = "These beans are healthier."
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_analysis(ReviewAnalysis(**inventory), self.text)

    def test_missing_amount_is_deferred_even_if_model_says_apply(self):
        value = {"changes": [{"id": "milk", "modification_type": "ingredient_substitution",
                              "summary": "Use milk", "evidence": "I used milk.", "disposition": "apply"}]}
        analysis = validate_analysis(ReviewAnalysis(**value), "I used milk.")
        self.assertEqual(analysis.changes[0].disposition, "needs_clarification")
        self.assertIn("quantity", analysis.changes[0].clarification)

    def test_milk_percentage_is_not_an_amount(self):
        value = {"changes": [{"id": "milk", "modification_type": "ingredient_substitution",
                              "summary": "Use milk", "evidence": "I used 2% milk.", "disposition": "apply",
                              "amount": "2%", "amount_evidence": "I used 2% milk."}]}
        analysis = validate_analysis(ReviewAnalysis(**value), "I used 2% milk.")
        self.assertEqual(analysis.changes[0].disposition, "needs_clarification")

    def test_future_edits_missing_changes_and_instruction_omissions_rejected(self):
        analysis = validate_analysis(ReviewAnalysis(**self.inventory), self.text)
        for edits in [
            [{"target": "ingredients", "operation": "add_after", "find": "1 cup beans",
              "add": "1 cup cream", "change_ids": ["cream"]}],
            [{"target": "ingredients", "operation": "replace", "find": "1 cup beans",
              "replace": "2 cups beans", "change_ids": ["beans"]}],
            [{"target": "ingredients", "operation": "replace", "find": "1 cup beans",
              "replace": "2 cups beans", "change_ids": ["beans"]},
             {"target": "ingredients", "operation": "remove", "find": "1 cup water", "change_ids": ["water"]}],
        ]:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                validate_plan(EditPlan(edits=edits), analysis, self.recipe)

    def test_invented_numeric_quantity_is_rejected(self):
        analysis = validate_analysis(ReviewAnalysis(**self.inventory), self.text)
        plan = EditPlan(edits=[{"target": "ingredients", "operation": "replace", "find": "1 cup beans",
                               "replace": "99 cups beans", "change_ids": ["beans"]}])
        with self.assertRaises(ValueError):
            validate_plan(plan, analysis, self.recipe)

    def test_deferred_and_future_changes_need_no_planner_call(self):
        text = "I used fresh herbs. Next time I will double the salt."
        inventory = {"changes": [
            {"id": "herbs", "modification_type": "addition", "summary": "Add herbs",
             "evidence": "I used fresh herbs.", "disposition": "needs_clarification",
             "clarification": "Which herbs and how much?"},
            {"id": "salt", "modification_type": "quantity_adjustment", "summary": "Double salt later",
             "evidence": "Next time I will double the salt.", "disposition": "future_plan"},
        ]}
        extractor = TweakExtractor(api_key="offline-test")
        review = Review(text=text, has_modification=True)
        for change in inventory["changes"]:
            change["evidence"] = change["evidence"].rstrip(".")
        with patch.object(extractor.client.chat.completions, "create", return_value=response(inventory)) as create:
            result = extractor.extract_modification(review, self.recipe)
        self.assertEqual(create.call_count, 1)
        from llm_pipeline.prompts import INVENTORY_SYSTEM
        self.assertTrue(all(call.kwargs["messages"][0]["content"] == INVENTORY_SYSTEM for call in create.call_args_list))
        self.assertEqual(result.edits, [])
        enhanced = EnhancedRecipeGenerator().generate_enhanced_recipe(self.recipe, self.recipe, result, review, [])
        self.assertEqual(enhanced.enhancement_status, "needs_clarification")
        self.assertEqual(enhanced.modifications_applied, [])
        self.assertEqual(enhanced.ingredients, self.recipe.ingredients)
        self.assertEqual(enhanced.enhancement_summary.expected_impact, "No benefit established by this pipeline.")

    def test_invalid_plan_defers_all_actionable_changes_without_partial_edits(self):
        extractor = TweakExtractor(api_key="offline-test")
        with patch.object(extractor, "_extract_analysis", return_value=validate_analysis(ReviewAnalysis(**self.inventory), self.text)), patch.object(
            extractor.client.chat.completions, "create", return_value=response({"edits": []})
        ):
            result = extractor.extract_modification(Review(text=self.text, has_modification=True), self.recipe, max_retries=0)
        self.assertEqual(result.edits, [])
        self.assertEqual([c.disposition for c in result.analysis.changes],
                         ["needs_clarification", "needs_clarification", "future_plan"])

    def test_validation_feedback_retries_with_same_model(self):
        extractor = TweakExtractor(api_key="offline-test")
        with patch.object(extractor.client.chat.completions, "create", side_effect=[
            response({"changes": [], "outcome_evidence": "Made it healthier"}),
            response({"changes": []}),
        ]) as create:
            result = extractor._request_validated("test", "Great as written.", ReviewAnalysis,
                                                   lambda value: validate_analysis(value, "Great as written."), 2)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(result.changes, [])
        self.assertTrue(all(call.kwargs["model"] == "gpt-6-luna" for call in create.call_args_list))
        self.assertEqual(create.call_args.kwargs["reasoning_effort"], "none")
        self.assertIn("max_completion_tokens", create.call_args.kwargs)
        self.assertNotIn("max_tokens", create.call_args.kwargs)
        self.assertIn("Validation failed", create.call_args.kwargs["messages"][-1]["content"])

    def test_equivalent_amount_notation_does_not_change_units(self):
        for amount in ("one-and-a-half cups", "1 1/2 cups", "1.5 cups"):
            self.assertEqual(normalize_amounts(amount), "1.5 cup")
        for amount in ("a half cup", "half a cup", "1/2 cup", "0.5 cups"):
            self.assertEqual(normalize_amounts(amount), "0.5 cup")
        self.assertNotEqual(normalize_amounts("1 teaspoon"), normalize_amounts("1 tablespoon"))

    def test_future_phrase_cannot_be_marked_tried(self):
        inventory = json.loads(json.dumps(self.inventory))
        inventory["changes"][2]["disposition"] = "apply"
        with self.assertRaisesRegex(ValueError, "future-intent"):
            validate_analysis(ReviewAnalysis(**inventory), self.text)

    def test_coverage_catches_omitted_shorthand_and_compound_change(self):
        incomplete = {"changes": [{"id": "herbs", "modification_type": "addition", "summary": "Add basil",
                                   "evidence": "Used basil", "disposition": "needs_clarification",
                                   "clarification": "How much?"}]}
        with self.assertRaisesRegex(ValueError, "Unaccounted change clause"):
            validate_analysis(ReviewAnalysis(**incomplete), "Even w skim milk. Used basil.")
        compound = {"changes": [{"id": "grains", "modification_type": "quantity_adjustment", "summary": "Change grains",
                                 "evidence": "I used half a cup oats and two cups raisins", "disposition": "apply",
                                 "amount": "half a cup", "amount_evidence": "half a cup oats"}]}
        with self.assertRaisesRegex(ValueError, "Compound change"):
            validate_analysis(ReviewAnalysis(**compound), "I used half a cup oats and two cups raisins")

    def test_supported_substitution_updates_ingredient_and_directions(self):
        from llm_pipeline.recipe_modifier import RecipeModifier
        text = "I used two cups lentils instead of beans."
        inventory = ReviewAnalysis(changes=[{
            "id": "c1", "modification_type": "ingredient_substitution", "summary": "Use lentils",
            "evidence": text, "disposition": "apply", "amount": "two cups", "amount_evidence": text,
        }])
        plan = {"ingredients": ["2 cups lentils", "1 cup water"], "instructions": ["Simmer lentils in water."]}
        extractor = TweakExtractor(api_key="offline-test")
        with patch.object(extractor, "_extract_analysis", return_value=inventory), patch.object(
            extractor.client.chat.completions, "create", return_value=response(plan)
        ):
            result = extractor.extract_modification(Review(text=text, has_modification=True), self.recipe)
        modified, records = RecipeModifier().apply_modification(self.recipe, result)
        self.assertEqual(modified.ingredients, ["2 cups lentils", "1 cup water"])
        self.assertEqual(modified.instructions, ["Simmer lentils in water."])
        self.assertEqual(len(records), 2)
        self.assertEqual(result.edit_sources, [["c1"], ["c1"]])
        self.assertIn(text, result.reasoning)

    def test_quantity_change_cannot_add_a_second_ingredient_use(self):
        analysis = ReviewAnalysis(changes=[self.inventory["changes"][0]])
        recipe = self.recipe.model_copy(update={"instructions": ["Simmer beans in water.", "Serve with herbs."]})
        plan = EditPlan(edits=[
            {"target": "ingredients", "operation": "replace", "find": "1 cup beans", "replace": "2 cups beans", "change_ids": ["beans"]},
            {"target": "instructions", "operation": "replace", "find": "Serve with herbs.", "replace": "Serve with herbs and 2 cups beans.", "change_ids": ["beans"]},
        ])
        with self.assertRaisesRegex(ValueError, "new ingredient-use"):
            validate_plan(plan, analysis, recipe)

    def test_technique_ordering_requires_preparation_before_new_step(self):
        recipe = self.recipe.model_copy(update={"instructions": ["Mix beans with water.", "Shape patties.", "Fry patties."]})
        analysis = ReviewAnalysis(changes=[{
            "id": "chill", "modification_type": "technique_change", "summary": "Chill patties",
            "evidence": "I chilled the patties for 1 hour before frying.", "disposition": "apply",
        }])
        for anchor, valid in [("Mix beans with water.", False), ("Shape patties.", True)]:
            plan = EditPlan(edits=[{"target": "instructions", "operation": "add_after", "find": anchor,
                                   "add": "Chill the patties for 1 hour.", "change_ids": ["chill"]}])
            if valid:
                self.assertEqual(len(validate_plan(plan, analysis, recipe)[0]), 1)
            else:
                with self.assertRaisesRegex(ValueError, "immediately before"):
                    validate_plan(plan, analysis, recipe)

    def test_removal_keeps_directions_for_unchanged_ingredients(self):
        analysis = ReviewAnalysis(changes=[self.inventory["changes"][1]])
        plan = EditPlan(edits=[
            {"target": "ingredients", "operation": "remove", "find": "1 cup water", "change_ids": ["water"]},
            {"target": "instructions", "operation": "replace", "find": "Simmer beans in water.",
             "replace": "Serve.", "change_ids": ["water"]},
        ])
        with self.assertRaisesRegex(ValueError, "unchanged ingredient 'beans'"):
            validate_plan(plan, analysis, self.recipe)

    def test_removal_cannot_rewrite_an_unrelated_step(self):
        recipe = self.recipe.model_copy(update={"instructions": ["Simmer beans in water.", "Serve warm."]})
        analysis = ReviewAnalysis(changes=[self.inventory["changes"][1]])
        plan = EditPlan(edits=[
            {"target": "ingredients", "operation": "remove", "find": "1 cup water", "change_ids": ["water"]},
            {"target": "instructions", "operation": "replace", "find": "Simmer beans in water.", "replace": "Cook beans.", "change_ids": ["water"]},
            {"target": "instructions", "operation": "replace", "find": "Serve warm.", "replace": "Serve hot.", "change_ids": ["water"]},
        ])
        with self.assertRaisesRegex(ValueError, "unrelated instruction"):
            validate_plan(plan, analysis, recipe)

    def test_compound_actions_and_resting_are_not_lost(self):
        extractor = TweakExtractor(api_key="offline-test")
        text = "I added two eggs and omitted the water. I let the mixture rest for an hour."
        inventory = {"changes": [
            {"id": "eggs", "modification_type": "addition", "summary": "Add eggs", "evidence": "I added two eggs", "disposition": "apply"},
            {"id": "water", "modification_type": "removal", "summary": "Omit water", "evidence": "omitted the water", "disposition": "apply"},
            {"id": "rest", "modification_type": "technique_change", "summary": "Rest mixture", "evidence": "I let the mixture rest for an hour", "disposition": "apply"},
        ]}
        with patch.object(extractor.client.chat.completions, "create", return_value=response(inventory)) as create:
            analysis = extractor._extract_analysis(Review(text=text, has_modification=True), self.recipe, 0)
        self.assertEqual(create.call_count, 1)
        self.assertEqual([c.modification_type for c in analysis.changes], ["addition", "removal", "technique_change"])
        self.assertTrue(all(c.disposition == "apply" for c in analysis.changes))
        self.assertTrue(all(c.evidence in text for c in analysis.changes))

    def test_vague_quantity_is_retained_for_clarification(self):
        extractor = TweakExtractor(api_key="offline-test")
        text = "I reduced the beans a bit."
        inventory = {"changes": [{"id": "beans", "modification_type": "quantity_adjustment", "summary": "Reduce beans", "evidence": text, "disposition": "apply"}]}
        with patch.object(extractor.client.chat.completions, "create", return_value=response(inventory)):
            analysis = extractor._extract_analysis(Review(text=text, has_modification=True), self.recipe, 0)
        self.assertEqual(len(analysis.changes), 1)
        self.assertEqual(analysis.changes[0].disposition, "needs_clarification")
        self.assertIsNone(analysis.changes[0].amount)


if __name__ == "__main__":
    unittest.main()
