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


def test_clear_token_cache_removes_only_rejected_account(
    tmp_path, monkeypatch
) -> None:
    import auth

    removed = []

    class FakeCache:
        has_state_changed = True

        def serialize(self):
            return "remaining-account-cache"

    class FakeApp:
        def remove_account(self, account):
            removed.append(account)

    monkeypatch.chdir(tmp_path)
    local = tmp_path / ".local"
    local.mkdir()
    cache = local / ".token_cache.bin"
    preserved = local / "config.json"
    cache.write_text("cached", encoding="utf-8")
    preserved.write_text("{}", encoding="utf-8")

    account = {"home_account_id": "rejected-account"}
    auth.clear_token_cache(
        "https://example.crm.dynamics.com",
        cache=FakeCache(),
        app=FakeApp(),
        account=account,
    )

    assert removed == [account]
    assert cache.read_text(encoding="utf-8") == "remaining-account-cache"
    assert preserved.exists()


@responses.activate
def test_dataverse_token_validation_detects_401(
    dataverse_url: str,
) -> None:
    import auth

    responses.add(
        responses.GET,
        f"{dataverse_url}/api/data/v9.2/WhoAmI",
        status=401,
        json={"error": {"code": "InvalidToken"}},
    )

    assert not auth._dataverse_accepts_token(dataverse_url, "stale-token")


def test_authenticate_replaces_dataverse_rejected_cached_token(
    tmp_path, monkeypatch
) -> None:
    import auth

    class FakeCache:
        def __init__(self) -> None:
            self.has_state_changed = True

        def deserialize(self, value: str) -> None:
            assert value == "cached"

        def serialize(self) -> str:
            return "refreshed"

    class FakeApp:
        instances = 0

        def __init__(self, *args, **kwargs) -> None:
            self.instance = FakeApp.instances
            FakeApp.instances += 1

        def get_accounts(self) -> list[dict]:
            return [{"home_account_id": "account"}]

        def acquire_token_silent(self, scopes, account):
            assert self.instance == 0
            return {"access_token": "stale-token"}

        def acquire_token_interactive(self, scopes, prompt):
            assert self.instance == 1
            return {"access_token": "fresh-token"}

        def remove_account(self, account):
            assert self.instance == 0
            assert account == {"home_account_id": "account"}

    monkeypatch.chdir(tmp_path)
    local = tmp_path / ".local"
    local.mkdir()
    (local / ".token_cache.bin").write_text("cached", encoding="utf-8")
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: "tenant-id")
    monkeypatch.setattr(
        auth,
        "_dataverse_accepts_token",
        lambda _url, token: token != "stale-token",
    )
    monkeypatch.setattr(auth.msal, "SerializableTokenCache", FakeCache)
    monkeypatch.setattr(auth.msal, "PublicClientApplication", FakeApp)

    token = auth.authenticate("https://example.crm.dynamics.com")

    assert token == "fresh-token"
    assert FakeApp.instances == 2
    assert (local / ".token_cache.bin").read_text(
        encoding="utf-8"
    ) == "refreshed"


