# Baseline evaluation

Production pipeline files are unchanged. Expectations in `cases.json` were
written from recipe/review text before any new model call. Existing saved
outputs had already been inspected during the initial review; they are not
used as expected answers or replayed as model output.

## Run

From the repository root (Python 3.13+, existing project dependencies):

```sh
uv sync
.venv/bin/python evaluation/run.py
.venv/bin/python -m unittest evaluation.test_evaluation
```

The default evaluation is offline. To also run the **current, unchanged**
extractor, set `OPENAI_API_KEY` in the environment or ignored root `.env`:

```sh
.venv/bin/python evaluation/run.py --live --output test_output/after.json
.venv/bin/python evaluation/run.py --live --case cookie_multi_change --output test_output/cookie.json
```

Do not overwrite `evaluation/baseline.json` when comparing fixes. CLI exit codes:
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

## Fix priority after this checkpoint

1. Make application trustworthy: unique exact anchors/spans or stable line IDs;
   reject ambiguous/wrong targets, validate operation payloads, and never count
   no-ops as changes. These failures are reproduced without the model.
2. With an API key, run the pinned cookie and soup reviews and complete the
   semantic rubric. Then address measured extraction omissions, future-intent
   handling, explicit unknown quantities, and ingredient/instruction consistency.
   Do not attribute the historical saved-output omissions to this extractor yet.
3. Add explicit applied/partial/rejected/no-tweaks outcomes and make the existing
   runner's success criteria reflect them. Keep blocked live evaluation visible.
4. Address featured-review selection and missing vote provenance before claiming
   highest-voted behavior. This small evaluation intentionally does not measure
   ranking, conflicting reviews, or broad generalization.
