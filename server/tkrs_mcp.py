#!/usr/bin/env python3
"""Local MCP server for TKRS.

This server is intentionally read-only. It exposes the searchable TKRS catalog
without loading model binaries into the agent context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from tools.search_assets import REPO_ROOT, load_index, search_assets as search_catalog

INDEX_PATH = REPO_ROOT / "index" / "index.json"

mcp = MCPServer("TKRS")


def _catalog() -> dict[str, Any]:
    return load_index(INDEX_PATH)


def _find_asset(asset_id: str) -> dict[str, Any] | None:
    for asset in _catalog()["assets"]:
        if asset.get("id") == asset_id:
            return asset
    return None


def _asset_files(asset: dict[str, Any]) -> list[str]:
    path = asset.get("path")
    if not path:
        return []
    directory = REPO_ROOT / path
    if not directory.is_dir():
        return []
    return [
        str(file.relative_to(REPO_ROOT)).replace("\\", "/")
        for file in sorted(directory.iterdir())
        if file.is_file()
    ]


@mcp.tool()
def search_assets(
    query: str,
    limit: int = 8,
    subcategory: str | None = None,
    style: str | None = None,
    format_name: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Search TKRS assets by natural-language description.

    Use this before building environment geometry from scratch. Returns only a
    small ranked set of metadata records, file paths and dimensions.
    """
    catalog = _catalog()
    safe_limit = max(1, min(int(limit), 25))
    results = search_catalog(
        catalog["assets"],
        query,
        limit=safe_limit,
        subcategory=subcategory,
        style=style,
        format_name=format_name,
        source=source,
    )
    return {
        "query": query,
        "catalog_asset_count": len(catalog["assets"]),
        "result_count": len(results),
        "results": results,
    }


@mcp.tool()
def get_asset(asset_id: str) -> dict[str, Any]:
    """Get one TKRS asset after selecting its ID from search_assets."""
    asset = _find_asset(asset_id)
    if asset is None:
        return {"found": False, "id": asset_id}
    return {
        "found": True,
        "asset": asset,
        "files": _asset_files(asset),
        "absolute_directory": str((REPO_ROOT / asset["path"]).resolve()),
    }


@mcp.tool()
def list_asset_categories() -> dict[str, Any]:
    """List available TKRS subcategories and counts."""
    catalog = _catalog()
    counts: dict[str, int] = {}
    for asset in catalog["assets"]:
        subcategory = str(asset.get("subcategory") or "unknown")
        counts[subcategory] = counts.get(subcategory, 0) + 1
    return {
        "asset_count": len(catalog["assets"]),
        "subcategories": dict(sorted(counts.items())),
    }


@mcp.resource("tkrs://catalog/info")
def catalog_info() -> str:
    """Small summary of the current TKRS catalog."""
    catalog = _catalog()
    payload = {
        "version": catalog.get("version"),
        "generated_at": catalog.get("generated_at"),
        "asset_count": len(catalog["assets"]),
        "index": str(INDEX_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
    }
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
