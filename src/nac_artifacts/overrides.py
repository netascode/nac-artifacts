# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Disable entries from ``overrides.yaml``.

Layers can add or replace artifacts of lower layers; ``overrides.yaml`` lets a
layer also *remove* some:

.. code-block:: yaml

    disable:
      rules: ["102"]                     # by rule ID (exact)
      templates: ["config/*.robot"]      # by relative path (glob, ``*`` crosses ``/``)

Entries are declarative: they state what must not be active. An entry that
matches nothing is not an error, since the condition already holds.
"""

import fnmatch
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ruamel.yaml import YAML

from .constants import BUNDLE_DIR, OVERRIDES_FILENAME
from .exceptions import OverridesError

logger = logging.getLogger(__name__)

# Supported keys below ``disable:``
DISABLE_KEYS = ("rules", "templates")


@dataclass(frozen=True)
class Overrides:
    """The content of one ``overrides.yaml``.

    Attributes:
        rules: Rule IDs to disable.
        templates: Template paths or globs (relative, POSIX style) to disable.
    """

    rules: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Whether nothing is disabled."""
        return not self.rules and not self.templates


@dataclass(frozen=True)
class DisableEntry:
    """One entry to disable, with the layer it came from.

    Attributes:
        pattern: Rule ID or template path/glob.
        source: ``"project"`` for ``.nac/overrides.yaml``, otherwise the label of
            the bundle whose ``overrides.yaml`` it came from (``bundle acme``).
    """

    pattern: str
    source: str


@dataclass(frozen=True)
class LayerDisables:
    """The disable entries that apply to one layer.

    Entries from the project and from layers above apply; the highest priority
    source comes first.
    """

    rules: tuple[DisableEntry, ...] = ()
    templates: tuple[DisableEntry, ...] = ()


def _item(value: object, key: str, where: str) -> str:
    """Convert one list item to a string, rejecting anything that is not text or int."""
    # YAML reads an unquoted 102 as an int; rule IDs are digit strings
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise OverridesError(
            f"'disable.{key}' in {where} must contain strings, got {value!r}"
        )
    text = str(value).strip()
    if not text:
        raise OverridesError(f"'disable.{key}' in {where} contains an empty entry")
    return text


def _template_pattern(text: str, where: str) -> str:
    pattern = text.removeprefix("./")
    pure = PurePosixPath(pattern)
    if pure.is_absolute() or ".." in pure.parts or "\\" in pattern:
        raise OverridesError(
            f"'disable.templates' entry {text!r} in {where} must be a relative "
            "POSIX path or glob without '..'"
        )
    return pattern


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _parse(data: Any, where: str) -> Overrides:
    if data is None:
        return Overrides()
    if not isinstance(data, dict):
        raise OverridesError(f"{where} must be a mapping")
    unknown = sorted(str(k) for k in data if k != "disable")
    if unknown:
        raise OverridesError(
            f"Unknown key(s) {', '.join(unknown)} in {where}; supported: disable"
        )
    disable = data.get("disable")
    if disable is None:
        return Overrides()
    if not isinstance(disable, dict):
        raise OverridesError(f"'disable' in {where} must be a mapping")
    unknown = sorted(str(k) for k in disable if k not in DISABLE_KEYS)
    if unknown:
        raise OverridesError(
            f"Unknown key(s) {', '.join(unknown)} under 'disable' in {where}; "
            f"supported: {', '.join(DISABLE_KEYS)}"
        )
    lists: dict[str, list[str]] = {}
    for key in DISABLE_KEYS:
        value = disable.get(key)
        if value is None:
            lists[key] = []
        elif isinstance(value, list):
            lists[key] = [_item(v, key, where) for v in value]
        else:
            raise OverridesError(f"'disable.{key}' in {where} must be a list")
    return Overrides(
        rules=_unique(lists["rules"]),
        templates=_unique([_template_pattern(t, where) for t in lists["templates"]]),
    )


def load_overrides(path: Path, description: str | None = None) -> Overrides:
    """Read and validate an ``overrides.yaml``.

    Args:
        path: The file to read.
        description: How to refer to the file in error messages (defaults to
            the path); useful when the path is inside a cache directory.

    Raises:
        OverridesError: If the file is unreadable or malformed. Unknown keys and
            wrongly typed values are errors; entries that match nothing are not.
    """
    where = description or str(path)
    try:
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise OverridesError(f"Invalid {where}: {e}") from e
    return _parse(data, where)


def load_project_overrides(project_dir: Path) -> Overrides:
    """Read ``.nac/overrides.yaml`` of a project, or return no overrides."""
    path = project_dir / BUNDLE_DIR / OVERRIDES_FILENAME
    if not path.is_file():
        return Overrides()
    overrides = load_overrides(path, f"{BUNDLE_DIR / OVERRIDES_FILENAME}")
    logger.info(
        "Project overrides disable %d rule(s) and %d template pattern(s)",
        len(overrides.rules),
        len(overrides.templates),
    )
    return overrides


class DisableMatcher:
    """Match values against disable entries and remember which entries matched.

    Args:
        entries: The entries to match against.
        glob: Treat patterns as globs (``fnmatch``; ``*`` also matches ``/``).
            Otherwise they must equal the value exactly.
    """

    def __init__(self, entries: Sequence[DisableEntry], *, glob: bool = False) -> None:
        self._entries = tuple(entries)
        self._glob = glob
        self._matched: set[DisableEntry] = set()

    def match(self, value: str) -> DisableEntry | None:
        """Return the first entry that disables ``value``, or None."""
        for entry in self._entries:
            hit = (
                fnmatch.fnmatchcase(value, entry.pattern)
                if self._glob
                else value == entry.pattern
            )
            if hit:
                self._matched.add(entry)
                return entry
        return None

    def unmatched(self) -> list[DisableEntry]:
        """Entries that have not matched any value so far."""
        return [e for e in self._entries if e not in self._matched]
