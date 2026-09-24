# Baseline evaluation

The two baseline reports preserve the original pipeline. The editor fixes and
offline replay results are documented at the end of this file. Natural-language
expectations in `cases.json` were written from recipe/review text before any new model call. Existing saved
outputs had already been inspected during the initial review; they are not
used as expected answers or replayed as model output.

## Run

From the repository root (Python 3.13+, existing project dependencies):

```sh
uv sync
.venv/bin/python evaluation/run.py
.venv/bin/python -m unittest evaluation.test_evaluation evaluation.test_recipe_modifier
```

The default evaluation is offline. To also run the **current, unchanged**
extractor, set `OPENAI_API_KEY` in the environment or ignored root `.env`:

```sh
.venv/bin/python evaluation/run.py --live --output test_output/after.json
.venv/bin/python evaluation/run.py --live --case cookie_multi_change --output test_output/cookie.json
```

Do not overwrite `evaluation/baseline.json` (offline) or
`evaluation/baseline_live.json` (first live run) when comparing fixes. CLI exit codes:
`0` = all selected checks passed with no pending stages; `1` = measured failures;
`2` = blocked/not-run extraction or pending semantic review, without other failures.
Model text still needs human semantic review, so a live run does not claim full
correctness merely because its targeted checks pass.

## Cases and expectations

| Case | Expected behavior, established before this run |
| --- | --- |
| Cookie multi-change review | White sugar 0.5 cup; brown sugar 1.5 cups; omit water; add 1 tsp cream of tartar; chill at least an hour before scooping/baking. Update dependent directions, retain baking soda and unrelated content. |
| Soup: “Even w 2% milk ... Used fresh grated ginger” | Recognize both tried substitutions. Do not apply “more broth next time.” Keep directions consistent. Surface missing ginger quantity; do not invent a supported conversion. Inheriting milk volume is an assumption. |
| Plum jam, no reviews | No model call, no invented edits. Accept the current `None` return as a legitimate skip for this baseline. |
| Carrot salad, capitalization | Accepted case-insensitive anchor must actually replace lemon-juice quantity, without a false change record. |
| Roasted carrots, short span | Replace unique `200 C` with `220 C` inside a long instruction, preserving the rest. |
| Oat topping, absent ingredient | Reject removing pumpkin seeds when only sunflower seeds exist. Preserve the recipe and report no successful removal. |

Cookie/soup selection uses **exact review text**, verified against the source
file. Only that review is supplied through a test seam in `load_recipe_data`;
the real `process_single_recipe` still selects, extracts, applies, and packages.
No seed or review-array index is relied on. The original files are not rewritten.
Selection is fixed; live model generation is not guaranteed deterministic.

The cookie oracle is a hand-written six-edit application fixture, **not an
extractor proposal**. It exercises five substantive changes and dependent
directions. Exact wording is one valid rendering, not a semantic requirement
for the model. Synthetic proposals also bypass extraction intentionally to
isolate application defects. There is no made-up soup quantity oracle.

## Separating stages

The report records original content, expected behavior, raw model requests and
responses (when available), parsed proposal, per-edit before/after content,
reported changes, final content, actual diff, and source/dependency fingerprints.

- **Extraction:** compare the proposal to each expectation. A conservative
  independent literal applicator projects the proposal, and targeted regex
  checks screen that projected content. If an anchor cannot be resolved, those
  checks are withheld instead of blaming extraction for projection failure.
  Human review must still check order (chill before scooping), equivalent unit
  phrasing, extra edits, omissions, and unsupported quantity assumptions. These
  checks are not a semantic correctness score.
- **Application:** observe calls to the real modifier. Compare each transition
  with the unique literal edit contract and, for hand-written fixtures, the
  expected final recipe. The contract permits case variation and exact spans;
  it does not permit fuzzy ingredient guesses. Unknown anchors are surfaced.
- **Attribution:** independently replay every change record against the observed
  transition. Reject unchanged `from`/`to`, nonexistent sources, and unreported
  mutations. Addition records omit indexes, so the audit proves a possible
  insertion location, not unique location attribution. Check aggregate ledger,
  final packaging, source review, and counts separately.

