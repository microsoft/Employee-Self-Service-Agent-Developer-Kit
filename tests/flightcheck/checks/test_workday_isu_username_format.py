# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for WD-ENV-101 — Workday ISU username
alignment with Entra UPN format.

Mocks the Dataverse environmentvariabledefinitions /
environmentvariablevalues queries (where the ISU env var lives) AND
the Graph /organization endpoint (where verifiedDomains lives), then
runs the actual production check function against the mocked state.

Asserts:

* When the ISU username is `<localpart>@<verified-domain>`, the
  check PASSES.

* When the ISU username has no `@` (legacy short-employee-id format —
  common on federated tenants where the ISU was provisioned before
  adopting UPN-shaped service-account naming), the check WARNS and
  remediation points the operator at the env var.

* When the ISU username's domain is not in the tenant's verified
  domains, the check WARNS (could be legitimate cross-tenant, but
  worth surfacing).

* When the Dataverse env var is unset, the check SKIPS and defers to
  WD-ENV-001 — no double-reporting of the same root cause.

* Skipped paths: missing Dataverse token, missing Graph client.

Mock tier: dataverse=`documented`, graph=`validatable`. Both are
permitted FlightCheck tiers; require_validated_mock(...) at module
import time enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv
from tests.mocks import graph as gx

require_validated_mock(dv)
require_validated_mock(gx)


# ───────────────────────────────────────────────────────────────────────
# Test runner — minimal stand-in for FlightCheckRunner. The check needs
# .env_url, .dv_token, and .graph (a Graph-like object with
# .get_organization()). We don't import the real FlightCheckRunner
# because it does too much for what these tests need.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalGraph:
    """Stand-in for GraphClient that exposes only the surface the
    check uses (.get_organization()). The production
    GraphClient.get_organization() returns the first /organization
    record directly (or {} on auth failure / empty), NOT a value-
    wrapped collection envelope. We mirror that here.
    """

    org_payload: dict[str, Any] | None = None
    raise_exc: Exception | None = None

    def get_organization(self) -> dict[str, Any]:
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.org_payload or {}


@dataclass
class _MinimalRunner:
    env_url: str
    dv_token: str
    graph: _MinimalGraph | None = None


_VERIFIED_DOMAIN = "contoso.com"
_INITIAL_DOMAIN = "mocktenant.onmicrosoft.com"


@pytest.fixture
def org_with_verified_domains() -> dict[str, Any]:
    """Tenant org record with two verified domains (one initial, one
    custom) — modelled on the Graph mock builder which already cites
    the schema EntityType `organization` and the
    `https://learn.microsoft.com/graph/api/organization-get` example.
    """
    return gx.organization(
        display_name="Mock Tenant",
    ) | {
        "verifiedDomains": [
            {
                "capabilities": "Email,OfficeCommunicationsOnline",
                "isDefault": True,
                "isInitial": True,
                "name": _INITIAL_DOMAIN,
                "type": "Managed",
            },
            {
                "capabilities": "Email,OfficeCommunicationsOnline",
                "isDefault": False,
                "isInitial": False,
                "name": _VERIFIED_DOMAIN,
                "type": "Managed",
            },
        ],
    }


@pytest.fixture
def runner_with_graph(
    fake_dataverse_url: str,
    fake_token: str,
    org_with_verified_domains: dict[str, Any],
) -> _MinimalRunner:
    return _MinimalRunner(
        env_url=fake_dataverse_url,
        dv_token=fake_token,
        graph=_MinimalGraph(org_payload=org_with_verified_domains),
    )


# ───────────────────────────────────────────────────────────────────────
# Helpers — Dataverse mock registration mirrors test_workday_env_vars.py
# ───────────────────────────────────────────────────────────────────────


def _ess_env_var_def(schema_name: str, definition_id: str) -> dict[str, Any]:
    return {
        "@odata.etag": 'W/"1"',
        "displayname": schema_name.replace("EmployeeContext", ""),
        "schemaname": f"new_{schema_name}",
        "environmentvariabledefinitionid": definition_id,
    }


def _ess_env_var_value(definition_id: str, schema_name: str, value: str) -> dict[str, Any]:
    return {
        "@odata.etag": 'W/"1"',
        "value": value,
        "schemaname": f"new_{schema_name}_value",
        "_environmentvariabledefinitionid_value": definition_id,
    }


