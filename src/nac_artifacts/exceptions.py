# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Exceptions raised when artifacts cannot be resolved."""

from collections.abc import Sequence
from pathlib import Path

from .constants import ARTIFACTS_DIRNAME


class ArtifactError(Exception):
    """Raised when packaged artifacts (module or bundle) cannot be resolved."""


class ModuleDiscoveryError(ArtifactError):
    """Raised when the module-embedded artifacts cannot be resolved."""


class BundleError(ArtifactError):
    """Raised when an artifact bundle is invalid or incompatible."""


class AmbiguousModuleError(ModuleDiscoveryError):
    """Raised when several installed modules provide the requested artifacts.

    Attributes:
        candidates: Root directories of the matching modules.
    """

    def __init__(self, candidates: Sequence[Path]):
        self.candidates = tuple(candidates)
        found = ", ".join(sorted(str(p) for p in self.candidates))
        super().__init__(
            f"Multiple installed modules provide {ARTIFACTS_DIRNAME}/ artifacts: "
            f"{found}. Select one explicitly."
        )
