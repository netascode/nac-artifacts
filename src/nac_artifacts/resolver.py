# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Resolution of all artifact layers for a project."""

import logging
from collections.abc import Sequence
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .bundle import find_bundle_layer
from .exceptions import BundleError
from .layer import ArtifactLayer, validate_provides
from .module import find_installed_modules, find_module_layer

logger = logging.getLogger(__name__)


def _check_compatibility(
    project_dir: Path, bundle: ArtifactLayer, explicit_module: ArtifactLayer | None
) -> None:
    """Fail if the bundle declares a module version range the module does not meet.

    The module is the one installed module that ships a ``nac/`` directory,
    whatever artifacts the caller asked for. If the module cannot be determined
    or has no version (local and git sources), the check is skipped and the
    reason is logged.
    """
    declared = bundle.manifest.get("module")
    specifier = declared.get("versions") if isinstance(declared, dict) else None
    if not specifier:
        return

    if explicit_module is not None:
        module: ArtifactLayer | None = explicit_module
    else:
        installed = find_installed_modules(project_dir)
        if len(installed) > 1:
            logger.warning(
                "Bundle compatibility '%s' not checked: several installed modules "
                "provide nac/ artifacts, cannot tell which one the bundle targets",
                specifier,
            )
            return
        module = installed[0] if installed else None

    if module is None or module.version is None:
        logger.info(
            "Bundle compatibility '%s' not checked: %s",
            specifier,
            "no installed module found"
            if module is None
            else f"version of {module.detail} is unknown",
        )
        return
    try:
        compatible = Version(module.version) in SpecifierSet(specifier)
    except (InvalidSpecifier, InvalidVersion) as e:
        raise BundleError(f"Cannot check bundle compatibility: {e}") from e
    if not compatible:
        raise BundleError(
            f"Bundle requires module version '{specifier}' "
            f"but {module.detail} is version {module.version}"
        )


def resolve_artifact_layers(
    project_dir: Path,
    *,
    provides: Sequence[str],
    bundle: Path | None = None,
    module_dir: Path | None = None,
) -> list[ArtifactLayer]:
    """Resolve the bundle and module layers, highest priority first.

    Args:
        project_dir: Project directory.
        provides: Paths relative to ``nac/`` of which a layer must have at
            least one to be used. Lets each tool select the layers relevant to it.
        bundle: Explicit bundle archive or directory.
        module_dir: Explicit module directory.

    Raises:
        TypeError: If ``provides`` is a single string.
        ValueError: If ``provides`` is empty or has an invalid path.
        ArtifactError: If a layer cannot be resolved or a bundle is incompatible
            with the module.
    """
    paths = validate_provides(provides)
    bundle_layer = find_bundle_layer(project_dir, provides=paths, bundle=bundle)
    module_layer = find_module_layer(project_dir, provides=paths, module_dir=module_dir)

    layers: list[ArtifactLayer] = []
    if bundle_layer is not None:
        explicit = module_layer if module_dir is not None else None
        _check_compatibility(project_dir, bundle_layer, explicit)
        layers.append(bundle_layer)
    if module_layer is not None:
        layers.append(module_layer)

    for layer in layers:
        logger.info("Artifact layer [%s]: %s", layer.origin, layer.detail)
    return layers
