"""Conservative checks between evidence extraction and editing."""

import re
from fractions import Fraction
from difflib import SequenceMatcher

from .models import EditPlan, ModificationEdit, ReviewAnalysis
from .recipe_modifier import RecipeModifier


def normalize_amounts(text):
    """Normalize common written numbers/fractions, without converting units."""
    text = text.lower()
    text = re.sub(r"\b(?:a|an) (half|quarter)\b", r"\1", text)
    text = re.sub(r"\b(half|quarter) (?:a|an)\b", r"\1", text)
    text = re.sub(r"\b(one|two|three)[ -]and[ -]a[ -]half\b",
                  lambda m: str({"one": 1.5, "two": 2.5, "three": 3.5}[m[1]]), text)
    text = re.sub(r"\b(\d+)\s+(\d+)/(\d+)\b", lambda m: str(float(int(m[1]) + Fraction(int(m[2]), int(m[3])))), text)
    text = re.sub(r"\b(\d+)/(\d+)\b", lambda m: str(float(Fraction(int(m[1]), int(m[2])))), text)
    words = {"one": "1", "two": "2", "three": "3", "four": "4", "half": "0.5", "quarter": "0.25"}
    text = re.sub(r"\b(one|two|three|four|half|quarter)\b", lambda m: words[m[0]], text)
    text = re.sub(r"\b(?:a|an) (?=cup|teaspoon|tablespoon|hour|minute|egg|pinch)", "1 ", text)
    text = re.sub(r"\b(cup|teaspoon|tablespoon|hour|minute|egg)s\b", r"\1", text)
    text = re.sub(r"\b(\d+)\.0\b", r"\1", text)
    return text


def compile_draft(draft, recipe, change_id):
    """Compile actual list differences into the existing safe editor contract."""
    edits = []
    for target in ("ingredients", "instructions"):
        before, after = getattr(recipe, target), getattr(draft, target)
        for operation, i, j, a, b in reversed(SequenceMatcher(None, before, after, autojunk=False).get_opcodes()):
            if operation == "equal":
                continue
            old, new = before[i:j], after[a:b]
            paired = min(len(old), len(new))
            for offset in reversed(range(paired)):
                edits.append(dict(target=target, operation="replace", find=old[offset], replace=new[offset], change_ids=[change_id]))
            for line in reversed(old[paired:]):
                edits.append(dict(target=target, operation="remove", find=line, change_ids=[change_id]))
            if new[paired:]:
                anchor = new[paired - 1] if paired else before[i - 1] if i else None
                if anchor is None:
                    raise ValueError("Add new lines after an existing line, not before the first line")
                for line in reversed(new[paired:]):
                    edits.append(dict(target=target, operation="add_after", find=anchor, add=line, change_ids=[change_id]))
    return EditPlan(edits=edits)


def ingredient_names(lines):
    """Simple literal identities for dependency checks, not a food ontology."""
    names = set()
    for line in lines:
        name = re.sub(r"^[\d. /]+\s*(?:cup|teaspoon|tablespoon|pound|ounce|gram|pinch)s?\s*", "", normalize_amounts(line))
        name = re.sub(r"^(?:packed|chopped|sifted)\s+", "", name).split(",")[0].strip()
        if name:
            names.add(name)
    return names


