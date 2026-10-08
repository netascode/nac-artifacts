# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

from importlib.metadata import version

from .bundle import find_bundle_layers
from .exceptions import (
    AmbiguousModuleError,
    ArtifactError,
    BundleError,
    ModuleDiscoveryError,
    OverridesError,
)
from .layer import ArtifactLayer, ArtifactOrigin
from .module import find_installed_modules, find_module_layer
from .overrides import (
    DisableEntry,
    DisableMatcher,
    LayerDisables,
    Overrides,
    load_overrides,
    load_project_overrides,
)
from .resolver import disables_by_layer, layer_disables, resolve_artifact_layers

__version__ = version("nac-artifacts")

__all__ = [
    "AmbiguousModuleError",
    "ArtifactError",
    "ArtifactLayer",
    "ArtifactOrigin",
    "BundleError",
    "DisableEntry",
    "DisableMatcher",
    "LayerDisables",
    "ModuleDiscoveryError",
    "Overrides",
    "OverridesError",
    "disables_by_layer",
    "find_bundle_layers",
    "find_installed_modules",
    "find_module_layer",
    "layer_disables",
    "load_overrides",
    "load_project_overrides",
    "resolve_artifact_layers",
    "__version__",
]
