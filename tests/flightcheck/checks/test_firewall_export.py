# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the firewall-requirements markdown renderer.

Pure file-render helper — no external API calls, no probes. Tests verify
the markdown structure against a small deterministic fixture catalog so
the rendered output stays in sync with what the network team expects to
hand-off to corporate IT.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flightcheck.checks.firewall_export import export_firewall_requirements


_FIXTURE_CATALOG = {
    "integrations": [
        {
            "name": "Workday",
            "required": True,
            "hostingPattern": "Data center based (not tenant-prefixed)",
            "ipRangeNote": "Workday IP ranges per data center at https://community.workday.com (login required).",
            "endpoints": [
                {"host": "wd2-impl-services1.workday.com", "port": 443,
                 "purpose": "Implementation services (DC2)"},
                {"host": "wd5.myworkday.com", "port": 443,
                 "purpose": "Production services (DC5)"},
            ],
        },
        {
            "name": "ServiceNow",
            "required": True,
            "hostingPattern": "Instance-prefixed hostname",
            "ipRangeNote": "ServiceNow IP ranges at https://docs.servicenow.com.",
            "endpoints": [
                {"host": "{instance}.service-now.com", "port": 443,
                 "purpose": "Instance API"},
            ],
        },
    ],
    "microsoftEndpointsReference": {
        "links": [
            {"title": "Power Platform URLs and IP address ranges",
             "url": "https://learn.microsoft.com/en-us/power-platform/admin/online-requirements"},
        ],
    },
}

_FIXED_NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    p = tmp_path / "required-endpoints.json"
    p.write_text(json.dumps(_FIXTURE_CATALOG), encoding="utf-8")
    return p


def _render(catalog_path: Path, tmp_path: Path, config: dict | None = None) -> str:
    out = tmp_path / "out.md"
    export_firewall_requirements(
        config or {}, str(out),
        catalog_path=str(catalog_path),
        now=_FIXED_NOW,
    )
    return out.read_text(encoding="utf-8")


class TestRender:
    def test_includes_title_and_timestamp(self, catalog_path: Path, tmp_path: Path) -> None:
        text = _render(catalog_path, tmp_path)
        assert text.startswith("# ESS Firewall Allow-List Requirements")
        assert "2026-05-19 12:00:00 UTC" in text

    def test_lists_every_integration_with_required_flag(
        self, catalog_path: Path, tmp_path: Path
    ) -> None:
        text = _render(catalog_path, tmp_path)
        assert "## Workday" in text
        assert "## ServiceNow" in text
        # Workday is required, ServiceNow is required → both show "Required: Yes"
        assert text.count("**Required:** Yes") == 2

    def test_includes_all_endpoint_hosts(self, catalog_path: Path, tmp_path: Path) -> None:
        text = _render(catalog_path, tmp_path)
        assert "wd2-impl-services1.workday.com" in text
        assert "wd5.myworkday.com" in text
        assert "{instance}.service-now.com" in text  # left unresolved when no instance configured

    def test_servicenow_instance_substituted_when_configured(
        self, catalog_path: Path, tmp_path: Path
    ) -> None:
        text = _render(catalog_path, tmp_path,
                       config={"network": {"servicenow_instance": "contoso"}})
        assert "contoso.service-now.com" in text
        # We replace the host outright when configured — no leftover placeholder.
        assert "{instance}.service-now.com" not in text

    def test_microsoft_endpoints_referenced_not_listed(
        self, catalog_path: Path, tmp_path: Path
    ) -> None:
        text = _render(catalog_path, tmp_path)
        # Reference link present
        assert "https://learn.microsoft.com/en-us/power-platform/admin/online-requirements" in text
        # Scope statement is clear that we don't enumerate Microsoft hosts
        assert "Vendor endpoints only" in text

    def test_includes_tls_inspection_note(self, catalog_path: Path, tmp_path: Path) -> None:
        text = _render(catalog_path, tmp_path)
        assert "TLS inspection" in text

    def test_writes_to_specified_path(self, catalog_path: Path, tmp_path: Path) -> None:
        out = tmp_path / "subdir" / "out.md"
        out.parent.mkdir()  # caller is responsible per docstring
        returned = export_firewall_requirements(
            {}, str(out), catalog_path=str(catalog_path), now=_FIXED_NOW,
        )
        assert returned == str(out)
        assert out.exists()
