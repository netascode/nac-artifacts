# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Conventional paths and limits shared by module and bundle discovery."""

from pathlib import Path

# Directory inside a module or bundle that holds the artifacts
ARTIFACTS_DIRNAME = "nac"

# Terraform / OpenTofu install manifest, relative to the data directory
TERRAFORM_DEFAULT_DATA_DIR = Path(".terraform")
TERRAFORM_MODULES_MANIFEST = Path("modules") / "modules.json"

# Bundles dropped into a project
BUNDLE_DIR = Path(".nac")
BUNDLE_CACHE_DIR = BUNDLE_DIR / "cache"
BUNDLE_CANDIDATES = ("bundle.zip", "bundle.tar.gz", "bundle")
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
