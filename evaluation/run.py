#!/usr/bin/env python3
"""Evaluate the existing pipeline without modifying production code."""

import argparse
import copy
from collections import Counter
from datetime import datetime, timezone
from difflib import unified_diff
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
from loguru import logger
from llm_pipeline.models import ModificationObject
from llm_pipeline.pipeline import LLMAnalysisPipeline

FIELDS = ("ingredients", "instructions")


def content(recipe):
    return {field: list(getattr(recipe, field)) for field in FIELDS}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_edit(before, edit):
    """Independent, conservative contract: unique literal span, ignoring case.

    No fuzzy guesses. Missing/ambiguous anchors leave content unchanged and are
    marked unresolved. Removal requires a whole-line match, not a substring.
    This is an evaluation oracle, never used to produce pipeline output.
    """
    if not edit.find.strip():
        return None, "empty anchor"
    matches = [
        (i, match.span(1)) for i, line in enumerate(before)
        for match in re.finditer(f"(?=({re.escape(edit.find)}))", line, re.IGNORECASE)
    ]
    if len(matches) != 1:
        return None, f"expected one literal anchor, found {len(matches)}"
    i, (start, end) = matches[0]
    expected = list(before)
    if edit.operation == "replace" and edit.replace and edit.replace.strip():
        expected[i] = before[i][:start] + edit.replace + before[i][end:]
    elif edit.operation == "add_after" and edit.add and edit.add.strip():
        expected.insert(i + 1, edit.add)
    elif edit.operation == "remove" and (start, end) == (0, len(before[i])):
        expected.pop(i)
    else:
        return None, "missing payload or non-whole-line removal"
    return expected, None


def audit_records(before, after, records, target):
    """Verify every ledger entry against the observed per-edit transition.

    Replay all possible insertion locations because ChangeRecord has no index.
    Reject no-ops, absent sources, and extra/unreported changes. Ambiguous
    positions can be validated as possible, not uniquely attributed.
    """
    states = {tuple(before)}
    issues = []
    for number, record in enumerate(records):
        wanted_type = "ingredient" if target == "ingredients" else "instruction"
        if record.type != wanted_type or record.from_text == record.to_text:
            issues.append(f"record {number}: wrong target type or no-op")
            states = set()
            break
        next_states = set()
        for state in states:
            if record.operation == "add" and record.from_text == "" and record.to_text:
                for i in range(len(state) + 1):
                    next_states.add(state[:i] + (record.to_text,) + state[i:])
            elif record.operation in ("replace", "remove"):
                if record.operation == "remove" and record.to_text != "":
                    continue
                for i, line in enumerate(state):
                    if line == record.from_text:
                        replacement = (record.to_text,) if record.operation == "replace" else ()
                        next_states.add(state[:i] + replacement + state[i + 1:])
        states = next_states
        if not states:
            issues.append(f"record {number}: cannot replay from observed content")
            break
    if tuple(after) not in states:
        issues.append("reported changes do not reproduce actual content")
    return {"passed": not issues, "issues": issues}


def check_content(case, candidate):
    """Targeted checks only; do not mistake these for a semantic LLM judge."""
    results = []
    for check in case.get("checks", []):
        lines = candidate[check["target"]]
        if "expected_lines" in check:
            observed = [line for line in lines if re.search(check["matching_pattern"], line, re.IGNORECASE)]
            passed = observed == check["expected_lines"]
        elif "exact_line" in check:
            passed = check["exact_line"] in lines
        else:
            found = bool(re.search(check["pattern"], "\n".join(lines), re.IGNORECASE))
            passed = not found if check.get("absent") else found
        results.append({"id": check["id"], "passed": passed})
    return results


def difference(before, after):
    return {field: list(unified_diff(
        before[field], after[field], fromfile=f"original/{field}",
        tofile=f"actual/{field}", lineterm=""
    )) for field in FIELDS}


