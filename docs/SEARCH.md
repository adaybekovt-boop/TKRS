# TKRS asset search

`tools/search_assets.py` is the first agent-facing search layer for TKRS.

It searches only `index/index.json`. It does not scan or load the 3D binaries, so an agent can query hundreds or thousands of assets cheaply and inspect only the selected results.

## Basic usage

```bash
python tools/search_assets.py "industrial wall" --limit 5
```

```bash
python tools/search_assets.py "medieval door" --limit 5
```

Basic Russian aliases are also supported:

```bash
python tools/search_assets.py "средневековая дверь" --limit 5
```

## Filters

```bash
python tools/search_assets.py "wall" --subcategory walls --style industrial --format glb --limit 10
```

Available filters:

- `--category` (`architecture`, `movement`, `lighting`, `uiux`, or `vfx`)
- `--subcategory`
- `--style`
- `--format`
- `--source`
- `--license`
- `--min-score`
- `--limit`

## Output

The command emits JSON. Every result includes:

- asset ID and name
- relevance score
- matched query terms
- category and subcategory
- tags and styles
- format
- dimensions
- source and license
- repository path
- concrete asset files
- SHA-256 from the catalog

`index/index.json` contains one record per logical asset. The indexed SHA-256
and `index/checksums.sha256` both refer to that record's `primary_file`.

## Agent contract

Agents should use TKRS in this order:

1. Call `search_assets.py` with a short natural-language description.
2. Inspect only the returned candidates.
3. Choose an asset ID/path.
4. Read/import only that asset's files.
5. Search again if none of the first candidates fit.

Agents should not recursively scan `assets/` to discover models. The index is the discovery layer.

This CLI is intentionally dependency-free. A later MCP/skill layer can wrap the same `search_assets()` Python function without changing the asset library format.
