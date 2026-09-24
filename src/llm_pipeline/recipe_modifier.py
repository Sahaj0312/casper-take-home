"""
Step 2: Recipe Modification

This module applies structured modifications to recipes using search-and-replace operations.
It takes ModificationObject instances and applies their edits to recipe ingredients and instructions.
"""

import copy
import re
from typing import List, Optional, Tuple

from loguru import logger

from .models import (
    ModificationObject,
    ModificationEdit,
    Recipe,
    ChangeRecord
)


class RecipeModifier:
    """Applies structured modifications to recipes using search-and-replace operations."""

    def __init__(self, similarity_threshold: float = 0.6):
        # Retain the constructor argument for existing callers. Fuzzy matching
        # is no longer used: a similarity score cannot establish ingredient identity.
        self.similarity_threshold = similarity_threshold

    def _find_unique_span(self, target: str, candidates: List[str]) -> Optional[Tuple[int, int, int]]:
        """Return (line index, start, end) for one case-insensitive literal span.

        Count occurrences across all lines, including overlapping occurrences.
        Empty, absent, and ambiguous anchors are rejected rather than guessed.
        """
        if not target.strip():
            return None
        pattern = re.compile(re.escape(target), re.IGNORECASE)
        found = None
        for index, line in enumerate(candidates):
            offset = 0
            while match := pattern.search(line, offset):
                if found is not None:
                    return None
                found = (index, match.start(), match.end())
                offset = match.start() + 1
        return found

    def find_best_match(self, target: str, candidates: List[str]) -> Tuple[Optional[str], Optional[int], float]:
        """Compatibility wrapper: unique literal match scores 1, rejection 0."""
        match = self._find_unique_span(target, candidates)
        if match is None:
            return None, None, 0.0
        index, _, _ = match
        return candidates[index], index, 1.0

    def _resolve_edit(
        self, edit: ModificationEdit, content: List[str]
    ) -> Tuple[Optional[Tuple[int, int, int]], Optional[str]]:
        """Resolve and validate an edit against the content at this step."""
        match = self._find_unique_span(edit.find, content)
        if match is None:
            return None, "target is empty, missing, or ambiguous"
        index, start, end = match
        if edit.operation == "replace":
            if not edit.replace or not edit.replace.strip():
                return None, "replacement text is missing; use remove to delete a line"
            new_text = content[index][:start] + edit.replace + content[index][end:]
            if new_text == content[index]:
                return None, "replacement would not change content"
        elif edit.operation == "add_after":
            if not edit.add or not edit.add.strip():
                return None, "addition text is missing"
        elif edit.operation == "remove":
            if start != 0 or end != len(content[index]):
                return None, "removal requires a whole-line target"
        return match, None

    def apply_edit(
        self,
        edit: ModificationEdit,
        recipe_content: List[str]
    ) -> Tuple[List[str], List[ChangeRecord]]:
        """Apply one uniquely anchored edit; reject without mutation or records.

        Replacement uses the resolved span, so case variants and short literal
        instruction snippets behave consistently. Removal always deletes a whole
        line and therefore requires a whole-line anchor. Rejected edits are
        logged; the existing (content, records) return contract is preserved.
        """
        modified_content = list(recipe_content)
        match, reason = self._resolve_edit(edit, modified_content)
        if match is None:
            logger.warning(f"Rejected {edit.operation} in {edit.target}: {reason}: {edit.find!r}")
            return modified_content, []

        index, start, end = match
        original_text = modified_content[index]
        if edit.operation == "replace":
            new_text = original_text[:start] + edit.replace + original_text[end:]
            modified_content[index] = new_text
            from_text, to_text, operation = original_text, new_text, "replace"
        elif edit.operation == "add_after":
            modified_content.insert(index + 1, edit.add)
            from_text, to_text, operation = "", edit.add, "add"
        else:  # remove; _resolve_edit has required a whole-line match
            modified_content.pop(index)
            from_text, to_text, operation = original_text, "", "remove"

        record = ChangeRecord(
            type="ingredient" if edit.target == "ingredients" else "instruction",
            from_text=from_text, to_text=to_text, operation=operation,
        )
        return modified_content, [record]

    def apply_modification(
        self,
        recipe: Recipe,
        modification: ModificationObject
    ) -> Tuple[Recipe, List[ChangeRecord]]:
        """
        Apply a complete modification to a recipe.

        Args:
            recipe: Original recipe to modify
            modification: Structured modification to apply

        Returns:
            Tuple of (modified_recipe, all_change_records)
        """
        logger.info(f"Applying {modification.modification_type} with {len(modification.edits)} edits")

        # Deep copy the recipe
        modified_recipe = Recipe(
            recipe_id=f"{recipe.recipe_id}_modified",
            title=recipe.title,
            ingredients=copy.deepcopy(recipe.ingredients),
            instructions=copy.deepcopy(recipe.instructions),
            description=recipe.description,
            servings=recipe.servings,
            rating=recipe.rating
        )

        all_change_records = []

        # Apply each edit
        for edit in modification.edits:
            if edit.target == "ingredients":
                modified_recipe.ingredients, change_records = self.apply_edit(
                    edit, modified_recipe.ingredients
                )
            elif edit.target == "instructions":
                modified_recipe.instructions, change_records = self.apply_edit(
                    edit, modified_recipe.instructions
                )
            else:
                logger.warning(f"Unknown edit target: {edit.target}")
                continue

            all_change_records.extend(change_records)

        logger.info(f"Finished modification: {len(all_change_records)} actual changes from {len(modification.edits)} proposed edits")
        return modified_recipe, all_change_records

    def apply_modifications_batch(
        self,
        recipe: Recipe,
        modifications: List[ModificationObject]
    ) -> Tuple[Recipe, List[List[ChangeRecord]]]:
        """
        Apply multiple modifications to a recipe sequentially.

        Args:
            recipe: Original recipe to modify
            modifications: List of modifications to apply

        Returns:
            Tuple of (final_modified_recipe, list_of_change_records_per_modification)
        """
        current_recipe = recipe
        all_change_records = []

        logger.info(f"Applying {len(modifications)} modifications sequentially")

        for i, modification in enumerate(modifications):
            logger.info(f"Applying modification {i + 1}/{len(modifications)}: {modification.modification_type}")

            current_recipe, change_records = self.apply_modification(current_recipe, modification)
            all_change_records.append(change_records)

        logger.info(f"Finished batch. Final recipe has {len(current_recipe.ingredients)} ingredients and {len(current_recipe.instructions)} instructions")
        return current_recipe, all_change_records

    def validate_modification_safety(
        self,
        modification: ModificationObject,
        recipe: Recipe
    ) -> Tuple[bool, List[str]]:
        """
        Validate edit targets and payloads in sequence, without mutating the recipe.

        Args:
            modification: Modification to validate
            recipe: Recipe being modified

        Returns:
            Tuple of (is_safe, list_of_warnings)
        """
        warnings = []
        current = {
            "ingredients": list(recipe.ingredients),
            "instructions": list(recipe.instructions),
        }
        for edit in modification.edits:
            _, reason = self._resolve_edit(edit, current[edit.target])
            if reason:
                warnings.append(f"Cannot apply {edit.operation} for {edit.find!r}: {reason}")
                continue
            current[edit.target], _ = self.apply_edit(edit, current[edit.target])
        return not warnings, warnings
