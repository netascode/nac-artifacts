# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Unit tests for nac_artifacts.overrides module.

Tests verify that ``overrides.yaml`` is parsed and validated strictly in its
structure, that entries matching nothing are never an error, and that the
matcher reports which entries were used.
"""

import logging
from pathlib import Path

import pytest

from nac_artifacts import (
    DisableEntry,
    DisableMatcher,
    Overrides,
    OverridesError,
    load_overrides,
    load_project_overrides,
)
from nac_artifacts.testing import overrides_yaml, write_files


def parse(tmp_path: Path, text: str, description: str | None = None) -> Overrides:
    path = tmp_path / "overrides.yaml"
    path.write_text(text)
    return load_overrides(path, description)


class TestParsing:
    """Tests for reading a valid overrides.yaml."""

    def test_rules_and_templates(self, tmp_path: Path) -> None:
        """Should read both lists."""
        text = overrides_yaml(rules=["102", "103"], templates=["config/a.robot"])

        overrides = parse(tmp_path, text)

        assert overrides.rules == ("102", "103")
        assert overrides.templates == ("config/a.robot",)

    @pytest.mark.parametrize("text", ["", "# only a comment\n", "disable:\n", "{}\n"])
    def test_empty_content_disables_nothing(self, tmp_path: Path, text: str) -> None:
        """Should accept an empty file or an empty disable section."""
        assert parse(tmp_path, text).is_empty

    def test_missing_lists_are_empty(self, tmp_path: Path) -> None:
        """Should allow giving only one of the lists."""
        overrides = parse(tmp_path, "disable:\n  rules: ['1']\n")

        assert overrides.rules == ("1",)
        assert overrides.templates == ()

    def test_unquoted_numeric_rule_ids_are_accepted(self, tmp_path: Path) -> None:
        """Should turn 102 (read by YAML as a number) into the string '102'."""
        assert parse(tmp_path, "disable:\n  rules: [102, 103]\n").rules == (
            "102",
            "103",
        )

    def test_duplicates_are_removed_keeping_order(self, tmp_path: Path) -> None:
        """Should keep the first occurrence of repeated entries."""
        text = "disable:\n  rules: ['2', '1', '2']\n"

        assert parse(tmp_path, text).rules == ("2", "1")

    def test_entries_are_stripped_and_leading_dot_slash_removed(
        self, tmp_path: Path
    ) -> None:
        """Should normalize whitespace and a leading ./ in template paths."""
        text = "disable:\n  rules: [' 7 ']\n  templates: ['./config/a.robot']\n"

        overrides = parse(tmp_path, text)

        assert overrides.rules == ("7",)
        assert overrides.templates == ("config/a.robot",)

    def test_is_empty_property(self) -> None:
        """Should report whether anything is disabled."""
        assert Overrides().is_empty
        assert not Overrides(rules=("1",)).is_empty
        assert not Overrides(templates=("a",)).is_empty


class TestValidation:
    """Tests that structural mistakes are errors, never silently ignored."""

    @pytest.mark.parametrize("text", ["- a\n- b\n", "just text\n", "5\n"])
    def test_top_level_must_be_a_mapping(self, tmp_path: Path, text: str) -> None:
        """Should refuse anything but a mapping at the top level."""
        with pytest.raises(OverridesError, match="must be a mapping"):
            parse(tmp_path, text)

    def test_unknown_top_level_key(self, tmp_path: Path) -> None:
        """Should refuse a misspelled top-level key, e.g. disabel."""
        with pytest.raises(OverridesError, match=r"Unknown key\(s\) disabel"):
            parse(tmp_path, "disabel:\n  rules: ['1']\n")

    def test_unknown_key_under_disable(self, tmp_path: Path) -> None:
        """Should name the supported keys when one is not supported."""
        with pytest.raises(
            OverridesError, match=r"jinja_filters.*supported: rules, templ"
        ):
            parse(tmp_path, "disable:\n  jinja_filters: [x]\n")

    def test_disable_must_be_a_mapping(self, tmp_path: Path) -> None:
        """Should refuse a list where the disable mapping is expected."""
        with pytest.raises(OverridesError, match="'disable'.*must be a mapping"):
            parse(tmp_path, "disable: [rules]\n")

    @pytest.mark.parametrize("value", ["'102'", "{a: 1}", "102"])
    def test_lists_must_be_lists(self, tmp_path: Path, value: str) -> None:
        """Should refuse a scalar or mapping instead of a list."""
        with pytest.raises(OverridesError, match="'disable.rules'.*must be a list"):
            parse(tmp_path, f"disable:\n  rules: {value}\n")

    @pytest.mark.parametrize("item", ["true", "1.5", "[a]", "{a: 1}"])
    def test_items_must_be_text_or_integers(self, tmp_path: Path, item: str) -> None:
        """Should refuse booleans, floats and nested structures."""
        with pytest.raises(OverridesError, match="must contain strings"):
            parse(tmp_path, f"disable:\n  rules: [{item}]\n")

    @pytest.mark.parametrize("item", ["''", "'  '"])
    def test_empty_entries_are_rejected(self, tmp_path: Path, item: str) -> None:
        """Should refuse blank entries, which could be mistaken for everything."""
        with pytest.raises(OverridesError, match="empty entry"):
            parse(tmp_path, f"disable:\n  templates: [{item}]\n")

    @pytest.mark.parametrize(
        "pattern", ["/etc/passwd", "../x.robot", "a/../../x", "a\\\\b.robot"]
    )
    def test_template_paths_must_be_relative_posix(
        self, tmp_path: Path, pattern: str
    ) -> None:
        """Should refuse absolute paths, parent references and backslashes."""
        with pytest.raises(OverridesError, match="relative POSIX path"):
            parse(tmp_path, f"disable:\n  templates: ['{pattern}']\n")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """Should report YAML syntax errors."""
        with pytest.raises(OverridesError, match="Invalid"):
            parse(tmp_path, "disable: [unclosed\n")

    def test_missing_file(self, tmp_path: Path) -> None:
        """Should report an unreadable file as an overrides error."""
        with pytest.raises(OverridesError, match="Invalid"):
            load_overrides(tmp_path / "nope.yaml")

    def test_description_is_used_in_messages(self, tmp_path: Path) -> None:
        """Should name the file as the caller describes it, not by its cache path."""
        with pytest.raises(OverridesError, match="overrides.yaml in bundle acme.zip"):
            parse(tmp_path, "- x\n", "overrides.yaml in bundle acme.zip")

    def test_matching_nothing_is_not_an_error(self, tmp_path: Path) -> None:
        """Should accept entries without checking they exist anywhere."""
        text = overrides_yaml(rules=["999999"], templates=["does/not/exist.robot"])

        assert not parse(tmp_path, text).is_empty


class TestProjectOverrides:
    """Tests for .nac/overrides.yaml of a project."""

    def test_missing_file_means_no_overrides(self, tmp_path: Path) -> None:
        """Should return no overrides without a file."""
        assert load_project_overrides(tmp_path).is_empty

    def test_reads_the_file_from_the_nac_directory(self, tmp_path: Path) -> None:
        """Should read .nac/overrides.yaml."""
        write_files(tmp_path / ".nac", {"overrides.yaml": overrides_yaml(rules=["5"])})

        assert load_project_overrides(tmp_path).rules == ("5",)

    def test_errors_name_the_project_file(self, tmp_path: Path) -> None:
        """Should point at .nac/overrides.yaml in messages."""
        write_files(tmp_path / ".nac", {"overrides.yaml": "- x\n"})

        with pytest.raises(OverridesError, match=r"\.nac.overrides\.yaml"):
            load_project_overrides(tmp_path)

    def test_logs_what_the_project_disables(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log a summary at INFO level."""
        caplog.set_level(logging.INFO, logger="nac_artifacts")
        write_files(
            tmp_path / ".nac",
            {"overrides.yaml": overrides_yaml(rules=["1", "2"], templates=["a"])},
        )

        load_project_overrides(tmp_path)

        assert "disable 2 rule(s) and 1 template pattern(s)" in caplog.text