A failed proposal-content check with successful application points to extraction;
a correct proposal whose actual edit differs points to application. An edit can
be faithfully recorded but still target the wrong ingredient; ledger validity
alone is insufficient. No percentage over six hand-picked cases implies general
accuracy or culinary quality.

## Recorded baseline

Command: `.venv/bin/python evaluation/run.py --live --output evaluation/baseline.json`.
Exit code **1**, intentionally exposing existing failures.

| Stage | Observed result |
| --- | --- |
| Cookie live extraction | **Blocked:** no API key in environment, root `.env`, or `src/.env`. No model proposal or live application exists. |
| Soup live extraction | **Blocked:** same reason. Tried-versus-planned accuracy is unmeasured. |
| Cookie hand-written application plan | **Pass:** all six edits apply, final content matches, change records are truthful. This does not establish extractor completeness. |
| No-tweaks orchestrator | **Pass:** returns `None`, with no extraction/application or model call. The old all-recipes runner still does not distinguish this skip from failure. |
| Capitalization | **Fail:** accepted match leaves quantity unchanged but reports a replacement. Ledger audit catches the no-op. |
| Short instruction span | **Fail:** exact temperature span is not applied; no change is recorded. Whole-line similarity blocks the edit. |
| Absent ingredient | **Fail:** removes sunflower seeds when asked to remove absent pumpkin seeds. Ledger truthfully records a semantically wrong deletion. |

## Live baseline and completed semantic review

Recorded in `baseline_live.json` on 2026-09-24 against commit `ce5a5a0`:

```sh
.venv/bin/python evaluation/run.py --live \
  --case cookie_multi_change --case soup_tried_vs_planned \
  --output evaluation/baseline_live.json
```

Both requests succeeded on their first attempt. Requested model:
`gpt-3.5-turbo`; returned model: `gpt-3.5-turbo-0125`. Both finish reasons were
`stop`, not token-limit truncation. The exact requests, responses, proposals,
transitions, and enhanced recipes are retained. Pipeline, prompt, evaluator,
fixture, and input hashes match the offline baseline. No production or
evaluation logic was changed for this run.

Exit code was **1**: both extraction screenings failed; both application audits
passed. The raw report's `semantic_reviews_pending: 2` records the evaluator's
state at generation time. **The manual review is now complete below**; the raw
report has not been edited to replace or conceal automated results.

### Cookie: incomplete extraction, faithful application

| Expected behavior | Model proposal | Actual output / manual verdict |
| --- | --- | --- |
| White sugar: 1 -> 0.5 cup | Replace with `1/2 cup white sugar` | Applied correctly; equivalent fraction accepted. |
| Brown sugar: 1 -> 1.5 cups | Replace with `1 1/2 cups packed brown sugar` | Applied correctly. |
| Remove water and its dependent instruction; retain baking soda | No edit | **Fail:** `2 teaspoons hot water` and “Dissolve baking soda in hot water” remain. Baking soda is retained. |
| Add 1 tsp cream of tartar and incorporate into batter | No edit | **Fail:** absent from both ingredients and instructions. |
| Chill at least an hour before scooping/baking | No edit | **Fail:** no chilling step. |
| Preserve unrelated content; do not add another review's yolk | No unrelated edit | Pass: every other ingredient, all nine instructions, and servings are unchanged. |

Only two ingredient lines changed. Both change records accurately describe the
actual before/after lines. Automated screening passes 4 of 9 checks, including
two preservation checks; **that is not modification recall**. The omitted
changes are missing from the raw response itself, establishing an extraction
failure in this live run, not a lost edit in application.

The model also claims a “sweeter cookie.” The review does not report increased
sweetness, and total sugar volume remains two cups. This rationale is unsupported
by the supplied evidence; actual sensory effects were not tested. It is copied
into the enhanced recipe's `expected_impact`, and the regex checks do not catch it.

### Soup: unsupported edit, faithful application

