# Extraction changes and GPT-6 Luna comparison

The final live run is `luna_live.json`. Original `baseline.json`,
`baseline_live.json`, and `editor_replay.json` remain byte-for-byte unchanged.
`extraction_comparison.json` evaluates the original and Luna outputs against
the same expected behavior, with additional checks for the observed failures.
`luna_replay.json` replays the saved Luna proposals through the editor, with
zero LLM calls, including the existing adversarial editor and no-tweaks cases.

## What changed

- The default model is `gpt-6-luna`; no automatic GPT-3.5 fallback remains.
- One full-review inventory retains each discrete change, exact evidence,
  disposition, and any missing-detail question. It separates tried changes
  from future intentions. Compound changes are not collapsed into one edit.
- Each actionable change gets a recipe draft. Actual differences compile into
  the existing literal editor contract. Plans must be executable and preserve
  ingredient uses, dependent directions, source quantities, and explicit ordering.
- Validation failures get at most two correction retries. If a complete plan
  cannot be validated, the whole plan is withheld and its changes are retained
  for manual review. No partial draft is presented as a complete enhancement.
- Missing substitution amounts are deferred instead of inherited or invented.
  Explanations cite evidence; outcomes are attributed reviewer quotations.

The editor implementation itself is unchanged from commit `6884d97`.

## Manual review of the actual Luna output

| Expected behavior, written before the original live baseline | Original live baseline | Luna extraction and actual result |
| --- | --- | --- |
| White sugar: 1 cup → 1/2 cup | Extracted and applied | Extracted and applied |
| Brown sugar: 1 cup → 1 1/2 cups | Extracted and applied | Extracted and applied |
| Omit water, retain and incorporate baking soda | Missed | Water ingredient removed; directions now add baking soda and salt directly |
| Add 1 teaspoon cream of tartar and incorporate it | Missed | Ingredient added; same batter step incorporates it |
| Chill at least an hour before scooping/baking | Missed | Separate refrigeration step after flour/chips/walnuts are mixed, immediately before scooping |
| Soup: recognize 2% milk as tried | Missed | Extracted; asks how much was used; no assumed volume |
| Soup: recognize fresh grated ginger as tried | Missed | Extracted; asks how much was used; no assumed conversion |
| Soup: exclude future broth increase | Invented 2-cup broth replacement, leaving 5 cups total | Retained as future intent; no edit; exactly the original single 3-cup broth entry |

I inspected all final ingredient and instruction lines alongside the proposal
and ledger. Cookie has **five supported changes and seven actual edit records**.
Two successive edits update the same batter instruction (first remove water,
then incorporate tartar); the ledger accurately retains both transitions.
All unrelated ingredients and steps are preserved. Baking soda remains in both
lists, neither sugar is used twice, and refrigeration follows completed mixing.
The attributed outcome is exactly “The cookies retained their shape and didn't
spread when baked.” No independent culinary result is claimed.

Soup has **three extracted decisions, zero edits**, and a `needs_clarification`
status. Ingredients and directions both remain exactly original while the two
missing quantities are unresolved. This satisfies the original expectation
explicitly allowing clarification. The model labels the future broth increase
as `addition` instead of `quantity_adjustment`; that category imprecision remains,
but it neither changes the future disposition nor causes an edit.

Every reported edit was checked against the actual transition and independently
replayed ledger. Application and packaging checks pass for both recipes.
The final replay reproduces both outputs exactly with zero model calls.

## Automated checks and their limits

The original cookie screen passes **9/9**. Soup's original recipe-content screen
still passes **1/5**, because it expects applied substitutions rather than the
allowed clarification result. These raw results are preserved: `run.py` exits
1 and leaves semantic review pending. This document supplies that manual review.

The separate comparison adds checks for the clarification alternative, exact
broth entries, retained baking soda use, duplicate sugar use, instruction order,
unchanged steps, source evidence, and attributed outcomes. Both final cases
pass it. Regression tests deliberately inject those faults to ensure the new
checks reject them. They supplement rather than erase the original screens.

There are **41 offline regression/evaluation tests**. Mocked extraction tests
verify validation and API behavior; they are not evidence of model accuracy
on unseen recipes. One successful live pair establishes these outputs, not a
general accuracy rate or proof that Luna always outperforms GPT-3.5.

## Calls, costs, and prior experiments

Luna used **seven calls, zero validation retries**: one inventory plus five
plans for cookie, and one inventory for soup. Requests explicitly use
`reasoning_effort="none"`, temperature 0.1, and `max_completion_tokens=3000`.
Both requested and returned model IDs are `gpt-6-luna`.

| Run | Input tokens | Output tokens | Estimated total USD |
| --- | ---: | ---: | ---: |
| Original live baseline, two GPT-3.5 calls | 1,570 | 214 | $0.00111 |
| Final Luna pair, seven calls | 5,541 | 1,726 | $0.00142 |

Estimates use standard uncached token rates checked on 2026-09-24:
[GPT-3.5 Turbo](https://developers.openai.com/api/docs/models/gpt-3.5-turbo)
at $0.50/$1.50 and
[GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
at $0.10/$0.50 per million input/output tokens. These are token estimates, not
invoice totals. Luna has lower token prices, but this workflow uses more calls
than the incomplete original pipeline, so the pair is not cheaper overall.

`experiments/gpt35/extraction_attempt1.json` through `extraction_attempt13.json`
retain all intermediate GPT-3.5 runs, including incomplete and unsafe drafts.
They total 140 calls, 148,384 input tokens, and 25,088 output tokens (~$0.112).
Do not use them as production outputs. The attempts changed prompts, validation,
and decomposition; they are development traces, not repeated trials of one
fixed implementation. Their source hashes record each implementation's identity.
Some earlier screens passed despite semantic errors later caught manually.

The Luna migration also replaced the experimental action-verb heuristics and
per-clause classification with one full-review inventory call. Consequently this
comparison measures the final system, not the isolated causal effect of its model.

## Rerun

```sh
.venv/bin/python -m unittest discover -s evaluation -p 'test_*.py'
.venv/bin/python evaluation/run.py --live \
  --case cookie_multi_change --case soup_tried_vs_planned \
  --output test_output/luna_live.json
.venv/bin/python evaluation/compare_extraction.py \
  --after test_output/luna_live.json --output test_output/extraction_comparison.json
.venv/bin/python evaluation/run.py --replay evaluation/luna_live.json \
  --output test_output/luna_replay.json
```

The comparison exits zero when its additional checks pass. The raw live/replay
runner retains the original screening behavior described above. Inspect new
outputs manually too; never overwrite the committed baseline artifacts.

## Remaining work

First expand held-out live coverage and repeated trials: alternate wording,
negation, conflicting tweaks, conversions, quantities embedded in directions,
and ambiguous ingredient identities. The literal dependency/amount/order checks
are conservative English heuristics, not a culinary semantic model. They can
reject valid paraphrases and cannot detect every unsupported rewrite. Relative
amounts and unclear conversions may need clarification. Structured JSON schemas
and fewer planning calls are later optimizations, after broader correctness
coverage. Review selection still uses a random flagged review; featured/highest-
voted selection remains separate work.
