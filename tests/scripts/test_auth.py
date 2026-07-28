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

import json

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


class TestCreateRecord:
    """Drives scripts/auth.py:create_record through the mock.

    create_record must return the NEW record's GUID for ANY entity set, not
    just ``botcomponents``. The historical bug: it read
    ``result.get("botcomponentid", result.get("id"))`` from the
    representation body, so a ``workflows`` create (whose primary key is
    ``workflowid``) returned ``None``. That null propagated into
    ``.component-map.json`` as ``"workflowid": null``, which made the next
    ``/push`` skip the flow entirely ("no workflow ID in map") and printed
    ``Created: ... (ID: None)``. See session findings
    ``adk-gap-createrecord-idkey-rootcause`` / ``adk-fix-map-null-workflowid``.

    The contract these tests pin: prefer the entity-agnostic
    ``OData-EntityId`` response header; fall back to the entity-specific
    primary-key column in the representation body.
    """

    @responses.activate
    def test_returns_workflowid_for_workflow_create(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        """Regression: a workflows create must return the workflowid, not None."""
        import auth

        wf_id = "d4e5f6a7-1111-2222-3333-444455556666"
        responses.add(**dv.create_record_response(
            base_url=dataverse_url,
            entity_set="workflows",
            record_id=wf_id,
        ))

        result = auth.create_record(
            dataverse_url, fake_token, "workflows",
            {"name": "Options flow", "clientdata": "{}"},
        )
        assert result == wf_id

    @responses.activate
    def test_returns_botcomponentid_for_botcomponent_create(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        """The botcomponents path (previously the only working one) still works."""
        import auth

        bc_id = "342bebe6-1111-2222-3333-444455556666"
        responses.add(**dv.create_record_response(
            base_url=dataverse_url,
            entity_set="botcomponents",
            record_id=bc_id,
        ))

        result = auth.create_record(
            dataverse_url, fake_token, "botcomponents",
            {"name": "System topic", "schemaname": "mspva_x"},
        )
        assert result == bc_id

    @responses.activate
    def test_returns_connectionreferenceid_for_connref_create(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        """A connectionreferences create returns connectionreferenceid."""
        import auth

        cr_id = "8be14999-1111-2222-3333-444455556666"
        responses.add(**dv.create_record_response(
            base_url=dataverse_url,
            entity_set="connectionreferences",
            record_id=cr_id,
        ))

        result = auth.create_record(
            dataverse_url, fake_token, "connectionreferences",
            {"connectionreferencelogicalname": "msdyn_x.shared_service-now"},
        )
        assert result == cr_id

    @responses.activate
    def test_reads_id_from_odata_entityid_header_when_no_body(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        """A header-only (204, no representation) create still yields the GUID."""
        import auth

        wf_id = "7536348b-1111-2222-3333-444455556666"
        responses.add(**dv.create_record_response(
            base_url=dataverse_url,
            entity_set="workflows",
            record_id=wf_id,
            return_representation=False,
            status=204,
        ))

        result = auth.create_record(
            dataverse_url, fake_token, "workflows",
            {"name": "Options flow"},
        )
        assert result == wf_id

    @responses.activate
    def test_falls_back_to_body_when_header_absent(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        """With no OData-EntityId header, the representation body key is used."""
        import auth

        wf_id = "11112222-3333-4444-5555-666677778888"
        responses.add(**dv.create_record_response(
            base_url=dataverse_url,
            entity_set="workflows",
            record_id=wf_id,
            include_entity_id_header=False,
        ))

        result = auth.create_record(
            dataverse_url, fake_token, "workflows",
            {"name": "Options flow"},
        )
        assert result == wf_id


class TestAssociateRef:
    """Drives scripts/auth.py:associate_ref through the mock.

    ``associate_ref`` creates a Dataverse N:N link by POSTing an ``@odata.id``
    pointer to a collection-valued navigation property's ``/$ref`` endpoint.
    The ADK use case is ``botcomponent_workflow`` — wiring a system-topic
    botcomponent to the workflow it invokes so Copilot Studio's publish
    validator can resolve the flow reference (root cause of CloudFlow-not-found
    when the link is missing).
    """

    @responses.activate
    def test_posts_odata_id_pointer_and_returns_true(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        bc_id = "d1c227f6-1111-2222-3333-444455556666"
        wf_id = "5d1d1bb2-1111-2222-3333-444455556666"
        responses.add(**dv.associate_ref_response(
            base_url=dataverse_url,
            entity_set="botcomponents",
            record_id=bc_id,
            nav_property="botcomponent_workflow",
        ))

        result = auth.associate_ref(
            dataverse_url, fake_token,
            "botcomponents", bc_id, "botcomponent_workflow",
            "workflows", wf_id,
        )
        assert result is True

        sent = responses.calls[0].request
        assert sent.url == (
            f"{dataverse_url}/api/data/v9.2/"
            f"botcomponents({bc_id})/botcomponent_workflow/$ref"
        )
        body = json.loads(sent.body)
        assert body == {
            "@odata.id": f"{dataverse_url}/api/data/v9.2/workflows({wf_id})"
        }

    @responses.activate
    def test_raises_auth_expired_on_401(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        responses.add(
            method="POST",
            url=(
                f"{dataverse_url}/api/data/v9.2/"
                "botcomponents(bc)/botcomponent_workflow/$ref"
            ),
            status=401,
        )
        with pytest.raises(auth.AuthExpiredError):
            auth.associate_ref(
                dataverse_url, fake_token,
                "botcomponents", "bc", "botcomponent_workflow",
                "workflows", "wf",
            )

    def test_rejects_http_url_before_sending(self, fake_token: str) -> None:
        import auth

        with pytest.raises(ValueError, match="https"):
            auth.associate_ref(
                "http://insecure/", fake_token,
                "botcomponents", "bc", "botcomponent_workflow",
                "workflows", "wf",
            )


class TestPublishBot:
    """Drives scripts/auth.py:publish_bot through the mock.

    Publishing a Copilot Studio bot makes pushed botcomponent (topic) changes
    go live in the test pane and runtime — Dataverse writes alone don't take
    effect until publish. It is the unbound Dataverse action ``PvaPublish``
    with a ``botid`` payload.
    """

    @responses.activate
    def test_posts_botid_and_returns_true(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        bot_id = "00000000-0000-0000-0000-0000000b0771"
        responses.add(**dv.pva_publish_response(
            base_url=dataverse_url, bot_id=bot_id))

        result = auth.publish_bot(dataverse_url, fake_token, bot_id)
        assert result is True

        sent = responses.calls[0].request
        assert sent.url == (
            f"{dataverse_url}/api/data/v9.2/"
            f"bots({bot_id})/Microsoft.Dynamics.CRM.PvaPublish"
        )

    @responses.activate
    def test_raises_auth_expired_on_401(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        bot_id = "bot"
        responses.add(
            method="POST",
            url=(
                f"{dataverse_url}/api/data/v9.2/"
                f"bots({bot_id})/Microsoft.Dynamics.CRM.PvaPublish"
            ),
            status=401,
        )
        with pytest.raises(auth.AuthExpiredError):
            auth.publish_bot(dataverse_url, fake_token, bot_id)

    def test_rejects_http_url_before_sending(self, fake_token: str) -> None:
        import auth

        with pytest.raises(ValueError, match="https"):
            auth.publish_bot("http://insecure/", fake_token, "bot")


class TestRecordExists:
    """Drives scripts/auth.py:record_exists through the mock.

    Detects a stale component-map id: a GET on a missing Dataverse record
    returns a clean 404, whereas a PATCH against the same missing id returns an
    ambiguous 400 — so existence must be probed with GET, not inferred from a
    failed update.
    """

    @responses.activate
    def test_true_when_record_exists(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        wf_id = "11111111-2222-3333-4444-555566667777"
        responses.add(**dv.record_get(
            base_url=dataverse_url, entity_set="workflows",
            record_id=wf_id, id_key="workflowid", exists=True))

        assert auth.record_exists(
            dataverse_url, fake_token, "workflows", wf_id, "workflowid") is True

    @responses.activate
    def test_false_when_record_missing(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        bc_id = "deadbeef-0000-4000-8000-000000000001"
        responses.add(**dv.record_get(
            base_url=dataverse_url, entity_set="botcomponents",
            record_id=bc_id, id_key="botcomponentid", exists=False))

        assert auth.record_exists(
            dataverse_url, fake_token, "botcomponents", bc_id,
            "botcomponentid") is False

    @responses.activate
    def test_raises_auth_expired_on_401(
        self, dataverse_url: str, fake_token: str
    ) -> None:
        import auth

        responses.add(
            method="GET",
            url=f"{dataverse_url}/api/data/v9.2/workflows(x)?$select=workflowid",
            status=401,
        )
        with pytest.raises(auth.AuthExpiredError):
            auth.record_exists(
                dataverse_url, fake_token, "workflows", "x", "workflowid")

    def test_rejects_http_url_before_sending(self, fake_token: str) -> None:
        import auth

        with pytest.raises(ValueError, match="https"):
            auth.record_exists(
                "http://insecure/", fake_token, "workflows", "x", "workflowid")

