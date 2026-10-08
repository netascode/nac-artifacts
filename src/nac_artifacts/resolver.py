# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Resolution of all artifact layers for a project."""

import logging
from collections.abc import Sequence
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .bundle import find_bundle_layers
from .exceptions import BundleError
from .layer import ArtifactLayer, validate_provides
from .module import find_installed_modules, find_module_layer
from .overrides import (
    DisableEntry,
    LayerDisables,
    Overrides,
    load_project_overrides,
)

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
                "%s compatibility '%s' not checked: several installed modules "
                "provide nac/ artifacts, cannot tell which one the bundle targets",
                bundle.label.capitalize(),
                specifier,
            )
            return
        module = installed[0] if installed else None

    if module is None or module.version is None:
        logger.info(
            "%s compatibility '%s' not checked: %s",
            bundle.label.capitalize(),
            specifier,
            "no installed module found"
            if module is None
            else f"version of {module.detail} is unknown",
        )
        return
    try:
        compatible = Version(module.version) in SpecifierSet(specifier)
    except (InvalidSpecifier, InvalidVersion) as e:
        raise BundleError(f"Cannot check {bundle.label} compatibility: {e}") from e
    if not compatible:
        raise BundleError(
            f"{bundle.label.capitalize()} requires module version '{specifier}' "
            f"but {module.detail} is version {module.version}"
        )


def resolve_artifact_layers(
    project_dir: Path,
    *,
    provides: Sequence[str],
    bundles: Sequence[Path] | None = None,
    module_dir: Path | None = None,
) -> list[ArtifactLayer]:
    """Resolve the bundle and module layers, highest priority first.

    All bundles are peers of one tier above the module. They may coexist as long
    as they provide different artifacts; the tools report any artifact that two
    of them provide.

    Args:
        project_dir: Project directory.
        provides: Paths relative to ``nac/`` of which a layer must have at
            least one to be used. Lets each tool select the layers relevant to it.
        bundles: Explicit bundle archives or directories (replace auto-detection).
        module_dir: Explicit module directory.

    Raises:
        TypeError: If ``provides`` is a single string.
        ValueError: If ``provides`` is empty or has an invalid path.
        ArtifactError: If a layer cannot be resolved or a bundle is incompatible
            with the module.
    """
    paths = validate_provides(provides)
    bundle_layers = find_bundle_layers(project_dir, provides=paths, bundles=bundles)
    module_layer = find_module_layer(project_dir, provides=paths, module_dir=module_dir)

    layers: list[ArtifactLayer] = []
    explicit = module_layer if module_dir is not None else None
    for bundle_layer in bundle_layers:
        _check_compatibility(project_dir, bundle_layer, explicit)
        layers.append(bundle_layer)
    if module_layer is not None:
        layers.append(module_layer)

    for layer in layers:
        logger.info("Artifact layer [%s]: %s", layer.label, layer.detail)
    return layers


def _tier(layer: ArtifactLayer) -> int:
    """Priority tier of a layer: bundles (peers) above the module."""
    return 0 if layer.origin == "bundle" else 1


def disables_by_layer(
    project: Overrides, layers: Sequence[ArtifactLayer]
) -> list[LayerDisables]:
    """Work out which disable entries apply to each layer.

    The project's entries and the entries of every layer in a *higher tier* apply
    to a layer. Bundles are peers, so a bundle's entries do not affect other
    bundles, only the module. A layer's own artifacts and the local layer are
    never affected.

    Args:
        project: Entries from ``.nac/overrides.yaml``.
        layers: Resolved layers, highest priority first.

    Returns:
        One result per layer, in the same order. Within each, entries from the
        highest priority source come first.
    """
    result: list[LayerDisables] = []
    for layer in layers:
        rules = [DisableEntry(p, "project") for p in project.rules]
        templates = [DisableEntry(p, "project") for p in project.templates]
        for above in layers:
            if _tier(above) >= _tier(layer):
                continue
            rules += [DisableEntry(p, above.label) for p in above.overrides.rules]
            templates += [
                DisableEntry(p, above.label) for p in above.overrides.templates
            ]
        result.append(LayerDisables(tuple(rules), tuple(templates)))
    return result


def layer_disables(
    project_dir: Path, layers: Sequence[ArtifactLayer]
) -> list[LayerDisables]:
    """Read the project's ``overrides.yaml`` and work out what applies to each layer.

    Args:
        project_dir: Project directory holding ``.nac/``.
        layers: Resolved layers, highest priority first.

    Raises:
        OverridesError: If the project's ``overrides.yaml`` is malformed.
    """
    layers = list(layers)
    for layer in layers:
        if not layer.overrides.is_empty:
            logger.info(
                "%s %s disables %d rule(s) and %d template pattern(s) of lower layers",
                layer.label.capitalize(),
                layer.version or "",
                len(layer.overrides.rules),
                len(layer.overrides.templates),
            )
    return disables_by_layer(load_project_overrides(project_dir), layers)
