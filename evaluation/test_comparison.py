"""Regression checks for observed failures missed by the original screens."""

import copy
import json
from pathlib import Path
import unittest

from evaluation.compare_extraction import assess


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        report = json.loads(Path(__file__).with_name("luna_live.json").read_text())
        self.cases = {c["id"]: copy.deepcopy(c) for c in report["cases"]}

    def test_manually_reviewed_outputs_pass_including_soup_abstention(self):
        for case in self.cases.values():
            self.assertTrue(assess(case)["passed"])
        self.assertEqual(self.cases["soup_tried_vs_planned"]["extraction"]["content_screening"]["status"], "failed")

    def test_extra_broth_and_applied_future_intent_fail(self):
        case = self.cases["soup_tried_vs_planned"]
        case["actual_application"]["actual_content"]["ingredients"].append("2 cups vegetable stock")
        self.assertFalse(assess(case)["checks"]["single_original_broth_entry"])
        case["extraction"]["proposal"]["analysis"]["changes"][1]["disposition"] = "apply"
        self.assertFalse(assess(case)["checks"]["broth_future_only"])

    def test_missing_soda_use_and_duplicate_sugar_fail(self):
        case = self.cases["cookie_multi_change"]
        steps = case["actual_application"]["actual_content"]["instructions"]
        steps[3] = "Add salt and cream of tartar to batter."
        self.assertFalse(assess(case)["checks"]["ingredients_used_once"])
        steps[3] = "Add baking soda, salt, cream of tartar and brown sugar to batter."
        self.assertFalse(assess(case)["checks"]["ingredients_used_once"])

    def test_chilling_unmixed_batter_fails(self):
        case = self.cases["cookie_multi_change"]
        steps = case["actual_application"]["actual_content"]["instructions"]
        steps.insert(3, steps.pop(5))
        self.assertFalse(assess(case)["checks"]["chill_after_mixing_before_scooping"])


if __name__ == "__main__":
    unittest.main()
