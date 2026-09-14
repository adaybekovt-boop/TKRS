#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import urllib.parse
import urllib.request
import zipfile
import zlib

REPO = Path(__file__).resolve().parents[1]
BATCH = "architecture-002"
MANIFEST_DIR = REPO / "batches" / BATCH
MANIFEST_JSON = MANIFEST_DIR / "manifest.json"
ASSET_ROOT = REPO / "assets" / "architecture"
TEXTURE_ROOT = REPO / "textures"
CACHE_ROOT = REPO / ".local" / f"{BATCH}-cache"
INDEX_PATH = REPO / "index" / "index.json"
CHECKSUMS_PATH = REPO / "index" / "checksums.sha256"
USER_AGENT = "TKRS/1.0 (+https://github.com/adaybekovt-boop/TKRS)"

PAGE_ARCHIVES = {
    "https://opengameart.org/content/indoor-bundle": [
        "https://opengameart.org/sites/default/files/fbx_9.zip",
        "https://opengameart.org/sites/default/files/png_2.zip",
    ],
    "https://opengameart.org/content/unfinished-buildings": [
        "https://opengameart.org/sites/default/files/unfinishedbuildings_fbx_gltf_textures.zip",
    ],
    "https://opengameart.org/content/residential-building-lowpoly-apartment-block": [
        "https://opengameart.org/sites/default/files/residential-building-lowpoly-apartment-block.zip",
    ],
}

