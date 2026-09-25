# Recipe pipeline assessment

The first thing I wanted to know was whether the existing pipeline actually applied what a reviewer said. The cookie example answered that pretty quickly: the review described five changes, but the pipeline only made two. The soup example was worse. It turned something the reviewer planned to try next time into an actual ingredient change, with an amount they never specified.

I used a coding agent to investigate the repo, build a repeatable evaluation, and implement the fixes. I kept separate checkpoints for the baseline, editor changes, extraction changes, and review selection. The saved results show what improved and what still fails.

The pipeline now handles the original cookie and soup cases as intended. Five additional cases produced three passes, one partial result, and one failure. That's enough to show progress, but the failure also exposed a tradeoff I'd want to address next.

## Assumptions

- I assumed changing the model was within scope, including switching from GPT-3.5 Turbo to GPT-6 Luna. The brief didn't require keeping the original model. I still wanted to check the outputs rather than assume a newer model would solve the problems.
- I treated a reviewer's description of what they tried as the source for a change. Something they planned to try next time wasn't enough to apply it, and their reported results weren't independent proof that the recipe was better.
- I kept the existing approach of selecting one review per recipe. Combining suggestions from different reviewers would need a policy for handling conflicting changes.

## Problem analysis and solution approach

The most useful decision was to evaluate the model and the editor separately. The model can misunderstand a review while the Python code faithfully applies its bad instructions. The model can also propose a correct change that the editor fails to make. Both were happening here.

The original test script mostly checked whether the pipeline returned an output. I had the agent pin specific reviews, write down the expected changes before new model calls, and record the model's proposals alongside the actual recipe differences. Existing saved outputs had already been inspected, so the first cases were development cases. Later cases were evaluated without further tuning.

| Original live run | What went wrong |
| --- | --- |
| Cookie | Applied both sugar adjustments, but missed water removal, cream of tartar, and chilling. |
| Soup | Replaced dairy with an unsupported two cups of broth while keeping the original three-cup broth entry. Missed the substitutions the reviewer had actually tried. |

Even the new evaluation needed a correction: its first broth check passed because the original broth line was still present. Inspecting the full output revealed the extra entry. The check now examines all broth entries, and the original results are preserved.

## Technical decisions and rationale

I chose to defer substitutions with missing amounts rather than assume the original quantity carries over. That's conservative, and it means some reviews won't produce an edited recipe. The output distinguishes clarification from an enhancement and links edits to their source evidence. Any claimed benefit is attributed to the reviewer; we haven't cooked these recipes to verify it.

I initially kept GPT-3.5 Turbo to compare changes on the existing model. That went on too long: 13 development runs and 140 calls. I then asked the agent to compare newer models and switched to GPT-6 Luna. The cookie and soup run succeeded without retries, using seven calls. The workflow was simplified during the switch too, so this isn't a controlled model-only comparison. The [extraction findings](../evaluation/extraction_findings.md) include the attempts, token costs, and final outputs.

## Implementation details and challenges overcome

**The first code fix was the editor.** It used fuzzy matching to find a line, then exact, case-sensitive replacement to change it. That meant it could find `1 cup white sugar` when looking for `1 Cup White Sugar`, replace nothing, and still report success. It also skipped short phrases inside longer instructions. In another test, a request to remove absent pumpkin seeds deleted sunflower seeds instead.

The editor now requires one literal match, ignoring capitalization. It replaces the matching span, rejects missing or ambiguous targets, and only deletes a line when the target matches the whole line. A replacement that changes nothing produces no change record. Saved model proposals can be replayed through the editor without calling the model again, which made these fixes straightforward to verify.

**The next change was how the model reads a review.** It now lists each suggestion with an exact supporting quote and decides whether to apply it, treat it as a future plan, or request clarification. Each applicable suggestion then gets a recipe draft. Python converts the differences into edits and checks them before accepting the plan.

Those checks look for unsupported quantities, missing ingredient or instruction changes, and some ordering mistakes. Removing water, for example, must also update the instruction that uses it without losing the baking soda from the same step. The model gets up to two correction retries per stage. If a plan still fails validation, the pipeline withholds its edits and retains the analysis for review.

**Review selection also needed changing.** It previously picked a random flagged review. It now prefers nonblank `featured_tweaks`, falling back to flagged reviews if there are none. Within that pool, it uses the highest vote count when every candidate has one; otherwise it uses stored order. Ties also use stored order. The result records which review was selected and why.

The supplied data has no vote counts, and the scraper's featured labels come from photo reviews and keyword matching. So the fallback is predictable, but I can't call it highest-voted. Star ratings don't influence selection. The pipeline still chooses one review per recipe rather than combining potentially conflicting reviews.

The extraction comparisons use pinned reviews. They aren't necessarily the entries selected by the new default policy, which was checked separately with an offline audit and tests.

## Results

Here's where the final evaluation landed.

| Case | Result |
| --- | --- |
| Original cookie | All five suggestions applied, including instruction updates. Seven actual edit records. |
| Original soup | Tried substitutions recognized, missing amounts flagged, future broth increase excluded. Recipe unchanged. |
| New apple cake case | Pass: vague frosting change deferred; future extra apples excluded. |
| New nikujaga case | Partial: quantities deferred, but conditional broth advice described as tried. Some reasonable approximate wording rejected. |
| New porridge case | Pass: oat milk substituted in ingredients and directions; simmer time reduced to eight minutes. |
| New zucchini case | Fail: “I did not add butter” became a removal request. Rejecting it also discarded a valid oil reduction. |
| New ambiguous sugar case | Pass: asks which sugar to change instead of guessing. |

The five new cases had one run each, including the pipeline's existing retries, with no subsequent tuning. No incorrect edits reached their final recipes, but four of the five outputs made no edits. Avoiding a bad change doesn't always give the user a useful result, as the zucchini case shows.

There are 51 passing offline tests covering editing, validation, selection, and the evaluation code. Saved proposals replay to the same outputs. These checks support the implementation; the seven live cases are too small a sample to establish general model accuracy.

## Future improvements

I'd tackle negation and the all-or-nothing plan policy next. An invalid butter removal shouldn't necessarily block an independent oil reduction. The quantity and ingredient-name checks also need work: they're text rules that can reject valid approximations or aliases. Finally, genuine vote-based selection needs better source data. I left these limitations documented rather than continuing to tune against the same examples.

## Running the evaluation

To inspect the work, start with the [baseline and editor results](../evaluation/README.md), [extraction comparison](../evaluation/extraction_findings.md), and [five new cases](../evaluation/heldout_findings.md). Setup is in the [README](../README.md). From the repo root after installing dependencies, these commands run the offline tests and replay the saved cookie and soup proposals:

```sh
.venv/bin/python -m unittest discover -s evaluation -p 'test_*.py'
.venv/bin/python evaluation/run.py --replay evaluation/luna_live.json \
  --output test_output/replay.json
```

Replay needs no API key. Its raw content checks still flag the soup because those checks expect applied substitutions; the documented manual assessment accepts clarification. That can produce exit code 1 even when replay matches the saved output. The old smoke script also still counts a returned clarification object as success, so use the evaluation findings to judge correctness.
