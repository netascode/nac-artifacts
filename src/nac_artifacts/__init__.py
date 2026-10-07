# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

from importlib.metadata import version

from .bundle import find_bundle_layer
from .exceptions import (
    AmbiguousModuleError,
    ArtifactError,
    BundleError,
    ModuleDiscoveryError,
)
from .layer import ArtifactLayer, ArtifactOrigin
from .module import find_installed_modules, find_module_layer
from .resolver import resolve_artifact_layers

__version__ = version("nac-artifacts")

__all__ = [
    "AmbiguousModuleError",
    "ArtifactError",
    "ArtifactLayer",
    "ArtifactOrigin",
    "BundleError",
    "ModuleDiscoveryError",
    "find_bundle_layer",
    "find_installed_modules",
    "find_module_layer",
    "resolve_artifact_layers",
    "__version__",
]
