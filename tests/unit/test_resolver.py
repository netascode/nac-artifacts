# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Unit tests for nac_artifacts.resolver module.

Tests verify how bundle and module layers are combined, how callers select
layers through the paths they need, and bundle/module compatibility checks.
"""

import logging
from pathlib import Path
from typing import Any

import pytest

from nac_artifacts import (
    ArtifactLayer,
    ArtifactOrigin,
    BundleError,
    DisableEntry,
    ModuleDiscoveryError,
    Overrides,
    OverridesError,
    SeverityEntry,
    disables_by_layer,
    layer_disables,
    layer_overrides,
    overrides_by_layer,
)
from nac_artifacts.testing import overrides_yaml, write_files
from tests.unit.helpers import (
    bundle_files,
    install_module,
    make_zip,
    module_entry,
    resolve_artifacts,
    write_artifacts,
    write_modules_json,
)


def origins(layers: list[ArtifactLayer]) -> list[str]:
    """Return the origin of each layer, highest priority first."""
    return [layer.origin for layer in layers]


class TestBundleCompatibility:
    """Tests for the bundle manifest's declared module version range."""

    def test_compatible_module_version(self, project: Path, tmp_path: Path) -> None:
        """Should accept a module whose version satisfies the declared range."""
        install_module(project, version="0.3.1")
        files = bundle_files()
        files["manifest.yaml"] += "module:\n  versions: '>=0.3,<0.4'\n"

        layers = resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", files))

        assert origins(layers) == ["bundle", "module"]

    def test_incompatible_module_version(self, project: Path, tmp_path: Path) -> None:
        """Should raise when the module version is outside the declared range."""
        install_module(project, version="0.5.0")
        files = bundle_files()
        files["manifest.yaml"] += "module:\n  versions: '>=0.3,<0.4'\n"

        with pytest.raises(BundleError, match="requires module version"):
            resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", files))

    def test_invalid_version_specifier(self, project: Path, tmp_path: Path) -> None:
        """Should raise when the declared range cannot be parsed."""
        install_module(project, version="1.0.0")
        files = bundle_files()
        files["manifest.yaml"] += "module:\n  versions: 'not a specifier'\n"

        with pytest.raises(BundleError, match="compatibility"):
            resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", files))

    def test_skipped_when_module_version_unknown(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should not check compatibility for local or git modules (no version)."""
        install_module(project)
        files = bundle_files()
        files["manifest.yaml"] += "module:\n  versions: '>=9'\n"

        layers = resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", files))

        assert layers[-1].origin == "module"


class TestProvides:
    """Tests that each tool selects layers through the paths it needs."""

    def test_nac_dir_property(self, project: Path) -> None:
        """Should expose <root>/nac as the layer's artifact directory."""
        module_dir = install_module(project)

        layer = resolve_artifacts(project)[0]

        assert layer.nac_dir == module_dir.resolve() / "nac"

    def test_module_selected_by_requested_paths(self, project: Path) -> None:
        """Should use a module only if it has one of the requested paths."""
        module_dir = install_module(project, schema=False)
        (module_dir / "nac/tests/templates").mkdir(parents=True)

        assert resolve_artifacts(project) == []
        layers = resolve_artifacts(project, provides=("tests/templates",))
        assert origins(layers) == ["module"]

    def test_ambiguity_depends_on_requested_paths(self, project: Path) -> None:
        """Should only count modules relevant to the tool as ambiguous."""
        write_artifacts(project / ".terraform/modules/a")
        other = project / ".terraform/modules/b"
        (other / "nac/tests/templates").mkdir(parents=True)
        write_modules_json(
            project,
            [
                module_entry("a", ".terraform/modules/a"),
                module_entry("b", ".terraform/modules/b"),
            ],
        )

        assert origins(resolve_artifacts(project)) == ["module"]
        with pytest.raises(ModuleDiscoveryError, match="Multiple"):
            resolve_artifacts(project, provides=("schema.yaml", "tests/templates"))

    def test_bundle_selected_by_requested_paths(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should accept a tests-only bundle when the caller asks for tests."""
        files = {
            "manifest.yaml": "name: tests-only\n",
            "tests/templates/a.robot": "*** Test Cases ***\n",
        }
        archive = make_zip(tmp_path / "b.zip", files)

        layers = resolve_artifacts(
            project, provides=("tests/templates",), bundle=archive
        )

        assert origins(layers) == ["bundle"]
        assert (layers[0].nac_dir / "tests/templates/a.robot").is_file()

    def test_error_message_names_requested_paths(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should tell the user which paths were expected."""
        (tmp_path / "empty").mkdir()

        with pytest.raises(ModuleDiscoveryError, match="nac/tests/templates"):
            resolve_artifacts(
                project,
                provides=("tests/templates",),
                module_dir=tmp_path / "empty",
            )


class TestCompatibilityTarget:
    """Tests for which installed module a bundle's version range is checked against."""

    @staticmethod
    def bundle_with_range(tmp_path: Path, versions: str = "<1") -> Path:
        files = bundle_files(manifest_extra=f"module:\n  versions: '{versions}'\n")
        return make_zip(tmp_path / "b.zip", files)

    def test_checked_even_if_module_ships_other_artifacts(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should compare against the installed module whatever paths were asked for."""
        module_dir = install_module(project, schema=False, version="9.0.0")
        (module_dir / "nac/tests/templates").mkdir(parents=True)

        with pytest.raises(BundleError, match="requires module version"):
            resolve_artifacts(project, bundle=self.bundle_with_range(tmp_path))

    def test_several_installed_modules_warn_and_skip(
        self, project: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should warn instead of guessing when the target module is ambiguous."""
        caplog.set_level(logging.WARNING, logger="nac_artifacts")
        write_artifacts(project / ".terraform/modules/a")
        (project / ".terraform/modules/b/nac/tests/templates").mkdir(parents=True)
        write_modules_json(
            project,
            [
                module_entry("a", ".terraform/modules/a", "9.0.0"),
                module_entry("b", ".terraform/modules/b", "9.0.0"),
            ],
        )

        layers = resolve_artifacts(project, bundle=self.bundle_with_range(tmp_path))

        assert [layer.origin for layer in layers] == ["bundle", "module"]
        assert "cannot tell which one the bundle targets" in caplog.text

    def test_unknown_module_version_is_logged(
        self, project: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should say why the check was skipped for local or git modules."""
        caplog.set_level(logging.INFO, logger="nac_artifacts")
        install_module(project)

        resolve_artifacts(project, bundle=self.bundle_with_range(tmp_path))

        assert "not checked" in caplog.text
        assert "version of" in caplog.text

    def test_no_installed_module_is_logged(
        self, project: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should say why the check was skipped when there is no module at all."""
        caplog.set_level(logging.INFO, logger="nac_artifacts")

        resolve_artifacts(project, bundle=self.bundle_with_range(tmp_path))

        assert "no installed module found" in caplog.text

    def test_explicit_module_dir_has_no_version(
        self, project: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should skip the check for --module-dir, whose version is unknown."""
        caplog.set_level(logging.INFO, logger="nac_artifacts")
        write_artifacts(tmp_path / "mod")

        layers = resolve_artifacts(
            project,
            bundle=self.bundle_with_range(tmp_path),
            module_dir=tmp_path / "mod",
        )

        assert [layer.origin for layer in layers] == ["bundle", "module"]
        assert "version of" in caplog.text

    def test_no_check_without_a_declared_range(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should not look at installed modules if the bundle declares no range."""
        install_module(project, version="9.0.0")
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        assert len(resolve_artifacts(project, bundle=archive)) == 2


class TestResolveValidation:
    """Tests for argument validation in resolve_artifact_layers()."""

    def test_string_provides_is_rejected(self, project: Path) -> None:
        """Should refuse a plain string instead of iterating its characters."""
        with pytest.raises(TypeError):
            resolve_artifacts(project, provides="rules")

    def test_empty_provides_is_rejected(self, project: Path) -> None:
        """Should refuse an empty list of paths."""
        with pytest.raises(ValueError, match="at least one"):
            resolve_artifacts(project, provides=())


class TestOverridesByLayer:
    """Tests for which disable entries apply to which layer."""

    @staticmethod
    def layer(
        origin: ArtifactOrigin, name: str = "acme", **disabled: tuple[Any, ...]
    ) -> ArtifactLayer:
        return ArtifactLayer(
            origin,
            Path("/x"),
            manifest={"name": name},
            overrides=Overrides(**disabled),
        )

    def test_project_entries_apply_to_every_layer(self) -> None:
        """Should apply the project's entries to the bundle and the module."""
        layers = [self.layer("bundle"), self.layer("module")]

        result = overrides_by_layer(Overrides(rules=("1",), templates=("a",)), layers)

        for applied in result:
            assert applied.rules == (DisableEntry("1", "project"),)
            assert applied.templates == (DisableEntry("a", "project"),)

    def test_bundle_entries_apply_only_to_layers_below(self) -> None:
        """Should apply a bundle's entries to the module but not to the bundle."""
        layers = [self.layer("bundle", rules=("7",)), self.layer("module")]

        bundle, module = overrides_by_layer(Overrides(), layers)

        assert bundle.rules == ()
        assert module.rules == (DisableEntry("7", "bundle acme"),)

    def test_project_entries_come_before_bundle_entries(self) -> None:
        """Should list the highest priority source first."""
        layers = [self.layer("bundle", rules=("7",)), self.layer("module")]

        _, module = overrides_by_layer(Overrides(rules=("1",)), layers)

        assert [(e.pattern, e.source) for e in module.rules] == [
            ("1", "project"),
            ("7", "bundle acme"),
        ]

    def test_bundles_are_peers_their_entries_do_not_affect_each_other(self) -> None:
        """Should apply each bundle's entries to the module only, not to a peer bundle."""
        layers = [
            self.layer("bundle", "a", rules=("1",)),
            self.layer("bundle", "b", rules=("2",)),
            self.layer("module"),
        ]

        a, b, module = overrides_by_layer(Overrides(), layers)

        assert a.rules == () and b.rules == ()
        assert [(e.pattern, e.source) for e in module.rules] == [
            ("1", "bundle a"),
            ("2", "bundle b"),
        ]

    def test_project_entries_reach_every_peer_bundle(self) -> None:
        """Should still apply the project's entries to all bundles."""
        layers = [self.layer("bundle", "a"), self.layer("bundle", "b")]

        a, b = overrides_by_layer(Overrides(rules=("9",)), layers)

        assert a.rules == b.rules == (DisableEntry("9", "project"),)

    def test_module_entries_are_never_applied_upwards(self) -> None:
        """Should not let a lower layer disable anything above it."""
        layers = [self.layer("bundle"), self.layer("module", rules=("9",))]

        bundle, _ = overrides_by_layer(Overrides(), layers)

        assert bundle.rules == ()

    def test_severities_follow_the_same_layering(self) -> None:
        """Should apply project severities everywhere and bundle ones below only."""
        layers = [
            self.layer("bundle", rule_severities=(("7", "MEDIUM"),)),
            self.layer("module"),
        ]

        bundle, module = overrides_by_layer(
            Overrides(rule_severities=(("7", "LOW"),)), layers
        )

        assert bundle.rule_severities == (SeverityEntry("7", "LOW", "project"),)
        assert module.rule_severities == (
            SeverityEntry("7", "LOW", "project"),
            SeverityEntry("7", "MEDIUM", "bundle acme"),
        )

    def test_peer_bundles_setting_different_severities_fail(self) -> None:
        """Should not let the order of peer bundles decide a severity."""
        layers = [
            self.layer("bundle", "a", rule_severities=(("7", "LOW"),)),
            self.layer("bundle", "b", rule_severities=(("7", "HIGH"),)),
            self.layer("module"),
        ]

        with pytest.raises(
            OverridesError,
            match=r"Bundle a and bundle b set different severities for rule '7' "
            r"\(LOW, HIGH\); set it in nac/overrides\.yaml",
        ):
            overrides_by_layer(Overrides(), layers)

    def test_project_decides_between_peer_bundles(self) -> None:
        """Should accept the conflict when the project sets the rule itself."""
        layers = [
            self.layer("bundle", "a", rule_severities=(("7", "LOW"),)),
            self.layer("bundle", "b", rule_severities=(("7", "HIGH"),)),
            self.layer("module"),
        ]

        *_, module = overrides_by_layer(
            Overrides(rule_severities=(("7", "MEDIUM"),)), layers
        )

        assert module.rule_severities[0] == SeverityEntry("7", "MEDIUM", "project")

    def test_peer_bundles_agreeing_on_a_severity_are_fine(self) -> None:
        """Should only fail for different severities."""
        layers = [
            self.layer("bundle", "a", rule_severities=(("7", "LOW"),)),
            self.layer("bundle", "b", rule_severities=(("7", "LOW"),)),
            self.layer("module"),
        ]

        *_, module = overrides_by_layer(Overrides(), layers)

        assert len(module.rule_severities) == 2

    def test_no_layers(self) -> None:
        """Should return nothing without layers."""
        assert overrides_by_layer(Overrides(rules=("1",)), []) == []

    def test_one_result_per_layer_in_order(self) -> None:
        """Should keep the result aligned with the layers."""
        layers = [self.layer("bundle"), self.layer("module")]

        assert len(overrides_by_layer(Overrides(), layers)) == 2


class TestLayerOverrides:
    """Tests for reading overrides from the project and from bundles together."""

    def test_reads_project_and_bundle_overrides(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should combine nac/overrides.yaml with a bundle's overrides.yaml."""
        install_module(project)
        write_files(project / "nac", {"overrides.yaml": overrides_yaml(rules=["1"])})
        archive = make_zip(
            tmp_path / "b.zip",
            bundle_files(extra={"overrides.yaml": overrides_yaml(rules=["2"])}),
        )
        layers = resolve_artifacts(project, bundle=archive)

        bundle, module = layer_overrides(project, layers)

        assert [e.pattern for e in bundle.rules] == ["1"]
        assert [(e.pattern, e.source) for e in module.rules] == [
            ("1", "project"),
            ("2", "bundle acme"),
        ]

    def test_without_any_overrides(self, project: Path) -> None:
        """Should return empty results when no overrides exist."""
        install_module(project)

        (module,) = layer_overrides(project, resolve_artifacts(project))

        assert module.rules == () and module.templates == ()

    def test_logs_what_a_bundle_disables(
        self, project: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log a one-line summary so a bundle's effect is not hidden."""
        caplog.set_level(logging.INFO, logger="nac_artifacts")
        install_module(project)
        archive = make_zip(
            tmp_path / "b.zip",
            bundle_files(
                version="1.2.0",
                extra={"overrides.yaml": overrides_yaml(rules=["1", "2"])},
            ),
        )

        layer_overrides(project, resolve_artifacts(project, bundle=archive))

        assert (
            "Bundle acme 1.2.0 overrides of lower layers: 2 rule(s) disabled"
            in caplog.text
        )

    def test_reads_severities_of_project_and_bundle(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should combine severities from nac/overrides.yaml and a bundle."""
        install_module(project)
        write_files(
            project / "nac",
            {"overrides.yaml": overrides_yaml(severities={"1": "LOW"})},
        )
        archive = make_zip(
            tmp_path / "b.zip",
            bundle_files(
                extra={"overrides.yaml": overrides_yaml(severities={"2": "MEDIUM"})}
            ),
        )
        layers = resolve_artifacts(project, bundle=archive)

        bundle, module = layer_overrides(project, layers)

        assert bundle.rule_severities == (SeverityEntry("1", "LOW", "project"),)
        assert module.rule_severities == (
            SeverityEntry("1", "LOW", "project"),
            SeverityEntry("2", "MEDIUM", "bundle acme"),
        )


def test_old_function_names_are_aliases() -> None:
    """Should keep the names from before severity entries for compatibility."""
    assert disables_by_layer is overrides_by_layer
    assert layer_disables is layer_overrides
