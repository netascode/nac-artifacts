# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Discovery of artifacts embedded in installed Terraform modules."""

import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .constants import (
    TERRAFORM_DEFAULT_DATA_DIR,
    TERRAFORM_MODULES_MANIFEST,
)
from .exceptions import AmbiguousModuleError, ModuleDiscoveryError
from .layer import ArtifactLayer, describe_paths, provides_any, validate_provides

logger = logging.getLogger(__name__)


def find_installed_modules(
    project_dir: Path, *, provides: Sequence[str] | None = None
) -> list[ArtifactLayer]:
    """List installed modules that ship artifacts.

    Terraform and OpenTofu record every installed module, whatever its source
    (registry, git, archive, local path), in ``<data dir>/modules/modules.json``
    with the install location in ``Dir``. Reading that manifest avoids any
    per-source handling. Only the root module and the modules it calls directly
    are considered; modules nested inside other modules are their internals.

    Args:
        project_dir: Project (root module) directory.
        provides: Paths relative to ``nac/`` of which a module must have at
            least one. With None, any module with a ``nac/`` directory counts.

    Returns:
        The matching modules, without duplicates (several module calls can share
        one directory). Empty if there is no manifest or no module matches.
    """
    data_dir = Path(os.environ.get("TF_DATA_DIR") or TERRAFORM_DEFAULT_DATA_DIR)
    manifest = project_dir / data_dir / TERRAFORM_MODULES_MANIFEST
    if not manifest.is_file():
        return []
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8")).get("Modules")
    except (OSError, ValueError, AttributeError) as e:
        logger.warning("Ignoring unreadable module manifest %s: %s", manifest, e)
        return []
    if not isinstance(entries, list):
        logger.warning("Ignoring module manifest %s without a module list", manifest)
        return []

    candidates: dict[Path, ArtifactLayer] = {}
    missing: list[str] = []
    for entry in entries:
        layer = _module_entry_layer(project_dir, entry, provides, missing)
        if layer is not None:
            candidates.setdefault(layer.root, layer)

    if missing:
        # A stale entry only matters if it could have been the module we need
        level = logging.DEBUG if candidates else logging.WARNING
        logger.log(
            level,
            "Installed module directories not found (run terraform/tofu init): %s",
            ", ".join(missing),
        )
    return list(candidates.values())


def find_module_layer(
    project_dir: Path,
    *,
    provides: Sequence[str],
    module_dir: Path | None = None,
) -> ArtifactLayer | None:
    """Locate artifacts embedded in a Terraform module.

    Args:
        project_dir: Project (root module) directory.
        provides: Paths relative to ``nac/`` of which a module must have at
            least one to count as an artifact provider.
        module_dir: Use this module directory instead of discovering one.

    Returns:
        The module layer, or None if no installed module provides artifacts.

    Raises:
        TypeError: If ``provides`` is a single string.
        ValueError: If ``provides`` is empty or has an invalid path.
        ModuleDiscoveryError: If ``module_dir`` is invalid.
        AmbiguousModuleError: If several installed modules provide artifacts.
    """
    paths = validate_provides(provides)
    if module_dir is not None:
        if not module_dir.is_dir():
            raise ModuleDiscoveryError(f"Module directory not found: {module_dir}")
        if not provides_any(module_dir, paths):
            raise ModuleDiscoveryError(
                f"No {describe_paths(paths)} found in {module_dir}"
            )
        root = module_dir.resolve()
        return ArtifactLayer("module", root, None, f"module directory {root}")

    candidates = find_installed_modules(project_dir, provides=paths)
    if len(candidates) > 1:
        raise AmbiguousModuleError([layer.root for layer in candidates])
    return candidates[0] if candidates else None


def _module_entry_layer(
    project_dir: Path,
    entry: Any,
    provides: Sequence[str] | None,
    missing: list[str],
) -> ArtifactLayer | None:
    """Build a layer from one ``modules.json`` entry, or None if it has no artifacts."""
    if not isinstance(entry, dict):
        return None
    key, directory = entry.get("Key", ""), entry.get("Dir")
    # Nested modules (dotted keys) are internals of the modules we care about
    if not isinstance(key, str) or "." in key or not isinstance(directory, str):
        return None
    root = (project_dir / directory).resolve()
    if not root.is_dir():
        missing.append(f"'{key}' ({root})")
        return None
    if not provides_any(root, provides):
        return None
    version = entry.get("Version")
    version = version if isinstance(version, str) else None
    label = f"module '{key}'" if key else "root module"
    label += f" {version}" if version else ""
    return ArtifactLayer("module", root, version, f"{label} at {root}")