_DEF_ISU = "00000000-0000-0000-0000-000000006001"


def _register_isu(
    *, base_url: str, isu_value: str | None
) -> None:
    """Register the two paginated Dataverse queries the check makes —
    definitions table contains the ISU definition row; values table
    contains the value row only when isu_value is non-None.
    """
    defs = [_ess_env_var_def("EmployeeContextRequestAccountName", _DEF_ISU)]
    vals: list[dict[str, Any]] = []
    if isu_value is not None:
        vals.append(
            _ess_env_var_value(_DEF_ISU, "EmployeeContextRequestAccountName", isu_value)
        )
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariabledefinitions",
        json=dv.collection(defs),
        status=200,
    )
    responses.add(
        method="GET",
        url=f"{base_url}/api/data/v9.2/environmentvariablevalues",
        json=dv.collection(vals),
        status=200,
    )


def _result(results: list, checkpoint_id: str = "WD-ENV-101"):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ───────────────────────────────────────────────────────────────────────
# Tests — happy path
# ───────────────────────────────────────────────────────────────────────


class TestPassed:
    @responses.activate
    def test_isu_in_upn_format_with_verified_domain_passes(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        from flightcheck.checks.workday import _check_isu_username_format

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value=f"isu_ess@{_VERIFIED_DOMAIN}",
        )

        results = _check_isu_username_format(runner_with_graph)
        r = _result(results)

        assert r.status == "Passed"
        assert r.priority == "High"
        assert _VERIFIED_DOMAIN in r.result
        assert r.doc_link.startswith(
            "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
        )

    @responses.activate
    def test_isu_with_initial_onmicrosoft_domain_passes(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Initial `*.onmicrosoft.com` domain is verified — using it
        for the ISU is a valid (if not preferred) pattern."""
        from flightcheck.checks.workday import _check_isu_username_format

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value=f"isu_ess@{_INITIAL_DOMAIN}",
        )

        results = _check_isu_username_format(runner_with_graph)
        assert _result(results).status == "Passed"


# ───────────────────────────────────────────────────────────────────────
# Tests — bad / warning paths
# ───────────────────────────────────────────────────────────────────────


class TestWarning:
    @responses.activate
    def test_legacy_short_id_format_warns(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Legacy short-ID ISU scenario: ISU left in short-employee-id
        format with no `@` — common on federated tenants (Okta, Ping,
        ADFS) where the ISU was provisioned before adopting UPN-shaped
        service-account naming. Workday cannot match the Entra UPN ESS
        sends to a Worker."""
        from flightcheck.checks.workday import _check_isu_username_format

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value="ISU12345",
        )

        results = _check_isu_username_format(runner_with_graph)
        r = _result(results)

        assert r.status == "Warning"
        assert "does not contain '@'" in r.result
        assert "ISU12345" in r.result
        assert "EmployeeContextRequestAccountName" in r.remediation
        assert "powerplatform" in r.remediation.lower()

    @responses.activate
    def test_unverified_domain_warns(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """ISU `<x>@somethirdpartydomain.com` — could be legitimate
        cross-tenant federation, but worth surfacing for the operator
        to confirm the domain matches the UPN claim ESS actually sends.
        """
        from flightcheck.checks.workday import _check_isu_username_format

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value="isu_ess@unrelated-vendor.example",
        )

        results = _check_isu_username_format(runner_with_graph)
        r = _result(results)

        assert r.status == "Warning"
        assert "unrelated-vendor.example" in r.result
        assert _VERIFIED_DOMAIN in r.result  # lists verified domains for context

    @responses.activate
    def test_graph_returns_no_verified_domains_warns(
        self,
        fake_dataverse_url: str,
        fake_token: str,
    ) -> None:
        """Defensive — Graph returned an org record but with an empty
        verifiedDomains list. Don't pass silently; warn so the operator
        knows the comparison wasn't actually performed."""
        from flightcheck.checks.workday import _check_isu_username_format

        runner = _MinimalRunner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
            graph=_MinimalGraph(
                org_payload=gx.organization(display_name="Mock Tenant") | {
                    "verifiedDomains": [],
                },
            ),
        )

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value="isu_ess@contoso.com",
        )

        results = _check_isu_username_format(runner)
        r = _result(results)

        assert r.status == "Warning"
        assert "no verified domains" in r.result.lower()

    @responses.activate
    def test_graph_returns_empty_org_warns(
        self,
        fake_dataverse_url: str,
        fake_token: str,
    ) -> None:
        """GraphClient.get_organization() returns {} when /organization
        comes back empty (e.g. 401/403 → get_all returns partial empty
        list → orgs[0] if orgs else {}). Surface that as a Warning, not
        a crash, mirroring the existing pattern in _check_connections.
        """
        from flightcheck.checks.workday import _check_isu_username_format

        runner = _MinimalRunner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
            graph=_MinimalGraph(org_payload={}),
        )

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value="isu_ess@contoso.com",
        )

        results = _check_isu_username_format(runner)
        r = _result(results)

        assert r.status == "Warning"
        assert "no tenant record" in r.result.lower()
        assert "Organization.Read.All" in r.remediation

    @responses.activate
    def test_graph_get_organization_raises_warns(
        self,
        fake_dataverse_url: str,
        fake_token: str,
    ) -> None:
        """If Graph itself raises (network, 5xx, etc.) the check must
        not propagate the exception — surface it as a Warning so the
        rest of FlightCheck still runs."""
        from flightcheck.checks.workday import _check_isu_username_format

        runner = _MinimalRunner(
            env_url=fake_dataverse_url,
            dv_token=fake_token,
            graph=_MinimalGraph(raise_exc=RuntimeError("boom")),
        )

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value="isu_ess@contoso.com",
        )

        results = _check_isu_username_format(runner)
        r = _result(results)

        assert r.status == "Warning"
        assert "boom" in r.result


