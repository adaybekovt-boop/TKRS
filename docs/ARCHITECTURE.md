# TKRS Architecture

TKRS separates the asset library from the agent context.

Agents should search the index first, inspect only a small set of matching records, then request the exact asset they need. The full library should never be loaded into the model context at once.

Current flow:

`Agent -> TKRS search -> ranked asset results -> selected asset -> Roblox Studio`

The unified index covers architecture, movement, lighting, UI/UX, and VFX.
`tools/validate_repository.py` enforces metadata, licensing evidence, file safety,
model dependencies, media headers, unique IDs, paths, hashes, and index counts.
`tools/integrate_batches.py` provides the reusable inert-data import pipeline.
