# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Unit tests for nac_artifacts.bundle module.

Tests verify bundle discovery, safe extraction and the content-addressed cache.
"""

import hashlib
import os
import shutil
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from nac_artifacts import ArtifactLayer, BundleError, find_bundle_layer
from nac_artifacts.bundle import _sha256_file
from nac_artifacts.constants import BUNDLE_REPLACE_ATTEMPTS
from tests.unit.helpers import (
    bundle_files,
    make_tgz,
    make_zip,
    resolve_artifacts,
    write_artifacts,
)


def origins(layers: list[ArtifactLayer]) -> list[str]:
    """Return the origin of each layer, highest priority first."""
    return [layer.origin for layer in layers]


class TestBundleSource:
    """Tests for bundle discovery, extraction and caching."""

    def test_auto_detected_zip(self, project: Path) -> None:
        """Should detect .nac/bundle.zip and read its manifest version."""
        (project / ".nac").mkdir()
        make_zip(project / ".nac/bundle.zip", bundle_files())

        layers = resolve_artifacts(project)

        assert origins(layers) == ["bundle"]
        assert layers[0].version == "1.0.0"
        assert layers[0].manifest["name"] == "acme"
        assert (layers[0].nac_dir / "schema.yaml").is_file()

    def test_auto_detected_tar_gz(self, project: Path) -> None:
        """Should detect .nac/bundle.tar.gz."""
        (project / ".nac").mkdir()
        make_tgz(project / ".nac/bundle.tar.gz", bundle_files())

        assert resolve_artifacts(project)[-1].origin == "bundle"

    def test_auto_detected_directory(self, project: Path) -> None:
        """Should detect an already extracted .nac/bundle directory."""
        for name, content in bundle_files().items():
            target = project / ".nac/bundle" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        assert resolve_artifacts(project)[-1].origin == "bundle"

    def test_explicit_path(self, project: Path, tmp_path: Path) -> None:
        """Should use --bundle wherever the archive lives."""
        archive = make_zip(tmp_path / "customer.zip", bundle_files())

        assert resolve_artifacts(project, bundle=archive)[-1].origin == "bundle"

    def test_explicit_path_missing(self, project: Path, tmp_path: Path) -> None:
        """Should raise when --bundle does not exist."""
        with pytest.raises(BundleError, match="not found"):
            resolve_artifacts(project, bundle=tmp_path / "nope.zip")

    def test_extraction_is_cached_by_digest(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should reuse the extracted cache on later runs of the same archive."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())
        first = resolve_artifacts(project, bundle=archive)[-1].root
        assert first is not None
        (first / "marker").write_text("kept")

        second = resolve_artifacts(project, bundle=archive)[-1].root

        assert second == first
        assert (first / "marker").read_text() == "kept"
        assert first.parent == project / ".nac/cache"

    def test_different_content_gets_new_cache_entry(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should extract a changed archive into a separate cache entry."""
        a = resolve_artifacts(
            project, bundle=make_zip(tmp_path / "a.zip", bundle_files("1.0.0"))
        )
        b = resolve_artifacts(
            project, bundle=make_zip(tmp_path / "b.zip", bundle_files("2.0.0"))
        )

        assert a[-1].root != b[-1].root

    def test_cache_ignores_itself_in_git(self, project: Path, tmp_path: Path) -> None:
        """Should write a .gitignore so extracted bundles are not untracked files."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        resolve_artifacts(project, bundle=archive)

        gitignore = project / ".nac/cache/.gitignore"
        assert gitignore.read_text() == "*\n"

    def test_existing_cache_gitignore_is_kept(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should not overwrite a .gitignore the user already customized."""
        (project / ".nac/cache").mkdir(parents=True)
        (project / ".nac/cache/.gitignore").write_text("custom\n")

        resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", bundle_files()))

        assert (project / ".nac/cache/.gitignore").read_text() == "custom\n"

    def test_cache_gitignore_added_on_cache_hit(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should add the .gitignore even if the cache entry already exists."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())
        resolve_artifacts(project, bundle=archive)
        (project / ".nac/cache/.gitignore").unlink()

        resolve_artifacts(project, bundle=archive)

        assert (project / ".nac/cache/.gitignore").read_text() == "*\n"

    def test_directory_bundle_does_not_create_cache(self, project: Path) -> None:
        """Should not create a cache directory for an extracted bundle."""
        for name, content in bundle_files().items():
            target = project / ".nac/bundle" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        resolve_artifacts(project)

        assert not (project / ".nac/cache").exists()

    @pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
    def test_git_sees_bundle_archive_but_not_cache(self, project: Path) -> None:
        """Should leave only the bundle archive as a candidate for git add."""
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        (project / ".nac").mkdir()
        make_zip(project / ".nac/bundle.zip", bundle_files())

        resolve_artifacts(project)

        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert status == ["??", ".nac/bundle.zip"]

    def test_missing_manifest(self, project: Path, tmp_path: Path) -> None:
        """Should raise when the bundle has no manifest.yaml."""
        files = bundle_files()
        del files["manifest.yaml"]

        with pytest.raises(BundleError, match="manifest.yaml"):
            resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", files))

    def test_directory_bundle_without_manifest(self, project: Path) -> None:
        """Should require a manifest in directory bundles too."""
        write_artifacts(project / "dir-bundle")

        with pytest.raises(BundleError, match="manifest.yaml"):
            resolve_artifacts(project, bundle=project / "dir-bundle")

    @pytest.mark.parametrize("manifest", ["- a\n- b\n", "key: [unclosed\n"])
    def test_invalid_manifest(
        self, project: Path, tmp_path: Path, manifest: str
    ) -> None:
        """Should raise when the manifest is not valid YAML or not a mapping."""
        files = bundle_files()
        files["manifest.yaml"] = manifest

        with pytest.raises(BundleError, match="manifest.yaml"):
            resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", files))

    def test_no_artifacts_in_bundle(self, project: Path, tmp_path: Path) -> None:
        """Should raise when the bundle has neither schema nor rules."""
        archive = make_zip(tmp_path / "b.zip", {"manifest.yaml": "name: x\n"})

        with pytest.raises(BundleError, match="contains no"):
            resolve_artifacts(project, bundle=archive)

    def test_not_an_archive(self, project: Path, tmp_path: Path) -> None:
        """Should raise when the file is neither a zip nor a tar archive."""
        junk = tmp_path / "junk.zip"
        junk.write_text("hello")

        with pytest.raises(BundleError, match="not a zip or tar"):
            resolve_artifacts(project, bundle=junk)


class TestBundleExtractionSafety:
    """Tests that hostile archives are rejected without leaving files behind."""

    @pytest.mark.parametrize(
        "name",
        [
            "../evil.txt",
            "/abs/evil.txt",
            "a/../../evil",
            "C:\\evil.txt",
            "C:/evil.txt",
            "\\\\server\\share\\x",
            "..\\evil.txt",
        ],
    )
    def test_zip_path_traversal_rejected(
        self, project: Path, tmp_path: Path, name: str
    ) -> None:
        """Should reject zip members that escape the extraction directory."""
        archive = make_zip(tmp_path / "b.zip", bundle_files(extra={name: "x"}))

        with pytest.raises(BundleError, match="Unsafe path"):
            resolve_artifacts(project, bundle=archive)

    def test_tar_path_traversal_rejected(self, project: Path, tmp_path: Path) -> None:
        """Should reject tar members that escape the extraction directory."""
        archive = make_tgz(tmp_path / "b.tgz", bundle_files(extra={"../evil": "x"}))

        with pytest.raises(BundleError, match="Unsafe path"):
            resolve_artifacts(project, bundle=archive)

    def test_zip_symlink_rejected(self, project: Path, tmp_path: Path) -> None:
        """Should reject symlinks in zip archives."""
        archive = tmp_path / "b.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for name, content in bundle_files().items():
                zf.writestr(name, content)
            link = zipfile.ZipInfo("nac/link")
            link.external_attr = 0o120777 << 16
            zf.writestr(link, "/etc/passwd")

        with pytest.raises(BundleError, match="Symlink"):
            resolve_artifacts(project, bundle=archive)

    def test_tar_symlink_rejected(self, project: Path, tmp_path: Path) -> None:
        """Should reject anything but regular files and directories in tar."""
        archive = tmp_path / "link.tar"
        with tarfile.open(archive, "w") as tf:
            link = tarfile.TarInfo("nac/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)

        with pytest.raises(BundleError, match="regular files"):
            resolve_artifacts(project, bundle=archive)

    def test_size_limit(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should reject archives larger than the configured limit."""
        monkeypatch.setattr("nac_artifacts.bundle.BUNDLE_MAX_BYTES", 10)
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        with pytest.raises(BundleError, match="too large"):
            resolve_artifacts(project, bundle=archive)

    def test_failed_extraction_leaves_no_cache_or_temp_dirs(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should not leave partial extractions behind after a failure."""
        archive = make_zip(tmp_path / "b.zip", bundle_files(extra={"../x": "y"}))

        with pytest.raises(BundleError):
            resolve_artifacts(project, bundle=archive)

        cache = project / ".nac/cache"
        leftovers = [p.name for p in cache.iterdir() if p.name != ".gitignore"]
        assert leftovers == []

    def test_concurrent_cache_population_is_tolerated(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should accept a cache entry created by another process mid-extraction."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        def lost_race(src: Path, dst: Path) -> None:
            shutil.copytree(src, dst)
            raise OSError("destination exists")

        monkeypatch.setattr("nac_artifacts.bundle.os.replace", lost_race)

        layer = resolve_artifacts(project, bundle=archive)[-1]

        assert layer.root is not None and layer.root.is_dir()
        assert list(layer.root.parent.glob(".extract-*")) == []

    def test_replace_failure_without_cache_propagates(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should report a real filesystem failure instead of hiding it."""

        def broken(src: Path, dst: Path) -> None:
            raise OSError("disk on fire")

        monkeypatch.setattr(os, "replace", broken)
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        with pytest.raises(BundleError, match="disk on fire"):
            resolve_artifacts(project, bundle=archive)


class TestBundleSelection:
    """Tests for choosing which bundle to use."""

    def test_relative_directory_bundle_is_resolved(self, project: Path) -> None:
        """Should return an absolute root so later directory changes are harmless."""
        for name, content in bundle_files().items():
            target = project / "customer" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        layer = find_bundle_layer(
            project, provides=("schema.yaml",), bundle=Path("customer")
        )

        assert layer is not None
        assert layer.root.is_absolute()
        assert layer.root == (project / "customer").resolve()

    def test_multiple_default_bundles_raise(self, project: Path) -> None:
        """Should not silently pick one when several default bundles exist."""
        (project / ".nac").mkdir()
        make_zip(project / ".nac/bundle.zip", bundle_files(version="1.0.0"))
        make_tgz(project / ".nac/bundle.tar.gz", bundle_files(version="2.0.0"))

        with pytest.raises(BundleError, match="Multiple bundles.*bundle.zip"):
            resolve_artifacts(project)

    def test_explicit_bundle_wins_over_default_bundles(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should use --bundle even if default bundles exist."""
        (project / ".nac").mkdir()
        make_zip(project / ".nac/bundle.zip", bundle_files(version="1.0.0"))
        make_tgz(project / ".nac/bundle.tar.gz", bundle_files(version="2.0.0"))
        chosen = make_zip(tmp_path / "x.zip", bundle_files(version="3.0.0"))

        assert resolve_artifacts(project, bundle=chosen)[0].version == "3.0.0"

    def test_find_bundle_layer_returns_none_without_bundle(self, project: Path) -> None:
        """Should return None when no bundle is present."""
        assert find_bundle_layer(project, provides=("schema.yaml",)) is None

    def test_find_bundle_layer_validates_provides(self, project: Path) -> None:
        """Should reject invalid requested paths before touching the bundle."""
        with pytest.raises(ValueError, match="at least one"):
            find_bundle_layer(project, provides=())


class TestBundleRoot:
    """Tests for locating the manifest inside an extracted bundle."""

    @staticmethod
    def zip_with_prefix(path: Path, prefix: str, extra: dict[str, str]) -> Path:
        files = {prefix + name: text for name, text in bundle_files().items()}
        return make_zip(path, {**files, **extra})

    def test_single_top_level_directory_is_used(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should accept an archive made by zipping a folder."""
        archive = self.zip_with_prefix(tmp_path / "b.zip", "customer-bundle/", {})

        layer = resolve_artifacts(project, bundle=archive)[0]

        assert layer.root.name == "customer-bundle"
        assert (layer.nac_dir / "schema.yaml").is_file()

    def test_macos_resource_dir_is_ignored(self, project: Path, tmp_path: Path) -> None:
        """Should ignore the __MACOSX directory Finder adds to zip files."""
        archive = self.zip_with_prefix(
            tmp_path / "b.zip", "customer-bundle/", {"__MACOSX/._x": "junk"}
        )

        assert resolve_artifacts(project, bundle=archive)[0].root.name == (
            "customer-bundle"
        )

    def test_several_top_level_entries_are_rejected(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should not guess when the manifest is not at the root or in one folder."""
        archive = self.zip_with_prefix(
            tmp_path / "b.zip", "one/", {"two/readme.txt": "x"}
        )

        with pytest.raises(BundleError, match="no manifest.yaml at its root"):
            resolve_artifacts(project, bundle=archive)

    def test_error_names_the_archive_not_the_cache(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should mention the bundle the user supplied in the error."""
        archive = make_zip(tmp_path / "customer.zip", {"nac/schema.yaml": "x"})

        with pytest.raises(BundleError) as exc_info:
            resolve_artifacts(project, bundle=archive)

        assert "customer.zip" in str(exc_info.value)
        assert ".nac/cache" not in str(exc_info.value)


class TestManifestValidation:
    """Tests that wrongly typed manifest fields are rejected, not ignored."""

    @staticmethod
    def resolve_with(
        project: Path, tmp_path: Path, manifest: str
    ) -> list[ArtifactLayer]:
        files = bundle_files()
        files["manifest.yaml"] = manifest
        return resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", files))

    def test_unquoted_float_version_is_rejected(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should refuse 1.10, which YAML would silently turn into 1.1."""
        with pytest.raises(BundleError, match="quote it"):
            self.resolve_with(project, tmp_path, "version: 1.10\n")

    def test_quoted_version_is_accepted(self, project: Path, tmp_path: Path) -> None:
        """Should keep a quoted version exactly as written."""
        layers = self.resolve_with(project, tmp_path, 'version: "1.10"\n')

        assert layers[0].version == "1.10"

    def test_non_string_name_is_rejected(self, project: Path, tmp_path: Path) -> None:
        """Should refuse a name that is not a string."""
        with pytest.raises(BundleError, match="'name'.*must be a string"):
            self.resolve_with(project, tmp_path, "name: 5\n")

    @pytest.mark.parametrize(
        ("manifest", "message"),
        [
            ("module: '<1'\n", "'module'.*must be a mapping"),
            ("module: [a]\n", "'module'.*must be a mapping"),
            ("module:\n  versions: 5\n", "'module.versions'.*must be a string"),
        ],
    )
    def test_malformed_module_section_is_rejected(
        self, project: Path, tmp_path: Path, manifest: str, message: str
    ) -> None:
        """Should refuse a module section that would silently disable the check."""
        with pytest.raises(BundleError, match=message):
            self.resolve_with(project, tmp_path, manifest)

    def test_valid_module_section_is_accepted(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should accept a mapping with a string versions specifier."""
        manifest = "name: acme\nmodule:\n  versions: '>=0.3'\n"

        assert self.resolve_with(project, tmp_path, manifest)[0].manifest["module"] == {
            "versions": ">=0.3"
        }

    def test_unknown_module_keys_are_ignored(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should ignore module keys it does not use, so manifests can grow."""
        manifest = "module:\n  name: nac-nxos\n  versions: '>=0.3'\n"

        assert self.resolve_with(project, tmp_path, manifest)[0].origin == "bundle"

    def test_manifest_error_names_the_archive(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should mention the bundle the user supplied, not its cache directory."""
        with pytest.raises(BundleError, match=r"bundle .*b\.zip"):
            self.resolve_with(project, tmp_path, "- a\n")


class TestBundleLimits:
    """Tests for resource limits on bundles."""

    @staticmethod
    def compressible_zip(path: Path, size: int) -> Path:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.yaml", "name: x\n")
            archive.writestr("nac/schema.yaml", "a" * size)
        return path

    def test_archive_file_size_is_capped_before_reading(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should reject an oversized archive without loading or hashing it."""
        monkeypatch.setattr("nac_artifacts.bundle.BUNDLE_MAX_BYTES", 100)
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        def fail(self: Path) -> bytes:
            raise AssertionError("archive must not be read")

        monkeypatch.setattr(Path, "read_bytes", fail)
        with pytest.raises(BundleError, match="archive too large"):
            resolve_artifacts(project, bundle=archive)

    def test_extracted_size_is_capped(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should reject an archive that is small but expands beyond the limit."""
        archive = self.compressible_zip(tmp_path / "b.zip", 20_000)
        monkeypatch.setattr("nac_artifacts.bundle.BUNDLE_MAX_BYTES", 5_000)
        assert archive.stat().st_size < 5_000

        with pytest.raises(BundleError, match=r"too large \(\d+ files, \d+ bytes\)"):
            resolve_artifacts(project, bundle=archive)

    def test_file_count_is_capped(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should reject an archive with too many members."""
        monkeypatch.setattr("nac_artifacts.bundle.BUNDLE_MAX_FILES", 1)
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        with pytest.raises(BundleError, match="too large"):
            resolve_artifacts(project, bundle=archive)

    def test_archive_is_hashed_in_chunks(self, project: Path, tmp_path: Path) -> None:
        """Should produce the same digest as hashing the whole file at once."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        assert _sha256_file(archive) == hashlib.sha256(archive.read_bytes()).hexdigest()


class TestExtractionHousekeeping:
    """Tests for leftovers and fallbacks around extraction."""

    def test_stale_temp_dirs_are_removed(self, project: Path, tmp_path: Path) -> None:
        """Should delete old .extract-* directories from killed processes."""
        cache = project / ".nac/cache"
        stale, fresh = cache / ".extract-stale", cache / ".extract-fresh"
        stale.mkdir(parents=True)
        fresh.mkdir()
        (stale / "partial").write_text("x")
        old = time.time() - 2 * 3600
        os.utime(stale, (old, old))

        resolve_artifacts(project, bundle=make_zip(tmp_path / "b.zip", bundle_files()))

        assert not stale.exists()
        assert fresh.exists()

    def test_unreadable_temp_entries_are_skipped(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should not fail on a leftover that cannot be inspected."""
        cache = project / ".nac/cache"
        cache.mkdir(parents=True)
        try:
            (cache / ".extract-broken").symlink_to(tmp_path / "does-not-exist")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks cannot be created on this system")

        layers = resolve_artifacts(
            project, bundle=make_zip(tmp_path / "b.zip", bundle_files())
        )

        assert [layer.origin for layer in layers] == ["bundle"]

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_tar_extraction_without_data_filter(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should still extract on Python versions without tarfile.data_filter."""
        monkeypatch.setattr("nac_artifacts.bundle._TAR_FILTERS_SUPPORTED", False)
        archive = make_tgz(tmp_path / "b.tgz", bundle_files())

        layer = resolve_artifacts(project, bundle=archive)[0]

        assert (layer.nac_dir / "schema.yaml").is_file()


class TestCacheLocation:
    """Tests for the cache directory name."""

    def test_cache_key_is_a_short_digest_prefix(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Should name the cache directory after a prefix of the archive digest."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        layer = resolve_artifacts(project, bundle=archive)[0]

        assert layer.root.name == _sha256_file(archive)[:32]
        assert len(layer.root.name) == 32


class TestCacheErrors:
    """Tests that an unusable cache gives a clear error, not a raw OSError."""

    def test_unwritable_project_directory(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should report a read-only project instead of raising PermissionError."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        def deny(self: Path, *args: object, **kwargs: object) -> None:
            raise PermissionError("read-only file system")

        monkeypatch.setattr(Path, "mkdir", deny)

        with pytest.raises(BundleError, match="Cannot create bundle cache.*read-only"):
            resolve_artifacts(project, bundle=archive)

    def test_temp_dir_cannot_be_created(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should report a failure to create the extraction directory."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        def full_disk(*args: object, **kwargs: object) -> str:
            raise OSError("no space left on device")

        monkeypatch.setattr("nac_artifacts.bundle.tempfile.mkdtemp", full_disk)

        with pytest.raises(BundleError, match="Cannot extract bundle.*no space"):
            resolve_artifacts(project, bundle=archive)


class TestPublishRetry:
    """Tests for retrying the rename of a finished extraction."""

    @pytest.fixture
    def sleeps(self, monkeypatch: pytest.MonkeyPatch) -> list[float]:
        """Record sleeps instead of waiting."""
        recorded: list[float] = []
        monkeypatch.setattr("nac_artifacts.bundle.time.sleep", recorded.append)
        return recorded

    def test_permission_error_is_retried(
        self,
        project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sleeps: list[float],
    ) -> None:
        """Should retry while a scanner holds files open, then succeed."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())
        real_replace, calls = os.replace, []

        def flaky(src: Path, dst: Path) -> None:
            calls.append(src)
            if len(calls) < 3:
                raise PermissionError("[WinError 5] Access is denied")
            real_replace(src, dst)

        monkeypatch.setattr("nac_artifacts.bundle.os.replace", flaky)

        layer = resolve_artifacts(project, bundle=archive)[0]

        assert len(calls) == 3
        assert len(sleeps) == 2
        assert (layer.nac_dir / "schema.yaml").is_file()

    def test_permission_error_gives_up_after_the_attempt_limit(
        self,
        project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sleeps: list[float],
    ) -> None:
        """Should fail with a clear error once all attempts are used."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())
        calls: list[Path] = []

        def locked(src: Path, dst: Path) -> None:
            calls.append(src)
            raise PermissionError("[WinError 5] Access is denied")

        monkeypatch.setattr("nac_artifacts.bundle.os.replace", locked)

        with pytest.raises(BundleError, match="Access is denied"):
            resolve_artifacts(project, bundle=archive)

        assert len(calls) == BUNDLE_REPLACE_ATTEMPTS
        assert len(sleeps) == BUNDLE_REPLACE_ATTEMPTS - 1

    def test_other_errors_are_not_retried(
        self,
        project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sleeps: list[float],
    ) -> None:
        """Should fail immediately for errors that waiting cannot fix."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())
        calls: list[Path] = []

        def broken(src: Path, dst: Path) -> None:
            calls.append(src)
            raise OSError("disk on fire")

        monkeypatch.setattr("nac_artifacts.bundle.os.replace", broken)

        with pytest.raises(BundleError, match="disk on fire"):
            resolve_artifacts(project, bundle=archive)

        assert len(calls) == 1
        assert sleeps == []

    def test_existing_cache_ends_the_retries(
        self,
        project: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sleeps: list[float],
    ) -> None:
        """Should stop retrying once another process has populated the cache."""
        archive = make_zip(tmp_path / "b.zip", bundle_files())

        def lost_race(src: Path, dst: Path) -> None:
            shutil.copytree(src, dst)
            raise PermissionError("[WinError 5] Access is denied")

        monkeypatch.setattr("nac_artifacts.bundle.os.replace", lost_race)

        layer = resolve_artifacts(project, bundle=archive)[0]

        assert (layer.nac_dir / "schema.yaml").is_file()
        assert sleeps == []


class TestDefaultBundleDetection:
    """Tests for finding a bundle dropped into .nac/ under any file name."""

    @pytest.fixture
    def nac_dir(self, project: Path) -> Path:
        directory = project / ".nac"
        directory.mkdir()
        return directory

    def test_versioned_architecture_file_name(
        self, project: Path, nac_dir: Path
    ) -> None:
        """Should accept a name carrying a version and an architecture."""
        make_zip(nac_dir / "acme-nxos-1.2.0.zip", bundle_files(version="1.2.0"))

        layer = resolve_artifacts(project)[0]

        assert layer.origin == "bundle"
        assert layer.version == "1.2.0"

    @pytest.mark.parametrize("name", ["b.tar.gz", "b.tgz", "B.ZIP", "Acme.Tar.Gz"])
    def test_supported_extensions(
        self, project: Path, nac_dir: Path, name: str
    ) -> None:
        """Should recognize .zip, .tar.gz and .tgz case-insensitively."""
        if name.lower().endswith(".zip"):
            make_zip(nac_dir / name, bundle_files())
        else:
            make_tgz(nac_dir / name, bundle_files())

        assert resolve_artifacts(project)[0].origin == "bundle"

    def test_file_name_is_not_parsed(self, project: Path, nac_dir: Path) -> None:
        """Should take name and version from the manifest, not the file name."""
        make_zip(nac_dir / "totally-9.9.9-other.zip", bundle_files(version="1.0.0"))

        layer = resolve_artifacts(project)[0]

        assert layer.version == "1.0.0"
        assert "acme" in layer.detail

    def test_other_files_and_directories_are_ignored(
        self, project: Path, nac_dir: Path
    ) -> None:
        """Should ignore files without a bundle extension and unrelated directories."""
        (nac_dir / "README.md").write_text("notes")
        (nac_dir / "bundle.zip.sha256").write_text("abc")
        (nac_dir / "other-dir").mkdir()
        (nac_dir / "other.zip").mkdir()  # a directory, not an archive

        assert resolve_artifacts(project) == []

    def test_hidden_archives_are_ignored(self, project: Path, nac_dir: Path) -> None:
        """Should ignore hidden entries such as editor or temp files."""
        make_zip(nac_dir / ".hidden.zip", bundle_files())

        assert resolve_artifacts(project) == []

    def test_cache_directory_is_not_a_bundle(
        self, project: Path, nac_dir: Path, tmp_path: Path
    ) -> None:
        """Should not mistake the extraction cache for a bundle directory."""
        make_zip(nac_dir / "customer.zip", bundle_files())

        resolve_artifacts(project)
        layers = resolve_artifacts(project)  # the cache now exists

        assert [layer.origin for layer in layers] == ["bundle"]

    def test_multiple_archives_raise_with_sorted_names(
        self, project: Path, nac_dir: Path
    ) -> None:
        """Should list every candidate in a stable order instead of picking one."""
        make_zip(nac_dir / "b-2.0.0.zip", bundle_files(version="2.0.0"))
        make_zip(nac_dir / "a-1.0.0.zip", bundle_files(version="1.0.0"))

        with pytest.raises(BundleError, match=r"\(a-1\.0\.0\.zip, b-2\.0\.0\.zip\)"):
            resolve_artifacts(project)

    def test_archive_and_extracted_directory_raise(
        self, project: Path, nac_dir: Path
    ) -> None:
        """Should treat an archive next to a bundle/ directory as ambiguous."""
        make_zip(nac_dir / "customer.zip", bundle_files())
        for name, content in bundle_files().items():
            target = nac_dir / "bundle" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        with pytest.raises(BundleError, match="Multiple bundles.*bundle.*customer.zip"):
            resolve_artifacts(project)

    def test_no_nac_directory(self, project: Path) -> None:
        """Should find nothing when the project has no .nac directory."""
        assert resolve_artifacts(project) == []
