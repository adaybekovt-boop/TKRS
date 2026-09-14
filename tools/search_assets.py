#!/usr/bin/env python3
"""Search the TKRS asset catalog without loading asset binaries.

The module is intentionally dependency-free so coding agents can call it in any
normal Python 3 checkout of the repository.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = REPO_ROOT / "index" / "index.json"

# Canonical aliases keep agent queries simple and also allow basic Russian queries.
ALIASES = {
    "walls": "wall",
    "стена": "wall",
    "стены": "wall",
    "doors": "door",
    "дверь": "door",
    "двери": "door",
    "windows": "window",
    "окно": "window",
    "окна": "window",
    "stairs": "stair",
    "staircase": "stair",
    "лестница": "stair",
    "лестницы": "stair",
    "columns": "column",
    "pillar": "column",
    "pillars": "column",
    "колонна": "column",
    "колонны": "column",
    "roofs": "roof",
    "крыша": "roof",
    "крыши": "roof",
    "floors": "floor",
    "пол": "floor",
    "полы": "floor",
    "ceilings": "ceiling",
    "потолок": "ceiling",
    "потолки": "ceiling",
    "fences": "fence",
    "забор": "fence",
    "заборы": "fence",
    "gates": "gate",
    "ворота": "gate",
    "arches": "arch",
    "арка": "arch",
    "арки": "arch",
    "beams": "beam",
    "балка": "beam",
    "балки": "beam",
    "pipes": "pipe",
    "труба": "pipe",
    "трубы": "pipe",
    "railings": "railing",
    "перила": "railing",
    "panels": "panel",
    "панель": "panel",
    "панели": "panel",
    "vents": "vent",
    "вентиляция": "vent",
    "rooms": "room",
    "комната": "room",
    "комнаты": "room",
    "industrial": "industrial",
    "индустриальный": "industrial",
    "индустриальная": "industrial",
    "medieval": "medieval",
    "средневековый": "medieval",
    "средневековая": "medieval",
    "dungeon": "dungeon",
    "подземелье": "dungeon",
    "castle": "castle",
    "замок": "castle",
    "modular": "modular",
    "модульный": "modular",
    "lowpoly": "low-poly",
    "low-poly": "low-poly",
    "низкополигональный": "low-poly",
}

FIELD_WEIGHTS = {
    "name": 12.0,
    "tags": 9.0,
    "subcategory": 8.0,
    "style": 6.0,
    "id": 5.0,
    "source": 3.0,
    "description": 2.0,
    "formats": 1.0,
}


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("_", " ").replace("-", "-")
    return " ".join(re.findall(r"[\w-]+", text, flags=re.UNICODE))


def canonical_token(token: str) -> str:
    return ALIASES.get(token, token)


def tokens(value: Any) -> set[str]:
    normalized = normalize(value)
    raw = re.findall(r"[\w-]+", normalized, flags=re.UNICODE)
    return {canonical_token(token) for token in raw if token}


def list_tokens(values: Iterable[Any]) -> set[str]:
    result: set[str] = set()
    for value in values:
        result.update(tokens(value))
    return result


def load_index(path: Path | str = DEFAULT_INDEX) -> dict[str, Any]:
    index_path = Path(path)
    with index_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise ValueError(f"Invalid TKRS index: {index_path}")
    return data


def _asset_fields(asset: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "name": tokens(asset.get("name")),
        "tags": list_tokens(asset.get("tags") or []),
        "subcategory": tokens(asset.get("subcategory")),
        "style": list_tokens(asset.get("style") or []),
        "id": tokens(asset.get("id")),
        "source": tokens(asset.get("source")),
        "description": tokens(asset.get("description")),
        "formats": list_tokens(asset.get("formats") or []),
    }


def _matches_filter(asset: dict[str, Any], field: str, value: str | None) -> bool:
    if not value:
        return True
    wanted = canonical_token(normalize(value))
    current = asset.get(field)
    if isinstance(current, list):
        return any(wanted in tokens(item) or wanted == normalize(item) for item in current)
    if field == "source":
        return wanted in normalize(current)
    return wanted in tokens(current) or wanted == normalize(current)


def _score_asset(asset: dict[str, Any], query: str) -> tuple[float, list[str]]:
    normalized_query = normalize(query)
    query_tokens = [canonical_token(token) for token in re.findall(r"[\w-]+", normalized_query, flags=re.UNICODE)]
    if not query_tokens:
        return 0.0, []

    fields = _asset_fields(asset)
    score = 0.0
    matched: set[str] = set()

    normalized_name = normalize(asset.get("name"))
    normalized_id = normalize(asset.get("id"))
    normalized_description = normalize(asset.get("description"))

    if normalized_query == normalized_id:
        score += 60.0
    if normalized_query == normalized_name:
        score += 45.0
    elif normalized_query and normalized_query in normalized_name:
        score += 24.0
    if normalized_query and normalized_query in normalized_description:
        score += 5.0

    vocabulary = set().union(*fields.values())

    for query_token in query_tokens:
        token_score = 0.0
        token_matched = False
        for field, field_tokens in fields.items():
            if query_token in field_tokens:
                token_score += FIELD_WEIGHTS[field]
                token_matched = True
            elif len(query_token) >= 4:
                prefix_hit = any(
                    candidate.startswith(query_token) or query_token.startswith(candidate)
                    for candidate in field_tokens
                    if len(candidate) >= 4
                )
                if prefix_hit:
                    token_score += FIELD_WEIGHTS[field] * 0.35
                    token_matched = True

        if not token_matched and len(query_token) >= 5 and vocabulary:
            best_ratio = max(SequenceMatcher(None, query_token, candidate).ratio() for candidate in vocabulary)
            if best_ratio >= 0.86:
                token_score += 1.5 * best_ratio
                token_matched = True

        if token_matched:
            matched.add(query_token)
        score += token_score

    # Prefer results that satisfy more of the query instead of one very strong token.
    coverage = len(matched) / max(len(set(query_tokens)), 1)
    score *= 0.55 + (0.45 * coverage)
    if len(set(query_tokens)) > 1 and coverage == 1.0:
        score += 8.0

    return score, sorted(matched)


def _asset_files(asset: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    path = asset.get("path")
    if not path:
        return []
    directory = repo_root / path
    if not directory.is_dir():
        return []
    allowed = {".glb", ".gltf", ".bin", ".obj", ".mtl", ".fbx", ".png", ".jpg", ".jpeg", ".webp"}
    return [
        str(file.relative_to(repo_root)).replace("\\", "/")
        for file in sorted(directory.iterdir())
        if file.is_file() and file.suffix.casefold() in allowed
    ]


def search_assets(
    assets: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 10,
    subcategory: str | None = None,
    style: str | None = None,
    format_name: str | None = None,
    source: str | None = None,
    license_name: str | None = None,
    min_score: float = 1.0,
    repo_root: Path = REPO_ROOT,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, list[str], dict[str, Any]]] = []

    for asset in assets:
        if not _matches_filter(asset, "subcategory", subcategory):
            continue
        if not _matches_filter(asset, "style", style):
            continue
        if not _matches_filter(asset, "formats", format_name):
            continue
        if not _matches_filter(asset, "source", source):
            continue
        if not _matches_filter(asset, "license", license_name):
            continue

        score, matched_terms = _score_asset(asset, query)
        if score < min_score:
            continue
        ranked.append((score, matched_terms, asset))

    ranked.sort(key=lambda item: (-item[0], normalize(item[2].get("name")), item[2].get("id", "")))

    results: list[dict[str, Any]] = []
    for score, matched_terms, asset in ranked[: max(limit, 0)]:
        results.append(
            {
                "id": asset.get("id"),
                "name": asset.get("name"),
                "score": round(score, 3),
                "matched_terms": matched_terms,
                "category": asset.get("category"),
                "subcategory": asset.get("subcategory"),
                "tags": asset.get("tags") or [],
                "style": asset.get("style") or [],
                "formats": asset.get("formats") or [],
                "dimensions": asset.get("dimensions"),
                "source": asset.get("source"),
                "license": asset.get("license"),
                "path": asset.get("path"),
                "files": _asset_files(asset, repo_root),
                "sha256": asset.get("sha256"),
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search TKRS assets by natural-language keywords.")
    parser.add_argument("query", nargs="+", help="Search query, e.g. 'industrial wall' or 'средневековая дверь'")
    parser.add_argument("--index", default=str(DEFAULT_INDEX), help="Path to index/index.json")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of results (default: 10)")
    parser.add_argument("--subcategory", help="Filter by subcategory, e.g. walls, doors, stairs")
    parser.add_argument("--style", help="Filter by style/tag, e.g. industrial, medieval, low-poly")
    parser.add_argument("--format", dest="format_name", help="Filter by asset format, e.g. glb, gltf, obj")
    parser.add_argument("--source", help="Filter by source name substring")
    parser.add_argument("--license", dest="license_name", help="Filter by license")
    parser.add_argument("--min-score", type=float, default=1.0, help="Minimum relevance score")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    query = " ".join(args.query).strip()
    catalog = load_index(args.index)
    results = search_assets(
        catalog["assets"],
        query,
        limit=args.limit,
        subcategory=args.subcategory,
        style=args.style,
        format_name=args.format_name,
        source=args.source,
        license_name=args.license_name,
        min_score=args.min_score,
    )
    payload = {
        "query": query,
        "catalog_asset_count": len(catalog["assets"]),
        "result_count": len(results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