def evaluate_application(pipeline, recipe, proposal, case):
    """Run real apply_modification, observing each real apply_edit call."""
    transitions = []
    original_apply = pipeline.recipe_modifier.apply_edit

    def observe(edit, lines):
        before = list(lines)
        after, records = original_apply(edit, lines)
        expected, unresolved = reference_edit(before, edit)
        transitions.append({
            "edit": edit.model_dump(exclude_none=True), "before": before,
            "after": list(after), "records": [r.model_dump() for r in records],
            "content_changed": before != after,
            "literal_contract_passed": after == expected if expected is not None else None,
            "unresolved_anchor_or_payload": unresolved,
            "ledger": audit_records(before, after, records, edit.target),
        })
        return after, records

    before = content(recipe)
    with patch.object(pipeline.recipe_modifier, "apply_edit", side_effect=observe):
        modified, records = pipeline.recipe_modifier.apply_modification(recipe, proposal)
    after = content(modified)
    # Project the PROPOSED plan independently to separate missing extraction
    # from failures of the production matcher. Unresolvable plans need review.
    projected = {field: list(lines) for field, lines in before.items()}
    projection_issues = []
    for i, edit in enumerate(proposal.edits):
        expected, issue = reference_edit(projected[edit.target], edit)
        if issue:
            projection_issues.append({"edit_index": i, "reason": issue})
        else:
            projected[edit.target] = expected
    failures = []
    for i, transition in enumerate(transitions):
        if not transition["ledger"]["passed"]:
            failures.append(f"edit {i}: inaccurate change ledger")
        if transition["literal_contract_passed"] is False:
            failures.append(f"edit {i}: literal edit was not applied correctly")
        if transition["unresolved_anchor_or_payload"] and transition["content_changed"]:
            failures.append(f"edit {i}: mutated content without a unique literal anchor")
    if "expected_content" in case and after != case["expected_content"]:
        failures.append("actual recipe differs from hand-written expected recipe")
    if content(recipe) != before:
        failures.append("input recipe was mutated")
    ledger = [r.model_dump() for r in records]
    if ledger != [r for t in transitions for r in t["records"]]:
        failures.append("aggregate ledger differs from per-edit records")
    observed = {field: list(lines) for field, lines in before.items()}
    for transition in transitions:
        target = transition["edit"]["target"]
        if observed[target] != transition["before"]:
            failures.append("content changed between observed edits")
        observed[target] = transition["after"]
    if observed != after:
        failures.append("final content differs from observed edit transitions")
    report = {
        "status": "failed" if failures else "passed",
        "failures": failures, "transitions": transitions,
        "actual_content": after, "actual_diff": difference(before, after),
        "reported_changes": ledger,
        "proposal_projection": {
            "content": projected, "issues": projection_issues,
            "checks": check_content(case, projected) if not projection_issues else None,
        },
        "final_content_checks": check_content(case, after),
    }
    return modified, records, report


def load_case(case):
    if "recipe_file" in case:
        raw = json.loads((ROOT / case["recipe_file"]).read_text())
    else:
        raw = dict(case["recipe"])
    if case["review_text"] is None:
        if raw.get("reviews") or raw.get("featured_tweaks"):
            raise ValueError("no-tweak fixture unexpectedly contains reviews")
    elif "recipe_file" in case:
        matches = [r for r in raw["reviews"] if r["text"] == case["review_text"]]
        if len(matches) != 1:
            raise ValueError(f"{case['id']}: exact pinned review is missing or duplicated")
        raw["reviews"] = matches
    else:
        raw["reviews"] = [{"text": case["review_text"], "has_modification": True}]
    # There is exactly one eligible review: random.choice cannot vary selection.
    return raw


