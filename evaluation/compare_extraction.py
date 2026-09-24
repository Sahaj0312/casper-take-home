"""Compare saved results, including the explicitly allowed clarification outcome.

These independent case checks supplement the original content screens; they do
not replace manual review or rewrite any saved model output.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re


def assess(case):
    proposal = case["extraction"].get("proposal") or {}
    analysis = proposal.get("analysis") or {}
    changes = analysis.get("changes", [])
    application = case.get("actual_application", {})
    actual = application.get("actual_content", {"ingredients": [], "instructions": []})
    original = case["original_content"]
    enhanced = case.get("enhanced_recipe") or {}
    checks = {
        "application_and_ledger": application.get("status") == "passed",
        "packaging": bool(case.get("packaging_checks")) and all(case["packaging_checks"].values()),
        "literal_evidence": bool(changes) and all(c.get("evidence") and c["evidence"] in case["review_text"] for c in changes),
    }
    steps = actual["instructions"]
    if case["id"] == "cookie_multi_change":
        screens = application.get("final_content_checks") or []
        checks["original_nine_content_checks"] = len(screens) == 9 and all(c["passed"] for c in screens)
        checks["five_applied_changes"] = len(changes) == 5 and all(c["disposition"] == "apply" for c in changes)
        checks["all_changes_have_edits"] = {c["id"] for c in changes} == {ident for ids in proposal.get("edit_sources", []) for ident in ids}
        checks["no_extra_ingredients"] = len(actual["ingredients"]) == len(original["ingredients"]) and all(
            line in actual["ingredients"] for line in original["ingredients"]
            if not re.search(r"white sugar|brown sugar|water", line, re.I)
        )
        checks["unchanged_steps_preserved"] = [s for s in steps if s in original["instructions"]] == [s for s in original["instructions"] if "hot water" not in s]
        checks["ingredients_used_once"] = all(sum(term in s.lower() for s in steps) == 1 for term in ("white sugar", "brown sugar", "baking soda", "salt", "cream of tartar"))
        mixing = [i for i, s in enumerate(steps) if "Stir in flour" in s]
        chilling = [i for i, s in enumerate(steps) if re.search(r"refrigerat|chill", s, re.I)]
        scooping = [i for i, s in enumerate(steps) if "Drop spoonfuls" in s]
        checks["chill_after_mixing_before_scooping"] = len(mixing) == len(chilling) == len(scooping) == 1 and mixing[0] + 1 == chilling[0] == scooping[0] - 1
        outcome = analysis.get("outcome_evidence")
        checks["benefit_is_attributed_quote"] = bool(outcome) and outcome in case["review_text"] and enhanced.get("enhancement_summary", {}).get("expected_impact") == f'Reviewer reported (not independently verified): "{outcome}"'
    elif case["id"] == "soup_tried_vs_planned":
        for term in ("2% milk", "fresh grated ginger"):
            matches = [c for c in changes if term in c["evidence"].lower()]
            checks[f"clarify_{term}"] = len(matches) == 1 and matches[0]["disposition"] == "needs_clarification" and not matches[0].get("amount") and bool(matches[0].get("clarification"))
        broth = [c for c in changes if "broth" in c["evidence"].lower()]
        checks["broth_future_only"] = len(broth) == 1 and broth[0]["disposition"] == "future_plan"
        checks["exactly_three_decisions"] = len(changes) == 3
        checks["no_guessed_edits_or_claims"] = not proposal.get("edits") and not application.get("reported_changes") and not enhanced.get("modifications_applied")
        checks["original_recipe_retained"] = actual == original
        checks["single_original_broth_entry"] = [s for s in actual["ingredients"] if re.search(r"broth|stock", s, re.I)] == [s for s in original["ingredients"] if re.search(r"broth|stock", s, re.I)]
        checks["explicit_clarification_status"] = enhanced.get("enhancement_status") == "needs_clarification"
        checks["no_invented_benefit"] = enhanced.get("enhancement_summary", {}).get("expected_impact") == "No benefit established by this pipeline."
    return {"passed": all(checks.values()), "checks": checks}


def summarize(path):
    report = json.loads(path.read_text())
    cases = []
    for case in report["cases"]:
        if case["id"] not in ("cookie_multi_change", "soup_tried_vs_planned"):
            continue
        attempts = case["extraction"].get("attempts", [])
        usage = {key: sum((a.get("response", {}).get("usage") or {}).get(key, 0) for a in attempts)
                 for key in ("prompt_tokens", "completion_tokens")}
        cases.append({"id": case["id"], "outcome": assess(case), "calls": len(attempts), "usage": usage,
                      "models": sorted({a.get("response", {}).get("model", "unknown") for a in attempts}),
                      "original_content_screen": case["extraction"].get("content_screening"),
                      "manual_review": "See extraction_findings.md; automated checks do not prove general semantic correctness."})
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, default=Path("evaluation/baseline_live.json"))
    parser.add_argument("--after", type=Path, default=Path("evaluation/luna_live.json"))
    parser.add_argument("--output", type=Path, default=Path("test_output/extraction_comparison.json"))
    args = parser.parse_args()
    report = {"before": summarize(args.before), "after": summarize(args.after),
              "note": "Original expectations allow clarification for missing soup quantities. Original raw content screens remain unchanged."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({c["id"]: c["outcome"] for c in report["after"]["cases"]}, indent=2))
    return 0 if all(c["outcome"]["passed"] for c in report["after"]["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
