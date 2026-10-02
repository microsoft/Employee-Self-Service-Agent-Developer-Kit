# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Verify the bundled ESS Maker Profile package matches its source."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VSIX_DIR = REPO_ROOT / "tools" / "ess-maker-profile" / "extension"


def test_bundled_vsix_matches_source_package() -> None:
    """Keep the installer package, manifest, and shipped source in sync."""
    package = json.loads((VSIX_DIR / "package.json").read_text(encoding="utf-8"))
    expected_name = f"ess-maker-profile-{package['version']}.vsix"
    matches = sorted(VSIX_DIR.glob("ess-maker-profile-*.vsix"))

    assert [path.name for path in matches] == [expected_name]
    assert matches[0].stat().st_size > 1024

    with zipfile.ZipFile(matches[0]) as archive:
        bundled_package = json.loads(
            archive.read("extension/package.json").decode("utf-8")
        )
        bundled_source = archive.read("extension/extension.js").decode("utf-8")
        bundled_changelog = archive.read("extension/changelog.md").decode("utf-8")

    assert bundled_package["version"] == package["version"]
    assert bundled_source.splitlines() == (
        VSIX_DIR / "extension.js"
    ).read_text(encoding="utf-8").splitlines()
    assert bundled_changelog.splitlines() == (
        VSIX_DIR / "CHANGELOG.md"
    ).read_text(encoding="utf-8").splitlines()