# ───────────────────────────────────────────────────────────────────────
# Tests — skipped paths
# ───────────────────────────────────────────────────────────────────────


class TestSkipped:
    def test_skipped_when_no_dataverse_token(self) -> None:
        from flightcheck.checks.workday import _check_isu_username_format

        runner = _MinimalRunner(env_url="", dv_token="", graph=_MinimalGraph())

        results = _check_isu_username_format(runner)
        r = _result(results)

        assert r.status == "Skipped"
        assert "token not available" in r.result.lower()

    @responses.activate
    def test_skipped_when_no_graph_client_and_isu_in_upn_format(
        self, fake_dataverse_url: str, fake_token: str
    ) -> None:
        """ISU is `<x>@<domain>` and Graph is unavailable — we cannot
        verify domain alignment. SKIP so the operator knows the deeper
        check wasn't performed."""
        from flightcheck.checks.workday import _check_isu_username_format

        runner = _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token, graph=None)

        _register_isu(base_url=fake_dataverse_url, isu_value="isu_ess@contoso.com")
        results = _check_isu_username_format(runner)

        r = _result(results)
        assert r.status == "Skipped"
        assert "graph" in r.result.lower()
        assert "graph sign-in" in r.remediation.lower()

    @responses.activate
    def test_warns_on_legacy_isu_format_even_when_no_graph_client(
        self, fake_dataverse_url: str, fake_token: str
    ) -> None:
        """Regression: the no-`@` legacy-format detection (legacy
        short-ID ISU on a federated tenant) must run off the Dataverse
        value alone and still WARN even when Graph is unavailable.
        Earlier revisions short-circuited to SKIPPED on missing Graph
        and silently dropped this critical signal — pin that this no
        longer happens.
        """
        from flightcheck.checks.workday import _check_isu_username_format

        runner = _MinimalRunner(env_url=fake_dataverse_url, dv_token=fake_token, graph=None)

        _register_isu(base_url=fake_dataverse_url, isu_value="ISU12345")
        results = _check_isu_username_format(runner)

        r = _result(results)
        assert r.status == "Warning", (
            f"Expected legacy ISU format to WARN even without Graph; got "
            f"status={r.status} result={r.result!r}"
        )
        assert "does not contain '@'" in r.result
        assert "ISU12345" in r.result
        assert "EmployeeContextRequestAccountName" in r.remediation

    @responses.activate
    def test_skipped_when_isu_env_var_missing_defers_to_wd_env_001(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """When the env var isn't set, WD-ENV-001 already FAILs with
        the right remediation — this check skips to avoid duplicating
        the same root-cause finding."""
        from flightcheck.checks.workday import _check_isu_username_format

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value=None,  # No value record — env var unset
        )

        results = _check_isu_username_format(runner_with_graph)
        r = _result(results)

        assert r.status == "Skipped"
        assert "WD-ENV-001" in r.result