| Expected behavior | Model proposal | Actual output / manual verdict |
| --- | --- | --- |
| Recognize tried 2% milk substitution; update dairy directions | No supported milk edit | **Fail:** removes `1.5 cups half-and-half (or whole milk)` and substitutes `2 cups chicken broth`. Both instructions mentioning half-and-half remain. |
| Recognize tried fresh grated ginger | No edit | **Fail:** `1.5 teaspoons ground ginger` remains. |
| Do not apply “more broth next time” | Introduces `2 cups chicken broth` | **Fail:** original 3-cup broth line remains too; the ingredient list now contains 5 cups across two lines. Neither dairy-to-broth substitution nor the extra 2-cup amount is supported by the review. |
| Surface missing fresh-ginger quantity and milk-volume assumptions | No ambiguity/assumption annotation | **Fail:** omits both supported substitutions and gives no account of unknown quantities. No fresh-ginger conversion was proposed; do not misdescribe this as an invented ginger amount. |
| Preserve unrelated content or return needs-clarification | Returns an enhanced recipe | Fail overall: the unsupported dairy replacement is applied without qualification; all other ingredient lines and all seven instruction lines are unchanged. |

There is exactly one proposed edit and one actual ingredient replacement, with a
truthful change record. This is an **extraction/grounding failure**, followed by
successful mechanical application of the wrong plan. The future-only broth
suggestion was not respected as a constraint. The model's internal reasoning
for choosing “2 cups” is unknown.

**Automated blind spot:** `broth_unchanged` passes because it only checks that the
original 3-cup line still exists. It does not detect a second broth entry. Thus
the reported 1/5 passing checks overstates compliance with that expectation;
manual review rejects it. Expectations/checks were not rewritten after seeing
this output. A follow-up should compare all broth entries/quantities and detect
unexpected ingredient additions and ingredient/instruction contradictions.

### Combined interpretation and fix priority

All three live change records are truthful; both final recipes match their
proposals exactly, and all packaging checks pass. That does **not** make either
recipe correct. The offline capitalization, short-span, and wrong-ingredient
failures still demonstrate separate application defects. The cookie oracle
proves the existing modifier can apply one complete, carefully anchored plan.

1. **Make application trustworthy:** unique exact anchors/spans or stable line
   IDs; reject ambiguous/wrong targets and invalid payloads; never report a
   no-op as an applied change. Explicitly distinguish applied, rejected,
   partial, and no-tweaks outcomes. The three offline failures are deterministic
   regression cases and a focused first fix.
2. **Extract complete, evidence-backed changes before planning edits:** retain
   every discrete tried change, its source phrase, and any unknown quantity;
   distinguish tried actions from future intent. The cookie omitted three
   substantive changes; soup missed both tried substitutions and invented a
   replacement/amount. One top-level category must not collapse a mixed review.
   Do not assume a prompt tweak or model upgrade alone resolves this.
3. **Validate the complete recipe and its explanation:** synchronize dependent
   directions, flag unsupported additions/quantities and duplicate ingredients,
   and ground reasoning in the review. Strengthen the broth invariant and add
   checks for ordering and unsupported rationales. The existing runner should
   not call an incomplete or contradictory recipe successful merely because an
   object was returned. Preserve the baseline artifacts when improving checks.
4. **Then expand coverage and address selection:** rerun fixed cases plus new
   reviews and repeated live trials, retaining intermediate outputs. Resolve
   featured-review ranking and missing vote provenance before claiming
   highest-voted behavior.

These two live responses establish concrete failures, not their frequency,
general extraction accuracy, or culinary outcomes. The historical sample
outputs remain separate evidence with uncertain generating-code provenance.

## Editor fixes and saved-proposal replay

The editor now requires one case-insensitive **literal occurrence** across the
target list. Repeated targets (within a line, across lines, or overlapping) are
ambiguous and rejected. Replacements splice that span, so capitalization and
short instruction snippets work. Removal requires a whole-line match; it never
deletes a merely similar ingredient or an instruction containing only a matching
fragment. Empty anchors, missing/blank payloads, and no-op replacements are
rejected. A rejection leaves content unchanged, logs the reason, and returns no
change record. Input recipes are not mutated. The validation helper uses the
same rules against sequentially updated content.

The existing `(content, records)` API is preserved. Edits are still processed
sequentially; rejecting one edit does not roll back earlier valid edits or reject
the whole recipe. A structured partial/rejected pipeline outcome remains future
work. The legacy similarity-threshold constructor argument is accepted for
compatibility but no longer enables fuzzy matching.

Fixture version 2 strengthens `broth_unchanged`: **all** ingredient lines
mentioning broth or stock must equal the single original broth line. Extra,
duplicate, combined, or altered broth entries fail. The natural-language
expectation is unchanged; this repairs the checker after its observed false
pass. Baseline files retain their original results and hashes.

