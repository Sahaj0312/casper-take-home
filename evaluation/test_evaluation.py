"""Checks for the evaluator itself, with no network or model dependency."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from loguru import logger
from evaluation.run import audit_records, evaluate_case, load_case, reference_edit
from llm_pipeline.models import ChangeRecord, ModificationEdit

CASES = json.loads((Path(__file__).parent / "cases.json").read_text())["cases"]


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.disable("llm_pipeline")

    @classmethod
    def tearDownClass(cls):
        logger.enable("llm_pipeline")

    def test_ledger_rejects_noop(self):
        record = ChangeRecord(type="ingredient", operation="replace", from_text="sugar", to_text="sugar")
        self.assertFalse(audit_records(["sugar"], ["sugar"], [record], "ingredients")["passed"])

    def test_ledger_rejects_unreported_or_fictitious_changes(self):
        self.assertFalse(audit_records(["sugar"], ["salt"], [], "ingredients")["passed"])
        record = ChangeRecord(type="ingredient", operation="remove", from_text="nuts", to_text="")
        self.assertFalse(audit_records(["sugar"], ["sugar"], [record], "ingredients")["passed"])

    def test_ledger_replays_sequential_changes_with_duplicate_lines(self):
        records = [
            ChangeRecord(type="ingredient", operation="add", from_text="", to_text="salt"),
            ChangeRecord(type="ingredient", operation="remove", from_text="sugar", to_text=""),
        ]
        self.assertTrue(audit_records(["sugar", "sugar"], ["salt", "sugar"], records, "ingredients")["passed"])
        self.assertFalse(audit_records(["sugar", "sugar"], ["salt"], records, "ingredients")["passed"])

    def test_reference_does_not_guess_between_ingredients(self):
        edit = ModificationEdit(target="ingredients", operation="remove", find="1 cup pumpkin seeds")
        expected, reason = reference_edit(["1 cup sunflower seeds"], edit)
        self.assertIsNone(expected)
        self.assertIsNotNone(reason)

    def test_selection_is_exact_and_source_is_not_rewritten(self):
        case = CASES[0]
        raw = load_case(case)
        self.assertEqual([r["text"] for r in raw["reviews"]], [case["review_text"]])
        bad_case = dict(case, review_text="not present in source")
        with self.assertRaises(ValueError):
            load_case(bad_case)

    def test_incomplete_extraction_is_separate_from_correct_application(self):
        # Fake model output is only a harness test, never baseline evidence.
        proposal = {
            "modification_type": "quantity_adjustment", "reasoning": "test response",
            "edits": [{"target": "ingredients", "operation": "replace",
                       "find": "1 cup white sugar", "replace": "0.5 cup white sugar"}],
        }
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(proposal)))],
            model_dump=lambda **kwargs: {"test_double": True, "content": json.dumps(proposal)},
        )
        with TemporaryDirectory() as directory, patch(
            "openai.resources.chat.completions.Completions.create", return_value=response
        ) as create:
            result = evaluate_case(CASES[0], True, "offline-test-key", directory)
        self.assertEqual(create.call_count, 1)
        self.assertIn(CASES[0]["review_text"], create.call_args.kwargs["messages"][0]["content"])
        self.assertEqual(result["extraction"]["proposal"], proposal)
        application = result["actual_application"]
        self.assertEqual(application["status"], "passed")
        checks = {c["id"]: c["passed"] for c in application["proposal_projection"]["checks"]}
        self.assertTrue(checks["white_sugar"])
        self.assertFalse(checks["brown_sugar"])
        self.assertEqual(result["extraction"]["content_screening"]["status"], "failed")
        self.assertTrue(all(result["packaging_checks"].values()))

    def test_no_tweaks_never_calls_extractor(self):
        with TemporaryDirectory() as directory, patch(
            "llm_pipeline.tweak_extractor.TweakExtractor.extract_single_modification",
            side_effect=AssertionError("extractor should not be called"),
        ) as extract:
            result = evaluate_case(CASES[2], False, None, directory)
        extract.assert_not_called()
        self.assertEqual(result["no_tweaks"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
