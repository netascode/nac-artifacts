# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""The layer type returned by artifact discovery."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .constants import ARTIFACTS_DIRNAME, PROJECT_ENTRIES
from .overrides import Overrides

ArtifactOrigin = Literal["bundle", "module"]


@dataclass(frozen=True)
class ArtifactLayer:
    """A module or bundle that provides artifacts.

    A module holds its artifacts in its ``nac/`` directory, a bundle directly
    at its root (next to ``manifest.yaml``).

    Attributes:
        origin: Which layer this is (bundle or module).
        root: Module directory or bundle root.
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
        if self.origin == "bundle":
            return self.root
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
        ValueError: If it is empty or contains a path that is not relative
            (paths are relative to the directory holding a layer's artifacts).
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
                "(must be relative to the artifacts directory)"
            )
    return paths


def provides_any(artifacts_dir: Path, provides: Sequence[str] | None) -> bool:
    """Whether ``artifacts_dir`` contains at least one of the ``provides`` paths.

    With ``provides`` None, any entry counts except hidden ones and the bundles
    and overrides of a project, so that the ``nac/`` directory of a project
    that only holds those does not make the root module a layer.
    """
    if provides is None:
        if not artifacts_dir.is_dir():
            return False
        return any(
            not p.name.startswith(".") and p.name not in PROJECT_ENTRIES
            for p in artifacts_dir.iterdir()
        )
    return any((artifacts_dir / rel).exists() for rel in provides)


def describe_paths(
    provides: Sequence[str], *, prefix: str = f"{ARTIFACTS_DIRNAME}/"
) -> str:
    """Render ``provides`` for messages, e.g. ``nac/schema.yaml or nac/rules``.

    Bundles hold their artifacts at their root and pass an empty ``prefix``.
    """
    return " or ".join(f"{prefix}{rel}" for rel in provides)