def validate_analysis(analysis: ReviewAnalysis, review_text: str) -> ReviewAnalysis:
    ids = [change.id for change in analysis.changes]
    if len(ids) != len(set(ids)) or any(not ident.strip() for ident in ids):
        raise ValueError("Change IDs must be unique and nonempty")
    if analysis.outcome_evidence and analysis.outcome_evidence not in review_text:
        raise ValueError("Outcome must be an exact reviewer quote")
    for change in analysis.changes:
        if change.evidence not in review_text:
            raise ValueError(f"{change.id}: evidence is not an exact review quote")
        needs_amount = change.modification_type in ("addition", "ingredient_substitution", "quantity_adjustment")
        if needs_amount and change.disposition == "apply" and not change.amount:
            quantities = re.findall(
                r"\b(?:\d+(?:[./]\d+)?(?:\s+\d+/\d+)?|(?:one|two|three)(?:-and-a-half)?|(?:a\s+)?half|quarter|a|an)\s+(?:cups?|teaspoons?|tablespoons?|eggs?|pounds?|ounces?|grams?)\b",
                change.evidence, re.I,
            )
            if len(quantities) > 1:
                raise ValueError(f"{change.id}: evidence contains multiple ingredient quantities; split into discrete changes with narrow exact quotes")
            if quantities:
                change.amount, change.amount_evidence = quantities[0], change.evidence
        if change.amount is not None:
            if (not change.amount.strip() or not change.amount_evidence
                    or change.amount_evidence not in review_text
                    or normalize_amounts(change.amount) not in normalize_amounts(change.amount_evidence)):
                raise ValueError(f"{change.id}: amount must be copied from supporting review evidence")
        if re.search(r"\b(next time|will (?:use|add|try|make)|would (?:use|add|try))\b", change.evidence, re.I):
            if re.search(r"\b(used|added|omitted|even w)\b", change.evidence, re.I):
                raise ValueError(f"{change.id}: evidence mixes tried and future clauses; separate them and quote each clause individually")
            if change.disposition != "future_plan":
                raise ValueError(f"{change.id}: future-intent evidence must be classified future_plan; isolate tried actions separately")
        if change.disposition == "apply" and needs_amount and (not change.amount or "%" in change.amount):
            change.disposition = "needs_clarification"
            change.clarification = "What quantity and unit did you actually use? No amount will be assumed."
    # Clause coverage catches omissions, including shorthand such as 'Even w'.
    # This conservative screen complements, rather than proves, semantic recall.
    cue = re.compile(r"\b(used|added|omitted|substituted|replaced|refrigerated|chilled|halved|doubled|next time|even w)\b", re.I)
    for clause in re.split(r"[;!?]|\.(?!\d)|\s+-\s*|-(?=\s*will\b)", review_text):
        clause = clause.strip()
        if cue.search(clause) and not any(c.evidence in clause or clause in c.evidence for c in analysis.changes):
            raise ValueError(f"Unaccounted change clause: {clause!r}. Include its tried/future/unclear change(s).")
    # A second quantity joined by 'and' must not disappear inside one change.
    for match in re.finditer(r"\band\s+(\d+(?:\.\d+)?\s+(?:cup|teaspoon|tablespoon|egg))\b", normalize_amounts(review_text)):
        amount = match[1]
        if not any(c.amount and normalize_amounts(c.amount) == amount for c in analysis.changes):
            raise ValueError(f"Compound change lost amount {amount!r}; create a separate entry for each changed ingredient")
    return analysis


