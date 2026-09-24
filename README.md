# Recipe Enhancement Platform

Automatically enhances recipes by analyzing and applying community-tested modifications from AllRecipes.com. Uses LLM processing to extract meaningful recipe tweaks and apply them with full citation tracking.

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) for fast, reliable Python package management.

### Prerequisites

- Python 3.13+
- `uv` package manager

## Setup

```bash
# Install dependencies
uv venv
source .venv/bin/activate
uv pip sync pyproject.toml
```

### Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your-openai-api-key-here
```

## Usage

### 1. Scrape Recipes (Optional - data already provided)

```bash
uv run python src/scraper_v2.py
```

### 2. Run Recipe Enhancement Pipeline

```bash
cd src

# Test single recipe (chocolate chip cookies)
uv run python test_pipeline.py single

# Process all recipes
uv run python test_pipeline.py all
```

## Output

### Enhanced Recipes

Enhanced recipes are saved in `src/data/enhanced/`:

- `enhanced_[recipe_id]_[recipe-name].json` - Individual enhanced recipes with modifications applied
- `pipeline_summary_report.json` - Summary of all processing results

### Data Structure

Original scraped recipes in `data/` directory contain reviews with `has_modification: true` flags. Enhanced recipes include:

The output contains the recipe, actual edit records, source review, and
`review_analysis`: every extracted change has literal evidence and an `apply`,
`future_plan`, or `needs_clarification` disposition. `edit_sources` connects edits
to those changes. `enhancement_status` distinguishes an enhanced recipe from one
requiring clarification. Future plans and missing quantities are not applied.

## How It Works

1. **Selection and extraction**: Prefer nonblank entries in `featured_tweaks`.
   If none exist, fall back to flagged `reviews`. Rank by explicit `vote_count`
   only when every eligible entry has a valid count; otherwise use stored order.
   Ties also use stored order. Star ratings never affect selection. Supplied data
   has no vote counts, so highest-voted status is unknown. The scraper's featured
   labels are a photo-review heuristic, not verified vote ranking. Output
   `review_selection` records the source, original index, text, and selection reason.
   Use **GPT-6 Luna**
   to inventory all its changes in one call. Validate evidence, quantities, and
   tried/future distinctions. API requests use Chat Completions, JSON mode,
   `reasoning_effort="none"`, and a 3,000-token completion limit.
2. **Planning and editing**: Plan each actionable change against the current
   recipe, validate ingredient/instruction consistency, and compile actual
   differences into unique literal edits. Invalid plans receive up to two
   retries. An exhausted planning stage returns clarification with no edits.
3. **Attribution**: Report only actual changes. Benefits are quoted reviewer
   observations, explicitly unverified, rather than invented improvements.

Missing substitution quantities are surfaced as questions; original volumes or
conversion ratios are never silently inherited. Validators are conservative
checks, not proof of semantic correctness. Manual output review remains necessary.

## Development

For offline regression tests and saved-proposal replay, see
[`evaluation/README.md`](evaluation/README.md). Original baseline reports are
preserved separately from the editor replay and Luna results. See
[`evaluation/extraction_findings.md`](evaluation/extraction_findings.md) for the
latest comparison, limitations, and rerun commands.

```bash
# Add dependencies
uv add <package_name>

# Run tests
cd src && uv run python test_pipeline.py single
```
