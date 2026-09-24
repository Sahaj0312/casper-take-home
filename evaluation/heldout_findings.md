# Five new cases: bounded evaluation, no tuning

**Result: three passes, one partial result, one failure.** This is a targeted
five-case probe, not an estimate of general accuracy. Production code and prompts
are unchanged from `6c56225`. There was one live evaluation per case, using the
pipeline's existing two-retry limit, and no corrective reruns.

## Expectations and provenance

`heldout_cases.json` was written before the first model call. Its SHA-256 is
`385b0e5c1900e6aa5987cbb9310451dbd1eb866009d855ed082f9a04b155ac18`.
Both live and replay reports record this hash and the pipeline source hashes.
Apple cake and nikujaga use exact pinned reviews from the supplied data; the
porridge, zucchini, and crumble cases are explicitly synthetic new inputs.

| Case | Expected before running | What actually happened | Verdict |
| --- | --- | --- | --- |
| Apple cake: different frosting, more apples next time | Ask which frosting/how much; do not add future apples; unchanged recipe | Both decisions retained correctly; original 2 cups apples and all frosting content remain; zero edits | Pass, with unnecessary retries |
| Nikujaga: a little over 1 lb meat, extra soy/sugar, conditional broth advice | Preserve approximate amount or defer; ask for soy/sugar amounts; do not treat broth advice as tried | Three tried changes retained and deferred; original dashi retained. Analysis incorrectly says “Used beef broth or stock”; equivalent approximate beef drafts are rejected | Partial |
| Porridge: oat milk and shorter simmer | Replace dairy milk with 1 cup oat milk in both lists; 10 → 8 minutes; retain honey | Exactly those three edits; oats, honey, stirring, and serving unchanged | Pass |
| Zucchini: less oil, no butter, future garlic | 2 → 1 tablespoon oil in both lists; butter is not a change; garlic stays future-only | Correct oil plan was generated, then discarded because the model also proposed removing nonexistent butter. Actual recipe remains at 2 tablespoons | Fail |
| Crumble: “1/2 cup sugar” with white and brown sugar | Ask which sugar or whether combined total; do not guess | Asks “white sugar, brown sugar, or both?”; unchanged recipe | Pass |

## Inspection of actual outputs

The successful porridge result contains:

```text
Ingredient: 1 cup dairy milk → 1 cup oat milk
Direction: Combine dairy milk and rolled oats… → Combine oat milk and rolled oats…
Direction: Simmer for 10 minutes, stirring often. → Simmer for 8 minutes, stirring often.
```

Those are the only three actual edits across the five cases. Every other final
recipe is exactly unchanged. All reported records reproduce the actual content;
all five application and packaging audits pass. Four of those audits are for
zero-change recipes, so this is **not** five semantic successes. No unsupported
ingredient, guessed quantity, invented benefit, or future tweak reached a final
recipe in this run.

Saved final proposals were replayed without LLM calls; all five reproduce the
same content exactly. No failed model draft was substituted for the final output.

## Failures by stage

**Extraction: negation and conditional advice still break.** “I did not add
butter” becomes an actionable removal even though the recipe never had butter.
In nikujaga, conditional beef-stock advice is summarized as a substitution the
reviewer used, despite the following sentence explaining they obtained dashi.
Deferral prevented an incorrect soup change, but the analysis itself is wrong.

**Plan validation: brittle normalization rejects valid candidates.** The first
nikujaga draft preserves the approximate meaning with “a little over 1 pound”.
The validator requires the source phrase “a lil over 1lb” instead. The next draft
uses that phrase, but ingredient parsing mistakes it for part of a new ingredient
name. The final retry uses that name in directions, then fails because the
original directions say “beef” rather than “sirloin steak”. Offline replay of
these three raw drafts confirms each rejection; no new model calls were used.

**Failure policy: one inapplicable action discards an independent valid one.**
The zucchini oil reduction was correctly proposed for both ingredient and
instruction. Three no-change attempts to remove absent butter fail validation,
so the existing whole-plan policy withholds the valid oil edits too. The generic
clarification message obscures the fact that the oil quantity was already clear.
The literal editor did not misapply or falsely report anything.

**Inventory validation also wastes calls.** Apple cake needed two retries:
“one more cup” was initially represented as “1 cup”, then clause coverage rejected
an otherwise exact frosting quote because its trailing period crossed the
checker's sentence split. Narrowing the quote eventually passed. This is a
validator limitation, not evidence that the reviewer omitted necessary wording.

## Artifacts and reruns

- `heldout_cases.json`: pre-run expectations and pinned inputs.
- `heldout_live.json`: complete requests, raw responses, final proposals, outputs,
  independent application checks, and change ledgers.
- `heldout_review.json`: per-case manual verdicts and actual content.
- `heldout_replay.json`: deterministic editor replay, zero LLM calls.

The run used **16 model calls, including six validation retries**; 12,152 input
and 2,165 output tokens. All returned model IDs were `gpt-6-luna`. The original
regex screens fail the oil case, while cases without regex checks have empty
check lists. Neither empty checks nor an application pass is a semantic verdict;
the manual review above supplies that missing assessment.

The harness now accepts a separate `--fixtures` file and explicit
`evaluate_extraction: true` for synthetic inputs. Original adversarial editor
fixtures remain editor-only. All **42** offline tests pass, including a test of
that opt-in boundary. Original fixtures and all prior baselines are untouched.

```sh
.venv/bin/python evaluation/run.py --live --fixtures evaluation/heldout_cases.json \
  --output test_output/heldout_live.json
.venv/bin/python evaluation/run.py --replay evaluation/heldout_live.json \
  --fixtures evaluation/heldout_cases.json --output test_output/heldout_replay.json
.venv/bin/python -m unittest discover -s evaluation -p 'test_*.py'
```

The live/replay runner intentionally exits 1 for the oil screening failures and
leaves automatic semantic review pending. The separate manual report records
the completed review without rewriting those raw results.

## What remains before submission

The brief explicitly does not require solving everything, prioritizes diagnosis
and evaluation over a UI/deployment, and recommends at most four hours. Stop
open-ended tuning. This evaluation supports an honest engineering submission,
not a claim that the MVP reliably applies every supported change.

If spending one more focused implementation block, prioritize negation/no-op
classification and separating independent applicable changes from unresolved
ones. Then address semantic quantity/ingredient normalization instead of growing
literal phrase exceptions. Keep this failed run as the regression checkpoint.
These are recommendations, not changes made in this evaluation.

For assignment alignment, the production selector still picks a random flagged
review. It does not implement the brief's highest-voted Featured Tweaks policy.
Fix the selection contract or explicitly document this gap and any missing vote
data; pinned evaluation selection does not solve it. The smoke script still
counts a returned clarification object as success. Do not present its count as
the number of successfully enhanced recipes.

Submission packaging still needs:

1. A clear document entry point tying together assumptions, diagnosis, decisions,
   implemented fixes, results, limitations, and next steps. The existing
   evaluation README, extraction findings, and this report contain the evidence.
2. The required **5–7 minute video**: show one success and this oil failure, explain
   why safe non-application still fails usefulness, and state remaining gaps.
3. An **actual coding-agent conversation export committed to the repository**.
   Model request/response evaluation logs are not that trajectory. No such export
   is currently tracked; do not substitute a fabricated transcript.
4. Verify the repository is **private** and shared with the assessment recipients;
   prepare the repository/video links and the requested “Take Home Assessment”
   email. Access, visibility, external video status, and delivery were not verified
   in this evaluation. No invitations or messages were sent.
