# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Unit tests for nac_artifacts.testing module.

Tests verify the builders downstream tools use to create modules and bundles.
"""

import json
import tarfile
import zipfile
from pathlib import Path

from nac_artifacts import find_module_layer, load_overrides
from nac_artifacts.testing import (
    bundle_files,
    install_module,
    make_tgz,
    make_zip,
    module_entry,
    overrides_yaml,
    write_files,
    write_modules_json,
)


class TestWriteFiles:
    """Tests for write_files()."""

    def test_creates_nested_files(self, tmp_path: Path) -> None:
        """Should create parent directories and write the content."""
        root = write_files(tmp_path / "root", {"a/b/c.txt": "x", "d.txt": "y"})

        assert (root / "a/b/c.txt").read_text() == "x"
        assert (root / "d.txt").read_text() == "y"

    def test_creates_root_for_empty_files(self, tmp_path: Path) -> None:
        """Should still create the root directory when there are no files."""
        assert write_files(tmp_path / "empty", {}).is_dir()


class TestModulesJson:
    """Tests for module_entry(), write_modules_json() and install_module()."""

    def test_module_entry_without_version(self) -> None:
        """Should omit Version when none is given."""
        assert module_entry("m", "dir") == {"Key": "m", "Source": "x", "Dir": "dir"}

    def test_module_entry_with_version(self) -> None:
        """Should include Version when given."""
        assert module_entry("m", "dir", "1.0.0")["Version"] == "1.0.0"

    def test_write_modules_json_adds_root_entry(self, tmp_path: Path) -> None:
        """Should write the root module entry before the given entries."""
        write_modules_json(tmp_path, [module_entry("m", "dir")])

        data = json.loads((tmp_path / ".terraform/modules/modules.json").read_text())
        assert [e["Key"] for e in data["Modules"]] == ["", "m"]

    def test_write_modules_json_custom_data_dir(self, tmp_path: Path) -> None:
        """Should write below a custom data directory."""
        write_modules_json(tmp_path, [], data_dir="custom")

        assert (tmp_path / "custom/modules/modules.json").is_file()

    def test_install_module_is_discoverable(self, tmp_path: Path) -> None:
        """Should produce a module that discovery finds, with its version."""
        module_dir = install_module(
            tmp_path, {"schema.yaml": "a: str()\n"}, key="nxos", version="0.3.0"
        )

        layer = find_module_layer(tmp_path, provides=("schema.yaml",))

        assert layer is not None
        assert layer.root == module_dir.resolve()
        assert layer.version == "0.3.0"


class TestBundles:
    """Tests for bundle_files(), make_zip() and make_tgz()."""

    def test_bundle_files_prefixes_artifacts_and_adds_manifest(self) -> None:
        """Should put artifacts below nac/ next to a manifest."""
        files = bundle_files({"schema.yaml": "x"}, name="acme", version="2.0.0")

        assert files["nac/schema.yaml"] == "x"
        assert files["manifest.yaml"] == "name: acme\nversion: 2.0.0\n"

    def test_bundle_files_manifest_extra_and_raw_members(self) -> None:
        """Should append manifest YAML and keep extra archive paths verbatim."""
        files = bundle_files(
            {}, manifest_extra="module:\n  versions: '>=1'\n", extra={"../x": "y"}
        )

        assert files["manifest.yaml"].endswith("module:\n  versions: '>=1'\n")
        assert files["../x"] == "y"

    def test_make_zip_roundtrip(self, tmp_path: Path) -> None:
        """Should write a zip with the given members."""
        archive = make_zip(tmp_path / "b.zip", {"a/b.txt": "x"})

        with zipfile.ZipFile(archive) as zf:
            assert zf.read("a/b.txt") == b"x"

    def test_make_tgz_roundtrip(self, tmp_path: Path) -> None:
        """Should write a gzipped tar with the given members."""
        archive = make_tgz(tmp_path / "b.tgz", {"a/b.txt": "x"})

        with tarfile.open(archive) as tf:
            member = tf.extractfile("a/b.txt")
            assert member is not None
            assert member.read() == b"x"


class TestOverridesYaml:
    """Tests for overrides_yaml()."""

    def test_roundtrips_through_the_parser(self, tmp_path: Path) -> None:
        """Should produce text that load_overrides reads back unchanged."""
        path = tmp_path / "overrides.yaml"
        path.write_text(overrides_yaml(rules=["1", "2"], templates=["a/*.robot"]))

        overrides = load_overrides(path)

        assert overrides.rules == ("1", "2")
        assert overrides.templates == ("a/*.robot",)

    def test_empty(self, tmp_path: Path) -> None:
        """Should produce a valid file that disables nothing."""
        path = tmp_path / "overrides.yaml"
        path.write_text(overrides_yaml())

        assert load_overrides(path).is_empty
