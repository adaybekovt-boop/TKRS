#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path, PurePosixPath
import urllib.parse

import materialize_architecture_batch as batch

_INDEX: dict[Path, dict[str, list[Path]]] = {}


def dependency_index(source_root: Path) -> dict[str, list[Path]]:
    root = source_root.resolve()
    cached = _INDEX.get(root)
    if cached is not None:
        return cached
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            index.setdefault(path.name.lower(), []).append(path)
    _INDEX[root] = index
    return index


def resolve_uri(base: Path, uri: str, source_root: Path) -> Path:
    decoded = urllib.parse.unquote(uri.replace("\\", "/"))
    direct = batch.ensure_inside(base / PurePosixPath(decoded), source_root)
    if direct.is_file():
        return direct

    candidates = dependency_index(source_root).get(PurePosixPath(decoded).name.lower(), [])
    if not candidates:
        return direct

    root = source_root.resolve()
    base_parts = base.resolve().relative_to(root).parts

    def rank(candidate: Path) -> tuple[int, int, str]:
        parts = candidate.parent.resolve().relative_to(root).parts
        common = 0
        for a, b in zip(base_parts, parts):
            if a.lower() != b.lower():
                break
            common += 1
        return common, -abs(len(parts) - len(base_parts)), candidate.as_posix()

    chosen = max(candidates, key=rank)
    print(f"Resolved stale dependency {uri!r} -> {chosen.relative_to(root)}", flush=True)
    return chosen


batch.resolve_uri = resolve_uri

if __name__ == "__main__":
    batch.main()