class TestDisableMatcher:
    """Tests for matching values and tracking which entries were used."""

    @staticmethod
    def entries(*patterns: str) -> list[DisableEntry]:
        return [DisableEntry(p, "project") for p in patterns]

    def test_exact_matching_by_default(self) -> None:
        """Should only match equal values, not substrings or patterns."""
        matcher = DisableMatcher(self.entries("102"))

        assert matcher.match("102") is not None
        assert matcher.match("1020") is None
        assert matcher.match("10") is None
        assert matcher.match("1*") is None

    def test_glob_matching(self) -> None:
        """Should match shell-style patterns when glob is enabled."""
        matcher = DisableMatcher(self.entries("config/*.robot"), glob=True)

        assert matcher.match("config/a.robot") is not None
        assert matcher.match("config/a.resource") is None

    def test_star_crosses_directories(self) -> None:
        """Should let * match across / so lib/* covers nested files."""
        matcher = DisableMatcher(self.entries("lib/*"), glob=True)

        assert matcher.match("lib/deep/Utils.py") is not None

    def test_glob_is_case_sensitive(self) -> None:
        """Should not treat different case as a match on any platform."""
        matcher = DisableMatcher(self.entries("Config/A.robot"), glob=True)

        assert matcher.match("config/a.robot") is None

    def test_first_matching_entry_wins(self) -> None:
        """Should return the highest priority entry (the first in the list)."""
        first = DisableEntry("a*", "project")
        second = DisableEntry("ab", "bundle")
        matcher = DisableMatcher([first, second], glob=True)

        assert matcher.match("ab") == first

    def test_unmatched_entries_are_reported(self) -> None:
        """Should tell which entries never matched anything."""
        matcher = DisableMatcher(self.entries("1", "2", "3"))
        matcher.match("2")

        assert [e.pattern for e in matcher.unmatched()] == ["1", "3"]

    def test_entry_shadowed_by_an_earlier_one_counts_as_unmatched(self) -> None:
        """Should only credit the entry that actually decided the match."""
        matcher = DisableMatcher(self.entries("a*", "ab"), glob=True)
        matcher.match("ab")

        assert [e.pattern for e in matcher.unmatched()] == ["ab"]

    def test_no_entries(self) -> None:
        """Should never match and report nothing unmatched."""
        matcher = DisableMatcher([])

        assert matcher.match("anything") is None
        assert matcher.unmatched() == []
