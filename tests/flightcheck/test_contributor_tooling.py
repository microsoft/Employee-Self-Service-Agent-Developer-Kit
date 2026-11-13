# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contributor tooling: check catalog search and gap report."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    scripts_dir = (
        Path(__file__).resolve().parents[2]
        / "solutions" / "ess-maker-skills" / "scripts"
    )
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        sys.path.remove(str(scripts_dir))


def test_catalog_lists_every_listable_registry_entry():
    from flightcheck import catalog, registry

    assert len(catalog.build_catalog()) == len(registry.list_checkpoints())


def test_search_requires_every_term_and_ignores_case():
    from flightcheck import catalog

    rows = catalog.build_catalog()
    both = catalog.search(rows, ["WORKDAY", "connection"])
    assert both and all("workday" in catalog._haystack(r) for r in both)
    assert catalog.search(rows, ["workday", "zz-no-such-term"]) == []


def test_search_filters_by_release_line():
    from flightcheck import catalog

    rows = catalog.build_catalog()
    assert {r["release_line"] for r in catalog.search(rows, [], "da")} == {"da"}


def test_every_inventory_documentation_source_is_in_the_manifest():
    from flightcheck import gap_report

    problems = gap_report.manifest_problems(
        gap_report._read_csv(gap_report.MANIFEST),
        gap_report._read_csv(gap_report.INVENTORY),
    )
    assert problems == []


def test_manifest_problems_flags_missing_source_and_bad_applicability():
    from flightcheck import gap_report

    manifest = [{"source": "a", "applies_to": "maybe"}]
    inventory = [{"documentation": "https://x.test/doc#anchor"}]
    problems = gap_report.manifest_problems(manifest, inventory)
    assert any("https://x.test/doc" in p for p in problems)
    assert any("applies_to='maybe'" in p for p in problems)


DOCS = "solutions/ess-maker-skills/src/reference/ess-docs/flightcheck/"


@pytest.mark.parametrize("changed,expect_warning", [
    ([DOCS + "validation-matrix.md"], True),
    ([DOCS + "validation-matrix.md", DOCS + "doc-sources.csv"], False),
    (["solutions/ess-maker-skills/scripts/flightcheck/da_inventory.csv"], True),
    (["README.md"], False),
])
def test_guidance_change_needs_manifest_update(changed, expect_warning):
    from flightcheck import gap_report

    assert bool(gap_report.changed_without_manifest(changed)) is expect_warning
