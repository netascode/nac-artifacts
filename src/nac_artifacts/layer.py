# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""The layer type returned by artifact discovery."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .constants import ARTIFACTS_DIRNAME
from .overrides import Overrides

ArtifactOrigin = Literal["bundle", "module"]


@dataclass(frozen=True)
class ArtifactLayer:
    """A module or bundle that provides artifacts below its ``nac/`` directory.

    Attributes:
        origin: Which layer this is (bundle or module).
        root: Directory containing the ``nac/`` directory.
        version: Module version or bundle manifest version, if known.
        detail: Human-readable description of where the layer came from.
        manifest: Parsed bundle ``manifest.yaml`` (empty for modules).
        overrides: Entries from the bundle's ``overrides.yaml`` (none for modules).
    """

    origin: ArtifactOrigin
    root: Path
    version: str | None = None
    detail: str = ""
    manifest: Mapping[str, Any] = field(default_factory=dict, compare=False)
    overrides: Overrides = field(default_factory=Overrides, compare=False)

    @property
    def label(self) -> str:
        """Short name for messages, e.g. ``module`` or ``bundle acme-base``."""
        if self.origin == "bundle":
            return f"bundle {self.manifest.get('name', '?')}"
        return self.origin

    @property
    def nac_dir(self) -> Path:
        """Directory holding the artifacts of this layer."""
        return self.root / ARTIFACTS_DIRNAME


def _is_relative_path(path: object) -> bool:
    """Whether ``path`` is a non-empty relative string without ``..`` parts."""
    if not isinstance(path, str):  # callers may not respect the type hints
        return False
    pure = PurePosixPath(path)
    return bool(pure.parts) and not pure.is_absolute() and ".." not in pure.parts


def validate_provides(provides: Sequence[str]) -> tuple[str, ...]:
    """Check the ``provides`` argument of the public functions.

    Raises:
        TypeError: If ``provides`` is a single string (which would be iterated
            character by character).
        ValueError: If it is empty or contains a path that is not relative to
            the ``nac/`` directory.
    """
    if isinstance(provides, str):
        raise TypeError("provides must be a sequence of paths, not a single string")
    paths = tuple(provides)
    if not paths:
        raise ValueError("provides must contain at least one path")
    for rel in paths:
        if not _is_relative_path(rel):
            raise ValueError(
                f"Invalid path in provides: {rel!r} "
                f"(must be relative to {ARTIFACTS_DIRNAME}/)"
            )
    return paths


def provides_any(root: Path, provides: Sequence[str] | None) -> bool:
    """Whether ``root/nac/`` contains at least one of the ``provides`` paths.

    With ``provides`` None, any ``nac/`` directory counts.
    """
    nac_dir = root / ARTIFACTS_DIRNAME
    if provides is None:
        return nac_dir.is_dir()
    return any((nac_dir / rel).exists() for rel in provides)


def describe_paths(provides: Sequence[str]) -> str:
    """Render ``provides`` for messages, e.g. ``nac/schema.yaml or nac/rules``."""
    return " or ".join(f"{ARTIFACTS_DIRNAME}/{rel}" for rel in provides)
