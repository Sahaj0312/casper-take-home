"""Deterministic selection using source provenance, never star ratings."""

from .models import Review, ReviewSelection


def select_review(reviews: list[Review]) -> Review | None:
    featured = [r for r in reviews if r.source == "featured_tweaks" and r.text.strip()]
    candidates = featured or [r for r in reviews if r.has_modification and r.text.strip()]
    if not candidates:
        return None
    # Unknown counts cannot be treated as zero or compared with known counts.
    complete_votes = all(r.vote_count is not None for r in candidates)
    selected = (max(candidates, key=lambda r: r.vote_count)
                if complete_votes else candidates[0])
    # max preserves source order on ties. This is a rank within this pool only.
    reason = (
        "Highest explicit vote_count among eligible entries in this source; ties use stored order. Not a site-wide ranking."
        if complete_votes else
        "Vote counts are missing or incomplete; using stored source order. Highest-voted status is unknown."
    )
    if not featured:
        reason = "No nonblank Featured Tweaks entries; falling back to flagged reviews. " + reason
    return selected.model_copy(update={"selection": ReviewSelection(
        source=selected.source, source_index=selected.source_index,
        review_text=selected.text, eligible_count=len(candidates),
        method="highest_available_vote_count" if complete_votes else "source_order",
        vote_count=selected.vote_count, reason=reason,
    )})
