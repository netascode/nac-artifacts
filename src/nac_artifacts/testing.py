# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Builders for tests of tools that consume nac-artifacts.

These create the on-disk shapes the discovery code reads: installed modules
(with the ``modules.json`` Terraform writes) and bundles as zip or tar.gz
archives. File maps are keyed by path relative to the ``nac/`` directory unless
stated otherwise.
"""

import json
import os
import tarfile
import zipfile
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path

from .constants import (
    ARTIFACTS_DIRNAME,
    BUNDLE_MANIFEST_FILENAME,
    TERRAFORM_DEFAULT_DATA_DIR,
    TERRAFORM_MODULES_MANIFEST,
)


def _data_dir(data_dir: str | None) -> str:
    """The Terraform data directory: ``data_dir``, ``TF_DATA_DIR`` or the default."""
    return data_dir or os.environ.get("TF_DATA_DIR") or str(TERRAFORM_DEFAULT_DATA_DIR)


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
    project: Path, entries: list[dict[str, str]], data_dir: str | None = None
) -> None:
    """Write a ``modules.json`` with the root module entry plus ``entries``.

    Args:
        project: Project (root module) directory.
        entries: Module entries, e.g. from ``module_entry``.
        data_dir: Terraform data directory, relative to ``project`` or absolute.
            Defaults to ``TF_DATA_DIR`` if set, else ``.terraform``.
    """
    manifest = project / _data_dir(data_dir) / TERRAFORM_MODULES_MANIFEST
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
    data_dir: str | None = None,
) -> Path:
    """Install a module below ``<data dir>/modules`` and register it.

    Args:
        project: Project (root module) directory.
        files: Artifacts to create, relative to the module's ``nac/`` directory.
        key: Module key in ``modules.json``.
        version: Module version recorded in ``modules.json``, if any.
        data_dir: Terraform data directory, relative to ``project`` or absolute.
            Defaults to ``TF_DATA_DIR`` if set, else ``.terraform``.

    Returns:
        The module directory (the one containing ``nac/``).
    """
    data = _data_dir(data_dir)
    directory = (Path(data) / "modules" / key).as_posix()
    module_dir = project / directory
    write_files(module_dir / ARTIFACTS_DIRNAME, files)
    write_modules_json(project, [module_entry(key, directory, version)], data)
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
        name: Bundle name in the manifest (written quoted).
        version: Bundle version in the manifest (written quoted, so ``"1.10"``
            stays a string).
        manifest_extra: Raw YAML appended to the manifest.
        extra: Additional archive members, keyed by their exact archive path.
    """
    content: dict[str, str] = {
        # JSON strings are valid YAML scalars and keep their quotes
        BUNDLE_MANIFEST_FILENAME: (
            f"name: {json.dumps(name)}\nversion: {json.dumps(version)}\n"
            f"{manifest_extra}"
        )
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