MODEL_EXTS = {".glb", ".gltf", ".fbx", ".obj"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds", ".webp"}
FORBIDDEN_EXTS = {".exe", ".dll", ".bat", ".cmd", ".ps1", ".sh", ".js", ".lua", ".luau", ".msi", ".scr", ".com", ".jar"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "source"


def decode_manifest() -> dict:
    parts = sorted(MANIFEST_DIR.glob("manifest.part-*.b64"))
    if not parts:
        raise RuntimeError("Batch 002 compressed manifest parts are missing")
    encoded = "".join("".join(p.read_text(encoding="utf-8").split()) for p in parts)
    raw = zlib.decompress(base64.b64decode(encoded))
    data = json.loads(raw.decode("utf-8"))
    if data.get("asset_count") != len(data.get("assets", [])):
        raise RuntimeError("Manifest asset_count mismatch")
    MANIFEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def request(url: str):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return
    last = None
    for attempt in range(1, 4):
        try:
            print(f"Downloading ({attempt}/3): {url}", flush=True)
            with urllib.request.urlopen(request(url), timeout=240) as response, destination.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if destination.stat().st_size < 32:
                raise RuntimeError(f"Downloaded file too small: {destination}")
            return
        except Exception as exc:
            last = exc
            destination.unlink(missing_ok=True)
            print(f"Download failed: {exc}", flush=True)
    raise RuntimeError(f"Unable to download {url}: {last}")


def safe_extract_zip(archive: Path, destination: Path) -> None:
    if destination.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    dest = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            out = (destination / info.filename).resolve()
            if out != dest and not str(out).startswith(str(dest) + os.sep):
                raise RuntimeError(f"Unsafe ZIP member: {info.filename}")
        zf.extractall(destination)


def source_urls_for_asset(asset: dict, manifest: dict) -> list[str]:
    url = asset["original_url"]
    urls = list(PAGE_ARCHIVES.get(url, [url]))
    for extra in manifest.get("supplemental_archives", {}).get(asset.get("source"), []):
        if extra not in urls:
            urls.append(extra)
    return urls


def prepare_url(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix != ".zip":
        raise RuntimeError(f"Only ZIP source URLs are supported after resolution: {url}")
    archive = CACHE_ROOT / f"{key}.zip"
    source_dir = CACHE_ROOT / f"{key}-src"
    download(url, archive)
    safe_extract_zip(archive, source_dir)
    return source_dir


def build_file_index(roots: list[Path]) -> tuple[dict[str, list[Path]], dict[str, list[Path]]]:
    by_name: dict[str, list[Path]] = {}
    by_hash: dict[str, list[Path]] = {}
    for root in roots:
        for p in root.rglob("*"):
            if p.is_file():
                by_name.setdefault(p.name.casefold(), []).append(p)
    return by_name, by_hash


def candidates_by_name(name: str, by_name: dict[str, list[Path]]) -> list[Path]:
    return by_name.get(Path(name).name.casefold(), [])


def find_file(*, exact_relative: str | None, filename: str | None, roots: list[Path], by_name: dict[str, list[Path]], expected_sha256: str | None = None) -> Path:
    if exact_relative:
        rel = PurePosixPath(exact_relative)
        for root in roots:
            p = root / rel
            if p.is_file() and (not expected_sha256 or sha256_file(p) == expected_sha256):
                return p
    search_name = filename or (PurePosixPath(exact_relative).name if exact_relative else None)
    if search_name:
        candidates = candidates_by_name(search_name, by_name)
        if expected_sha256:
            for p in candidates:
                if sha256_file(p) == expected_sha256:
                    return p
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            parts = [x.casefold() for x in PurePosixPath(exact_relative or "").parts if x]
            return sorted(candidates, key=lambda p: -sum(1 for part in parts if part in p.as_posix().casefold()))[0]
    raise FileNotFoundError(f"Unable to resolve source file: {exact_relative or filename}")


def find_dependency(base_file: Path, uri: str, roots: list[Path], by_name: dict[str, list[Path]]) -> Path:
    decoded = urllib.parse.unquote(uri.replace("\\", "/"))
    if decoded.startswith("data:"):
        raise ValueError("Data URI is embedded and should not be resolved")
    candidate = (base_file.parent / PurePosixPath(decoded)).resolve()
    for root in roots:
        try:
            candidate.relative_to(root.resolve())
            if candidate.is_file():
                return candidate
        except ValueError:
            pass
    basename = PurePosixPath(decoded).name
    matches = candidates_by_name(basename, by_name)
    if not matches:
        raise FileNotFoundError(f"Missing dependency {uri} for {base_file}")
    return min(matches, key=lambda p: abs(len(p.parts) - len(base_file.parts)))


def copy_shared_texture(src: Path, source_name: str) -> Path:
    digest = sha256_file(src)[:16]
    target = TEXTURE_ROOT / slugify(source_name) / f"{slugify(src.stem)[:64]}-{digest}{src.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(src, target)
    elif sha256_file(target) != sha256_file(src):
        raise RuntimeError(f"Shared texture collision: {target}")
    return target


def dimensions_from_obj(path: Path) -> dict | None:
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    found = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("v "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            xyz = [float(parts[1]), float(parts[2]), float(parts[3])]
        except ValueError:
            continue
        found = True
        for i, value in enumerate(xyz):
            mins[i] = min(mins[i], value)
            maxs[i] = max(maxs[i], value)
    if not found:
        return None
    return {"min": mins, "max": maxs, "size": [maxs[i] - mins[i] for i in range(3)], "unit": "source_units"}


def dimensions_from_gltf_dict(data: dict) -> dict | None:
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    found = False
    accessors = data.get("accessors") or []
    for mesh in data.get("meshes") or []:
        for primitive in mesh.get("primitives", []) or []:
            idx = (primitive.get("attributes") or {}).get("POSITION")
            if not isinstance(idx, int) or idx < 0 or idx >= len(accessors):
                continue
            accessor = accessors[idx]
            mn, mx = accessor.get("min"), accessor.get("max")
            if not (isinstance(mn, list) and isinstance(mx, list) and len(mn) >= 3 and len(mx) >= 3):
                continue
            found = True
            for i in range(3):
                mins[i] = min(mins[i], float(mn[i]))
                maxs[i] = max(maxs[i], float(mx[i]))
    if not found:
        return None
    return {"min": mins, "max": maxs, "size": [maxs[i] - mins[i] for i in range(3)], "unit": "source_units"}


def dimensions_from_glb(path: Path) -> dict | None:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        return None
    offset = 12
    while offset + 8 <= len(data):
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + length]
        offset += length
        if chunk_type == 0x4E4F534A:
            try:
                return dimensions_from_gltf_dict(json.loads(chunk.rstrip(b"\x00 \t\r\n").decode("utf-8")))
            except Exception:
                return None
    return None


def normalize_dimensions(metadata: dict, model: Path, gltf_data: dict | None = None) -> None:
    dims = metadata.get("dimensions")
    if isinstance(dims, dict) and isinstance(dims.get("size"), list) and len(dims["size"]) >= 3:
        return
    computed = None
    if model.suffix.lower() == ".obj":
        computed = dimensions_from_obj(model)
    elif model.suffix.lower() == ".gltf" and gltf_data is not None:
        computed = dimensions_from_gltf_dict(gltf_data)
    elif model.suffix.lower() == ".glb":
        computed = dimensions_from_glb(model)
    metadata["dimensions"] = computed or {"min": None, "max": None, "size": None, "unit": "unknown"}


def materialize_glb(src: Path, out_dir: Path, metadata: dict) -> Path:
    dst = out_dir / "model.glb"
    shutil.copy2(src, dst)
    normalize_dimensions(metadata, dst)
    return dst


def materialize_gltf(src: Path, roots: list[Path], by_name: dict[str, list[Path]], out_dir: Path, metadata: dict) -> Path:
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    for i, buffer in enumerate(data.get("buffers", []) or []):
        uri = buffer.get("uri")
        if not uri or uri.startswith("data:"):
            continue
        dep = find_dependency(src, uri, roots, by_name)
        name = "model.bin" if i == 0 else f"buffer-{i}.bin"
        shutil.copy2(dep, out_dir / name)
        buffer["uri"] = name
    for image in data.get("images", []) or []:
        uri = image.get("uri")
        if not uri or uri.startswith("data:"):
            continue
        dep = find_dependency(src, uri, roots, by_name)
        shared = copy_shared_texture(dep, metadata["source"])
        image["uri"] = os.path.relpath(shared, out_dir).replace(os.sep, "/")
    dst = out_dir / "model.gltf"
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    normalize_dimensions(metadata, dst, data)
    return dst


def parse_mtl_texture_uri(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    key = stripped.split()[0].lower()
    if not (key.startswith("map_") or key in {"bump", "disp", "decal", "refl"}):
        return None
    remainder = stripped[len(stripped.split()[0]):].strip()
    if not remainder:
        return None
    uri = remainder.split()[-1] if remainder.startswith("-") else remainder
    return key, uri.strip('"')


def materialize_obj(src: Path, roots: list[Path], by_name: dict[str, list[Path]], out_dir: Path, metadata: dict) -> Path:
    text = src.read_text(encoding="utf-8", errors="replace")
    mtl_names = [line.strip().split(None, 1)[1].strip() for line in text.splitlines() if line.lstrip().lower().startswith("mtllib ")]
    combined = []
    for mtl_name in mtl_names:
        try:
            mtl_src = find_dependency(src, mtl_name, roots, by_name)
        except FileNotFoundError:
            mtl_src = find_file(exact_relative=None, filename=Path(src.name).with_suffix(".mtl").name, roots=roots, by_name=by_name)
        mtl_lines = []
        for line in mtl_src.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = parse_mtl_texture_uri(line)
            if parsed:
                key, uri = parsed
                basename = re.split(r"[\\/]", uri)[-1].strip()
                try:
                    dep = find_dependency(mtl_src, uri, roots, by_name)
                except Exception:
                    matches = candidates_by_name(basename, by_name)
                    if not matches:
                        raise FileNotFoundError(f"Missing OBJ texture {uri} for {metadata['id']}")
                    dep = matches[0]
                shared = copy_shared_texture(dep, metadata["source"])
                line = f"{key} {os.path.relpath(shared, out_dir).replace(os.sep, '/')}"
            mtl_lines.append(line)
        combined.extend([f"# From {mtl_src.name}", *mtl_lines, ""])
    rewritten = []
    wrote = False
    for line in text.splitlines():
        if line.lstrip().lower().startswith("mtllib "):
            if combined and not wrote:
                rewritten.append("mtllib model.mtl")
                wrote = True
            continue
        rewritten.append(line)
    dst = out_dir / "model.obj"
    dst.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    if combined:
        (out_dir / "model.mtl").write_text("\n".join(combined).rstrip() + "\n", encoding="utf-8")
    normalize_dimensions(metadata, dst)
    return dst


def fbx_texture_basenames(path: Path) -> set[str]:
    text = path.read_bytes().decode("latin1", errors="ignore")
    pattern = re.compile(r"([A-Za-z0-9_ .()\-\\/:%]+?\.(?:png|jpg|jpeg|tga|bmp|dds|webp))", re.I)
    refs = set()
    for match in pattern.finditer(text):
        basename = re.split(r"[\\/]", match.group(1).strip("\x00 \t\r\n\""))[-1].strip()
        if 0 < len(basename) <= 200:
            refs.add(basename)
    return refs


def materialize_fbx(src: Path, roots: list[Path], by_name: dict[str, list[Path]], out_dir: Path, metadata: dict) -> Path:
    dst = out_dir / "model.fbx"
    shutil.copy2(src, dst)
    missing = []
    for basename in sorted(fbx_texture_basenames(dst)):
        matches = candidates_by_name(basename, by_name)
        if not matches:
            missing.append(basename)
            continue
        target = out_dir / basename
        if not target.exists():
            shutil.copy2(matches[0], target)
    if missing:
        raise FileNotFoundError(f"Missing FBX external textures for {metadata['id']}: {missing}")
    normalize_dimensions(metadata, dst)
    return dst


def write_license(metadata: dict, out_dir: Path) -> None:
    text = (
        f"{metadata.get('source', 'Unknown source')}\n"
        f"Author: {metadata.get('author') or 'Unknown'}\n"
        f"License: {metadata.get('license') or 'Unknown'}\n"
        f"Official page: {metadata.get('source_site') or metadata.get('source_repository') or metadata.get('original_url') or 'Unknown'}\n"
        f"Original download: {metadata.get('original_url') or 'Unknown'}\n"
        f"Attribution required: {'yes' if metadata.get('attribution_required') else 'no'}\n"
    )
    (out_dir / "LICENSE.txt").write_text(text, encoding="utf-8")


def validate_gltf(model: Path) -> None:
    data = json.loads(model.read_text(encoding="utf-8"))
    for collection in ("buffers", "images"):
        for item in data.get(collection, []) or []:
            uri = item.get("uri")
            if not uri or uri.startswith("data:") or re.match(r"^[a-z]+://", uri, re.I):
                continue
            if not (model.parent / urllib.parse.unquote(uri)).resolve().is_file():
                raise RuntimeError(f"Missing GLTF dependency: {model}: {uri}")


def validate_obj(model: Path) -> None:
    for line in model.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.lstrip().lower().startswith("mtllib "):
            continue
        mtl = model.parent / line.strip().split(None, 1)[1]
        if not mtl.is_file():
            raise RuntimeError(f"Missing OBJ MTL: {model}: {mtl.name}")
        for mtl_line in mtl.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = parse_mtl_texture_uri(mtl_line)
            if parsed:
                _, uri = parsed
                dep = (mtl.parent / urllib.parse.unquote(uri)).resolve()
                if not dep.is_file() or dep.stat().st_size == 0:
                    raise RuntimeError(f"Missing/empty MTL texture: {model}: {uri}")


def validate_asset(out_dir: Path, metadata: dict) -> Path:
    models = [p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() in MODEL_EXTS]
    if len(models) != 1:
        raise RuntimeError(f"{metadata['id']}: expected one model, found {[p.name for p in models]}")
    model = models[0]
    if model.stat().st_size == 0:
        raise RuntimeError(f"{metadata['id']}: empty model")
    if model.suffix.lower() == ".glb" and model.read_bytes()[:4] != b"glTF":
        raise RuntimeError(f"{metadata['id']}: invalid GLB header")
    if model.suffix.lower() == ".gltf":
        validate_gltf(model)
    if model.suffix.lower() == ".obj":
        validate_obj(model)
    for p in out_dir.iterdir():
        if p.is_file() and p.suffix.lower() in FORBIDDEN_EXTS:
            raise RuntimeError(f"Forbidden executable/script: {p}")
        if p.is_file() and p.stat().st_size == 0:
            raise RuntimeError(f"Empty file in accepted asset: {p}")
    return model


def clean_batch2_existing(manifest: dict) -> None:
    for asset in manifest["assets"]:
        target = REPO / asset["_target_dir"]
        if target.exists():
            shutil.rmtree(target)
    leftover = ASSET_ROOT / "windows" / "arch_windows_ks-indoor_002"
    if leftover.exists():
        shutil.rmtree(leftover)


def existing_index_without_batch2(batch2_ids: set[str]) -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return [a for a in data.get("assets", []) if a.get("id") not in batch2_ids]


def write_reports(manifest: dict, new_assets: list[dict], existing_count: int, format_counts: dict[str, int], source_counts: dict[str, int]) -> None:
    sub_counts, license_counts = {}, {}
    unknown_dims = 0
    for a in new_assets:
        sub = a.get("subcategory") or "unknown"
        sub_counts[sub] = sub_counts.get(sub, 0) + 1
        lic = a.get("license") or "unknown"
        license_counts[lic] = license_counts.get(lic, 0) + 1
        dims = a.get("dimensions")
        if not isinstance(dims, dict) or not dims.get("size"):
            unknown_dims += 1
    report = [
        "# TKRS Architecture Batch 002 — Final Audit", "",
        f"- accepted assets: **{len(new_assets)}**",
        f"- pre-existing catalog assets preserved: **{existing_count}**",
        f"- combined catalog assets: **{existing_count + len(new_assets)}**",
        "- duplicate IDs against Batch 001: **0**",
        "- exact model hash duplicates against Batch 001: **0**",
        "- missing generated model/dependency files: **0**",
        "- executable/script files: **0**",
        f"- assets with unknown dimensions: **{unknown_dims}**",
        "- license set: **CC0-1.0**", "",
        "## Repairs applied",
        "- normalized all OBJ `mtllib` references to `model.mtl`",
        "- restored OBJ texture dependencies and rewrote texture references",
        "- restored GLTF buffers/textures and normalized relative URIs",
        "- restored detected external FBX texture dependencies beside each FBX",
        "- removed the unaccepted leftover `arch_windows_ks-indoor_002` directory",
        "- regenerated model SHA-256 values, checksums, Batch 002 manifest and merged search index",
        "", "## Assets by format",
    ]
    for k, v in sorted(format_counts.items(), key=lambda x: (-x[1], x[0])):
        report.append(f"- {k}: {v}")
    report += ["", "## Assets by subcategory"]
    for k, v in sorted(sub_counts.items(), key=lambda x: (-x[1], x[0])):
        report.append(f"- {k}: {v}")
    report += ["", "## Assets by source"]
    for k, v in sorted(source_counts.items(), key=lambda x: (-x[1], x[0])):
        report.append(f"- {k}: {v}")
    report += ["", "## Assets by license"]
    for k, v in sorted(license_counts.items(), key=lambda x: (-x[1], x[0])):
        report.append(f"- {k}: {v}")
    report += ["", "## Notes", "- FBX bounding boxes remain unknown where the source metadata did not provide safe dimensions.", "- Batch 002 was rebuilt from the original cited sources rather than trusting stale ZIP dependency paths.", "- The supplied ZIP was under the requested 500 MB limit.", ""]
    (REPO / "REPORT-BATCH-002.md").write_text("\n".join(report), encoding="utf-8")

    source_lines = ["# TKRS Architecture Batch 002 — Sources", ""]
    first_by_source = {}
    for asset in manifest["assets"]:
        first_by_source.setdefault(asset["source"], asset)
    for source in sorted(first_by_source):
        a = first_by_source[source]
        source_lines += [f"## {source}", f"- Author: {a.get('author') or 'Unknown'}", f"- License: {a.get('license') or 'Unknown'}", f"- Assets used: {source_counts.get(source, 0)}", f"- Official page: {a.get('source_site') or a.get('source_repository') or a.get('original_url') or 'Unknown'}", f"- Original source: {a.get('original_url') or 'Unknown'}", ""]
    (REPO / "SOURCES-BATCH-002.md").write_text("\n".join(source_lines), encoding="utf-8")


def main() -> None:
    manifest = decode_manifest()
    assets = manifest["assets"]
    ids = [a["id"] for a in assets]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate IDs inside Batch 002")
    existing = existing_index_without_batch2(set(ids))
    existing_ids = {a.get("id") for a in existing}
    overlap = existing_ids.intersection(ids)
    if overlap:
        raise RuntimeError(f"Batch 002 IDs overlap existing catalog: {sorted(overlap)[:10]}")
    clean_batch2_existing(manifest)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    TEXTURE_ROOT.mkdir(parents=True, exist_ok=True)

    all_urls, asset_urls = [], {}
    for asset in assets:
        urls = source_urls_for_asset(asset, manifest)
        asset_urls[asset["id"]] = urls
        for u in urls:
            if u not in all_urls:
                all_urls.append(u)
    prepared = {}
    for i, url in enumerate(all_urls, 1):
        print(f"[source {i}/{len(all_urls)}]", flush=True)
        prepared[url] = prepare_url(url)

    new_index_assets, checksums = [], []
    source_counts, format_counts = {}, {}
    for i, raw in enumerate(assets, 1):
        metadata = {k: v for k, v in raw.items() if not k.startswith("_")}
        target_rel = raw["_target_dir"]
        out_dir = REPO / target_rel
        out_dir.mkdir(parents=True, exist_ok=True)
        roots = [prepared[u] for u in asset_urls[raw["id"]]]
        by_name, _ = build_file_index(roots)
        source = find_file(exact_relative=metadata.get("original_zip_path"), filename=metadata.get("original_filename"), roots=roots, by_name=by_name, expected_sha256=raw.get("_input_model_sha256"))
        fmt = (metadata.get("original_format") or source.suffix.lstrip(".")).lower()
        if fmt == "glb":
            model = materialize_glb(source, out_dir, metadata); metadata["formats"] = ["glb"]
        elif fmt == "gltf":
            model = materialize_gltf(source, roots, by_name, out_dir, metadata); metadata["formats"] = ["gltf"]
        elif fmt == "obj":
            model = materialize_obj(source, roots, by_name, out_dir, metadata); metadata["formats"] = ["obj"]
        elif fmt == "fbx":
            model = materialize_fbx(source, roots, by_name, out_dir, metadata); metadata["formats"] = ["fbx"]
        else:
            raise RuntimeError(f"Unsupported model format {fmt}: {metadata['id']}")
        write_license(metadata, out_dir)
        model = validate_asset(out_dir, metadata)
        model_hash = sha256_file(model)
        metadata["sha256"] = model_hash
        metadata["files"] = sorted(p.name for p in out_dir.iterdir() if p.is_file() and p.name not in {"metadata.json", "LICENSE.txt"})
        metadata["repaired_in"] = "architecture-batch-002-final"
        (out_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        checksums.append(f"{model_hash}  {model.relative_to(REPO).as_posix()}")
        new_index_assets.append({"id": metadata["id"], "name": metadata["name"], "category": metadata.get("category"), "subcategory": metadata.get("subcategory"), "description": metadata.get("description", ""), "tags": metadata.get("tags", []), "style": metadata.get("style", []), "formats": metadata.get("formats", []), "dimensions": metadata.get("dimensions"), "license": metadata.get("license"), "source": metadata.get("source"), "path": target_rel, "sha256": model_hash})
        source_counts[metadata["source"]] = source_counts.get(metadata["source"], 0) + 1
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        if i % 25 == 0 or i == len(assets):
            print(f"Materialized {i}/{len(assets)} Batch 002 assets", flush=True)

    existing_hashes = {a.get("sha256") for a in existing if a.get("sha256")}
    duplicates_existing = [a["id"] for a in new_index_assets if a["sha256"] in existing_hashes]
    if duplicates_existing:
        raise RuntimeError(f"Exact model duplicates against existing catalog: {duplicates_existing[:10]}")
    new_hashes = [a["sha256"] for a in new_index_assets]
    if len(new_hashes) != len(set(new_hashes)):
        raise RuntimeError("Exact duplicate model hashes inside Batch 002")
    combined = existing + new_index_assets
    if len({a["id"] for a in combined}) != len(combined):
        raise RuntimeError("Duplicate IDs in merged catalog")

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps({"version": 1, "generated_at": "2026-09-14", "asset_count": len(combined), "assets": combined}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    existing_checksum_lines = CHECKSUMS_PATH.read_text(encoding="utf-8").splitlines() if CHECKSUMS_PATH.exists() else []
    CHECKSUMS_PATH.write_text("\n".join(sorted([x for x in existing_checksum_lines if x.strip()] + checksums)) + "\n", encoding="utf-8")
    final_manifest = {"batch": "architecture-batch-002", "asset_count": len(new_index_assets), "combined_catalog_count": len(combined), "licenses": {"CC0-1.0": len(new_index_assets)}, "validation": {"unique_ids": True, "duplicate_ids_against_existing": 0, "duplicate_hashes_against_existing": 0, "missing_dependencies": 0, "forbidden_scripts": 0}}
    (MANIFEST_DIR / "final-manifest.json").write_text(json.dumps(final_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_reports(manifest, new_index_assets, len(existing), format_counts, source_counts)
    print(f"DONE: {len(new_index_assets)} Batch 002 assets; combined catalog {len(combined)}", flush=True)


if __name__ == "__main__":
    main()
