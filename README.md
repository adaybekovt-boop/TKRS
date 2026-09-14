# TKRS

TKRS is a searchable asset library for Roblox Studio agents. It lets AI coding agents find and reuse ready-made assets instead of generating every environment piece from scratch.

## Current state

- 3,604 validated assets across architecture, movement, lighting, UI/UX, and VFX
- searchable `index/index.json`
- dependency-free natural-language search CLI
- filters for subcategory, style, format, source, and license
- English search plus basic Russian aliases
- per-asset dimensions, source, license, path, format, and SHA-256 metadata

## Search

```bash
python tools/search_assets.py "industrial wall" --limit 5
```

Filter explicitly by category when the query is domain-specific:

```bash
python tools/search_assets.py "sprint animation" --category movement --limit 5
python tools/search_assets.py "window gobo" --category lighting --limit 5
```

```bash
python tools/search_assets.py "средневековая дверь" --limit 5
```

The command returns compact agent-friendly asset records without loading the 3D model files. See `docs/SEARCH.md` for the search contract and filters.

## Repository layout

- `assets/` — ready-made assets grouped by category/subcategory
- `textures/` — shared deduplicated textures
- `index/` — searchable catalog and checksums
- `schemas/` — metadata schemas
- `tools/` — search, materialization, and validation tooling
- `docs/` — project documentation
- `tests/` — automated checks

## Agent rule

Agents should search the catalog first and inspect/import only selected candidates. They should not recursively scan the entire `assets/` tree to discover models.

Every imported asset must retain clear source and license information. Assets with unclear redistribution/use rights must not be added.
