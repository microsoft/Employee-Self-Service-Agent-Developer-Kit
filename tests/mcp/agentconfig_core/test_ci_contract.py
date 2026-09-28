# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Keep CI triggers and permissions aligned with upstream policy."""

from pathlib import Path

import yaml


def test_ci_accepts_only_upstream_targets():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.load(
        (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert workflow["on"]["push"]["branches"] == ["main", "release/**"]
    assert workflow["on"]["pull_request"]["branches"] == ["main", "release/**"]
    assert workflow["on"]["pull_request"]["types"] == [
        "opened", "synchronize", "reopened", "edited",
    ]
    assert workflow["permissions"] == {"contents": "read"}
