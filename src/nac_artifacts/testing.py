# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Builders for tests of tools that consume nac-artifacts.

These create the on-disk shapes the discovery code reads: installed modules
(with the ``modules.json`` Terraform writes) and bundles as zip or tar.gz
archives. File maps are keyed by path relative to the ``nac/`` directory unless
stated otherwise.
"""

import json
import tarfile
import zipfile
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path

from .constants import ARTIFACTS_DIRNAME, BUNDLE_MANIFEST_FILENAME


def write_files(root: Path, files: Mapping[str, str]) -> Path:
    """Write ``files`` (relative path -> content) below ``root`` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def module_entry(
    key: str, directory: str, version: str | None = None
) -> dict[str, str]:
    """Return a ``modules.json`` entry as written by ``terraform init``."""
    entry = {"Key": key, "Source": "x", "Dir": directory}
    if version is not None:
        entry["Version"] = version
    return entry


def write_modules_json(
    project: Path, entries: list[dict[str, str]], data_dir: str = ".terraform"
) -> None:
    """Write a ``modules.json`` with the root module entry plus ``entries``."""
    manifest = project / data_dir / "modules" / "modules.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"Modules": [{"Key": "", "Source": "", "Dir": "."}, *entries]})
    )


def install_module(
    project: Path,
    files: Mapping[str, str],
    *,
    key: str = "m",
    version: str | None = None,
) -> Path:
    """Install a module below ``.terraform/modules`` and register it.

    Args:
        project: Project (root module) directory.
        files: Artifacts to create, relative to the module's ``nac/`` directory.
        key: Module key in ``modules.json``.
        version: Module version recorded in ``modules.json``, if any.

    Returns:
        The module directory (the one containing ``nac/``).
    """
    directory = f".terraform/modules/{key}"
    module_dir = project / directory
    write_files(module_dir / ARTIFACTS_DIRNAME, files)
    write_modules_json(project, [module_entry(key, directory, version)])
    return module_dir


def bundle_files(
    files: Mapping[str, str],
    *,
    name: str = "acme",
    version: str = "1.0.0",
    manifest_extra: str = "",
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the archive content of a bundle.

    Args:
        files: Artifacts, relative to the bundle's ``nac/`` directory.
        name: Bundle name in the manifest.
        version: Bundle version in the manifest.
        manifest_extra: Raw YAML appended to the manifest.
        extra: Additional archive members, keyed by their exact archive path.
    """
    content: dict[str, str] = {
        BUNDLE_MANIFEST_FILENAME: f"name: {name}\nversion: {version}\n{manifest_extra}"
    }
    for rel, text in files.items():
        content[f"{ARTIFACTS_DIRNAME}/{rel}"] = text
    for archive_path, text in (extra or {}).items():
        content[archive_path] = text
    return content


def overrides_yaml(*, rules: Sequence[str] = (), templates: Sequence[str] = ()) -> str:
    """Return the text of an ``overrides.yaml`` disabling the given entries."""
    return (
        "disable:\n"
        f"  rules: {json.dumps(list(rules))}\n"
        f"  templates: {json.dumps(list(templates))}\n"
    )


def make_zip(path: Path, files: Mapping[str, str]) -> Path:
    """Write ``files`` (archive path -> content) as a zip archive."""
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def make_tgz(path: Path, files: Mapping[str, str]) -> Path:
    """Write ``files`` (archive path -> content) as a gzipped tar archive."""
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
    return path
