# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Conventional paths and limits shared by module and bundle discovery."""

from pathlib import Path

# Directory of a module (and of the project) that holds everything nac-related:
# the artifacts of a module, the bundles and overrides of a project. A bundle
# belongs to nac only and holds its artifacts directly at its root
ARTIFACTS_DIRNAME = "nac"

# Terraform / OpenTofu install manifest, relative to the data directory
TERRAFORM_DEFAULT_DATA_DIR = Path(".terraform")
TERRAFORM_MODULES_MANIFEST = Path("modules") / "modules.json"

# Bundles dropped into a project; every archive and directory in it is a bundle
BUNDLES_DIRNAME = "bundles"
BUNDLE_DIR = Path(ARTIFACTS_DIRNAME) / BUNDLES_DIRNAME
# Hidden, so that discovery skips it
BUNDLE_CACHE_DIR = BUNDLE_DIR / ".cache"
# Archives are recognized by extension for auto-detection only; the file name is
# otherwise free (it may carry a version or architecture) and is never parsed
BUNDLE_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")
# Archives that are likely meant as bundles but cannot be read; an error rather
# than skipped like other files. Checked after BUNDLE_ARCHIVE_SUFFIXES (.tar.gz)
BUNDLE_UNSUPPORTED_ARCHIVE_SUFFIXES = (
    ".tar",
    ".gz",
    ".xz",
    ".txz",
    ".bz2",
    ".tbz",
    ".tbz2",
    ".zst",
    ".tzst",
    ".7z",
    ".rar",
)
# File with disable entries: in nac/ of a project and at the root of a bundle
OVERRIDES_FILENAME = "overrides.yaml"
PROJECT_OVERRIDES_FILE = Path(ARTIFACTS_DIRNAME) / OVERRIDES_FILENAME
# Entries of a project's nac/ that are not artifacts of the root module
PROJECT_ENTRIES = (BUNDLES_DIRNAME, OVERRIDES_FILENAME)
BUNDLE_MANIFEST_FILENAME = "manifest.yaml"
BUNDLE_MAX_FILES = 5000
BUNDLE_MAX_BYTES = 100 * 1024 * 1024
# Cache directory name length (hex digits of the archive sha256); short enough to
# keep paths below the Windows 260 character limit, long enough to never collide
BUNDLE_CACHE_KEY_LENGTH = 32
# Renaming a freshly extracted directory can fail on Windows while a virus
# scanner or indexer still holds files open, so it is retried
BUNDLE_REPLACE_ATTEMPTS = 5
BUNDLE_REPLACE_DELAY_SECONDS = 0.1
# Extraction directories older than this are leftovers of killed processes
BUNDLE_STALE_TEMP_SECONDS = 3600
# Cache entries not used for this long (typically old bundle versions) are removed;
# a bundle that is still present is simply extracted again on its next use
BUNDLE_CACHE_MAX_AGE_SECONDS = 30 * 24 * 3600