def evaluate_case(case, live, api_key, output_dir, replay_case=None):
    raw = load_case(case)
    pipeline = LLMAnalysisPipeline(openai_api_key=(api_key if live else None) or "offline-unused", output_dir=output_dir)
    recipe = pipeline.parse_recipe_data(raw)
    if replay_case is not None:
        if (replay_case["id"] != case["id"] or replay_case["review_text"] != case["review_text"]
                or replay_case["original_content"] != content(recipe)):
            raise ValueError(f"{case['id']}: replay input does not match pinned recipe/review")
        if not replay_case.get("extraction", {}).get("proposal"):
            raise ValueError(f"{case['id']}: no saved model proposal to replay")
    result = {"id": case["id"], "review_text": case["review_text"],
              "original_content": content(recipe), "expected_behavior": case["expected_behavior"]}
    if "oracle_edits" in case:
        proposal = ModificationObject(modification_type="quantity_adjustment",
                                      reasoning="Hand-written evaluation fixture; not LLM output.",
                                      edits=case["oracle_edits"])
        _, _, application = evaluate_application(pipeline, recipe, proposal, case)
        result["oracle_application"] = application
    if "recipe_file" not in case and not case.get("evaluate_extraction", False):
        result["extraction"] = {"status": "not_applicable", "reason": "isolated adversarial application case"}
        return result
    if case["review_text"] is not None and replay_case is None and (not live or not api_key):
        result["extraction"] = {
            "status": "blocked" if not api_key else "not_run",
            "reason": "OPENAI_API_KEY is missing" if not api_key else "pass --live to call the model",
            "proposal": None, "actual_application": None,
        }
        return result

    extraction = {"status": "running", "attempts": [], "proposal": None}
    result["extraction"] = extraction
    real_create = pipeline.tweak_extractor.client.chat.completions.create
    real_extract = pipeline.tweak_extractor.extract_modification
    real_apply = pipeline.recipe_modifier.apply_modification

    def capture_request(**kwargs):
        attempt = {"request": copy.deepcopy(kwargs)}
        extraction["attempts"].append(attempt)
        if case["review_text"] is None or replay_case is not None:
            raise AssertionError("offline case attempted an LLM request")
        try:
            response = real_create(**kwargs)
            attempt["response"] = response.model_dump(mode="json")
            return response
        except Exception as exc:
            # Exception messages can contain credentials or account details.
            attempt["error_type"] = type(exc).__name__
            attempt["http_status"] = getattr(exc, "status_code", None)
            raise

    def capture_extraction(review, recipe):
        if review.text != case["review_text"]:
            raise AssertionError("pipeline selected a different review")
        extracted = (ModificationObject(**replay_case["extraction"]["proposal"])
                     if replay_case is not None else real_extract(review, recipe))
        extraction["proposal"] = extracted.model_dump(exclude_none=True) if extracted is not None else None
        return extracted

    def capture_application(recipe, proposal):
        # Restore only this method while evaluate_application spies on apply_edit.
        with patch.object(pipeline.recipe_modifier, "apply_modification", real_apply):
            modified, records, application = evaluate_application(
                pipeline, recipe, proposal, {k: v for k, v in case.items() if k != "expected_content"}
            )
        result["actual_application"] = application
        return modified, records

    with patch.object(pipeline, "load_recipe_data", return_value=raw), \
         patch.object(pipeline.tweak_extractor.client.chat.completions, "create", side_effect=capture_request), \
         patch.object(pipeline.tweak_extractor, "extract_single_modification", wraps=pipeline.tweak_extractor.extract_single_modification) as select, \
         patch.object(pipeline.tweak_extractor, "extract_modification", side_effect=capture_extraction), \
         patch.object(pipeline.recipe_modifier, "apply_modification", side_effect=capture_application):
        enhanced = pipeline.process_single_recipe(case.get("recipe_file", case["id"]), save_output=False)

    if case["review_text"] is None:
        passed = enhanced is None and not select.called and not extraction["attempts"] and "actual_application" not in result
        extraction["status"] = "not_applicable"
        result["no_tweaks"] = {"status": "passed" if passed else "failed",
                               "returned": None if enhanced is None else enhanced.model_dump(),
                               "extraction_calls": select.call_count, "llm_calls": len(extraction["attempts"])}
    else:
        extraction["status"] = ("replayed" if replay_case is not None else "returned") if extraction["proposal"] is not None else "failed"
        extraction["semantic_review"] = "pending: compare each expected behavior with proposal; check wording, order, omissions, unsupported edits and quantity assumptions"
        if "actual_application" in result:
            projection = result["actual_application"]["proposal_projection"]
            checks = projection["checks"]
            extraction["content_screening"] = {
                "status": "inconclusive" if checks is None else (
                    "passed" if all(c["passed"] for c in checks) else "failed"
                ),
                "checks": checks,
                "note": "Heuristic screening only; complete the semantic review separately.",
            }
    if enhanced:
        result["enhanced_recipe"] = enhanced.model_dump()
        records = [c.model_dump() for m in enhanced.modifications_applied for c in m.changes_made]
        result["packaging_checks"] = {
            "ledger_preserved": records == result["actual_application"]["reported_changes"],
            "content_preserved": content(enhanced) == result["actual_application"]["actual_content"],
            "count_matches_records": enhanced.enhancement_summary.total_changes == len(records),
            "source_matches": all(m.source_review.text == case["review_text"] for m in enhanced.modifications_applied),
        }
    if replay_case is not None:
        result["replay_comparison"] = {
            "proposal_unchanged": extraction["proposal"] == replay_case["extraction"]["proposal"],
            "content_matches_saved_run": result.get("actual_application", {}).get("actual_content") == replay_case["actual_application"]["actual_content"],
            "llm_calls": len(extraction["attempts"]),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="call the unchanged extractor for pinned real reviews")
    mode.add_argument("--replay", type=Path, help="replay parsed proposals from a saved live report; never call the model")
    parser.add_argument("--case", action="append", dest="cases", help="case ID; repeat to select several")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "evaluation/cases.json", help="separate expectation fixtures; original baselines are not modified")
    parser.add_argument("--output", type=Path, default=ROOT / "test_output/evaluation.json")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "src/.env")
    api_key = os.getenv("OPENAI_API_KEY")
    logger.remove()  # API errors may include secrets; store only exception type/status.
    fixture_path = args.fixtures.resolve()
    fixture = json.loads(fixture_path.read_text())
    cases = fixture["cases"]
    if args.cases:
        unknown = set(args.cases) - {c["id"] for c in cases}
        if unknown:
            parser.error(f"unknown cases: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in args.cases]
    replay_cases = {}
    if args.replay:
        saved = json.loads(args.replay.read_text())
        replay_cases = {c["id"]: c for c in saved["cases"]}
        if len(replay_cases) != len(saved["cases"]):
            parser.error("duplicate case IDs in replay report")
        missing = [c["id"] for c in cases if ("recipe_file" in c or c.get("evaluate_extraction")) and c["review_text"] is not None
                   and c["id"] not in replay_cases]
        if missing:
            parser.error(f"replay report lacks proposals for {missing}")
    paths = list((ROOT / "src/llm_pipeline").glob("*.py")) + [fixture_path, Path(__file__).resolve()]
    paths += [ROOT / c["recipe_file"] for c in cases if "recipe_file" in c]
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python": sys.version, "dependencies": {p: version(p) for p in ("openai", "pydantic", "loguru")},
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))},
        "expectations_version": fixture["expectations_version"],
        "live_requested": args.live,
        "selection": "exact review text; only that review supplied to unmodified orchestrator",
        "limitations": "Fixed selection is reproducible; live model responses are not guaranteed deterministic. Regex checks are screening aids; semantic review is required. Oracle edits are not extractor output.",
    }
    if args.replay:
        report["replay_source"] = {"path": str(args.replay), "sha256": digest(args.replay)}
    with TemporaryDirectory(prefix="casper-evaluation-") as output_dir:
        report["cases"] = [evaluate_case(c, args.live, api_key, output_dir, replay_cases.get(c["id"])) for c in cases]
    counts = Counter()
    for result in report["cases"]:
        status = result["extraction"]["status"]
        counts[f"extraction_{status}"] += 1
        if result["extraction"].get("semantic_review"):
            counts["semantic_reviews_pending"] += 1
        if result["extraction"].get("content_screening", {}).get("status") == "failed":
            counts["extraction_screening_failed"] += 1
        for stage in ("oracle_application", "actual_application", "no_tweaks"):
            if stage in result:
                counts[f"{stage}_{result[stage]['status']}"] += 1
        if result.get("packaging_checks") and not all(result["packaging_checks"].values()):
            counts["packaging_failed"] += 1
    report["summary"] = dict(counts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output}")
    if any(v for k, v in counts.items() if k.endswith("_failed")):
        return 1
    if any(counts[k] for k in ("extraction_blocked", "extraction_not_run", "semantic_reviews_pending")):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
