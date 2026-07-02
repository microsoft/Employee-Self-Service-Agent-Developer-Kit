# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/auth.py.

Round-trips production code in auth.py through the mocks in
tests/mocks/dataverse.py to prove the kit's Dataverse client correctly
handles paginated responses, 401/403 errors, and the WWW-Authenticate
challenge format.

Two of the discover_tenant tests are regression tests pinning a known
regex bug — see the test docstrings.
"""

from __future__ import annotations

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import dataverse as dv

require_validated_mock(dv)


@pytest.fixture
def dataverse_url(fake_dataverse_url: str) -> str:
    return fake_dataverse_url


class TestDiscoverTenant:
    """Drives scripts/auth.py:discover_tenant through the mock.

    The kit's regex `login\\.microsoftonline\\.com/([^/]+)` is fragile.
    Two of the three documented Microsoft challenge formats trigger
    over-capture. The tests below pin which formats work and which
    leak garbage into the returned tenant ID. When the regex is
    tightened (TODO: solutions/ess-maker-skills/scripts/auth.py:110),
    flip the regression-test assertions.
    """

    @responses.activate
    def test_extracts_tenant_id_from_bare_unquoted_header(
        self, dataverse_url: str
    ) -> None:
        """Happy path: bare unquoted authorization_uri, no suffix."""
        import auth

        responses.add(**dv.discover_tenant_challenge(
            base_url=dataverse_url,
            tenant_id="11111111-2222-3333-4444-555555555555",
        ))

        result = auth.discover_tenant(dataverse_url)
        assert result == "11111111-2222-3333-4444-555555555555"

    @responses.activate
    def test_overcaptures_when_header_includes_resource_id(
        self, dataverse_url: str
    ) -> None:
        """Regression: even unquoted, the regex over-captures across the
        comma into the resource_id suffix.

        TODO: tighten regex in auth.py:110.
        """
        import auth

        responses.add(**dv.discover_tenant_challenge(
            base_url=dataverse_url,
            tenant_id="11111111-2222-3333-4444-555555555555",
            include_resource_id=True,
        ))

        result = auth.discover_tenant(dataverse_url)
        assert result.startswith("11111111-2222-3333-4444-555555555555")
        assert "resource_id" in result, (
            "auth.discover_tenant regex was tightened — flip this assertion."
        )

    @responses.activate
    def test_overcaptures_when_header_is_quoted(
        self, dataverse_url: str
    ) -> None:
        """Regression: regex over-captures the closing quote in
        authorization_uri="..." (RFC 7235 quoted-string).

        TODO: tighten regex in auth.py:110.
        """
        import auth

        responses.add(**dv.discover_tenant_challenge(
            base_url=dataverse_url,
            tenant_id="11111111-2222-3333-4444-555555555555",
            quoted=True,
        ))

        result = auth.discover_tenant(dataverse_url)
        assert result.startswith("11111111-2222-3333-4444-555555555555")
        assert result.endswith('"'), (
            "auth.discover_tenant regex was tightened — flip this assertion."
        )

    @responses.activate
    def test_falls_back_to_organizations_when_header_missing(
        self, dataverse_url: str
    ) -> None:
        import auth

        responses.add(
            method="GET",
            url=f"{dataverse_url}/api/data/v9.2/",
            status=401,
            json={"error": "no header"},
        )
        result = auth.discover_tenant(dataverse_url)
        assert result == "organizations"

    def test_rejects_http_url(self) -> None:
        import auth

        with pytest.raises(ValueError, match="https"):
            auth.discover_tenant("http://insecure.example/")


class TestQueryAll:
    """Drives scripts/auth.py:query_all through the mock.

    query_all is the FlightCheck-relevant slice of auth.py — it's used by
    flightcheck/checks/workday.py to read environment variable definitions
    and values from Dataverse.
    """

    @responses.activate
    def test_single_page_returns_all_records(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        records = [
            dv.env_var_def(schema_name="VarA", definition_id="def-a"),
            dv.env_var_def(schema_name="VarB", definition_id="def-b"),
            dv.env_var_def(schema_name="VarC", definition_id="def-c"),
        ]
        responses.add(**dv.query(
            base_url=dataverse_url,
            entity_set="environmentvariabledefinitions",
            select="displayname,schemaname,environmentvariabledefinitionid",
            records=records,
        ))

        result = auth.query_all(
            dataverse_url, fake_token,
            "environmentvariabledefinitions",
            "displayname,schemaname,environmentvariabledefinitionid",
        )
        assert len(result) == 3
        assert {r["schemaname"] for r in result} == {"VarA", "VarB", "VarC"}

    @responses.activate
    def test_follows_odata_next_link_across_pages(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        page1_url = (
            f"{dataverse_url}/api/data/v9.2/environmentvariablevalues?$select=value"
        )
        page2_url = (
            f"{dataverse_url}/api/data/v9.2/environmentvariablevalues?$skiptoken=PAGE2"
        )

        responses.add(
            method="GET",
            url=page1_url,
            json=dv.collection(
                [dv.env_var_value(value=f"V{i}", value_id=f"id-{i}") for i in range(2)],
                next_link=page2_url,
            ),
            status=200,
        )
        responses.add(
            method="GET",
            url=page2_url,
            json=dv.collection(
                [dv.env_var_value(value=f"V{i}", value_id=f"id-{i}") for i in range(2, 5)]
            ),
            status=200,
        )

        result = auth.query_all(
            dataverse_url, fake_token, "environmentvariablevalues", "value",
        )
        assert len(result) == 5
        assert [r["value"] for r in result] == ["V0", "V1", "V2", "V3", "V4"]

    @responses.activate
    def test_raises_auth_expired_on_401(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        responses.add(**dv.auth_expired(
            base_url=dataverse_url, entity_set="environmentvariabledefinitions"
        ))

        with pytest.raises(auth.AuthExpiredError):
            auth.query_all(
                dataverse_url, fake_token,
                "environmentvariabledefinitions", "schemaname",
            )

    @responses.activate
    def test_emits_api_call_on_client_error_before_raising(
        self, dataverse_url: str, fake_token: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 403 read must be recorded in api-call telemetry, not silently
        dropped, so failed reads show up in the outcome distribution alongside
        create/update/delete/get failures. (5xx is retried by the Session and
        surfaces as RetryError before reaching here; 403 falls straight
        through to raise_api_error.)"""
        import auth

        calls: list[dict] = []
        monkeypatch.setattr(
            auth,
            "_emit_api_call",
            lambda endpoint, op, start, *, status=None, error=None: calls.append(
                {"endpoint": endpoint, "op": op, "status": status}
            ),
        )

        responses.add(
            responses.GET,
            dv.build_query_url(
                dataverse_url,
                "environmentvariabledefinitions",
                select="schemaname",
            ),
            json={"error": {"code": "0x80040220", "message": "forbidden"}},
            status=403,
        )

        with pytest.raises(auth.APIError):
            auth.query_all(
                dataverse_url, fake_token,
                "environmentvariabledefinitions", "schemaname",
            )

        assert calls == [
            {"endpoint": "environmentvariabledefinitions", "op": "read", "status": 403}
        ]

    @responses.activate
    def test_sends_bearer_token(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        responses.add(**dv.query(
            base_url=dataverse_url,
            entity_set="environmentvariabledefinitions",
            select="schemaname",
            records=[],
        ))

        auth.query_all(
            dataverse_url, fake_token,
            "environmentvariabledefinitions", "schemaname",
        )

        sent = responses.calls[0].request
        assert sent.headers["Authorization"] == f"Bearer {fake_token}"

    def test_rejects_http_url_before_sending(self, fake_token: str) -> None:
        import auth

        with pytest.raises(ValueError, match="https"):
            auth.query_all(
                "http://insecure/", fake_token,
                "environmentvariabledefinitions", "schemaname",
            )
