#!/usr/bin/env python3
"""Publish immutable asset/data snapshots, then atomically select the page.

Runs on the web host after the deployment gates and rsync. Dataset snapshots
use hard links: subsequent deployments must replace files, never edit in place.
Old snapshots remain available to open tabs and CDN misses; no automatic GC.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

PAGE_FILES = ("app.js", "boot.js", "preview.png", "llms.txt", "robots.txt", "sitemap.xml")
DATA_FILES = ("index.json", "hover_cells.bin", "reading_parents.bin", "water.pmtiles",
              "borders.pmtiles", "borders.json", "places.json", "airports.json", "airspace.json")


def regular_files(root: Path, names: tuple[str, ...]) -> list[Path]:
    """List only regular files within the supplied trees, refusing symlinks."""
    result = []
    for name in names:
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        paths = [path, *path.rglob("*")] if path.is_dir() and not path.is_symlink() else [path]
        for item in paths:
            if item.is_symlink():
                raise ValueError(f"refusing symlink: {item}")
            if any(part.startswith(".") for part in item.relative_to(root).parts):
                continue
            if item.is_file():
                result.append(item)
    return sorted(result)


def manifest(root: Path, files: list[Path]) -> list[tuple[str, int, int]]:
    return [(str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in files]


def atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def snapshot(root: Path, directory: str, identity: str, files: list[Path], *, link: bool) -> Path:
    parent = root / directory
    if parent.is_symlink():
        raise ValueError(f"refusing symlink: {parent}")
    parent.mkdir(exist_ok=True)
    target = parent / identity
    if target.is_symlink():
        raise ValueError(f"refusing symlink: {target}")
    if target.exists():
        for source in files:
            saved = target / source.relative_to(root)
            if saved.is_symlink() or not saved.is_file() or saved.stat().st_size != source.stat().st_size:
                raise ValueError(f"incomplete immutable snapshot: {saved}")
        target.chmod(0o755)
        return target
    staging = Path(tempfile.mkdtemp(prefix=".release-", dir=parent))
    before = manifest(root, files)
    try:
        for source in files:
            dest = staging / source.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if link:
                os.link(source, dest)
            else:
                shutil.copy2(source, dest)
        if manifest(root, files) != before:
            raise ValueError("source files changed while publishing; retry after the deploy finishes")
        staging.chmod(0o755)
        os.rename(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def render_page(template: str, asset_id: str, data_id: str, assets: set[str]) -> str:
    def replace(match: re.Match) -> str:
        attr, quote, name = match.groups()
        path = name.removeprefix("./")
        if path in assets or path.startswith("vendor/"):
            name = f"/assets/{asset_id}/{path}"
        elif path in DATA_FILES:
            name = f"/data/{data_id}/{path}"
        return f"{attr}={quote}{name}{quote}"

    html = re.sub(r'''\b(href|src)=(["'])([^"']+)\2''', replace, template)
    return html.replace("<head>", f'<head>\n<meta name="worldmap-data-root" content="/data/{data_id}/">', 1)


def publish(root: Path) -> dict[str, str]:
    root = root.resolve(strict=True)
    template_path = root / ".release-index.html"
    if template_path.is_symlink():
        raise ValueError("the page template must not be a symlink")
    template = template_path.read_text(encoding="utf-8")
    if "worldmap-data-root" in template or "<head>" not in template:
        raise ValueError("expected an unpublished HTML template with a head element")
    index_path = root / "index.json"
    if index_path.is_symlink():
        raise ValueError("index.json must not be a symlink")
    index = json.loads(index_path.read_bytes())
    build = index.get("buildId", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", build) or not index.get("origins"):
        raise ValueError("a complete dataset with a safe buildId is required")
    for name in ("hover_cells.bin", "water.pmtiles", "app.js", "boot.js"):
        if not (root / name).is_file():
            raise ValueError(f"required release file is missing: {name}")
    assets = regular_files(root, (*PAGE_FILES, "vendor"))
    digest = hashlib.sha256(template.encode())
    for path in assets:
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    asset_id = digest.hexdigest()[:20]
    data = regular_files(root, (*DATA_FILES, "origins", "v"))
    data_manifest = manifest(root, data)
    data_id = build + "-" + hashlib.sha256(json.dumps(data_manifest).encode()).hexdigest()[:16]
    snapshot(root, "assets", asset_id, assets, link=False)
    snapshot(root, "data", data_id, data, link=True)
    if manifest(root, data) != data_manifest:
        raise ValueError("dataset changed before publication; keeping the previous page")
    html = render_page(template, asset_id, data_id, {str(p.relative_to(root)) for p in assets})
    atomic_write(root / "index.html", html.encode())
    release = {"assets": asset_id, "data": data_id, "buildId": build}
    atomic_write(root / ".release.json", (json.dumps(release) + "\n").encode())
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    print(json.dumps(publish(parser.parse_args().root)))