Replay without model calls:

```sh
.venv/bin/python evaluation/run.py --replay evaluation/baseline_live.json \
  --output test_output/editor_replay.json
```

The committed `editor_replay.json` was produced with the same command, using
`--output evaluation/editor_replay.json`. Replay verifies the archived review
and original recipe content, substitutes the saved parsed proposal at the
extraction boundary, and runs the current editor and generator. The report
includes the source archive hash and before/after content. `--replay` and
`--live` are mutually exclusive; tests assert that neither extraction nor the
model client is called during replay.

| Check | Result after editor fixes |
| --- | --- |
| Case-variant quantity replacement | Pass: quantity changes and record matches. |
| Short temperature span | Pass: only `200 C` becomes `220 C`. |
| Missing pumpkin-seed target | Pass: sunflower seeds retained, no change record. |
| Complete hand-written cookie plan | Pass: all six edits still apply. |
| No-tweaks recipe | Pass: no extraction or edits. |
| Saved cookie and soup proposals | Application/ledger/packaging checks pass; both final recipes exactly match the live baseline. Zero model calls. |
| Soup broth check | Now correctly fails on the extra 2-cup broth entry. |

All **19 regression/evaluator tests pass**, including empty/missing/ambiguous
targets, no-op records, whole-line removal, missing payloads, sequential edits,
replay input mismatch, and extra/duplicate broth. The new editor regressions
were run before implementation and reproduced failures in the old editor.

The replay command intentionally exits **1**: the archived proposals still fail
extraction screening. Cookie omissions and the unsupported soup substitution
are unchanged; the editor correctly executes those uniquely anchored edits.
The raw report's semantic-review-pending counters are automatic. Manual review
confirms unchanged cookie content and unchanged soup content, with the soup
false pass now corrected (0/5 screening checks pass). No extractor or prompt
changes, live calls, or baseline rewrites were made in this checkpoint.

That editor checkpoint is preserved above. The subsequent extraction fixes,
GPT-6 Luna live outputs, manual review, costs, limitations, and rerun commands
are in [extraction_findings.md](extraction_findings.md). The new comparison is
[extraction_comparison.json](extraction_comparison.json); the original baselines
remain unchanged.

The next bounded evaluation of five new cases is documented in
[heldout_findings.md](heldout_findings.md): three passes, one partial result, and
one failure, with expectations frozen before the calls and no pipeline tuning.

## Deterministic Featured Tweaks selection

Production now prefers nonblank `featured_tweaks` entries, including entries
without a redundant `has_modification` flag. Only when none exist does it use
nonblank `reviews` explicitly flagged as modifications. Selection considers one
source pool at a time. A regular review cannot outrank an eligible featured entry.

An explicit nonnegative integer `vote_count` is the optional vote-data contract.
If every candidate in that pool has it, select the largest count, with ties in
stored order. Missing, partial, negative, string, fractional, or boolean counts
trigger stored-order fallback. Zero is a valid count. Star ratings and aggregate
recipe rating counts are never treated as votes. No vote scraping was added.

All supplied entries lack vote counts. Their `featured_tweaks` lists were derived
by the scraper from photo reviews with modification keywords, so their provenance
does not establish genuine highest-voted status. Every output now records this
selection decision in `review_selection`, including clarification-only outputs.
Its index is zero-based in the original selected source array.

`selection_audit.json` records selection from the complete six source recipes:
first featured entry for cookies, nikujaga, apple cake, and soup; no selection for
jam or marinade. This changes the default cookie/soup choice from the historical
pinned evaluation cases; it does not imply new live extraction results for those
first entries.

All **51** offline tests pass. Tests cover featured-only recipes, preference over
regular reviews, ratings ignored, ties, complete/missing/partial/invalid counts,
empty sources, supplied data, and selection provenance on clarification. The
saved Luna proposals replay exactly in `selection_replay.json` with zero model
calls. The known soup content-screen exit code remains 1. Extraction fixtures
pin both source arrays so selection changes cannot silently change their reviews.
Extraction prompts, grounding rules, editor behavior, and historical reports
are unchanged by this selection checkpoint.