def validate_plan(plan, analysis, recipe):
    """Require complete, executable edits with traceable changes and quantities.

    These checks are not a semantic proof: quote interpretation and ingredient
    identity still need evaluation. Fail closed on invalid/partial plans.
    """
    supported = {c.id: c for c in analysis.changes if c.disposition == "apply"}
    covered = {ident: set() for ident in supported}
    current = {field: list(getattr(recipe, field)) for field in ("ingredients", "instructions")}
    modifier = RecipeModifier()
    edits, sources = [], []
    for edit in plan.edits:
        if not set(edit.change_ids) <= supported.keys():
            raise ValueError("Edit cites an unknown, future, or unresolved change")
        payload = edit.replace if edit.operation == "replace" else edit.add or ""
        payload = payload or ""
        evidence = " ".join(supported[ident].evidence + " " + (supported[ident].amount_evidence or "")
                            for ident in edit.change_ids)
        # Do not silently convert number words/units or create new numeric values.
        numbers = lambda text: set(re.findall(r"\d+(?:\.\d+)?", normalize_amounts(text)))
        if not numbers(payload) <= numbers(evidence + " " + edit.find):
            raise ValueError("Edit introduces numerical values absent from its source evidence/anchor")
        for ident in edit.change_ids:
            change = supported[ident]
            covered[ident].add(edit.target)
            if edit.target == "ingredients" and edit.operation != "remove" and change.amount:
                if normalize_amounts(change.amount) not in normalize_amounts(payload):
                    raise ValueError(f"{ident}: ingredient amount must preserve its evidence phrase")
        atomic = ModificationEdit(**edit.model_dump(exclude={"change_ids"}))
        after, records = modifier.apply_edit(atomic, current[edit.target])
        if len(records) != 1:
            raise ValueError("Edit target/payload is missing, ambiguous, or unchanged")
        current[edit.target] = after
        edits.append(atomic)
        sources.append(edit.change_ids)
    for ident, change in supported.items():
        required = {"instructions"} if change.modification_type == "technique_change" else {"ingredients"}
        if change.modification_type in ("addition", "removal", "ingredient_substitution"):
            required.add("instructions")
        if not required <= covered[ident]:
            raise ValueError(f"{ident}: missing ingredient or dependent instruction edits")
        linked = [edit for edit in plan.edits if ident in edit.change_ids]
        if change.modification_type == "quantity_adjustment":
            # Changing an amount cannot introduce an additional use of that
            # ingredient in an unrelated step (e.g. a second sugar addition).
            names = []
            for edit in linked:
                if edit.target == "ingredients":
                    name = re.sub(r"^[\d. /]+\s*(?:cups?|teaspoons?|tablespoons?|pounds?|ounces?|grams?)\s*", "", edit.find.lower())
                    name = re.sub(r"^(?:packed|chopped|sifted)\s+", "", name).split(",")[0]
                    names.append(name)
            for edit in linked:
                if edit.target == "instructions" and not any(name in edit.find.lower() for name in names):
                    raise ValueError("Quantity adjustment must not introduce a new ingredient-use step. Preserve instructions that do not already mention that ingredient.")
        if change.modification_type == "technique_change" and "before" in change.evidence.lower():
            following = change.evidence.lower().split("before", 1)[1]
            actions = []
            for word, pattern in (("scoop", r"\bscoop\w*|\bdrop spoonfuls\b"),
                                  ("bak", r"\bbake\b"), ("serv", r"\bserve\b"),
                                  ("fry", r"\bfry\b"), ("mix", r"\bmix\b")):
                if word in following:
                    actions.append(pattern)
            anchors = [line for line in recipe.instructions if any(re.search(p, line, re.I) for p in actions)]
            added = [line for line in current["instructions"] if line not in recipe.instructions]
            if not anchors or not added:
                raise ValueError("Cannot establish the explicit 'before' ordering; preserve the original actions and insert a separate step immediately before the named action")
            target = current["instructions"].index(anchors[0]) if anchors[0] in current["instructions"] else -1
            if target < 1 or current["instructions"][target - 1] not in added:
                raise ValueError(f"Place the new technique step immediately before: {anchors[0]!r}, after preceding preparation is complete")
    before_names, after_names = ingredient_names(recipe.ingredients), ingredient_names(current["ingredients"])
    removed_names, added_names = before_names - after_names, after_names - before_names
    for edit in plan.edits:
        if edit.target != "instructions":
            continue
        kinds = {supported[ident].modification_type for ident in edit.change_ids}
        if kinds <= {"removal", "ingredient_substitution"} and not any(name in edit.find.lower() for name in removed_names):
            raise ValueError("Do not rewrite unrelated instruction steps; only steps using the removed/replaced ingredient may change")
        if kinds == {"addition"} and not any(name in (edit.replace or edit.add or "").lower() for name in added_names):
            raise ValueError("An addition may only change instructions to incorporate the added ingredient")
    before_steps, after_steps = " ".join(recipe.instructions).lower(), " ".join(current["instructions"]).lower()
    for name in before_names & after_names:
        if name in before_steps and name not in after_steps:
            raise ValueError(f"Keep the instruction for unchanged ingredient {name!r}; removing another ingredient must not discard its use")
    for name in before_names - after_names:
        if name in after_steps:
            raise ValueError(f"Directions still use removed ingredient {name!r}")
    for name in after_names - before_names:
        if name not in after_steps:
            raise ValueError(f"Directions do not incorporate new ingredient {name!r}")
    return edits, sources
