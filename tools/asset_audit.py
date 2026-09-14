#!/usr/bin/env python3
"""Reusable, dependency-free TKRS asset auditing helpers.

The module never imports or executes code found inside an asset pack.  It only
reads archive entries, metadata and known media/container formats.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import urllib.parse
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REQUIRED_METADATA_FIELDS = {
    "id",
    "name",
    "description",
    "category",
    "subcategory",
    "tags",
    "style",
    "formats",
    "source",
    "author",
    "license",
    "original_url",
    "attribution",
    "has_scripts",
    "dimensions",
}

PERMISSIVE_LICENSES = {
    "CC0",
    "CC0-1.0",
    "CC-BY-3.0",
    "CC-BY-4.0",
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "Zlib",
}

EXECUTABLE_EXTENSIONS = {
    ".apk",
    ".app",
    ".appimage",
    ".bat",
    ".bin.exe",
    ".cmd",
    ".com",
    ".cpl",
    ".dll",
    ".dmg",
    ".exe",
    ".iso",
    ".jar",
    ".msi",
    ".msp",
    ".msix",
    ".pif",
    ".pkg",
    ".ps1",
    ".scr",
    ".sh",
    ".so",
    ".vbs",
}

SCRIPT_EXTENSIONS = {
    ".c",
    ".cpp",
    ".cs",
    ".gd",
    ".h",
    ".js",
    ".jsx",
    ".lua",
    ".luau",
    ".py",
    ".rb",
    ".ts",
    ".tsx",
}

MODEL_EXTENSIONS = {".fbx", ".glb", ".gltf", ".obj"}
ANIMATION_EXTENSIONS = {".anim", ".bvh", ".fbx", ".glb", ".gltf"}
IMAGE_EXTENSIONS = {".bmp", ".gif", ".hdr", ".jpeg", ".jpg", ".png", ".svg", ".tga", ".webp"}
UI_EXTENSIONS = {".png", ".svg", ".webp", ".jpg", ".jpeg"}
VFX_EXTENSIONS = IMAGE_EXTENSIONS | {".cube"}
TEXT_EXTENSIONS = SCRIPT_EXTENSIONS | {".json", ".md", ".mtl", ".obj", ".txt", ".xml", ".yaml", ".yml", ".cube"}

IGNORED_LOGICAL_NAMES = {
    "license",
    "license.txt",
    "metadata.json",
    "readme",
    "readme.md",
}

PRIMARY_PRIORITY = {
    ".glb": 0,
    ".gltf": 1,
    ".obj": 2,
    ".fbx": 3,
    ".png": 4,
    ".webp": 5,
    ".jpg": 6,
    ".jpeg": 7,
    ".hdr": 8,
    ".svg": 9,
    ".cube": 10,
    ".lua": 11,
    ".luau": 11,
    ".gd": 11,
    ".cs": 11,
    ".tsx": 11,
    ".json": 12,
    ".txt": 13,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_zip_name(name: str) -> PurePosixPath:
    return PurePosixPath(name.replace("\\", "/"))


def unsafe_zip_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in path.parts
    )


def zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def audit_zip(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "archive": path.name,
        "compressed_size": path.stat().st_size,
        "uncompressed_size": 0,
        "entry_count": 0,
        "file_count": 0,
        "extension_counts": {},
        "path_traversal_entries": [],
        "symlink_entries": [],
        "executable_entries": [],
        "script_entries": [],
        "files_over_100mb": [],
        "empty_files": [],
    }
    extensions: Counter[str] = Counter()
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        result["entry_count"] = len(infos)
        for info in infos:
            result["uncompressed_size"] += info.file_size
            if info.is_dir():
                continue
            result["file_count"] += 1
            suffix = Path(normalized_zip_name(info.filename).name).suffix.casefold()
            extensions[suffix or "<none>"] += 1
            if unsafe_zip_name(info.filename):
                result["path_traversal_entries"].append(info.filename)
            if zip_entry_is_symlink(info):
                result["symlink_entries"].append(info.filename)
            if suffix in EXECUTABLE_EXTENSIONS:
                result["executable_entries"].append(info.filename)
            if suffix in SCRIPT_EXTENSIONS:
                result["script_entries"].append(info.filename)
            if info.file_size > 100 * 1024 * 1024:
                result["files_over_100mb"].append(info.filename)
            if info.file_size == 0:
                result["empty_files"].append(info.filename)
    result["extension_counts"] = dict(sorted(extensions.items()))
    return result


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        value = json.loads(text)
        if not isinstance(value, dict):
            return None, "top-level JSON value is not an object"
        return value, None
    except UnicodeDecodeError as exc:
        return None, f"invalid UTF-8: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"malformed JSON: {exc}"
    except OSError as exc:
        return None, f"read error: {exc}"


def asset_directories(root: Path) -> list[Path]:
    assets_root = root / "assets"
    if not assets_root.is_dir():
        return []
    return sorted(path.parent for path in assets_root.rglob("metadata.json") if path.is_file())


def asset_files(asset_dir: Path) -> list[Path]:
    return sorted(path for path in asset_dir.rglob("*") if path.is_file())


def content_files(asset_dir: Path) -> list[Path]:
    return [
        path
        for path in asset_files(asset_dir)
        if path.name.casefold() not in IGNORED_LOGICAL_NAMES
        and not path.name.casefold().startswith(("license", "copying"))
    ]


def primary_file(asset_dir: Path, metadata: dict[str, Any]) -> Path | None:
    candidates = content_files(asset_dir)
    declared = metadata.get("files")
    if isinstance(declared, list):
        declared_paths: list[Path] = []
        for value in declared:
            if not isinstance(value, str):
                continue
            candidate = asset_dir / value
            if candidate.is_file() and candidate in candidates:
                declared_paths.append(candidate)
        if declared_paths:
            candidates = declared_paths
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda path: (
            PRIMARY_PRIORITY.get(path.suffix.casefold(), 100),
            str(path.relative_to(asset_dir)).casefold(),
        ),
    )


def logical_hash(asset_dir: Path) -> str | None:
    files = content_files(asset_dir)
    if not files:
        return None
    components = sorted((path.suffix.casefold(), sha256_file(path)) for path in files)
    digest = hashlib.sha256()
    for suffix, component_hash in components:
        digest.update(suffix.encode("utf-8"))
        digest.update(b"\0")
        digest.update(component_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def safe_relative_reference(base: Path, value: str, root: Path) -> Path | None:
    decoded = urllib.parse.unquote(value.replace("\\", "/"))
    if decoded.startswith("data:") or "://" in decoded:
        return None
    candidate = (base / PurePosixPath(decoded)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return Path("__OUTSIDE_ASSET__")
    return candidate


def _gltf_dependencies(path: Path, root: Path) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    outside: list[str] = []
    data, error = read_json(path)
    if error or data is None:
        return [f"{path.name}: {error}"], outside
    uris: list[str] = []
    for key in ("buffers", "images"):
        entries = data.get(key) or []
        if not isinstance(entries, list):
            missing.append(f"{path.name}: {key} is not a list")
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("uri"), str):
                uris.append(entry["uri"])
    for uri in uris:
        resolved = safe_relative_reference(path.parent, uri, root)
        if resolved is None:
            continue
        if resolved.name == "__OUTSIDE_ASSET__":
            outside.append(f"{path.name}: {uri}")
        elif not resolved.is_file():
            missing.append(f"{path.name}: {uri}")
    return missing, outside


def _obj_dependencies(path: Path, root: Path) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    outside: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path.name}: {exc}"], outside
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.casefold().startswith("mtllib "):
            continue
        value = stripped.split(maxsplit=1)[1].strip()
        resolved = safe_relative_reference(path.parent, value, root)
        if resolved is None:
            continue
        if resolved.name == "__OUTSIDE_ASSET__":
            outside.append(f"{path.name}: {value}")
        elif not resolved.is_file():
            missing.append(f"{path.name}: {value}")
    return missing, outside


def _mtl_dependencies(path: Path, root: Path) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    outside: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path.name}: {exc}"], outside
    texture_keys = {
        "map_ka",
        "map_kd",
        "map_ks",
        "map_bump",
        "bump",
        "disp",
        "decal",
        "norm",
    }
    for line in text.splitlines():
        stripped = line.strip()
        tokens = stripped.split(maxsplit=1)
        if len(tokens) < 2 or tokens[0].casefold() not in texture_keys:
            continue
        value = tokens[1].strip().strip('"')
        resolved = safe_relative_reference(path.parent, value, root)
        if resolved is None:
            continue
        if resolved.name == "__OUTSIDE_ASSET__":
            outside.append(f"{path.name}: {value}")
        elif not resolved.is_file():
            missing.append(f"{path.name}: {value}")
    return missing, outside


def _validate_glb(path: Path) -> str | None:
    try:
        size = path.stat().st_size
        if size < 12:
            return "file is shorter than a GLB header"
        with path.open("rb") as handle:
            magic, version, declared_size = struct.unpack("<4sII", handle.read(12))
        if magic != b"glTF":
            return "invalid GLB magic"
        if version != 2:
            return f"unsupported GLB version {version}"
        if declared_size != size:
            return f"declared GLB size {declared_size} differs from file size {size}"
    except OSError as exc:
        return str(exc)
    return None


def _validate_png(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return "invalid PNG header"
        width, height = struct.unpack(">II", header[16:24])
        if width <= 0 or height <= 0:
            return "invalid PNG dimensions"
    except OSError as exc:
        return str(exc)
    return None


def _validate_jpeg(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            start = handle.read(2)
            handle.seek(-2, os.SEEK_END)
            end = handle.read(2)
        if start != b"\xff\xd8" or end != b"\xff\xd9":
            return "invalid JPEG boundary markers"
    except OSError as exc:
        return str(exc)
    return None


def validate_media(path: Path) -> str | None:
    suffix = path.suffix.casefold()
    if suffix == ".glb":
        return _validate_glb(path)
    if suffix == ".png":
        return _validate_png(path)
    if suffix in {".jpg", ".jpeg"}:
        return _validate_jpeg(path)
    if suffix == ".fbx":
        try:
            header = path.read_bytes()[:32]
            if not (header.startswith(b"Kaydara FBX Binary") or header.lstrip().startswith(b"; FBX")):
                return "unrecognized FBX header"
        except OSError as exc:
            return str(exc)
    if suffix == ".svg":
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
            if "<svg" not in text[:4096].casefold():
                return "missing SVG root"
        except (OSError, UnicodeDecodeError) as exc:
            return str(exc)
    return None


@dataclass
class AssetAudit:
    asset_dir: Path
    metadata: dict[str, Any] | None = None
    metadata_error: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    path_errors: list[str] = field(default_factory=list)
    missing_declared_files: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    outside_dependencies: list[str] = field(default_factory=list)
    invalid_media: list[str] = field(default_factory=list)
    executable_files: list[str] = field(default_factory=list)
    script_files: list[str] = field(default_factory=list)
    empty_files: list[str] = field(default_factory=list)
    files_over_100mb: list[str] = field(default_factory=list)
    symlinks: list[str] = field(default_factory=list)
    logical_sha256: str | None = None
    primary_path: Path | None = None
    primary_sha256: str | None = None

    @property
    def asset_id(self) -> str | None:
        value = (self.metadata or {}).get("id")
        return value if isinstance(value, str) else None

    @property
    def hard_errors(self) -> list[str]:
        errors: list[str] = []
        if self.metadata_error:
            errors.append(self.metadata_error)
        errors.extend(f"missing metadata field: {name}" for name in self.missing_fields)
        errors.extend(f"metadata schema: {value}" for value in self.schema_errors)
        errors.extend(self.path_errors)
        errors.extend(f"missing declared file: {value}" for value in self.missing_declared_files)
        errors.extend(f"missing dependency: {value}" for value in self.missing_dependencies)
        errors.extend(f"dependency outside asset directory: {value}" for value in self.outside_dependencies)
        errors.extend(f"invalid media: {value}" for value in self.invalid_media)
        errors.extend(f"executable: {value}" for value in self.executable_files)
        errors.extend(f"symlink: {value}" for value in self.symlinks)
        errors.extend(f"file over 100 MB: {value}" for value in self.files_over_100mb)
        errors.extend(f"empty file: {value}" for value in self.empty_files)
        metadata = self.metadata or {}
        if metadata.get("license") not in PERMISSIVE_LICENSES:
            errors.append(f"unapproved or unclear license: {metadata.get('license')!r}")
        if not isinstance(metadata.get("source"), str) or not metadata.get("source", "").strip():
            errors.append("missing source")
        license_files = [
            path
            for path in asset_files(self.asset_dir)
            if path.name.casefold().startswith(("license", "copying"))
        ]
        if not license_files or not any(path.stat().st_size > 0 for path in license_files):
            errors.append("missing non-empty license evidence file")
        else:
            try:
                evidence = "\n".join(path.read_text(encoding="utf-8", errors="strict") for path in license_files).casefold()
                license_name = str(metadata.get("license") or "").casefold()
                expected = "cc0" if license_name.startswith("cc0") else license_name.split("-")[0]
                if expected and expected not in evidence:
                    errors.append("license evidence does not mention the declared license")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"invalid license evidence text: {exc}")
        if self.primary_path is None:
            errors.append("no primary content file")
        return errors


def audit_asset(asset_dir: Path, root: Path) -> AssetAudit:
    audit = AssetAudit(asset_dir=asset_dir)
    metadata, error = read_json(asset_dir / "metadata.json")
    audit.metadata = metadata
    audit.metadata_error = error
    if metadata is None:
        return audit

    audit.missing_fields = sorted(REQUIRED_METADATA_FIELDS - metadata.keys())
    for key in ("id", "name", "description", "category", "subcategory", "source", "license"):
        if key in metadata and not isinstance(metadata[key], str):
            audit.schema_errors.append(f"{key} must be a string")
    for key in ("tags", "style", "formats"):
        value = metadata.get(key)
        if value is not None and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            audit.schema_errors.append(f"{key} must be an array of strings")
    if "has_scripts" in metadata and not isinstance(metadata["has_scripts"], bool):
        audit.schema_errors.append("has_scripts must be boolean")
    if metadata.get("dimensions") is not None and not isinstance(metadata.get("dimensions"), dict):
        audit.schema_errors.append("dimensions must be an object or null")
    for key in ("author", "original_url"):
        if metadata.get(key) is not None and not isinstance(metadata.get(key), str):
            audit.schema_errors.append(f"{key} must be a string or null")
    if metadata.get("attribution") is not None and not isinstance(metadata.get("attribution"), (str, bool)):
        audit.schema_errors.append("attribution must be a string, boolean or null")
    try:
        relative = asset_dir.resolve().relative_to((root / "assets").resolve())
        parts = relative.parts
        if len(parts) != 3:
            audit.path_errors.append(f"asset path must be category/subcategory/id: {relative.as_posix()}")
        else:
            category, subcategory, directory_id = parts
            if metadata.get("category") != category:
                audit.path_errors.append("metadata category does not match path")
            if metadata.get("subcategory") != subcategory:
                audit.path_errors.append("metadata subcategory does not match path")
            if metadata.get("id") != directory_id:
                audit.path_errors.append("metadata id does not match directory")
    except ValueError:
        audit.path_errors.append("asset directory is outside assets root")

    declared = metadata.get("files")
    if isinstance(declared, list):
        for value in declared:
            if not isinstance(value, str) or unsafe_zip_name(value):
                audit.missing_declared_files.append(str(value))
                continue
            candidate = (asset_dir / PurePosixPath(value.replace("\\", "/"))).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                audit.missing_declared_files.append(value)
                continue
            if not candidate.is_file():
                audit.missing_declared_files.append(value)

    for path in asset_files(asset_dir):
        rel = path.relative_to(asset_dir).as_posix()
        suffix = path.suffix.casefold()
        if path.is_symlink():
            audit.symlinks.append(rel)
        if suffix in EXECUTABLE_EXTENSIONS:
            audit.executable_files.append(rel)
        if suffix in SCRIPT_EXTENSIONS:
            audit.script_files.append(rel)
        if path.stat().st_size == 0:
            audit.empty_files.append(rel)
        if path.stat().st_size > 100 * 1024 * 1024:
            audit.files_over_100mb.append(rel)
        media_error = validate_media(path)
        if media_error:
            audit.invalid_media.append(f"{rel}: {media_error}")
        if suffix == ".gltf":
            missing, outside = _gltf_dependencies(path, root)
            audit.missing_dependencies.extend(missing)
            audit.outside_dependencies.extend(outside)
        elif suffix == ".obj":
            missing, outside = _obj_dependencies(path, root)
            audit.missing_dependencies.extend(missing)
            audit.outside_dependencies.extend(outside)
        elif suffix == ".mtl":
            missing, outside = _mtl_dependencies(path, root)
            audit.missing_dependencies.extend(missing)
            audit.outside_dependencies.extend(outside)

    audit.logical_sha256 = logical_hash(asset_dir)
    audit.primary_path = primary_file(asset_dir, metadata)
    if audit.primary_path is not None:
        audit.primary_sha256 = sha256_file(audit.primary_path)
    return audit


def audit_tree(root: Path) -> tuple[list[AssetAudit], dict[str, Any]]:
    audits = [audit_asset(path, root) for path in asset_directories(root)]
    ids: defaultdict[str, list[str]] = defaultdict(list)
    logical: defaultdict[str, list[str]] = defaultdict(list)
    source_counts: Counter[str] = Counter()
    license_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    subcategory_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    total_bytes = 0
    for audit in audits:
        metadata = audit.metadata or {}
        asset_id = audit.asset_id
        if asset_id:
            ids[asset_id].append(str(audit.asset_dir))
        if audit.logical_sha256:
            logical[audit.logical_sha256].append(asset_id or str(audit.asset_dir))
        source_counts[str(metadata.get("source"))] += 1
        license_counts[str(metadata.get("license"))] += 1
        category_counts[str(metadata.get("category"))] += 1
        subcategory_counts[str(metadata.get("subcategory"))] += 1
        for path in asset_files(audit.asset_dir):
            extension_counts[path.suffix.casefold() or "<none>"] += 1
            total_bytes += path.stat().st_size
    summary = {
        "asset_count": len(audits),
        "valid_asset_count": sum(not item.hard_errors for item in audits),
        "invalid_asset_count": sum(bool(item.hard_errors) for item in audits),
        "metadata_error_count": sum(bool(item.metadata_error) for item in audits),
        "missing_metadata_field_count": sum(len(item.missing_fields) for item in audits),
        "schema_error_count": sum(len(item.schema_errors) for item in audits),
        "missing_dependency_count": sum(len(item.missing_dependencies) for item in audits),
        "outside_dependency_count": sum(len(item.outside_dependencies) for item in audits),
        "invalid_media_count": sum(len(item.invalid_media) for item in audits),
        "executable_file_count": sum(len(item.executable_files) for item in audits),
        "script_file_count": sum(len(item.script_files) for item in audits),
        "empty_file_count": sum(len(item.empty_files) for item in audits),
        "file_over_100mb_count": sum(len(item.files_over_100mb) for item in audits),
        "symlink_count": sum(len(item.symlinks) for item in audits),
        "duplicate_ids": {key: value for key, value in ids.items() if len(value) > 1},
        "exact_duplicate_logical_assets": {key: value for key, value in logical.items() if len(value) > 1},
        "category_counts": dict(sorted(category_counts.items())),
        "subcategory_counts": dict(sorted(subcategory_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "license_counts": dict(sorted(license_counts.items())),
        "extension_counts": dict(sorted(extension_counts.items())),
        "asset_bytes": total_bytes,
    }
    return audits, summary


def compact_asset_errors(audits: Iterable[AssetAudit]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(item.asset_dir),
            "id": item.asset_id,
            "errors": item.hard_errors,
            "scripts": item.script_files,
            "empty_files": item.empty_files,
        }
        for item in audits
        if item.hard_errors or item.script_files or item.empty_files
    ]