class TestSimplifiedInstallGate:
    """Pins the install-flavor gating contract for `_check_isu_username_format`
    (see AGENTS.md design principle #11). WD-ENV-101 inspects an ISU
    service-account username — a concept that does not exist on the
    simplified install (OBO uses the signed-in user's identity).

    Skip semantics mirror `_check_env_vars` — only skip on a positive
    "simplified" match; any other verdict runs the existing logic.
    """

    def test_simplified_skips_with_correct_message(self) -> None:
        """`flavor == "simplified"` → single SKIPPED row, zero HTTP
        calls (gate fires before any Dataverse or Graph read)."""
        from flightcheck.checks.workday import _check_isu_username_format

        runner = _MinimalRunner(
            env_url="https://dv.example",
            dv_token="dv-token",
            graph=_MinimalGraph(),
        )
        runner._workday_package_flavor = "simplified"

        results = _check_isu_username_format(runner)
        r = _result(results)

        assert r.status == "Skipped"
        assert r.priority == "High"
        assert "WD-PKG-001" in r.result
        assert "simplified" in r.result.lower()
        # Remediation must surface the `{ff0df}`-only ambiguity so an
        # operator who intended the full install doesn't dismiss it.
        assert "Generic User" in r.remediation
        assert "Context Generic User" in r.remediation
        assert "workday-simplified-setup" in r.doc_link

    @responses.activate
    def test_full_verdict_runs_existing_logic_unchanged(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """`flavor == "full"` → check runs as today and reports the
        real underlying state (PASSED in this happy-path mock)."""
        from flightcheck.checks.workday import _check_isu_username_format

        runner_with_graph._workday_package_flavor = "full"
        _register_isu(
            base_url=fake_dataverse_url,
            isu_value=f"isu_ess@{_VERIFIED_DOMAIN}",
        )

        results = _check_isu_username_format(runner_with_graph)
        assert _result(results).status == "Passed"

    @responses.activate
    @pytest.mark.parametrize("flavor", ["partial", "unknown", "none", "skipped"])
    def test_ambiguous_verdicts_still_run_existing_logic(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str, flavor: str,
    ) -> None:
        """Per AGENTS.md principle #11.b: skip ONLY on `"simplified"`.
        Anything else — partial install, unknown shape, no Workday refs
        at all, or Dataverse-skipped — runs the existing logic so
        operators debugging a broken install see every signal.

        Pinned with a legacy-short-ID ISU so we observe a real WARNING
        rather than a SKIP that could be the gate's. If a future
        rewrite accidentally widens the gate (`if flavor != "full": skip`),
        this test catches it.
        """
        from flightcheck.checks.workday import _check_isu_username_format

        runner_with_graph._workday_package_flavor = flavor
        _register_isu(base_url=fake_dataverse_url, isu_value="ISU12345")

        results = _check_isu_username_format(runner_with_graph)
        r = _result(results)
        assert r.status == "Warning", (
            f"flavor={flavor!r} must run existing logic and WARN on legacy "
            f"short-ID ISU; got status={r.status}"
        )
        assert "does not contain '@'" in r.result

    @responses.activate
    def test_attribute_absent_runs_existing_logic_for_backwards_compat(
        self, runner_with_graph: _MinimalRunner, fake_dataverse_url: str
    ) -> None:
        """Backwards-compat: minimal test runners that don't set
        `_workday_package_flavor` (e.g. the existing `_MinimalRunner`
        dataclass default) must continue producing the pre-gating
        behavior. The `getattr(..., None)` default enables this."""
        from flightcheck.checks.workday import _check_isu_username_format

        assert not hasattr(runner_with_graph, "_workday_package_flavor")

        _register_isu(
            base_url=fake_dataverse_url,
            isu_value=f"isu_ess@{_VERIFIED_DOMAIN}",
        )

        results = _check_isu_username_format(runner_with_graph)
        assert _result(results).status == "Passed"
