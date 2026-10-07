# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Discovery, extraction and caching of artifact bundles."""

import hashlib
import os
import shutil
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ruamel.yaml import YAML

from .constants import (
    BUNDLE_CACHE_DIR,
    BUNDLE_CACHE_KEY_LENGTH,
    BUNDLE_CANDIDATES,
    BUNDLE_DIR,
    BUNDLE_MANIFEST_FILENAME,
    BUNDLE_MAX_BYTES,
    BUNDLE_MAX_FILES,
    BUNDLE_REPLACE_ATTEMPTS,
    BUNDLE_REPLACE_DELAY_SECONDS,
    BUNDLE_STALE_TEMP_SECONDS,
)
from .exceptions import BundleError
from .layer import ArtifactLayer, describe_paths, provides_any, validate_provides

# Extraction filters were added to tarfile in 3.12 and backported to 3.10.12+
_TAR_FILTERS_SUPPORTED = hasattr(tarfile, "data_filter")


def _check_member_name(name: str) -> None:
    """Reject archive member names that could escape the extraction directory."""
    posix, windows = PurePosixPath(name), PureWindowsPath(name)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise BundleError(f"Unsafe path in bundle: {name}")


def _check_limits(count: int, size: int) -> None:
    if count > BUNDLE_MAX_FILES or size > BUNDLE_MAX_BYTES:
        raise BundleError(
            f"Bundle too large ({count} files, {size} bytes); "
            f"limits are {BUNDLE_MAX_FILES} files and {BUNDLE_MAX_BYTES} bytes"
        )


