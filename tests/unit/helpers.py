# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Test helpers building modules and bundles with a schema and rules."""

from collections.abc import Sequence
from pathlib import Path

from nac_artifacts import ArtifactLayer, resolve_artifact_layers
from nac_artifacts.testing import (
    bundle_files as _bundle_files,
)
from nac_artifacts.testing import (
    install_module as _install_module,
)
from nac_artifacts.testing import (
    make_tgz,
    make_zip,
    module_entry,
    write_files,
    write_modules_json,
)

__all__ = [
    "PROVIDES",
    "artifact_files",
    "bundle_files",
    "install_module",
    "make_tgz",
    "make_zip",
    "module_entry",
    "resolve_artifacts",
    "write_artifacts",
    "write_modules_json",
]

# Paths below nac/ that the test tools ask for
PROVIDES = ("schema.yaml", "rules")


def artifact_files(
    *, schema: bool = True, rules: dict[str, str] | None = None
) -> dict[str, str]:
    """Return a schema and rule files relative to ``nac/``.

    Args:
        schema: Whether to include a schema file.
        rules: Mapping of rule ID to a description written into the file.
    """
    files: dict[str, str] = {"schema.yaml": "a: str()\n"} if schema else {}
    for rule_id, description in (rules or {}).items():
        files[f"rules/{rule_id}.py"] = f"# {description}\n"
    return files


def write_artifacts(
    root: Path, *, schema: bool = True, rules: dict[str, str] | None = None
) -> Path:
    """Create ``root/nac/`` with a schema and rules."""
    write_files(root / "nac", artifact_files(schema=schema, rules=rules))
    (root / "nac").mkdir(exist_ok=True)
    return root


def install_module(
    project: Path,
    key: str = "m",
    *,
    version: str | None = None,
    schema: bool = True,
    rules: dict[str, str] | None = None,
) -> Path:
    """Install a module with a schema and rules and register it."""
    return _install_module(
        project,
        artifact_files(schema=schema, rules=rules),
        key=key,
        version=version,
    )


def bundle_files(
    version: str = "1.0.0",
    extra: dict[str, str] | None = None,
    manifest_extra: str = "",
) -> dict[str, str]:
    """Return a bundle with a schema, one rule (ID 2) and optional additions.

    Args:
        version: Bundle version in the manifest
        extra: Raw archive members, keyed by their exact archive path
        manifest_extra: Raw YAML appended to the manifest
    """
    return _bundle_files(
        artifact_files(rules={"2": "bundle rule"}),
        version=version,
        extra=extra,
        manifest_extra=manifest_extra,
    )


def resolve_artifacts(
    project: Path,
    *,
    provides: Sequence[str] = PROVIDES,
    bundle: Path | None = None,
    module_dir: Path | None = None,
) -> list[ArtifactLayer]:
    """Resolve the bundle and module layers."""
    return resolve_artifact_layers(
        project, provides=provides, bundle=bundle, module_dir=module_dir
    )
