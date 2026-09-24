"""
Pydantic data models for the LLM Analysis Pipeline.

These models define the structure for recipe modifications, enhanced recipes,
and all intermediate data formats used throughout the pipeline.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StrictInt, model_validator


ChangeType = Literal["ingredient_substitution", "quantity_adjustment", "technique_change", "addition", "removal"]


class ReviewChange(BaseModel):
    """One discrete change, including suggestions that must not become edits."""

    id: str
    modification_type: ChangeType
    summary: str
    evidence: str = Field(min_length=1, description="Exact supporting quote from the review")
    disposition: Literal["apply", "needs_clarification", "future_plan"]
    amount: Optional[str] = None
    amount_evidence: Optional[str] = None
    clarification: Optional[str] = None

    @model_validator(mode="after")
    def require_details(self):
        if self.disposition == "needs_clarification" and not self.clarification:
            raise ValueError("Deferred changes need a clarification question")
        return self


class ReviewAnalysis(BaseModel):
    changes: List[ReviewChange]
    outcome_evidence: Optional[str] = None


class GroundedEdit(BaseModel):
    target: Literal["ingredients", "instructions"]
    operation: Literal["replace", "add_after", "remove"]
    find: str
    replace: Optional[str] = None
    add: Optional[str] = None
    change_ids: List[str] = Field(min_length=1)


class EditPlan(BaseModel):
    edits: List[GroundedEdit]


class RecipeDraft(BaseModel):
    ingredients: List[str]
    instructions: List[str]


class ModificationEdit(BaseModel):
    """Individual atomic edit operation for a recipe modification."""

    target: Literal["ingredients", "instructions"] = Field(
        description="Whether this edit applies to ingredients or instructions"
    )
    operation: Literal["replace", "add_after", "remove"] = Field(
        default="replace",
        description="Type of operation: replace text, add after target, or remove",
    )
    find: str = Field(description="Text to find in the recipe")
    replace: Optional[str] = Field(
        default=None, description="Replacement text (required for replace operations)"
    )
    add: Optional[str] = Field(
        default=None, description="Text to add (required for add_after operations)"
    )


class ModificationObject(BaseModel):
    """Structured modification parsed from a review."""

    modification_type: Literal[
        "ingredient_substitution",
        "quantity_adjustment",
        "technique_change",
        "addition",
        "removal",
    ] = Field(description="Category of modification")

    reasoning: str = Field(description="Why this modification improves the recipe")

    edits: List[ModificationEdit] = Field(description="List of atomic edits to apply")
    analysis: Optional[ReviewAnalysis] = None
    edit_sources: Optional[List[List[str]]] = None


class SourceReview(BaseModel):
    """Reference to the original review that suggested the modification."""

    text: str = Field(description="Full text of the original review")
    reviewer: Optional[str] = Field(description="Username of the reviewer")
    rating: Optional[int] = Field(description="Star rating given by reviewer")


class ChangeRecord(BaseModel):
    """Record of a specific change made to the recipe."""

    type: Literal["ingredient", "instruction"] = Field(
        description="Type of element that was changed"
    )
    from_text: str = Field(description="Original text before modification")
    to_text: str = Field(description="New text after modification")
    operation: Literal["replace", "add", "remove"] = Field(
        description="Type of operation performed"
    )


class ModificationApplied(BaseModel):
    """Full record of a modification that was applied to a recipe."""

    source_review: SourceReview = Field(
        description="Review that suggested this modification"
    )
    modification_type: str = Field(description="Category of modification")
    reasoning: str = Field(description="Why this modification was applied")
    changes_made: List[ChangeRecord] = Field(
        description="Detailed list of changes made"
    )


class EnhancementSummary(BaseModel):
    """Summary of all modifications applied to a recipe."""

    total_changes: int = Field(description="Total number of changes made")
    change_types: List[str] = Field(description="Types of modifications applied")
    expected_impact: str = Field(
        description="Expected improvement from these modifications"
    )


class ReviewSelection(BaseModel):
    source: Literal["featured_tweaks", "reviews"]
    source_index: int
    review_text: str
    eligible_count: int
    method: Literal["highest_available_vote_count", "source_order"]
    vote_count: Optional[int] = None
    reason: str


class EnhancedRecipe(BaseModel):
    """Recipe with community modifications applied and full attribution."""

    recipe_id: str = Field(description="Enhanced recipe ID")
    original_recipe_id: str = Field(description="ID of the original recipe")
    title: str = Field(description="Enhanced recipe title")

    # Enhanced recipe content
    ingredients: List[str] = Field(description="Modified ingredients list")
    instructions: List[str] = Field(description="Modified instructions list")

    # Attribution and tracking
    modifications_applied: List[ModificationApplied] = Field(
        description="Full record of all modifications applied"
    )
    enhancement_summary: EnhancementSummary = Field(
        description="Summary of all enhancements"
    )
    review_analysis: Optional[ReviewAnalysis] = None
    edit_sources: Optional[List[List[str]]] = None
    enhancement_status: Literal["enhanced", "partial", "needs_clarification", "no_applicable_changes"] = "enhanced"
    review_selection: Optional[ReviewSelection] = None

    # Optional metadata
    description: Optional[str] = Field(description="Enhanced recipe description")
    servings: Optional[str] = Field(description="Number of servings")
    prep_time: Optional[str] = Field(description="Preparation time")
    cook_time: Optional[str] = Field(description="Cooking time")
    total_time: Optional[str] = Field(description="Total time")

    # Generation metadata
    created_at: str = Field(description="When this enhanced recipe was created")
    pipeline_version: str = Field(
        default="1.0.0", description="Version of the pipeline that created this"
    )


class Recipe(BaseModel):
    """Base recipe model for input data."""

    recipe_id: str
    title: str
    ingredients: List[str]
    instructions: List[str]
    description: Optional[str] = None
    servings: Optional[str] = None
    rating: Optional[Dict[str, Any]] = None
    # Include other fields as needed


class Review(BaseModel):
    """Review model for input data."""

    text: str
    rating: Optional[int] = None
    username: Optional[str] = None
    has_modification: bool = False
    source: Literal["featured_tweaks", "reviews"] = "reviews"
    source_index: int = 0
    vote_count: Optional[StrictInt] = Field(default=None, ge=0)
    selection: Optional[ReviewSelection] = None
