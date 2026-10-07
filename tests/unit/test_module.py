# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Unit tests for nac_artifacts.module module.

Tests verify discovery of artifacts embedded in installed Terraform modules
through the modules.json install manifest.
"""

import json
import logging
from pathlib import Path

import pytest

from nac_artifacts import (
    AmbiguousModuleError,
    ArtifactLayer,
    ModuleDiscoveryError,
    find_installed_modules,
    find_module_layer,
)
from tests.unit.helpers import (
    install_module,
    module_entry,
    resolve_artifacts,
    write_artifacts,
    write_modules_json,
)


def origins(layers: list[ArtifactLayer]) -> list[str]:
    """Return the origin of each layer, highest priority first."""
    return [layer.origin for layer in layers]


class TestModuleSource:
    """Tests for module discovery through Terraform's modules.json."""

    def test_no_manifest_means_no_module_layer(self, project: Path) -> None:
        """Should skip the module layer when terraform init was never run."""
        assert origins(resolve_artifacts(project)) == []

    def test_registry_style_module(self, project: Path) -> None:
        """Should use a module installed under .terraform/modules with its version."""
        install_module(project, "nxos", version="0.3.0", rules={"1": "rule"})

        layers = resolve_artifacts(project)

        assert origins(layers) == ["module"]
        assert layers[0].version == "0.3.0"
        assert (layers[0].nac_dir / "schema.yaml").is_file()
        assert (layers[0].nac_dir / "rules").is_dir()

    def test_local_path_module_outside_project(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should follow a relative Dir pointing outside the project."""
        write_artifacts(tmp_path / "sibling-module")
        write_modules_json(project, [module_entry("m", "../sibling-module")])

        layers = resolve_artifacts(project)

        assert layers[-1].origin == "module"
        assert layers[-1].version is None

    def test_root_module_itself(self, project: Path) -> None:
        """Should use artifacts in the root module (running inside a module repo)."""
        write_artifacts(project)
        write_modules_json(project, [])

        assert resolve_artifacts(project)[-1].origin == "module"

    def test_subdirectory_source(self, project: Path) -> None:
        """Should use a module installed from a // subdirectory source."""
        write_artifacts(project / ".terraform/modules/g/sub")
        write_modules_json(project, [module_entry("g", ".terraform/modules/g/sub")])

        assert resolve_artifacts(project)[-1].origin == "module"

    def test_nested_modules_ignored(self, project: Path) -> None:
        """Should ignore modules nested inside other modules (dotted keys)."""
        write_artifacts(project / ".terraform/modules/a.b")
        write_modules_json(project, [module_entry("a.b", ".terraform/modules/a.b")])

        assert origins(resolve_artifacts(project)) == []

    def test_module_without_artifacts_ignored(self, project: Path) -> None:
        """Should ignore installed modules that ship no nac/ directory."""
        (project / ".terraform/modules/plain").mkdir(parents=True)
        write_modules_json(project, [module_entry("plain", ".terraform/modules/plain")])

        assert origins(resolve_artifacts(project)) == []

    def test_ambiguous_modules_raise(self, project: Path) -> None:
        """Should raise an error listing the candidates when several modules match."""
        for key in ("a", "b"):
            write_artifacts(project / f".terraform/modules/{key}")
        write_modules_json(
            project, [module_entry(k, f".terraform/modules/{k}") for k in ("a", "b")]
        )

        with pytest.raises(AmbiguousModuleError, match="Multiple") as exc_info:
            resolve_artifacts(project)

        assert len(exc_info.value.candidates) == 2
        assert "--module-dir" not in str(exc_info.value)

    def test_same_directory_listed_twice_is_not_ambiguous(self, project: Path) -> None:
        """Should treat two entries resolving to one directory as one module."""
        write_artifacts(project / "shared")
        write_modules_json(
            project, [module_entry("a", "shared"), module_entry("b", "./shared")]
        )

        assert resolve_artifacts(project)[-1].origin == "module"

    def test_missing_dir_warns_when_nothing_else_is_found(
        self, project: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should warn about a stale module directory if no module was found."""
        caplog.set_level(logging.WARNING, logger="nac_artifacts")
        write_modules_json(project, [module_entry("gone", ".terraform/modules/gone")])

        assert origins(resolve_artifacts(project)) == []
        assert "terraform/tofu init" in caplog.text
        assert "'gone'" in caplog.text

    def test_missing_dir_is_quiet_when_a_module_was_found(
        self, project: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should not warn about unrelated stale entries if a module was found."""
        caplog.set_level(logging.WARNING, logger="nac_artifacts")
        write_artifacts(project / ".terraform/modules/a")
        write_modules_json(
            project,
            [
                module_entry("a", ".terraform/modules/a"),
                module_entry("gone", ".terraform/modules/gone"),
            ],
        )

        assert origins(resolve_artifacts(project)) == ["module"]
        assert caplog.text == ""

    def test_tf_data_dir_relative(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should read the manifest from a relative TF_DATA_DIR."""
        monkeypatch.setenv("TF_DATA_DIR", "custom")
        write_artifacts(project / "custom/modules/m")
        write_modules_json(
            project, [module_entry("m", "custom/modules/m")], data_dir="custom"
        )

        assert resolve_artifacts(project)[-1].origin == "module"

    def test_tf_data_dir_absolute(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should read the manifest from an absolute TF_DATA_DIR."""
        data_dir = tmp_path / "elsewhere"
        monkeypatch.setenv("TF_DATA_DIR", str(data_dir))
        write_artifacts(data_dir / "modules/m")
        write_modules_json(
            project,
            [module_entry("m", str(data_dir / "modules/m"))],
            data_dir=str(data_dir),
        )

        assert resolve_artifacts(project)[-1].origin == "module"

    def test_explicit_module_dir(self, project: Path, tmp_path: Path) -> None:
        """Should use --module-dir without reading modules.json."""
        write_artifacts(tmp_path / "mod")

        layers = resolve_artifacts(project, module_dir=tmp_path / "mod")

        assert layers[-1].origin == "module"

    def test_explicit_module_dir_missing(self, project: Path, tmp_path: Path) -> None:
        """Should raise when --module-dir does not exist."""
        with pytest.raises(ModuleDiscoveryError, match="not found"):
            resolve_artifacts(project, module_dir=tmp_path / "nope")

    def test_explicit_module_dir_without_artifacts(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should raise when --module-dir has neither schema nor rules."""
        (tmp_path / "empty").mkdir()

        with pytest.raises(ModuleDiscoveryError, match="No nac/"):
            resolve_artifacts(project, module_dir=tmp_path / "empty")


class TestModulesManifestParsing:
    """Tests that unexpected modules.json content never breaks validation."""

    @pytest.mark.parametrize(
        "content", ["{not json", '{"Modules": "nope"}', '{"Other": []}', "[]", "null"]
    )
    def test_unexpected_manifest_is_skipped(self, project: Path, content: str) -> None:
        """Should ignore a manifest that is corrupt or has an unexpected shape."""
        manifest = project / ".terraform/modules/modules.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(content)

        assert origins(resolve_artifacts(project)) == []

    @pytest.mark.parametrize(
        "entry",
        [
            "string",
            5,
            None,
            {"Key": 5, "Dir": "x"},
            {"Key": "k"},
            {"Key": "k", "Dir": 3},
        ],
    )
    def test_malformed_entries_are_skipped(self, project: Path, entry: object) -> None:
        """Should ignore entries that are not objects or lack a string Key/Dir."""
        manifest = project / ".terraform/modules/modules.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"Modules": [entry]}))

        assert origins(resolve_artifacts(project)) == []

    def test_non_string_version_is_ignored(self, project: Path) -> None:
        """Should treat a non-string Version as unknown."""
        write_artifacts(project / "m")
        manifest = project / ".terraform/modules/modules.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"Modules": [{"Key": "m", "Dir": "m", "Version": 3}]})
        )

        assert resolve_artifacts(project)[-1].version is None


class TestExplicitModuleDir:
    """Tests for module directories given explicitly."""

    def test_relative_module_dir_is_resolved(self, project: Path) -> None:
        """Should return an absolute root so later directory changes are harmless."""
        write_artifacts(project / "mod")

        layer = find_module_layer(
            project, provides=("schema.yaml",), module_dir=Path("mod")
        )

        assert layer is not None
        assert layer.root.is_absolute()
        assert layer.root == (project / "mod").resolve()


class TestFindModuleLayer:
    """Tests for find_module_layer() used directly."""

    def test_returns_none_without_manifest(self, project: Path) -> None:
        """Should return None when no module is installed."""
        assert find_module_layer(project, provides=("schema.yaml",)) is None

    def test_returns_the_module_layer(self, project: Path) -> None:
        """Should return the module providing the requested paths."""
        module_dir = install_module(project, version="1.2.3")

        layer = find_module_layer(project, provides=("schema.yaml",))

        assert layer is not None
        assert layer.origin == "module"
        assert layer.version == "1.2.3"
        assert layer.root == module_dir.resolve()

    def test_string_provides_is_rejected(self, project: Path) -> None:
        """Should refuse a plain string, which would be iterated per character."""
        with pytest.raises(TypeError, match="not a single string"):
            find_module_layer(project, provides="rules")

    def test_empty_provides_is_rejected(self, project: Path) -> None:
        """Should refuse an empty list of paths."""
        with pytest.raises(ValueError, match="at least one"):
            find_module_layer(project, provides=())

    @pytest.mark.parametrize("path", ["", "/etc/passwd", "../x", "a/../../x"])
    def test_invalid_provides_path_is_rejected(self, project: Path, path: str) -> None:
        """Should refuse empty, absolute and parent-relative paths."""
        with pytest.raises(ValueError, match="Invalid path"):
            find_module_layer(project, provides=(path,))

    def test_non_string_provides_item_is_rejected(self, project: Path) -> None:
        """Should refuse items that are not strings."""
        with pytest.raises(ValueError, match="Invalid path"):
            find_module_layer(project, provides=(5,))  # ty: ignore[invalid-argument-type]


class TestFindInstalledModules:
    """Tests for find_installed_modules()."""

    def test_any_nac_directory_counts_without_provides(self, project: Path) -> None:
        """Should list modules with any nac/ directory when no paths are given."""
        module_dir = install_module(project, schema=False)
        (module_dir / "nac/tests/templates").mkdir(parents=True)

        assert origins(find_installed_modules(project)) == ["module"]
        assert find_installed_modules(project, provides=("schema.yaml",)) == []

    def test_lists_every_matching_module(self, project: Path) -> None:
        """Should return all modules instead of raising on ambiguity."""
        for key in ("a", "b"):
            write_artifacts(project / f".terraform/modules/{key}")
        write_modules_json(
            project, [module_entry(k, f".terraform/modules/{k}") for k in ("a", "b")]
        )

        assert len(find_installed_modules(project)) == 2
