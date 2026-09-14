# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Keep review-stack CI support narrow without changing upstream event policy."""

from pathlib import Path

import yaml


def test_ci_accepts_only_the_approved_review_targets_in_addition_to_upstream():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.load(
        (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert workflow["on"]["push"]["branches"] == ["main", "release/**"]
    assert workflow["on"]["pull_request"]["branches"] == [
        "main", "release/**",
        "users/rebova/org-announcements-prerelease",
        "users/rebova/org-announcements-review-*",
    ]
    assert workflow["on"]["pull_request"]["types"] == [
        "opened", "synchronize", "reopened", "edited",
    ]
    assert workflow["permissions"] == {"contents": "read"}