def test_authenticate_resolves_tenant_name_before_start_session(
    tmp_path, monkeypatch
) -> None:
    """The ADK telemetry bootstrap in ``authenticate`` must resolve the
    tenant display name via SILENT-ONLY Graph BEFORE emitting the first
    ``adk.session.start`` event, so that first event carries ``tenant_name``.

    Before this ordering fix, ``start_session`` fired first, so the very
    first session_start on a fresh install always went out with blank
    tenant_name (only later events -- once FlightCheck interactively
    resolved and cached the name -- picked it up). This is a regression
    test for that ordering: silent resolution runs first, its result is
    fed to ``set_identity``, and only then does ``start_session`` emit.

    Asserts on the actual OneCollector envelope (not just call ordering)
    so that a regression where ``start_session`` internally wipes the
    ``tenant_name`` that ``set_identity`` just stored -- the exact
    reviewer-flagged bug that ``set_identity``'s ``None``-sentinel refactor
    fixes -- shows up as an assertion failure on the emitted payload.
    """
    import auth
    import adk_telemetry
    from flightcheck import graph_client
    from flightcheck import telemetry as fc_telemetry

    class FakeCache:
        has_state_changed = False

        def deserialize(self, value: str) -> None:
            pass

        def serialize(self) -> str:
            return ""

    class FakeApp:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_accounts(self) -> list[dict]:
            return []

        def acquire_token_silent(self, scopes, account):
            return None

        def acquire_token_interactive(self, scopes, prompt):
            return {
                "access_token": "fresh-token",
                "id_token_claims": {
                    "tid": "00000000-0000-0000-0000-0000000000ab"
                },
            }

    monkeypatch.chdir(tmp_path)
    # Isolate ADK telemetry state (so we don't touch ~/.adk on the dev box).
    cfg_dir = tmp_path / ".adk"
    monkeypatch.setattr(adk_telemetry, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(adk_telemetry, "CONFIG_PATH", str(cfg_dir / "config"))
    monkeypatch.setattr(
        adk_telemetry, "SESSION_PATH", str(cfg_dir / "session.json")
    )
    monkeypatch.setattr(
        adk_telemetry, "BUFFER_PATH", str(cfg_dir / "telemetry-buffer.ndjson")
    )
    monkeypatch.setattr(adk_telemetry, "_SYNC", True)
    monkeypatch.setattr(
        adk_telemetry,
        "_IDENTITY",
        {"instance_id": "", "tenant_id": "", "tenant_name": ""},
    )
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "on")

    monkeypatch.setattr(
        auth, "discover_tenant", lambda _url: "00000000-0000-0000-0000-0000000000ab"
    )
    monkeypatch.setattr(auth, "_dataverse_accepts_token", lambda _url, _tok: True)
    monkeypatch.setattr(auth.msal, "SerializableTokenCache", FakeCache)
    monkeypatch.setattr(auth.msal, "PublicClientApplication", FakeApp)

    monkeypatch.setattr(
        graph_client,
        "resolve_tenant_display_name_silent",
        lambda tid: (
            "Contoso Ltd"
            if tid == "00000000-0000-0000-0000-0000000000ab"
            else ""
        ),
    )

    # Instrument the OneCollector boundary to assert on real payloads.
    envelopes: list[tuple[str, list[dict]]] = []

    def _fake_post(ikey, evs):
        envelopes.append((ikey, evs))
        return 200

    monkeypatch.setattr(fc_telemetry, "_post", _fake_post)

    token = auth.authenticate("https://example.crm.dynamics.com")
    assert token == "fresh-token"

    starts = [
        ev
        for _ikey, batch in envelopes
        for ev in batch
        if ev.get("name") == "adk.session.start"
    ]
    assert starts, "expected a session_start envelope; got %r" % envelopes
    data = starts[-1].get("data", {})
    # Reviewer's Fix #2: start_session must NOT internally wipe the
    # tenant_name that set_identity stored a millisecond earlier.
    assert data.get("tenant_id") == "00000000-0000-0000-0000-0000000000ab", data
    assert data.get("tenant_name") == "Contoso Ltd", data


