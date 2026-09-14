#!/usr/bin/env python3
"""Repair, normalize, deduplicate and integrate extracted TKRS asset batches.

The tool treats batch contents as inert data.  It never imports, executes or
launches files from the supplied trees.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from asset_audit import (
    SCRIPT_EXTENSIONS,
    asset_directories,
    asset_files,
    audit_asset,
    audit_tree,
    logical_hash,
    read_json,
    safe_relative_reference,
    sha256_file,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
NULLABLE_DEFAULTS = {
    "author": None,
    "original_url": None,
    "attribution": None,
    "dimensions": None,
}
LIST_DEFAULTS = {"tags": [], "style": [], "formats": []}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_metadata(asset_dir: Path, root: Path) -> bool:
    path = asset_dir / "metadata.json"
    metadata, error = read_json(path)
    if error or metadata is None:
        return False
    changed = False
    relative = asset_dir.resolve().relative_to((root / "assets").resolve())
    if len(relative.parts) == 3:
        category, subcategory, asset_id = relative.parts
        for key, value in (("category", category), ("subcategory", subcategory), ("id", asset_id)):
            if metadata.get(key) != value:
                metadata[key] = value
                changed = True
    for key, value in NULLABLE_DEFAULTS.items():
        if key not in metadata:
            metadata[key] = value
            changed = True
    for key, value in LIST_DEFAULTS.items():
        if key not in metadata:
            metadata[key] = list(value)
            changed = True
    if "description" not in metadata:
        metadata["description"] = ""
        changed = True
    actual_scripts = any(path.suffix.casefold() in SCRIPT_EXTENSIONS for path in asset_files(asset_dir))
    normalized_scripts = bool(metadata.get("has_scripts")) or actual_scripts
    if metadata.get("has_scripts") is not normalized_scripts:
        metadata["has_scripts"] = normalized_scripts
        changed = True
    declared = metadata.get("files")
    if isinstance(declared, list):
        cleaned = list(dict.fromkeys(value for value in declared if isinstance(value, str) and value != "metadata.json"))
        if cleaned != declared:
            metadata["files"] = cleaned
            changed = True
    if changed:
        write_json(path, metadata)
    return changed


def _candidate_by_basename(asset_dir: Path, root: Path, uri: str) -> Path | None:
    basename = PurePosixPath(urllib.parse.unquote(uri.replace("\\", "/"))).name.casefold()
    local = [path for path in asset_files(asset_dir) if path.name.casefold() == basename]
    if len(local) == 1:
        return local[0]
    global_matches = [path for path in root.rglob("*") if path.is_file() and path.name.casefold() == basename]
    if len(global_matches) == 1:
        return global_matches[0]
    if len(global_matches) > 1:
        hashes = {sha256_file(path) for path in global_matches}
        if len(hashes) == 1:
            return min(global_matches, key=lambda path: (len(path.relative_to(root).parts), path.as_posix()))
    return None


def repair_gltf(path: Path, asset_dir: Path, root: Path) -> int:
    data, error = read_json(path)
    if error or data is None:
        return 0
    repaired = 0
    for key in ("buffers", "images"):
        entries = data.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("uri"), str):
                continue
            uri = entry["uri"]
            direct = safe_relative_reference(path.parent, uri, root)
            if direct is None or (direct.name != "__OUTSIDE_ASSET__" and direct.is_file()):
                continue
            candidate = _candidate_by_basename(asset_dir, root, uri)
            if candidate is None:
                continue
            entry["uri"] = Path(os.path.relpath(candidate, path.parent)).as_posix()
            repaired += 1
    if repaired:
        write_json(path, data)
    return repaired


def repair_obj(path: Path, asset_dir: Path, root: Path) -> int:
    try:
        original = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return 0
    mtl_files = sorted(asset_dir.glob("*.mtl"))
    if len(mtl_files) != 1:
        return 0
    repaired = 0
    lines: list[str] = []
    for line in original.splitlines():
        stripped = line.strip()
        if stripped.casefold().startswith("mtllib "):
            value = stripped.split(maxsplit=1)[1].strip()
            direct = safe_relative_reference(path.parent, value, root)
            if direct is not None and (direct.name == "__OUTSIDE_ASSET__" or not direct.is_file()):
                prefix = line[: len(line) - len(line.lstrip())]
                line = f"{prefix}mtllib {mtl_files[0].name}"
                repaired += 1
        lines.append(line)
    if repaired:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return repaired


def repair_mtl(path: Path, asset_dir: Path, root: Path) -> int:
    try:
        original = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return 0
    texture_keys = {"map_ka", "map_kd", "map_ks", "map_bump", "bump", "disp", "decal", "norm"}
    repaired = 0
    lines: list[str] = []
    for line in original.splitlines():
        stripped = line.strip()
        tokens = stripped.split(maxsplit=1)
        if len(tokens) >= 2 and tokens[0].casefold() in texture_keys:
            value = tokens[1].strip().strip('"')
            direct = safe_relative_reference(path.parent, value, root)
            if direct is not None and (direct.name == "__OUTSIDE_ASSET__" or not direct.is_file()):
                candidate = _candidate_by_basename(asset_dir, root, value)
                if candidate is not None:
                    prefix = line[: len(line) - len(line.lstrip())]
                    line = f"{prefix}{tokens[0]} {Path(os.path.relpath(candidate, path.parent)).as_posix()}"
                    repaired += 1
        lines.append(line)
    if repaired:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return repaired


def prepare_tree(root: Path) -> dict[str, int]:
    counts = Counter()
    for asset_dir in asset_directories(root):
        if normalize_metadata(asset_dir, root):
            counts["metadata_normalized"] += 1
        for path in asset_files(asset_dir):
            suffix = path.suffix.casefold()
            if suffix == ".gltf":
                counts["gltf_uri_references_repaired"] += repair_gltf(path, asset_dir, root)
            elif suffix == ".obj":
                counts["obj_mtllib_references_repaired"] += repair_obj(path, asset_dir, root)
            elif suffix == ".mtl":
                counts["mtl_texture_references_repaired"] += repair_mtl(path, asset_dir, root)
    return dict(counts)


def copy_shared_textures(source: Path, destination: Path) -> tuple[int, int]:
    source_textures = source / "textures"
    if not source_textures.is_dir():
        return 0, 0
    copied = 0
    deduplicated = 0
    for path in sorted(item for item in source_textures.rglob("*") if item.is_file()):
        relative = path.relative_to(source_textures)
        target = destination / "textures" / relative
        if target.exists():
            if sha256_file(path) != sha256_file(target):
                raise RuntimeError(f"shared texture collision with different content: {relative.as_posix()}")
            deduplicated += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied, deduplicated


def near_duplicate_groups(audits: list[Any]) -> list[list[str]]:
    groups: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for audit in audits:
        metadata = audit.metadata or {}
        source = re.sub(r"\W+", " ", str(metadata.get("source", "")).casefold()).strip()
        identity = str(metadata.get("original_filename") or metadata.get("name") or "")
        identity = re.sub(r"\W+", " ", identity.casefold()).strip()
        if source and identity:
            groups[(source, identity)].append(audit.asset_id or str(audit.asset_dir))
    return sorted((items for items in groups.values() if len(items) > 1), key=lambda value: (-len(value), value))


def report_markdown(name: str, report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# {name} independent integration report",
        "",
        "This report was generated from the extracted files; the supplied archive report was not used as validation evidence.",
        "",
        f"- Supplied candidates: {summary['supplied_candidates']}",
        f"- Accepted: {summary['accepted']}",
        f"- Rejected: {summary['rejected']}",
        f"- Duplicate IDs removed: {summary['duplicate_ids_removed']}",
        f"- Exact duplicates removed: {summary['exact_duplicates_removed']}",
        f"- Duplicates against current TKRS removed: {summary['current_tkrs_duplicates_removed']}",
        f"- Dependency references repaired: {summary['dependency_references_repaired']}",
        f"- Unresolved issues: {summary['unresolved_issues']}",
        f"- Integrated bytes: {summary['integrated_bytes']}",
        "",
        "## Accepted by subcategory",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in sorted(report["accepted_by_subcategory"].items()))
    lines.extend(["", "## Accepted by source", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(report["accepted_by_source"].items()))
    lines.extend(["", "## Accepted by license", ""])
    lines.extend(f"- {key}: {value}" for key, value in sorted(report["accepted_by_license"].items()))
    lines.extend(["", "## Rejections", ""])
    if report["rejections"]:
        for item in report["rejections"]:
            lines.append(f"- `{item['id'] or item['path']}`: {'; '.join(item['reasons'])}")
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def integrate(source_roots: list[Path], repo_root: Path, apply: bool) -> dict[str, Any]:
    prepare_tree(repo_root)
    existing_audits, _ = audit_tree(repo_root)
    known_ids = {item.asset_id for item in existing_audits if item.asset_id}
    known_hashes = {item.logical_sha256 for item in existing_audits if item.logical_sha256}
    reports: dict[str, Any] = {}

    for source_root in source_roots:
        before_audits, before_summary = audit_tree(source_root)
        repairs = prepare_tree(source_root)
        ledger_path = source_root / ".tkrs-repair-ledger.json"
        if ledger_path.is_file():
            ledger, ledger_error = read_json(ledger_path)
            if ledger_error:
                raise RuntimeError(f"invalid repair ledger {ledger_path}: {ledger_error}")
            for key, value in (ledger or {}).items():
                if isinstance(value, int):
                    repairs[key] = repairs.get(key, 0) + value
        audits, source_summary = audit_tree(source_root)
        source_ids: set[str] = set()
        source_hashes: set[str] = set()
        accepted: list[Any] = []
        rejections: list[dict[str, Any]] = []
        duplicate_ids_removed = 0
        exact_duplicates_removed = 0
        current_duplicates_removed = 0

        for audit in audits:
            reasons = list(audit.hard_errors)
            asset_id = audit.asset_id
            logical = audit.logical_sha256
            if asset_id in source_ids:
                reasons.append("duplicate ID inside supplied batch")
                duplicate_ids_removed += 1
            elif asset_id in known_ids:
                reasons.append("duplicate ID already present in current TKRS")
                current_duplicates_removed += 1
            if logical in source_hashes:
                reasons.append("exact duplicate logical asset inside supplied batch")
                exact_duplicates_removed += 1
            elif logical in known_hashes:
                reasons.append("exact duplicate logical asset already present in current TKRS or an earlier batch")
                current_duplicates_removed += 1
            if reasons:
                rejections.append({"id": asset_id, "path": str(audit.asset_dir), "reasons": sorted(set(reasons))})
                continue
            accepted.append(audit)
            if asset_id:
                source_ids.add(asset_id)
                known_ids.add(asset_id)
            if logical:
                source_hashes.add(logical)
                known_hashes.add(logical)

        integrated_bytes = 0
        shared_textures_copied = 0
        shared_textures_deduplicated = 0
        if apply:
            shared_textures_copied, shared_textures_deduplicated = copy_shared_textures(source_root, repo_root)
            for audit in accepted:
                relative = audit.asset_dir.relative_to(source_root)
                target = repo_root / relative
                if target.exists():
                    raise RuntimeError(f"refusing to overwrite existing asset directory: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(audit.asset_dir, target)
                integrated_bytes += sum(path.stat().st_size for path in asset_files(target))
        else:
            integrated_bytes = sum(path.stat().st_size for audit in accepted for path in asset_files(audit.asset_dir))

        accepted_by_subcategory = Counter(str((item.metadata or {}).get("subcategory")) for item in accepted)
        accepted_by_source = Counter(str((item.metadata or {}).get("source")) for item in accepted)
        accepted_by_license = Counter(str((item.metadata or {}).get("license")) for item in accepted)
        dependency_repairs = sum(value for key, value in repairs.items() if "references_repaired" in key)
        name = source_root.name.removeprefix("TKRS-")
        report = {
            "batch": name,
            "summary": {
                "supplied_candidates": len(audits),
                "accepted": len(accepted),
                "rejected": len(rejections),
                "duplicate_ids_removed": duplicate_ids_removed,
                "exact_duplicates_removed": exact_duplicates_removed,
                "current_tkrs_duplicates_removed": current_duplicates_removed,
                "dependency_references_before_repair": before_summary["missing_dependency_count"],
                "dependency_references_repaired": dependency_repairs,
                "unresolved_issues": sum(len(item["reasons"]) for item in rejections),
                "integrated_bytes": integrated_bytes,
                "shared_textures_copied": shared_textures_copied,
                "shared_textures_deduplicated": shared_textures_deduplicated,
                "script_files_retained_as_inert_text": sum(len(item.script_files) for item in accepted),
            },
            "repairs": repairs,
            "audit": source_summary,
            "accepted_by_subcategory": dict(sorted(accepted_by_subcategory.items())),
            "accepted_by_source": dict(sorted(accepted_by_source.items())),
            "accepted_by_license": dict(sorted(accepted_by_license.items())),
            "near_duplicate_groups_for_review": near_duplicate_groups(audits),
            "rejections": rejections,
        }
        reports[name] = report
        if apply:
            report_dir = repo_root / "docs" / "batches" / name
            report_dir.mkdir(parents=True, exist_ok=True)
            write_json(report_dir / "audit.json", report)
            (report_dir / "REPORT.md").write_text(report_markdown(name, report), encoding="utf-8")
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="Extracted batch roots")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    reports = integrate([path.resolve() for path in args.sources], args.repo.resolve(), args.apply)
    payload = json.dumps(reports, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
