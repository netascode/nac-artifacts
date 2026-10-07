# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Daniel Schmidt

"""Unit tests for the nac_artifacts package."""

import pytest

import nac_artifacts


@pytest.mark.unit
def test_version_is_exposed() -> None:
    """Should expose the installed package version."""
    assert nac_artifacts.__version__