def test_authenticate_still_emits_when_silent_graph_returns_blank(
    tmp_path, monkeypatch
) -> None:
    """When silent Graph resolution yields no name (both scopes admin-only
    or unconsented), the bootstrap must still emit ``adk.session.start`` --
    just with a blank ``tenant_name``. Telemetry stays best-effort and
    non-blocking; the missing-name case degrades to blank (recoverable when
    the maker later runs FlightCheck).

    This test is deliberately *end-to-end at the transport boundary*: it
    monkeypatches only the OneCollector ``_post`` (as ``captured_post`` in
    ``test_adk_telemetry.py`` does), so a regression that silently wipes
    ``tenant_name`` inside ``start_session`` -- or that skips the session
    emit entirely on the blank-name path -- shows up as a real assertion
    failure on the actual envelope payload. Trivial recorders that only
    watch ``set_identity`` / ``start_session`` call order would NOT catch
    such a regression, because the wipe happens *inside* one of those.
    """
    import auth
    import adk_telemetry
    from flightcheck import graph_client
    from flightcheck import telemetry as fc_telemetry

    class FakeCache:
        has_state_changed = False

        def deserialize(self, value: str) -> None:
            pass

        def serialize(self) -> str:
            return ""

    class FakeApp:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_accounts(self) -> list[dict]:
            return []

        def acquire_token_silent(self, scopes, account):
            return None

        def acquire_token_interactive(self, scopes, prompt):
            return {
                "access_token": "fresh-token",
                "id_token_claims": {
                    "tid": "00000000-0000-0000-0000-0000000000ab"
                },
            }

    monkeypatch.chdir(tmp_path)
    # Isolate ADK state so we don't leak into ~/.adk on the dev box.
    cfg_dir = tmp_path / ".adk"
    monkeypatch.setattr(adk_telemetry, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(adk_telemetry, "CONFIG_PATH", str(cfg_dir / "config"))
    monkeypatch.setattr(
        adk_telemetry, "SESSION_PATH", str(cfg_dir / "session.json")
    )
    monkeypatch.setattr(
        adk_telemetry, "BUFFER_PATH", str(cfg_dir / "telemetry-buffer.ndjson")
    )
    monkeypatch.setattr(adk_telemetry, "_SYNC", True)
    monkeypatch.setattr(
        adk_telemetry,
        "_IDENTITY",
        {"instance_id": "", "tenant_id": "", "tenant_name": ""},
    )
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "on")

    monkeypatch.setattr(auth, "discover_tenant", lambda _url: "00000000-0000-0000-0000-0000000000ab")
    monkeypatch.setattr(auth, "_dataverse_accepts_token", lambda _url, _tok: True)
    monkeypatch.setattr(auth.msal, "SerializableTokenCache", FakeCache)
    monkeypatch.setattr(auth.msal, "PublicClientApplication", FakeApp)

    # Silent resolver returns "" (Organization.Read.All + User.Read both
    # silently unavailable, as happens for a large fraction of enterprise
    # tenants on first Dataverse sign-in).
    monkeypatch.setattr(
        graph_client, "resolve_tenant_display_name_silent", lambda tid: ""
    )

    # Capture actual envelopes at the OneCollector boundary. This is what
    # would land in Aria in prod, so assertions here are the strongest
    # possible: they catch any regression that wipes tenant_name inside
    # set_identity / start_session, not just missing call orderings.
    envelopes: list[tuple[str, list[dict]]] = []

    def _fake_post(ikey, evs):
        envelopes.append((ikey, evs))
        return 200

    monkeypatch.setattr(fc_telemetry, "_post", _fake_post)

    token = auth.authenticate("https://example.crm.dynamics.com")
    assert token == "fresh-token"

    # A session_start envelope must have been emitted, carrying the raw
    # tenant_id (so it lands on the customer-filtered dashboard) with a
    # blank tenant_name (silent resolution failed).
    starts = [
        ev
        for _ikey, batch in envelopes
        for ev in batch
        if ev.get("name") == "adk.session.start"
    ]
    assert starts, "expected an adk.session.start envelope; got %r" % envelopes
    data = starts[-1].get("data", {})
    assert data.get("tenant_id") == "00000000-0000-0000-0000-0000000000ab", data
    assert data.get("tenant_name") == "", data
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


class TestExecuteAction:
    @responses.activate
    def test_posts_unbound_action(
        self,
        dataverse_url: str,
        fake_token: str,
    ) -> None:
        import auth

        responses.add(
            method="POST",
            url=f"{dataverse_url}/api/data/v9.2/SetPreferredSolution",
            status=204,
        )

        result = auth.execute_action(
            dataverse_url,
            fake_token,
            "SetPreferredSolution",
            {"SolutionId": "11111111-1111-1111-1111-111111111111"},
        )

        assert result == {}
        action_call = next(
            call for call in responses.calls
            if call.request.url.endswith("/SetPreferredSolution")
        )
        assert action_call.request.headers["Authorization"] == (
            f"Bearer {fake_token}"
        )
        assert json.loads(action_call.request.body) == {
            "SolutionId": "11111111-1111-1111-1111-111111111111"
        }

    def test_rejects_bound_or_nested_action_name(
        self,
        dataverse_url: str,
        fake_token: str,
    ) -> None:
        import auth

        with pytest.raises(ValueError, match="unbound action name"):
            auth.execute_action(
                dataverse_url,
                fake_token,
                "bots(id)/Microsoft.Dynamics.CRM.Action",
                {},
            )
