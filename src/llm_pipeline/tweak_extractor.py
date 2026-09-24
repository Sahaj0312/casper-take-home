"""
Step 1: Tweak Extraction & Parsing

This module extracts structured modifications from review text using LLM processing.
It converts natural language descriptions of recipe changes into structured
ModificationObject instances.
"""

import os
from typing import Optional

from loguru import logger
from openai import OpenAI
from pydantic import ValidationError

from .models import ModificationObject, Recipe, RecipeDraft, Review, ReviewAnalysis
from .grounding import compile_draft, validate_analysis, validate_plan
from .prompts import INVENTORY_SYSTEM, PLANNING_SYSTEM, inventory_prompt, planning_prompt
from .review_selector import select_review


class TweakExtractor:
    """Extracts structured modifications from review text using LLM processing."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-6-luna"):
        """
        Initialize the TweakExtractor.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use for extraction
        """
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model
        logger.info(f"Initialized TweakExtractor with model: {model}")

    def _request_validated(self, system, prompt, schema, validate, max_retries):
        """Retry invalid output with explicit feedback; never silently accept it."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        failures = []
        for attempt in range(max_retries + 1):
            choice = None
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages,
                    response_format={"type": "json_object"}, temperature=0.1,
                    max_completion_tokens=3000, reasoning_effort="none",
                )
                choice = response.choices[0]
                if choice.finish_reason != "stop":
                    raise ValueError("Response incomplete; finish_reason is not stop")
                parsed = schema.model_validate_json(choice.message.content or "")
                return validate(parsed)
            except (ValidationError, ValueError) as exc:
                logger.warning(f"Invalid extraction stage, attempt {attempt + 1}: {exc}")
                if choice is not None and choice.message.content:
                    messages.append({"role": "assistant", "content": choice.message.content})
                failures.append(str(exc))
                messages.append({"role": "user", "content": "Validation failed. Satisfy ALL of these constraints together:\n"
                                 + "\n".join(dict.fromkeys(failures))
                                 + "\nReturn a corrected complete JSON object. Do not invent evidence."})
            except Exception as exc:
                # Do not log credential/account-bearing API exception messages.
                logger.error(f"Extraction request failed: {type(exc).__name__}")
                return None
        return None

    def _extract_analysis(self, review, recipe, max_retries):
        # Inventory the full review in one call, including compound changes and
        # future/uncertain actions. Code validates evidence and safe application;
        # it does not guess meaning from a restricted list of action verbs.
        return self._request_validated(
            INVENTORY_SYSTEM,
            inventory_prompt(review.text, recipe.title, recipe.ingredients, recipe.instructions),
            ReviewAnalysis, lambda value: validate_analysis(value, review.text), max_retries,
        )

    def extract_modification(
        self, review: Review, recipe: Recipe, max_retries: int = 2,
    ) -> Optional[ModificationObject]:
        if not review.has_modification:
            return None
        analysis = self._extract_analysis(review, recipe, max_retries)
        if analysis is None:
            return None
        actionable = [c for c in analysis.changes if c.disposition == "apply"]
        edits, sources = [], []
        working = recipe.model_copy(deep=True)
        from .recipe_modifier import RecipeModifier
        for change in actionable:
            single = ReviewAnalysis(changes=[change])
            targets = ("instructions" if change.modification_type == "technique_change" else
                       "ingredients AND instructions" if change.modification_type in ("addition", "removal", "ingredient_substitution") else "ingredients")
            validated = self._request_validated(
                PLANNING_SYSTEM,
                planning_prompt(change.evidence, working, single) + f"\nThis single change MUST edit {targets}. Keep unrelated actions intact.",
                RecipeDraft, lambda value: validate_plan(compile_draft(value, working, change.id), single, working), max_retries,
            )
            if validated is None:
                # Fail the whole connected plan closed; keep every extracted fact.
                for item in actionable:
                    item.disposition = "needs_clarification"
                    item.clarification = "Could not construct a complete, grounded and consistently applicable edit plan; review this change manually."
                edits, sources = [], []
                break
            part, links = validated
            edits.extend(part)
            sources.extend(links)
            patch = ModificationObject(modification_type=change.modification_type,
                                       reasoning=change.evidence, edits=part)
            working, _ = RecipeModifier().apply_modification(working, patch)
        applied = [c for c in analysis.changes if c.disposition == "apply"]
        reasoning = ("Reviewer evidence: " + "; ".join(c.evidence for c in applied)
                     if applied else "No actionable edits; see the review analysis for deferred changes.")
        return ModificationObject(
            modification_type=(applied or analysis.changes)[0].modification_type if analysis.changes else "technique_change",
            reasoning=reasoning, edits=edits, analysis=analysis, edit_sources=sources,
        )

    def extract_single_modification(
        self, reviews: list[Review], recipe: Recipe
    ) -> tuple[ModificationObject, Review] | tuple[None, None]:
        """
        Extract modification from one deterministically selected review.

        Args:
            reviews: List of reviews to choose from
            recipe: Original recipe being modified

        Returns:
            Tuple of (ModificationObject, source_Review) if successful, (None, None) otherwise
        """
        selected_review = select_review(reviews)
        if selected_review is None:
            logger.warning("No reviews with modifications found")
            return None, None

        logger.info(f"Selected review: {selected_review.text[:100]}...")
        logger.info(selected_review.selection.reason)

        modification = self.extract_modification(selected_review, recipe)
        if modification:
            logger.info("Successfully extracted modification from selected review")
            return modification, selected_review
        else:
            logger.warning("Failed to extract modification from selected review")
            return None, None

    def test_extraction(
        self, review_text: str, recipe_data: dict
    ) -> Optional[ModificationObject]:
        """
        Test extraction with raw text and recipe data.

        Args:
            review_text: Raw review text
            recipe_data: Raw recipe dictionary

        Returns:
            ModificationObject if successful
        """
        review = Review(text=review_text, has_modification=True)
        recipe = Recipe(
            recipe_id=recipe_data.get("recipe_id", "test"),
            title=recipe_data.get("title", "Test Recipe"),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
        )

        return self.extract_modification(review, recipe)
