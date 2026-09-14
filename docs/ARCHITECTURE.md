# TKRS Architecture

TKRS separates the asset library from the agent context.

Agents should search the index first, inspect only a small set of matching records, then request the exact asset they need. The full library should never be loaded into the model context at once.

Planned flow:

`Agent -> TKRS search -> ranked asset results -> selected asset -> Roblox Studio`

Current repository state is scaffold-only. Search, validation, import tooling, and MCP/skill integration come later.
