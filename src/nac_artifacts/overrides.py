# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Disable and severity entries from ``overrides.yaml``.

Layers can add or replace artifacts of lower layers; ``overrides.yaml`` lets a
layer also *remove* some, or change the severity of rules:

.. code-block:: yaml

    disable:
      rules: ["102"]                     # by rule ID (exact)
      templates: ["config/*.robot"]      # by relative path (glob, ``*`` crosses ``/``)
    severity:
      rules:
        "205": LOW                       # by rule ID (exact): HIGH, MEDIUM or LOW

Entries are declarative: they state what must not be active, or how severe a
rule is. An entry that matches nothing is not an error.
"""

import fnmatch
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Generic, Protocol, TypeVar

from ruamel.yaml import YAML

from .constants import PROJECT_OVERRIDES_FILE
from .exceptions import OverridesError

logger = logging.getLogger(__name__)

# Supported top-level keys
TOP_LEVEL_KEYS = ("disable", "severity")
# Supported keys below ``disable:``
DISABLE_KEYS = ("rules", "templates")
# Supported keys below ``severity:``
SEVERITY_KEYS = ("rules",)
# Rule severities, highest first
SEVERITY_LEVELS = ("HIGH", "MEDIUM", "LOW")
# Kinds of artifacts entries refer to: ``rules`` (``disable.rules`` and
# ``severity.rules``, read by nac-validate) and ``templates`` (nac-test)
OVERRIDE_KINDS = ("rules", "templates")


def validate_kinds(kinds: Sequence[str] | None) -> tuple[str, ...] | None:
    """Check a ``kinds`` argument: None (every kind) or kinds from ``OVERRIDE_KINDS``.

    Raises:
        TypeError: If ``kinds`` is a single string.
        ValueError: If it contains an unknown kind.
    """
    if kinds is None:
        return None
    if isinstance(kinds, str):
        raise TypeError("kinds must be a sequence of kinds, not a single string")
    result = tuple(kinds)
    unknown = [k for k in result if k not in OVERRIDE_KINDS]
    if unknown:
        raise ValueError(
            f"Unknown override kind(s) {', '.join(map(repr, unknown))}; "
            f"supported: {', '.join(OVERRIDE_KINDS)}"
        )
    return result


@dataclass(frozen=True)
class Overrides:
    """The content of one ``overrides.yaml``.

    Attributes:
        rules: Rule IDs to disable.
        templates: Template paths or globs (relative, POSIX style) to disable.
        rule_severities: Pairs of rule ID and the severity (``HIGH``,
            ``MEDIUM`` or ``LOW``) to give the rule, in file order.
    """

    rules: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    rule_severities: tuple[tuple[str, str], ...] = ()

    @property
    def is_empty(self) -> bool:
        """Whether nothing is disabled and no severity is changed."""
        return not self.affects()

    def affects(self, kinds: Sequence[str] | None = None) -> bool:
        """Whether there are entries for any of ``kinds`` (None: any kind).

        Raises:
            TypeError, ValueError: If ``kinds`` is invalid, see
                :func:`validate_kinds`.
        """
        kinds = validate_kinds(kinds)
        counts = {
            "rules": len(self.rules) + len(self.rule_severities),
            "templates": len(self.templates),
        }
        return any(n for kind, n in counts.items() if kinds is None or kind in kinds)

    def summary(self) -> str:
        """Describe the entries for logs, e.g. ``2 rule(s) disabled``."""
        parts = []
        if self.rules:
            parts.append(f"{len(self.rules)} rule(s) disabled")
        if self.templates:
            parts.append(f"{len(self.templates)} template pattern(s) disabled")
        if self.rule_severities:
            parts.append(f"severity of {len(self.rule_severities)} rule(s) set")
        return ", ".join(parts) or "nothing"


@dataclass(frozen=True)
class DisableEntry:
    """One entry to disable, with the layer it came from.

    Attributes:
        pattern: Rule ID or template path/glob.
        source: ``"project"`` for ``nac/overrides.yaml``, otherwise the label of
            the bundle whose ``overrides.yaml`` it came from (``bundle acme``).
    """

    pattern: str
    source: str


@dataclass(frozen=True)
class SeverityEntry:
    """One rule severity to set, with the layer it came from.

    Attributes:
        pattern: Rule ID (exact).
        severity: ``HIGH``, ``MEDIUM`` or ``LOW``.
        source: ``"project"`` for ``nac/overrides.yaml``, otherwise the label of
            the bundle whose ``overrides.yaml`` it came from (``bundle acme``).
    """

    pattern: str
    severity: str
    source: str


@dataclass(frozen=True)
class LayerOverrides:
    """The disable and severity entries that apply to one layer.

    Entries from the project and from layers above apply; the highest priority
    source comes first.
    """

    rules: tuple[DisableEntry, ...] = ()
    templates: tuple[DisableEntry, ...] = ()
    rule_severities: tuple[SeverityEntry, ...] = ()


# Name before severity entries were added, kept for compatibility
LayerDisables = LayerOverrides


def _item(value: object, key: str, where: str) -> str:
    """Convert one entry to a string, rejecting anything that is not text or int.

    ``key`` is the dotted key the entry is under, for messages.
    """
    # YAML reads an unquoted 102 as an int; rule IDs are digit strings
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise OverridesError(f"'{key}' in {where} must contain strings, got {value!r}")
    text = str(value).strip()
    if not text:
        raise OverridesError(f"'{key}' in {where} contains an empty entry")
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


def _section(
    data: dict[Any, Any], key: str, keys: Sequence[str], where: str
) -> dict[Any, Any]:
    """Return the mapping below ``key`` (empty if missing), rejecting unknown keys."""
    section = data.get(key)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise OverridesError(f"'{key}' in {where} must be a mapping")
    unknown = sorted(str(k) for k in section if k not in keys)
    if unknown:
        raise OverridesError(
            f"Unknown key(s) {', '.join(unknown)} under '{key}' in {where}; "
            f"supported: {', '.join(keys)}"
        )
    return section


def _rule_severities(value: Any, where: str) -> tuple[tuple[str, str], ...]:
    """Validate ``severity.rules``: a mapping of rule ID to HIGH, MEDIUM or LOW."""
    key = "severity.rules"
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise OverridesError(
            f"'{key}' in {where} must be a mapping of rule ID to severity"
        )
    result: dict[str, str] = {}
    for rule, level in value.items():
        rule_id = _item(rule, key, where)
        if rule_id in result:
            # 102 and "102" are different YAML keys but the same rule
            raise OverridesError(
                f"Rule {rule_id!r} is listed twice in '{key}' in {where}"
            )
        severity = level.strip().upper() if isinstance(level, str) else None
        if severity not in SEVERITY_LEVELS:
            raise OverridesError(
                f"Invalid severity {level!r} for rule {rule_id!r} in '{key}' in "
                f"{where}; expected one of {', '.join(SEVERITY_LEVELS)}"
            )
        result[rule_id] = severity
    return tuple(result.items())


def _parse(data: Any, where: str) -> Overrides:
    if data is None:
        return Overrides()
    if not isinstance(data, dict):
        raise OverridesError(f"{where} must be a mapping")
    unknown = sorted(str(k) for k in data if k not in TOP_LEVEL_KEYS)
    if unknown:
        raise OverridesError(
            f"Unknown key(s) {', '.join(unknown)} in {where}; "
            f"supported: {', '.join(TOP_LEVEL_KEYS)}"
        )
    disable = _section(data, "disable", DISABLE_KEYS, where)
    lists: dict[str, list[str]] = {}
    for key in DISABLE_KEYS:
        value = disable.get(key)
        if value is None:
            lists[key] = []
        elif isinstance(value, list):
            lists[key] = [_item(v, f"disable.{key}", where) for v in value]
        else:
            raise OverridesError(f"'disable.{key}' in {where} must be a list")
    severity = _section(data, "severity", SEVERITY_KEYS, where)
    return Overrides(
        rules=_unique(lists["rules"]),
        templates=_unique([_template_pattern(t, where) for t in lists["templates"]]),
        rule_severities=_rule_severities(severity.get("rules"), where),
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
    """Read ``nac/overrides.yaml`` of a project, or return no overrides."""
    path = project_dir / PROJECT_OVERRIDES_FILE
    if not path.is_file():
        return Overrides()
    overrides = load_overrides(path, PROJECT_OVERRIDES_FILE.as_posix())
    logger.info("Project overrides: %s", overrides.summary())
    return overrides


class _Entry(Protocol):
    @property
    def pattern(self) -> str: ...


EntryT = TypeVar("EntryT", bound=_Entry)


class EntryMatcher(Generic[EntryT]):
    """Match values against entries and remember which entries matched.

    Works for :class:`DisableEntry` and :class:`SeverityEntry` alike.

    Args:
        entries: The entries to match against.
        glob: Treat patterns as globs (``fnmatch``; ``*`` also matches ``/``).
            Otherwise they must equal the value exactly.
    """

    def __init__(self, entries: Sequence[EntryT], *, glob: bool = False) -> None:
        self._entries = tuple(entries)
        self._glob = glob
        self._matched: set[EntryT] = set()

    def match(self, value: str) -> EntryT | None:
        """Return the first entry that matches ``value``, or None."""
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

    def unmatched(self) -> list[EntryT]:
        """Entries that have not matched any value so far."""
        return [e for e in self._entries if e not in self._matched]


# Name before severity entries were added, kept for compatibility
DisableMatcher = EntryMatcher
