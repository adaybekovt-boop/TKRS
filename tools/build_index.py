#!/usr/bin/env python3
"""Rebuild the unified TKRS index and one-primary-file-per-asset checksums."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from asset_audit import audit_tree


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_FIELDS = (
    "id",
    "name",
    "category",
    "subcategory",
    "description",
    "tags",
    "style",
    "formats",
    "dimensions",
    "source",
    "license",
)
SEARCHABLE_OPTIONAL_FIELDS = (
    "alpha",
    "alpha_mode",
    "asset_type",
    "animation_type",
    "asset_kind",
    "cell_size",
    "channels",
    "clip_count",
    "clip_name",
    "clip_names",
    "code_dependency",
    "component_state",
    "component_type",
    "cubemap_layout",
    "device",
    "dimensionality",
    "directional_intent",
    "effect_type",
    "fps",
    "frame_count",
    "grid",
    "grid_layout",
    "grid_note",
    "has_alpha",
    "hdr",
    "humanoid",
    "in_place",
    "intended_usage",
    "language",
    "loopable",
    "lut_size",
    "motion_type",
    "responsive",
    "rig_family",
    "rig_name",
    "root_motion",
    "resolution",
    "retargeting_requirement",
    "retargeting_notes",
    "source_format",
    "source_scale",
    "source_unit",
    "up_axis",
    "vector",
)


def build(root: Path) -> tuple[dict[str, Any], list[str]]:
    audits, summary = audit_tree(root)
    hard_errors = [(item.asset_id, item.hard_errors) for item in audits if item.hard_errors]
    if hard_errors or summary["duplicate_ids"]:
        preview = hard_errors[:10]
        raise RuntimeError(f"refusing to index invalid repository: {preview!r}")
    records: list[dict[str, Any]] = []
    checksum_lines: list[str] = []
    for audit in audits:
        metadata = audit.metadata or {}
        record = {field: metadata.get(field) for field in CORE_FIELDS}
        for field in SEARCHABLE_OPTIONAL_FIELDS:
            if field in metadata:
                record[field] = metadata[field]
        record["path"] = audit.asset_dir.relative_to(root).as_posix()
        record["sha256"] = audit.primary_sha256
        record["primary_file"] = audit.primary_path.relative_to(audit.asset_dir).as_posix() if audit.primary_path else None
        records.append(record)
        if audit.primary_path and audit.primary_sha256:
            checksum_lines.append(f"{audit.primary_sha256}  {audit.primary_path.relative_to(root).as_posix()}")
    records.sort(key=lambda item: (str(item.get("category")), str(item.get("subcategory")), str(item.get("id"))))
    checksum_lines.sort()
    index = {
        "version": 2,
        "generated_at": date.today().isoformat(),
        "hash_strategy": "SHA-256 of the indexed primary_file; checksums.sha256 contains one primary file per logical asset",
        "asset_count": len(records),
        "assets": records,
    }
    return index, checksum_lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    index, checksum_lines = build(root)
    index_dir = root / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (index_dir / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    manifest = {
        "batch": "tkrs-unified-catalog",
        "generated_at": index["generated_at"],
        "asset_count": index["asset_count"],
        "categories": dict(sorted(Counter(str(item["category"]) for item in index["assets"]).items())),
        "formats": dict(sorted(Counter(value for item in index["assets"] for value in (item.get("formats") or [])).items())),
        "licenses": dict(sorted(Counter(str(item["license"]) for item in index["assets"]).items())),
        "sources": dict(sorted(Counter(str(item["source"]) for item in index["assets"]).items())),
        "validation": {
            "unique_ids": True,
            "missing_external_dependencies": 0,
            "unlicensed_assets": 0,
            "accepted_executables": 0,
        },
    }
    (root / "batch-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset_count": index["asset_count"], "checksum_count": len(checksum_lines)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
