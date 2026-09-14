#!/usr/bin/env python3
"""Validate TKRS metadata, assets, dependencies, index and checksums."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from asset_audit import audit_tree, compact_asset_errors, sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]


def validate_index(root: Path, audits: list[Any]) -> dict[str, Any]:
    errors: list[str] = []
    index_path = root / "index" / "index.json"
    checksum_path = root / "index" / "checksums.sha256"
    metadata_by_id = {item.asset_id: item for item in audits if item.asset_id}
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"errors": [f"cannot read index: {exc}"], "record_count": 0}
    records = index.get("assets")
    if not isinstance(records, list):
        return {"errors": ["index.assets is not a list"], "record_count": 0}
    if index.get("asset_count") != len(records):
        errors.append("index.asset_count does not match index record count")
    if len(records) != len(audits):
        errors.append("index record count does not match accepted asset directory count")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            errors.append("index contains a non-object record")
            continue
        asset_id = record.get("id")
        if not isinstance(asset_id, str):
            errors.append("index record has no string id")
            continue
        if asset_id in seen:
            errors.append(f"duplicate index id: {asset_id}")
        seen.add(asset_id)
        audit = metadata_by_id.get(asset_id)
        if audit is None:
            errors.append(f"index id has no asset directory: {asset_id}")
            continue
        expected_path = audit.asset_dir.relative_to(root).as_posix()
        if record.get("path") != expected_path:
            errors.append(f"index path mismatch for {asset_id}")
        if record.get("sha256") != audit.primary_sha256:
            errors.append(f"index SHA-256 mismatch for {asset_id}")

    checksums: dict[str, str] = {}
    try:
        for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                errors.append(f"invalid checksum line {line_number}")
                continue
            digest, relative = parts
            checksums[relative.strip().replace("\\", "/")] = digest
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read checksums: {exc}")
    if len(checksums) != len(audits):
        errors.append("checksum entry count does not match accepted asset directory count")
    for audit in audits:
        if audit.primary_path is None or audit.primary_sha256 is None:
            continue
        relative = audit.primary_path.relative_to(root).as_posix()
        if checksums.get(relative) != audit.primary_sha256:
            errors.append(f"checksum mismatch or missing: {relative}")
    manifest_path = root / "batch-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("asset_count") != len(audits):
            errors.append("batch-manifest asset count does not match accepted asset directory count")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read batch-manifest: {exc}")
    return {"errors": errors, "record_count": len(records), "checksum_count": len(checksums)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    audits, summary = audit_tree(root)
    id_errors = [f"duplicate asset id: {asset_id}" for asset_id in summary["duplicate_ids"]]
    asset_errors = [error for item in audits for error in item.hard_errors]
    index_result = {"errors": [], "record_count": None, "checksum_count": None}
    if not args.skip_index:
        index_result = validate_index(root, audits)
    result = {
        "root": str(root),
        "summary": summary,
        "asset_issue_count": len(asset_errors),
        "duplicate_id_count": len(id_errors),
        "index": index_result,
        "valid": not asset_errors and not id_errors and not index_result["errors"],
    }
    if args.details:
        result["assets_with_issues"] = compact_asset_errors(audits)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
