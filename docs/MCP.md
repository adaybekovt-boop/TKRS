# TKRS MCP

TKRS runs as a local MCP server over `stdio` by default. No website, domain, VPS, or open port is required.

## Why local

The coding agent launches `server/tkrs_mcp.py` as a child process and talks to it over stdin/stdout. The server reads the local TKRS index and returns only the small set of asset records the agent asks for.

This keeps the large 3D library out of model context and avoids uploading assets to a separate web service.

## Install

```bash
pip install -r requirements-mcp.txt
```

Python 3.10+ is required by the MCP Python SDK.

## Server

```bash
python server/tkrs_mcp.py
```

When started directly it appears to do nothing. That is correct for a stdio MCP server: it waits for an MCP host such as Codex to start sending protocol messages.

## Tools

### `search_assets`
Search the TKRS catalog using natural-language keywords and optional filters. Use this first.

### `get_asset`
Resolve one selected asset ID into full metadata, local file paths, and its absolute asset directory.

### `list_asset_categories`
Return the available subcategories and their asset counts.

The server also exposes `tkrs://catalog/info` as a small catalog resource.

## Intended agent flow

1. Agent decides it needs an environment object.
2. Agent calls `search_assets` instead of generating geometry immediately.
3. Agent compares a small ranked result set.
4. Agent calls `get_asset` for the selected candidate.
5. A Roblox Studio integration imports/places that selected asset.

TKRS MCP is currently read-only. It does not modify Roblox Studio yet.

## Remote deployment later

If TKRS needs to be shared across machines, the same MCP server can later be exposed with Streamable HTTP and hosted like a normal web service. That is optional; local stdio is the intended first version.
