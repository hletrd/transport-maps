#!/usr/bin/env python3
"""Publish immutable asset/data snapshots, then atomically select the page.

Runs on the web host after the deployment gates and rsync. Dataset snapshots
use hard links: subsequent deployments must replace files, never edit in place.
Old snapshots remain available to open tabs and CDN misses; no automatic GC.
"""

from __future__ import annotations

import argparse
import array
import bisect
import hashlib
import itertools
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

PAGE_FILES = ("app.js", "boot.js", "detail.js", "delivery.js", "preview.png", "llms.txt", "robots.txt", "sitemap.xml")
DATA_FILES = ("index.json", "hover_cells.bin", "reading_parents.bin", "water.pmtiles",
              "borders.pmtiles", "borders.json", "places.json", "airports.json", "airspace.json")


def prepare_reading_ranges(root: Path, index: dict) -> None:
    """Index existing sorted override arrays without rebuilding any journeys."""
    if not index.get("readingRes") or not index.get("overrideUrlSuffix"):
        return
    parents, slots = index["readingParentCount"], index["readingSlots"]
    channels = len(index["modeChannels"])
    if not all(isinstance(n, int) and n > 0 for n in (parents, slots, channels)):
        raise ValueError("invalid regional reading layout")
    width = 6 + 2 * channels
    suffix = index["overrideUrlSuffix"]
    if suffix != ".over.bin" or index.get("readingUrlSuffix") != ".r6.bin":
        raise ValueError("unknown regional reading file format")
    sources = {p for p in regular_files(root, ("origins", "v")) if p.name.endswith(suffix)}
    for prefix in ["origins/", *(v["path"] + "origins/" for v in index.get("variants", []))]:
        if not re.fullmatch(r"(?:v/[A-Za-z0-9_-]+/)?origins/", prefix):
            raise ValueError("unsafe variant directory")
        for origin in index["origins"]:
            slug = origin["slug"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
                raise ValueError("unsafe origin slug")
            if root / prefix / (slug + suffix) not in sources:
                raise ValueError(f"missing route overrides: {prefix}{slug}{suffix}")
    generated = 0
    for source in sorted(sources):
        stem = source.name.removesuffix(suffix)
        reading = source.with_name(stem + index["readingUrlSuffix"])
        if reading.is_symlink() or reading.stat().st_size != parents * slots * 2:
            raise ValueError(f"invalid fine reading length: {reading}")
        stat = source.stat()
        if stat.st_size % width:
            raise ValueError(f"invalid route override length: {source}")
        count = stat.st_size // width
        target = source.with_name(stem + ".over.index.bin")
        if target.is_symlink():
            raise ValueError(f"refusing symlink: {target}")
        if (target.exists() and target.stat().st_size == (parents + 2) * 4
                and target.stat().st_mtime_ns == stat.st_mtime_ns):
            continue
        with source.open("rb") as stream:
            numbers = array.array("I")
            numbers.fromfile(stream, count)
        if sys.byteorder != "little":
            numbers.byteswap()
        ordered = numbers.tolist()
        if (any(a >= b for a, b in itertools.pairwise(ordered))
                or (ordered and ordered[-1] >= parents * slots)):
            raise ValueError(f"route slots are not unique, sorted and in range: {source}")
        offsets = array.array("I", [count, *(bisect.bisect_left(ordered, n * slots) for n in range(parents + 1))])
        if sys.byteorder != "little":
            offsets.byteswap()
        atomic_write(target, offsets.tobytes())
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        generated += 1
        if generated % 200 == 0:
            print(f"indexed regional routes for {generated} origin/variant files", file=sys.stderr, flush=True)
    desired = {"blocks": 32, "overrideIndexSuffix": ".over.index.bin"}
    if index.get("readingRanges") != desired:
        index["readingRanges"] = desired
        atomic_write(root / "index.json", (json.dumps(index, ensure_ascii=False) + "\n").encode())


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


def render_page(template: str, asset_id: str, data_id: str, assets: set[str],
                styles: dict[str, str] | None = None) -> str:
    def replace(match: re.Match) -> str:
        attr, quote, name = match.groups()
        path = name.removeprefix("./")
        if path in assets or path.startswith("vendor/"):
            name = f"/assets/{asset_id}/{path}"
        elif path in DATA_FILES:
            name = f"/data/{data_id}/{path}"
        return f"{attr}={quote}{name}{quote}"

    html = re.sub(r'''\b(href|src)=(["'])([^"']+)\2''', replace, template)
    if styles is not None:
        def inline_style(match: re.Match) -> str:
            tag = match.group(0)
            href = re.search(r'''\bhref=["']([^"']+)["']''', tag)
            if not href or not re.search(r'''\brel=["']stylesheet["']''', tag):
                return tag
            prefix = f"/assets/{asset_id}/"
            name = href.group(1).removeprefix(prefix)
            if name not in ("vendor/fonts.css", "vendor/maplibre-gl.css"):
                return tag
            if name not in styles:
                raise ValueError(f"required first-paint stylesheet is missing: {name}")
            css = styles[name]
            if "</style" in css.lower():
                raise ValueError(f"stylesheet cannot be embedded safely: {name}")

            def rebase_url(url: re.Match) -> str:
                path = name.rsplit("/", 1)[0] + "/" + url.group(2)[2:]
                if path not in assets:
                    raise ValueError(f"stylesheet references a missing asset: {path}")
                return f'url("{prefix}{path}")'

            css = re.sub(r'''url\(\s*(["']?)(\./[^)'"\s]+)\1\s*\)''', rebase_url, css)
            if name == "vendor/maplibre-gl.css":
                # Native control icons are not on this page's first screen.
                # Keep every layout rule immediately, then apply the original
                # complete stylesheet after first paint and after it has loaded.
                image = re.compile(r'''background-image\s*:\s*url\((?:"[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*'|[^)]*)\)\s*;?''')

                def core_rule(rule: re.Match) -> str:
                    selector, body = rule.groups()
                    if ".maplibregl-ctrl" in selector:
                        body = image.sub("", body)
                    return selector + "{" + body + "}"

                core = re.sub(r"([^{}]+)\{([^{}]*)\}", core_rule, css)
                return (f'<style data-source="{name}">\n{core}\n</style>'
                        f'<link href="{prefix}{name}" rel="stylesheet" media="print" data-after-paint>'
                        f'<noscript><link href="{prefix}{name}" rel="stylesheet"></noscript>')
            return f'<style data-source="{name}">\n{css}\n</style>'

        html = re.sub(r"<link\b[^>]*>", inline_style, html)
    # Leave script bytes intact: the analytics bootstrap is protected by a
    # CSP hash. Source comments remain in the repository and vendored files.
    chunks = re.split(r"(<script\b.*?</script\s*>)", html, flags=re.S | re.I)
    css_tokens = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|/\*.*?\*/''', re.S)

    def trim_style(style: re.Match) -> str:
        def trim_token(token: re.Match) -> str:
            value = token.group(0)
            if value.startswith("/*") and not re.search(r"^/\*!|copyright|licen[cs]e", value, re.I):
                return ""
            return value
        return style.group(1) + css_tokens.sub(trim_token, style.group(2)) + style.group(3)

    for i in range(0, len(chunks), 2):
        chunks[i] = re.sub(r"<!--.*?-->", "", chunks[i], flags=re.S)
        chunks[i] = re.sub(r"(<style\b[^>]*>)(.*?)(</style\s*>)", trim_style, chunks[i], flags=re.S | re.I)
    html = "".join(chunks)
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
    prepare_reading_ranges(root, index)
    assets = regular_files(root, (*PAGE_FILES, "vendor"))
    digest = hashlib.sha256(template.encode())
    for path in assets:
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    asset_id = digest.hexdigest()[:20]
    data = regular_files(root, (*DATA_FILES, "origins", "v"))
    data_manifest = manifest(root, data)
    # Compression/range-policy revisions get fresh CDN keys without changing
    # the model build or mutating an existing snapshot.
    data_identity = {"transport": 1, "files": data_manifest}
    data_id = build + "-" + hashlib.sha256(json.dumps(data_identity).encode()).hexdigest()[:16]
    snapshot(root, "assets", asset_id, assets, link=False)
    snapshot(root, "data", data_id, data, link=True)
    if manifest(root, data) != data_manifest:
        raise ValueError("dataset changed before publication; keeping the previous page")
    styles = {name: (root / name).read_text(encoding="utf-8")
              for name in ("vendor/fonts.css", "vendor/maplibre-gl.css") if (root / name).is_file()}
    html = render_page(template, asset_id, data_id, {str(p.relative_to(root)) for p in assets}, styles)
    atomic_write(root / "index.html", html.encode())
    release = {"assets": asset_id, "data": data_id, "buildId": build}
    atomic_write(root / ".release.json", (json.dumps(release) + "\n").encode())
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    print(json.dumps(publish(parser.parse_args().root)))
