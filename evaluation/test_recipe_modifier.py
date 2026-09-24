"""Offline regressions for safe editing and truthful change records."""

import unittest

from loguru import logger
from evaluation.run import audit_records
from llm_pipeline.models import ModificationEdit, ModificationObject, Recipe
from llm_pipeline.recipe_modifier import RecipeModifier


class RecipeModifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.disable("llm_pipeline")

    @classmethod
    def tearDownClass(cls):
        logger.enable("llm_pipeline")

    def setUp(self):
        self.modifier = RecipeModifier()

    def assert_edit(self, before, expected, *, records_count=1, **kwargs):
        original = list(before)
        edit = ModificationEdit(**kwargs)
        actual, records = self.modifier.apply_edit(edit, before)
        self.assertEqual(before, original, "input mutated")
        self.assertEqual(actual, expected)
        self.assertEqual(len(records), records_count)
        self.assertTrue(audit_records(original, actual, records, edit.target)["passed"])

    def test_case_variant_replaces_actual_matched_span(self):
        self.assert_edit(
            ["2 tablespoons lemon juice", "1 cup grated carrots"],
            ["1 tablespoon lemon juice", "1 cup grated carrots"],
            target="ingredients", operation="replace", find="2 Tablespoons Lemon Juice",
            replace="1 tablespoon lemon juice",
        )

    def test_short_literal_span_preserves_rest_of_instruction(self):
        line = "Spread carrots on a tray and roast at 200 C for 25 minutes, turning halfway through cooking."
        self.assert_edit([line], [line.replace("200 C", "220 C")],
                         target="instructions", operation="replace", find="200 C", replace="220 C")

    def test_missing_ingredient_does_not_remove_similar_ingredient(self):
        lines = ["1 cup sunflower seeds", "2 cups rolled oats"]
        self.assert_edit(lines, lines, records_count=0, target="ingredients",
                         operation="remove", find="1 cup pumpkin seeds")

    def test_all_operations_reject_missing_empty_or_ambiguous_targets(self):
        for operation in ("replace", "add_after", "remove"):
            for find, lines in [
                ("nuts", ["salt"]), ("", ["salt"]), ("   ", ["salt"]),
                ("salt", []), ("salt", ["salt", "SALT"]),
                ("salt", ["1 tsp salt", "Mix salt with flour."]),
                ("salt", ["Mix salt with salt."]),
                ("aa", ["aaa"]),  # Overlapping occurrences are ambiguous too.
            ]:
                with self.subTest(operation=operation, find=find, lines=lines):
                    self.assert_edit(lines, lines, records_count=0, target="ingredients",
                                     operation=operation, find=find, replace="pepper", add="pepper")

    def test_removal_requires_whole_line(self):
        lines = ["1 cup salt", "Mix salt with flour."]
        self.assert_edit(lines, lines, records_count=0, target="instructions",
                         operation="remove", find="Mix salt")
        self.assert_edit(["1 cup salt"], [], target="ingredients", operation="remove", find="1 CUP SALT")

    def test_missing_payload_and_noop_create_no_records(self):
        for operation, payload in [("replace", "replace"), ("add_after", "add")]:
            for value in (None, "", "   "):
                with self.subTest(operation=operation, value=value):
                    self.assert_edit(["salt"], ["salt"], records_count=0, target="ingredients",
                                     operation=operation, find="salt", **{payload: value})
        self.assert_edit(["salt"], ["salt"], records_count=0, target="ingredients",
                         operation="replace", find="SALT", replace="salt")

    def test_anchor_is_literal_not_regex_and_add_position_is_preserved(self):
        self.assert_edit(["1 cup milk (2%)", "salt"], ["1 cup milk (2%)", "pepper", "salt"],
                         target="ingredients", operation="add_after", find="milk (2%)", add="pepper")

    def test_sequential_edits_and_validation_use_current_content(self):
        recipe = Recipe(recipe_id="test", title="Test", ingredients=["salt"], instructions=[])
        plan = ModificationObject(modification_type="addition", reasoning="test", edits=[
            ModificationEdit(target="ingredients", operation="add_after", find="salt", add="pepper"),
            ModificationEdit(target="ingredients", operation="replace", find="pepper", replace="black pepper"),
            ModificationEdit(target="ingredients", operation="remove", find="salt"),
        ])
        valid, warnings = self.modifier.validate_modification_safety(plan, recipe)
        self.assertTrue(valid, warnings)
        actual, records = self.modifier.apply_modification(recipe, plan)
        self.assertEqual(recipe.ingredients, ["salt"])
        self.assertEqual(actual.ingredients, ["black pepper"])
        self.assertEqual(len(records), 3)
        self.assertTrue(audit_records(recipe.ingredients, actual.ingredients, records, "ingredients")["passed"])

    def test_validation_rejects_same_invalid_edits_as_application(self):
        recipe = Recipe(recipe_id="test", title="Test", ingredients=["salt", "salt"], instructions=[])
        plan = ModificationObject(modification_type="removal", reasoning="test", edits=[
            ModificationEdit(target="ingredients", operation="remove", find="salt"),
        ])
        valid, warnings = self.modifier.validate_modification_safety(plan, recipe)
        self.assertFalse(valid)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
