# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for tests/mocks/dataverse.py.

Two layers:

1. Direct: each builder produces a payload with the expected shape.
2. Round-trip: register the builders with `responses` and drive the real
   production functions in scripts/auth.py through them. This proves
   both the mock and the production code agree on the wire format.
"""

from __future__ import annotations

import pytest
import responses

from tests.mocks import dataverse as dv


# ─────────────── Layer 1: builders produce the right shape ────────────


class TestPayloadBuilders:
    def test_who_am_i_has_expected_keys(self) -> None:
        payload = dv.who_am_i()
        for key in ("BusinessUnitId", "UserId", "OrganizationId"):
            assert key in payload, f"missing {key}"

    def test_bot_record_has_botid_and_metadata(self) -> None:
        payload = dv.bot()
        assert payload["botid"] == dv.MOCK_BOT_ID
        assert "schemaname" in payload
        assert "ismanaged" in payload
        assert "@odata.etag" in payload

    def test_bot_component_links_to_parent(self) -> None:
        payload = dv.bot_component(parent_bot_id="parent-123")
        assert payload["_parentbotid_value"] == "parent-123"
        assert payload["componenttype"] == 9  # topic default

    def test_env_var_def_uses_schema_name(self) -> None:
        payload = dv.env_var_def(schema_name="MyVar")
        assert payload["schemaname"] == "MyVar"

    def test_env_var_value_links_to_definition(self) -> None:
        payload = dv.env_var_value(definition_id="def-1", value="hello")
        assert payload["_environmentvariabledefinitionid_value"] == "def-1"
        assert payload["value"] == "hello"

    def test_collection_wraps_records_with_value_key(self) -> None:
        payload = dv.collection([{"a": 1}, {"a": 2}])
        assert payload["value"] == [{"a": 1}, {"a": 2}]
        assert "@odata.nextLink" not in payload

    def test_collection_with_next_link_includes_it(self) -> None:
        payload = dv.collection([], next_link="https://x/?page=2")
        assert payload["@odata.nextLink"] == "https://x/?page=2"


# ─────────────── Layer 2: round-trip through production code ──────────


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
    """Drives scripts/auth.py:query_all through the mock."""

    @responses.activate
    def test_single_page_returns_all_records(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        records = [
            dv.bot_component(name="Topic1"),
            dv.bot_component(name="Topic2"),
            dv.bot_component(name="Topic3"),
        ]
        responses.add(**dv.query(
            base_url=dataverse_url,
            entity_set="botcomponents",
            select="botcomponentid,name,componenttype,schemaname",
            records=records,
        ))

        result = auth.query_all(
            dataverse_url, fake_token,
            "botcomponents",
            "botcomponentid,name,componenttype,schemaname",
        )
        assert len(result) == 3
        assert {r["name"] for r in result} == {"Topic1", "Topic2", "Topic3"}

    @responses.activate
    def test_follows_odata_next_link_across_pages(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        page1_url = f"{dataverse_url}/api/data/v9.2/botcomponents?$select=name"
        page2_url = f"{dataverse_url}/api/data/v9.2/botcomponents?$skiptoken=PAGE2"

        responses.add(
            method="GET",
            url=page1_url,
            json=dv.collection(
                [dv.bot_component(name=f"T{i}") for i in range(2)],
                next_link=page2_url,
            ),
            status=200,
        )
        responses.add(
            method="GET",
            url=page2_url,
            json=dv.collection(
                [dv.bot_component(name=f"T{i}") for i in range(2, 5)]
            ),
            status=200,
        )

        result = auth.query_all(
            dataverse_url, fake_token, "botcomponents", "name",
        )
        assert len(result) == 5
        assert [r["name"] for r in result] == ["T0", "T1", "T2", "T3", "T4"]

    @responses.activate
    def test_raises_auth_expired_on_401(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        responses.add(**dv.auth_expired(
            base_url=dataverse_url, entity_set="botcomponents"
        ))

        with pytest.raises(auth.AuthExpiredError):
            auth.query_all(dataverse_url, fake_token, "botcomponents", "name")

    @responses.activate
    def test_sends_bearer_token(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        responses.add(**dv.query(
            base_url=dataverse_url,
            entity_set="bots",
            select="name",
            records=[],
        ))

        auth.query_all(dataverse_url, fake_token, "bots", "name")

        # Inspect the captured request.
        sent = responses.calls[0].request
        assert sent.headers["Authorization"] == f"Bearer {fake_token}"

    def test_rejects_http_url_before_sending(self, fake_token: str) -> None:
        import auth

        with pytest.raises(ValueError, match="https"):
            auth.query_all("http://insecure/", fake_token, "bots", "name")


class TestUpdateRecord:
    """Drives scripts/auth.py:update_record through the mock."""

    @responses.activate
    def test_patches_record_returns_true_on_success(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        record_id = "00000000-0000-0000-0000-000000003333"
        responses.add(
            method="PATCH",
            url=f"{dataverse_url}/api/data/v9.2/bots({record_id})",
            status=204,
        )

        result = auth.update_record(
            dataverse_url, fake_token, "bots", record_id, {"name": "Renamed"}
        )
        assert result is True

    @responses.activate
    def test_raises_auth_expired_on_401(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        record_id = "00000000-0000-0000-0000-000000003333"
        responses.add(
            method="PATCH",
            url=f"{dataverse_url}/api/data/v9.2/bots({record_id})",
            status=401,
            json={"error": {"message": "expired"}},
        )

        with pytest.raises(auth.AuthExpiredError):
            auth.update_record(
                dataverse_url, fake_token, "bots", record_id, {"name": "x"}
            )
