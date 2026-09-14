#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
import zlib

REPO = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO / "batches" / "architecture-001"
MANIFEST_JSON = MANIFEST_DIR / "manifest.json"
ASSET_ROOT = REPO / "assets" / "architecture"
TEXTURE_ROOT = REPO / "textures"
CACHE_ROOT = REPO / ".local" / "architecture-001-cache"
USER_AGENT = "TKRS/1.0 (+https://github.com/adaybekovt-boop/TKRS)"


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "source"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_manifest() -> dict:
    parts = sorted(MANIFEST_DIR.glob("manifest.part-*.b64"))
    if not parts:
        raise RuntimeError("Compressed manifest parts are missing")
    encoded = "".join("".join(p.read_text(encoding="utf-8").split()) for p in parts)
    raw = zlib.decompress(base64.b64decode(encoded))
    data = json.loads(raw.decode("utf-8"))
    if data.get("asset_count") != len(data.get("assets", [])):
        raise RuntimeError("Manifest asset_count does not match assets array")
    MANIFEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    last_error = None
    for attempt in range(1, 4):
        try:
            print(f"Downloading ({attempt}/3): {url}", flush=True)
            with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if destination.stat().st_size < 1024:
                raise RuntimeError(f"Downloaded file is unexpectedly small: {destination.stat().st_size} bytes")
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            print(f"Download failed: {exc}", flush=True)
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def safe_extract_zip(archive: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    dest_resolved = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            out = (destination / info.filename).resolve()
            if not str(out).startswith(str(dest_resolved) + os.sep) and out != dest_resolved:
                raise RuntimeError(f"Unsafe ZIP member: {info.filename}")
        zf.extractall(destination)


def ensure_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if not str(resolved).startswith(str(root_resolved) + os.sep) and resolved != root_resolved:
        raise RuntimeError(f"Dependency escapes source archive: {path}")
    return resolved


def resolve_uri(base: Path, uri: str, source_root: Path) -> Path:
    decoded = urllib.parse.unquote(uri.replace("\\", "/"))
    return ensure_inside(base / PurePosixPath(decoded), source_root)


def copy_shared_texture(source_file: Path, source_name: str) -> Path:
    digest = sha256_file(source_file)[:16]
    source_slug = slugify(source_name)
    suffix = source_file.suffix.lower()
    stem = slugify(source_file.stem)[:64]
    target = TEXTURE_ROOT / source_slug / f"{stem}-{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source_file, target)
    elif sha256_file(target) != sha256_file(source_file):
        raise RuntimeError(f"Texture hash collision: {target}")
    return target


def materialize_glb(source_file: Path, out_dir: Path) -> None:
    shutil.copy2(source_file, out_dir / "model.glb")


def materialize_gltf(source_file: Path, source_root: Path, source_name: str, out_dir: Path) -> None:
    data = json.loads(source_file.read_text(encoding="utf-8"))
    for i, buffer in enumerate(data.get("buffers", [])):
        uri = buffer.get("uri")
        if not uri or uri.startswith("data:"):
            continue
        src = resolve_uri(source_file.parent, uri, source_root)
        if not src.is_file():
            raise FileNotFoundError(f"Missing GLTF buffer: {src}")
        name = "model.bin" if i == 0 else f"buffer-{i}.bin"
        shutil.copy2(src, out_dir / name)
        buffer["uri"] = name
    for image in data.get("images", []):
        uri = image.get("uri")
        if not uri or uri.startswith("data:"):
            continue
        src = resolve_uri(source_file.parent, uri, source_root)
        if not src.is_file():
            raise FileNotFoundError(f"Missing GLTF image: {src}")
        target = copy_shared_texture(src, source_name)
        image["uri"] = os.path.relpath(target, out_dir).replace(os.sep, "/")
    (out_dir / "model.gltf").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def materialize_obj(source_file: Path, source_root: Path, out_dir: Path) -> None:
    text = source_file.read_text(encoding="utf-8", errors="replace")
    mtl_names = []
    for line in text.splitlines():
        if line.lstrip().startswith("mtllib "):
            mtl_names.append(line.strip().split(None, 1)[1])
    combined_mtl = []
    for mtl_name in mtl_names:
        mtl_src = resolve_uri(source_file.parent, mtl_name, source_root)
        if not mtl_src.is_file():
            raise FileNotFoundError(f"Missing OBJ MTL: {mtl_src}")
        mtl_lines = []
        for line in mtl_src.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                key = stripped.split()[0].lower()
                if key.startswith("map_") or key in {"bump", "disp", "decal", "refl"}:
                    parts = line.split()
                    uri = parts[-1]
                    tex_src = resolve_uri(mtl_src.parent, uri, source_root)
                    if not tex_src.is_file():
                        raise FileNotFoundError(f"Missing MTL texture: {tex_src}")
                    tex_name = f"texture-{sha256_file(tex_src)[:12]}{tex_src.suffix.lower()}"
                    shutil.copy2(tex_src, out_dir / tex_name)
                    parts[-1] = tex_name
                    line = " ".join(parts)
            mtl_lines.append(line)
        combined_mtl.extend([f"# From {mtl_name}", *mtl_lines, ""])
    rewritten = []
    wrote_mtllib = False
    for line in text.splitlines():
        if line.lstrip().startswith("mtllib "):
            if not wrote_mtllib and combined_mtl:
                rewritten.append("mtllib model.mtl")
                wrote_mtllib = True
            continue
        rewritten.append(line)
    (out_dir / "model.obj").write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    if combined_mtl:
        (out_dir / "model.mtl").write_text("\n".join(combined_mtl).rstrip() + "\n", encoding="utf-8")


def write_license(metadata: dict, out_dir: Path) -> None:
    text = (
        f"{metadata.get('source', 'Unknown source')}\n"
        f"Author: {metadata.get('author') or 'Unknown'}\n"
        f"License: {metadata.get('license', 'Unknown')}\n"
        f"Official page: {metadata.get('source_site') or metadata.get('source_repository') or metadata.get('original_url') or 'Unknown'}\n"
        f"Original download: {metadata.get('original_url') or 'Unknown'}\n"
        f"Attribution required: {'yes' if metadata.get('attribution_required') else 'no'}\n"
    )
    (out_dir / "LICENSE.txt").write_text(text, encoding="utf-8")


def validate_asset(out_dir: Path, metadata: dict) -> None:
    models = [p for p in (out_dir / "model.glb", out_dir / "model.gltf", out_dir / "model.obj") if p.exists()]
    if len(models) != 1:
        raise RuntimeError(f"Expected exactly one model for {metadata['id']}, found {len(models)}")
    model = models[0]
    if model.suffix == ".gltf":
        data = json.loads(model.read_text(encoding="utf-8"))
        for buffer in data.get("buffers", []):
            uri = buffer.get("uri")
            if uri and not uri.startswith("data:") and not (out_dir / uri).resolve().is_file():
                raise RuntimeError(f"Missing generated buffer {metadata['id']}: {uri}")
        for image in data.get("images", []):
            uri = image.get("uri")
            if uri and not uri.startswith("data:") and not (out_dir / uri).resolve().is_file():
                raise RuntimeError(f"Missing generated image {metadata['id']}: {uri}")
    if model.suffix == ".obj":
        for line in model.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("mtllib "):
                uri = line.split(None, 1)[1]
                if not (out_dir / uri).is_file():
                    raise RuntimeError(f"Missing generated MTL {metadata['id']}: {uri}")
    if metadata.get("dimensions") is None:
        raise RuntimeError(f"Null dimensions: {metadata['id']}")


def main() -> None:
    manifest = decode_manifest()
    assets = manifest["assets"]
    shutil.rmtree(ASSET_ROOT, ignore_errors=True)
    shutil.rmtree(TEXTURE_ROOT, ignore_errors=True)
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    TEXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    unique_urls = sorted({a["original_url"] for a in assets})
    extracted: dict[str, Path] = {}
    for idx, url in enumerate(unique_urls, 1):
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        archive = CACHE_ROOT / f"{key}.zip"
        source_dir = CACHE_ROOT / f"{key}-src"
        print(f"[{idx}/{len(unique_urls)}] Preparing source archive", flush=True)
        download(url, archive)
        safe_extract_zip(archive, source_dir)
        extracted[url] = source_dir
    checksums = []
    index_assets = []
    source_counts: dict[str, int] = {}
    format_counts: dict[str, int] = {}
    for idx, raw_metadata in enumerate(assets, 1):
        metadata = dict(raw_metadata)
        target_rel = metadata.pop("_target_dir")
        metadata["repaired_in"] = "architecture-batch-001-final"
        out_dir = REPO / target_rel
        out_dir.mkdir(parents=True, exist_ok=True)
        source_root = extracted[metadata["original_url"]]
        source_file = source_root / PurePosixPath(metadata["original_zip_path"])
        if not source_file.is_file():
            raise FileNotFoundError(f"Source asset not found: {source_file}")
        fmt = metadata["original_format"].lower()
        if fmt == "glb":
            materialize_glb(source_file, out_dir)
            model_file = out_dir / "model.glb"
            metadata["formats"] = ["glb"]
            metadata["files"] = ["model.glb"]
        elif fmt == "gltf":
            materialize_gltf(source_file, source_root, metadata["source"], out_dir)
            model_file = out_dir / "model.gltf"
            metadata["formats"] = ["gltf"]
            metadata["files"] = sorted(p.name for p in out_dir.iterdir() if p.name.startswith(("model", "buffer-")))
        elif fmt == "obj":
            materialize_obj(source_file, source_root, out_dir)
            model_file = out_dir / "model.obj"
            metadata["formats"] = ["obj"]
            metadata["files"] = sorted(p.name for p in out_dir.iterdir() if p.name.startswith(("model", "texture-")))
        else:
            raise RuntimeError(f"Unsupported format {fmt} for {metadata['id']}")
        write_license(metadata, out_dir)
        (out_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        validate_asset(out_dir, metadata)
        model_hash = sha256_file(model_file)
        checksums.append(f"{model_hash}  {model_file.relative_to(REPO).as_posix()}")
        index_assets.append({
            "id": metadata["id"], "name": metadata["name"], "category": metadata.get("category"),
            "subcategory": metadata.get("subcategory"), "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []), "style": metadata.get("style", []), "formats": metadata.get("formats", []),
            "dimensions": metadata.get("dimensions"), "license": metadata.get("license"), "source": metadata.get("source"),
            "path": target_rel, "sha256": model_hash,
        })
        source_counts[metadata["source"]] = source_counts.get(metadata["source"], 0) + 1
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        if idx % 25 == 0 or idx == len(assets):
            print(f"Materialized {idx}/{len(assets)} assets", flush=True)
    if len({a["id"] for a in index_assets}) != len(index_assets):
        raise RuntimeError("Duplicate asset IDs in final index")
    index_dir = REPO / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index = {"version": 1, "generated_at": "2026-09-14", "asset_count": len(index_assets), "assets": index_assets}
    (index_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (index_dir / "checksums.sha256").write_text("\n".join(sorted(checksums)) + "\n", encoding="utf-8")
    source_lines = ["# TKRS Architecture Batch 001 — Sources", ""]
    by_source = {}
    for a in assets:
        by_source.setdefault(a["source"], a)
    for source in sorted(by_source):
        a = by_source[source]
        source_lines.extend([
            f"## {source}", f"- Author: {a.get('author') or 'Unknown'}", f"- License: {a.get('license') or 'Unknown'}",
            f"- Assets used: {source_counts[source]}", f"- Official page: {a.get('source_site') or 'n/a'}",
            f"- Repository/source page: {a.get('source_repository') or 'n/a'}", f"- Original archive: {a.get('original_url') or 'n/a'}", "",
        ])
    (REPO / "SOURCES.md").write_text("\n".join(source_lines), encoding="utf-8")
    report = [
        "# TKRS Architecture Batch 001 — Final", "", f"- Assets: **{len(index_assets)}**",
        f"- GLB: **{format_counts.get('glb', 0)}**", f"- GLTF: **{format_counts.get('gltf', 0)}**", f"- OBJ: **{format_counts.get('obj', 0)}**",
        "- Duplicate IDs: **0**", "- Missing generated dependencies: **0**", "- Assets with null dimensions: **0**",
        "- License set: **CC0-1.0**", "",
        "GLTF textures are deduplicated under the repository-level `textures/` directory and referenced with relative paths.",
        "The searchable catalog is `index/index.json`; model hashes are in `index/checksums.sha256`.", "",
    ]
    (REPO / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    batch_manifest = {
        "batch": "architecture-batch-001-final", "asset_count": len(index_assets), "formats": format_counts,
        "sources": source_counts, "validation": {"unique_ids": True, "missing_external_dependencies": 0, "null_dimensions": 0},
    }
    (REPO / "batch-manifest.json").write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Done: {len(index_assets)} assets, {len(list(TEXTURE_ROOT.rglob('*.*')))} shared texture files", flush=True)


if __name__ == "__main__":
    main()