def _extract_zip(archive: Path, target: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        _check_limits(len(infos), sum(i.file_size for i in infos))
        for info in infos:
            _check_member_name(info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise BundleError(f"Symlink in bundle not allowed: {info.filename}")
        zf.extractall(target)  # nosec B202 - members vetted above


def _extract_tar(archive: Path, target: Path) -> None:
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        _check_limits(len(members), sum(m.size for m in members))
        for member in members:
            _check_member_name(member.name)
            if not (member.isreg() or member.isdir()):
                raise BundleError(
                    f"Only regular files and directories allowed in bundle: {member.name}"
                )
        if _TAR_FILTERS_SUPPORTED:
            tf.extractall(target, members=members, filter="data")
        else:
            tf.extractall(target, members=members)  # nosec B202 - members vetted above


def _ensure_cache_dir(cache_dir: Path) -> None:
    """Create the cache directory with a ``.gitignore`` that ignores its contents.

    Extracted bundles must not show up as untracked files in the project's
    repository (the same approach pytest, mypy and ruff use for their caches).
    """
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        gitignore = cache_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n", encoding="utf-8")
    except OSError as e:
        raise BundleError(f"Cannot create bundle cache {cache_dir}: {e}") from e


def _remove_stale_temp_dirs(cache_dir: Path) -> None:
    """Delete extraction directories left behind by killed processes."""
    cutoff = time.time() - BUNDLE_STALE_TEMP_SECONDS
    for leftover in cache_dir.glob(".extract-*"):
        try:
            if leftover.stat().st_mtime < cutoff:
                shutil.rmtree(leftover, ignore_errors=True)
        except OSError:
            continue


def _sha256_file(path: Path) -> str:
    """Hash a file in chunks so its size never has to fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_extraction(tmp: Path, cache: Path) -> None:
    """Atomically move a finished extraction to its cache location.

    Another process may populate the cache first, which is fine. A
    ``PermissionError`` (Windows, while a scanner holds files open) is retried.
    """
    for attempt in range(1, BUNDLE_REPLACE_ATTEMPTS + 1):
        try:
            os.replace(tmp, cache)
            return
        except OSError as e:
            if cache.is_dir():
                return
            if not isinstance(e, PermissionError) or attempt == BUNDLE_REPLACE_ATTEMPTS:
                raise
            time.sleep(BUNDLE_REPLACE_DELAY_SECONDS * attempt)


def _materialize_bundle(project_dir: Path, bundle: Path) -> tuple[Path, str | None]:
    """Return the directory holding the bundle content and the archive digest.

    Archives are extracted once into a content-addressed cache so repeated runs
    (and offline runs) reuse the same files.
    """
    if bundle.is_dir():
        return bundle.resolve(), None

    size = bundle.stat().st_size
    if size > BUNDLE_MAX_BYTES:
        raise BundleError(
            f"Bundle archive too large ({size} bytes); limit is {BUNDLE_MAX_BYTES} bytes"
        )
    digest = _sha256_file(bundle)
    cache = project_dir / BUNDLE_CACHE_DIR / digest[:BUNDLE_CACHE_KEY_LENGTH]
    _ensure_cache_dir(cache.parent)
    if cache.is_dir():
        return cache, digest

    if zipfile.is_zipfile(bundle):
        extract = _extract_zip
    elif tarfile.is_tarfile(bundle):
        extract = _extract_tar
    else:
        raise BundleError(f"Bundle is not a zip or tar archive: {bundle}")

    _remove_stale_temp_dirs(cache.parent)
    try:
        tmp = Path(tempfile.mkdtemp(dir=cache.parent, prefix=".extract-"))
    except OSError as e:
        raise BundleError(f"Cannot extract bundle {bundle}: {e}") from e
    try:
        extract(bundle, tmp)
        _publish_extraction(tmp, cache)
    except BundleError:
        raise
    except Exception as e:
        raise BundleError(f"Failed to extract bundle {bundle}: {e}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return cache, digest


def _locate_bundle_root(root: Path, bundle: Path) -> Path:
    """Find the directory holding ``manifest.yaml``.

    Archives made by zipping a folder have a single top-level directory
    (plus, on macOS, ``__MACOSX``); that directory is used as the root.
    """
    if (root / BUNDLE_MANIFEST_FILENAME).is_file():
        return root
    entries = [
        p for p in root.iterdir() if p.name != "__MACOSX" and not p.name.startswith(".")
    ]
    if (
        len(entries) == 1
        and entries[0].is_dir()
        and (entries[0] / BUNDLE_MANIFEST_FILENAME).is_file()
    ):
        return entries[0]
    raise BundleError(f"Bundle {bundle} has no {BUNDLE_MANIFEST_FILENAME} at its root")


def _read_manifest(root: Path, bundle: Path) -> dict[str, Any]:
    """Load and validate the bundle manifest."""
    path = root / BUNDLE_MANIFEST_FILENAME
    try:
        manifest = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise BundleError(
            f"Invalid {BUNDLE_MANIFEST_FILENAME} in bundle {bundle}: {e}"
        ) from e
    if not isinstance(manifest, dict):
        raise BundleError(
            f"{BUNDLE_MANIFEST_FILENAME} in bundle {bundle} must be a mapping"
        )
    _validate_manifest(manifest, bundle)
    return manifest


def _validate_manifest(manifest: dict[str, Any], bundle: Path) -> None:
    """Reject manifest fields of the wrong type instead of silently ignoring them."""
    where = f"{BUNDLE_MANIFEST_FILENAME} in bundle {bundle}"
    name = manifest.get("name")
    if name is not None and not isinstance(name, str):
        raise BundleError(f"'name' in {where} must be a string")
    if manifest.get("version") is not None and not isinstance(manifest["version"], str):
        # YAML reads an unquoted 1.10 as the number 1.1, so it cannot be recovered
        raise BundleError(
            f"'version' in {where} must be a string, quote it (e.g. version: \"1.10\")"
        )
    module = manifest.get("module")
    if module is None:
        return
    if not isinstance(module, dict):
        raise BundleError(f"'module' in {where} must be a mapping")
    if module.get("versions") is not None and not isinstance(module["versions"], str):
        raise BundleError(f"'module.versions' in {where} must be a string")


def find_bundle_layer(
    project_dir: Path,
    *,
    provides: Sequence[str],
    bundle: Path | None = None,
) -> ArtifactLayer | None:
    """Locate, materialize and describe the bundle layer.

    Args:
        project_dir: Project directory holding ``.nac/``.
        provides: Paths relative to ``nac/`` of which the bundle must have at
            least one.
        bundle: Use this archive or directory instead of ``.nac/bundle*``.

    Returns:
        The bundle layer, or None if no bundle is present.

    Raises:
        TypeError: If ``provides`` is a single string.
        ValueError: If ``provides`` is empty or has an invalid path.
        BundleError: If the bundle is missing (when given explicitly), several
            default bundles exist, or it is unsafe, invalid or provides nothing.
    """
    paths = validate_provides(provides)
    project_dir = project_dir.resolve()
    if bundle is None:
        found = [
            p
            for p in (project_dir / BUNDLE_DIR / name for name in BUNDLE_CANDIDATES)
            if p.exists()
        ]
        if len(found) > 1:
            names = ", ".join(p.name for p in found)
            raise BundleError(
                f"Multiple bundles found in {BUNDLE_DIR}/ ({names}); "
                "keep one or select one explicitly"
            )
        if not found:
            return None
        bundle = found[0]
    elif not bundle.exists():
        raise BundleError(f"Bundle not found: {bundle}")

    extracted, digest = _materialize_bundle(project_dir, bundle)
    root = _locate_bundle_root(extracted, bundle)
    manifest = _read_manifest(root, bundle)
    name, version = manifest.get("name"), manifest.get("version")
    detail = f"bundle {name or bundle.name}"
    detail += f" {version}" if version else ""
    detail += f" ({bundle}" + (f", sha256 {digest[:12]}" if digest else "") + ")"
    if not provides_any(root, paths):
        raise BundleError(f"Bundle {bundle} contains no {describe_paths(paths)}")
    return ArtifactLayer("bundle", root, version, detail, manifest)
