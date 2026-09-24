"""Small, evidence-focused prompts used for one review or one change at a time."""

import json

from .grounding import ingredient_names

INVENTORY_SYSTEM = """Extract recipe changes from the full reviewer text. Return JSON only.
Categories: ingredient_substitution, quantity_adjustment, technique_change, addition, removal.
Each changed ingredient or technique needs its own entry. Split compound sentences
and numbered items into ALL discrete changes, even when one item changes two
ingredients. Quote tried and future clauses separately; never merge them. Copy evidence directly
from the statement, without adding words. Disposition is apply for actual,
sufficiently specified changes; needs_clarification for actual changes missing
necessary details; future_plan for untried intentions. Never turn an opinion
('too thick', 'delicious') into a change. No changes means changes: [].
A substitution without an amount needs clarification. Do not inherit an amount
from the recipe. Milk fat percentage is not a volume. 'With X' / 'w X' reports
using X, not replacing X with something else. Technique changes include chilling,
resting, flattening, temperature, timing and portioning. Do not omit these.
Amount is null unless the statement supplies one; amount_evidence must be an
exact quote supporting it. Equivalent number notation is allowed, no unit
conversions. Clarification must ask about missing facts, not suggest new changes.
Do not invent quantities, motives or benefits. Optional outcome_evidence must be
one exact quote about the reviewer's observed result. Null is fine."""

PLANNING_SYSTEM = """Return the complete recipe after applying ONE supported change.
Output JSON with ingredients (array of strings) and instructions (array of strings).
Do not output edit operations. Preserve every unrelated ingredient and action.
Update ingredient AND directions for ingredient additions/removals/substitutions.
When removing an ingredient from a multi-action step, preserve other actions.
For example, if a step says 'Dissolve X in Y. Add to the mixture with Z', and
ONLY Y is omitted, rewrite it as 'Add X and Z to the mixture.' Do not discard X
or keep telling the cook to use Y. This is a general preservation rule, not a
new recipe change. All retained ingredients must still be incorporated.
Add an instruction explaining where to incorporate any added ingredient.
Place new technique steps before the actions they must precede.
An amount change does NOT add another use of the ingredient. Keep instructions
unchanged unless an existing stated amount needs updating. Never add the same
ingredient twice. A step described as 'before X' belongs immediately before X,
after the preceding preparation is complete (e.g. fully mix a batter before
chilling it for portioning). Do not move that step ahead of earlier preparation.
Use only quantities provided by the supporting statement, or retain unchanged
original quantities. Equivalent written fractions are allowed. No new quantities,
benefits, or commentary. Add new lines after an existing line, never at the start.
Do not apply any other change from the review."""


def inventory_prompt(review_text, title, ingredients, instructions, context=None):
    return f"""Recipe: {title}
Ingredients: {json.dumps(ingredients, ensure_ascii=False)}
Instructions: {json.dumps(instructions, ensure_ascii=False)}

Classify ALL changes in this reviewer statement:
{review_text}

Return this shape (null for unavailable optional values):
{{"changes":[{{"id":"c1","modification_type":"technique_change","summary":"neutral description","evidence":"exact substring of the statement","disposition":"apply","amount":null,"amount_evidence":null,"clarification":null}}],"outcome_evidence":null}}

Examples of classification:
"I let the dough rest for two hours" -> technique_change, apply.
"I used skim milk" -> ingredient_substitution, needs_clarification: how much milk?
"Next time I will add honey" -> addition, future_plan, never apply.
"Too thick" -> no change; do not ask how the user wants to change it.
These examples are not edits to the recipe. Analyze the reviewer statement above."""


def planning_prompt(review_text, recipe, analysis):
    dependencies = []
    if analysis.changes[0].modification_type in ("removal", "ingredient_substitution"):
        names = ingredient_names(recipe.ingredients)
        for step in recipe.instructions:
            used = sorted(name for name in names if name in step.lower())
            if len(used) > 1:
                dependencies.append({"step": step, "ingredients_used": used})
    return f"""Original recipe:
{json.dumps({"ingredients": recipe.ingredients, "instructions": recipe.instructions}, ensure_ascii=False)}

Apply ONLY this supported change:
{json.dumps(analysis.changes[0].model_dump(), ensure_ascii=False)}

Return the entire updated recipe as {{"ingredients":[...],"instructions":[...]}}.
Preserve unrelated content. Update the dependent instructions too.
Original multi-ingredient step dependencies: {json.dumps(dependencies)}
For each affected step, REMOVE the omitted ingredient's use but explicitly
INCORPORATE EVERY OTHER listed ingredient in the rewritten step. Do not delete
a whole action and lose the other ingredients. Do not restore the omitted ingredient."""
