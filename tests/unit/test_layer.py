# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Unit tests for nac_artifacts.layer module."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nac_artifacts import ArtifactLayer
from nac_artifacts.layer import describe_paths, provides_any, validate_provides


class TestArtifactLayer:
    """Tests for the ArtifactLayer type."""

    def test_nac_dir_is_below_root(self, tmp_path: Path) -> None:
        """Should expose <root>/nac as the artifact directory."""
        layer = ArtifactLayer("module", tmp_path)

        assert layer.nac_dir == tmp_path / "nac"

    def test_manifest_defaults_to_empty(self, tmp_path: Path) -> None:
        """Should have an empty manifest unless one is given (modules have none)."""
        assert ArtifactLayer("module", tmp_path).manifest == {}

    def test_manifest_does_not_affect_equality(self, tmp_path: Path) -> None:
        """Should compare layers by origin, root, version and detail only."""
        a = ArtifactLayer("bundle", tmp_path, "1.0.0", "x", {"name": "a"})
        b = ArtifactLayer("bundle", tmp_path, "1.0.0", "x", {"name": "b"})

        assert a == b

    def test_layer_is_immutable(self, tmp_path: Path) -> None:
        """Should not allow changing a resolved layer."""
        layer = ArtifactLayer("module", tmp_path)

        with pytest.raises(FrozenInstanceError):
            layer.version = "2.0.0"  # ty: ignore[invalid-assignment]


class TestProvidesHelpers:
    """Tests for the helpers that match layers against requested paths."""

    def test_provides_any_with_existing_path(self, tmp_path: Path) -> None:
        """Should be true when one of the paths exists below nac/."""
        (tmp_path / "nac/rules").mkdir(parents=True)

        assert provides_any(tmp_path, ("schema.yaml", "rules"))

    def test_provides_any_without_matching_path(self, tmp_path: Path) -> None:
        """Should be false when none of the paths exist below nac/."""
        (tmp_path / "nac/tests").mkdir(parents=True)

        assert not provides_any(tmp_path, ("schema.yaml", "rules"))

    def test_provides_any_without_nac_dir(self, tmp_path: Path) -> None:
        """Should be false for a directory without nac/."""
        assert not provides_any(tmp_path, ("schema.yaml",))

    def test_describe_paths(self) -> None:
        """Should render the requested paths with the nac/ prefix."""
        assert (
            describe_paths(("schema.yaml", "rules")) == "nac/schema.yaml or nac/rules"
        )


class TestValidateProvides:
    """Tests for the validation of requested artifact paths."""

    def test_returns_a_tuple_of_the_paths(self) -> None:
        """Should accept lists and return them as a tuple."""
        assert validate_provides(["schema.yaml", "tests/templates"]) == (
            "schema.yaml",
            "tests/templates",
        )

    def test_single_string_is_rejected(self) -> None:
        """Should refuse a string, which would be split into characters."""
        with pytest.raises(TypeError, match="not a single string"):
            validate_provides("rules")

    def test_empty_is_rejected(self) -> None:
        """Should refuse an empty sequence."""
        with pytest.raises(ValueError, match="at least one"):
            validate_provides([])

    @pytest.mark.parametrize("path", ["", ".", "/abs", "../up", "a/../../up"])
    def test_invalid_paths_are_rejected(self, path: str) -> None:
        """Should refuse empty, absolute and parent-relative paths."""
        with pytest.raises(ValueError, match="Invalid path"):
            validate_provides([path])


class TestProvidesAnyWithoutPaths:
    """Tests for the any-nac-directory mode used to find installed modules."""

    def test_nac_directory_counts(self, tmp_path: Path) -> None:
        """Should be true for any nac/ directory when no paths are given."""
        (tmp_path / "nac").mkdir()

        assert provides_any(tmp_path, None)

    def test_missing_nac_directory_does_not_count(self, tmp_path: Path) -> None:
        """Should be false when there is no nac/ directory."""
        assert not provides_any(tmp_path, None)
