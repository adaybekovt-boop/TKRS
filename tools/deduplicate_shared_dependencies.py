#!/usr/bin/env python3
"""Replace duplicate shared dependencies with existing SHA-256-identical files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from asset_audit import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]


def deduplicate(root: Path, candidate_dirs: list[Path]) -> dict[str, int]:
    candidates = [path.resolve() for path in candidate_dirs]
    for path in candidates:
        path.relative_to((root / "textures").resolve())
    canonical_by_hash: dict[str, Path] = {}
    for path in sorted(item for item in (root / "textures").rglob("*") if item.is_file()):
        resolved = path.resolve()
        if any(candidate == resolved or candidate in resolved.parents for candidate in candidates):
            continue
        canonical_by_hash.setdefault(sha256_file(path), path)
    replacements: dict[Path, Path] = {}
    for directory in candidates:
        if not directory.is_dir():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            canonical = canonical_by_hash.get(sha256_file(path))
            if canonical is not None:
                replacements[path.resolve()] = canonical.resolve()

    gltf_references = 0
    mtl_references = 0
    for path in sorted((root / "assets").rglob("*.gltf")):
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for key in ("buffers", "images"):
            for entry in data.get(key) or []:
                uri = entry.get("uri") if isinstance(entry, dict) else None
                if not isinstance(uri, str) or uri.startswith("data:") or "://" in uri:
                    continue
                resolved = (path.parent / uri.replace("\\", "/")).resolve()
                canonical = replacements.get(resolved)
                if canonical is None:
                    continue
                entry["uri"] = Path(os.path.relpath(canonical, path.parent)).as_posix()
                changed = True
                gltf_references += 1
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    texture_keys = {"map_ka", "map_kd", "map_ks", "map_bump", "bump", "disp", "decal", "norm"}
    for path in sorted((root / "assets").rglob("*.mtl")):
        lines: list[str] = []
        changed = False
        for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
            stripped = line.strip()
            tokens = stripped.split(maxsplit=1)
            if len(tokens) == 2 and tokens[0].casefold() in texture_keys:
                value = tokens[1].strip().strip('"')
                resolved = (path.parent / value.replace("\\", "/")).resolve()
                canonical = replacements.get(resolved)
                if canonical is not None:
                    prefix = line[: len(line) - len(line.lstrip())]
                    line = f"{prefix}{tokens[0]} {Path(os.path.relpath(canonical, path.parent)).as_posix()}"
                    changed = True
                    mtl_references += 1
            lines.append(line)
        if changed:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    removed_bytes = 0
    for duplicate, canonical in replacements.items():
        if sha256_file(duplicate) != sha256_file(canonical):
            raise RuntimeError(f"hash changed before deletion: {duplicate}")
        removed_bytes += duplicate.stat().st_size
        duplicate.unlink()
    for directory in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        for path in sorted((item for item in directory.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
            if not any(path.iterdir()):
                path.rmdir()
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return {
        "duplicate_files_removed": len(replacements),
        "duplicate_bytes_removed": removed_bytes,
        "gltf_references_rewritten": gltf_references,
        "mtl_references_rewritten": mtl_references,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_dirs", nargs="+", type=Path)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    candidates = [(root / path).resolve() if not path.is_absolute() else path.resolve() for path in args.candidate_dirs]
    print(json.dumps(deduplicate(root, candidates), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
