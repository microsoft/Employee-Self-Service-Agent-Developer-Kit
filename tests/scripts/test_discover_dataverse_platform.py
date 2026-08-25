# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure-logic projection tests for scripts/discover_dataverse_platform.py.

These assert that :class:`DataverseBackedPlatform` projects raw Dataverse rows into
the discovery crawler's §5.3 attribute shapes, and that deferred (not-yet-wired) kinds
raise ``PlatformError`` so the runner records their scope incomplete (spec §7).

No network is touched: ``auth.query_all`` and ``auth.authenticate`` are monkeypatched
to return canned rows / a dummy token. This is a pure-logic test (monkeypatched client,
no external API), so the cassette rule in tests/AGENTS.md does not apply.
"""

from __future__ import annotations

import os
import sys

import pytest

# The crawler package lives at repo-root tools/tenant-inventory-discovery/src and is not
# pip-installed; put it on sys.path the same way the bridge script does.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_CRAWLER_SRC = os.path.join(
    _REPO_ROOT, "tools", "tenant-inventory-discovery", "src"
)
if _CRAWLER_SRC not in sys.path:
    sys.path.insert(0, _CRAWLER_SRC)

import auth  # noqa: E402  (kit Dataverse client; pythonpath adds scripts/)
from discover_dataverse_platform import DataverseBackedPlatform  # noqa: E402

from tenant_inventory_discovery.errors import PlatformError  # noqa: E402
from tenant_inventory_discovery.mapping import map_resource  # noqa: E402
from tenant_inventory_discovery.models import Kind  # noqa: E402
from tenant_inventory_discovery.platform_clients import drain  # noqa: E402

_ENV_URL = "https://org538df70b.crm.dynamics.com"
# Environment identity is derived from the config endpoint (org unique name), not queried.
_ENV_ID = "org538df70b"
_ENTRA_APP_ID = "d64a50b6-f92c-43af-be17-53132d75b94d"
_TENANT_ID = "contoso.onmicrosoft.com"

_FAKE_APPLICATIONS = [
    {
        "appId": _ENTRA_APP_ID,
        "displayName": "ESS Agent App",
        "id": "9d4e2c31-0000-4a11-9b7e-7c6f2d1a5e33",
    }
]

_BOT_ID = "ff91def6-9597-40e2-b163-050682839b76"
_BAP_ENV_ID = "11111111-2222-3333-4444-555555555555"
_SP_SITE_URL = "https://contoso.sharepoint.com/sites/HR"
_SP_SITE_ID = "contoso.sharepoint.com,aaaa,bbbb"

_FAKE_ROWS = {
    "connectionreferences": [
        {
            "connectionreferenceid": "cr-1",
            "connectionreferencedisplayname": "ServiceNow ref",
            "connectorid": "shared_service-now",
            "statecode": 0,
        },
        {
            "connectionreferenceid": "cr-2",
            "connectionreferencedisplayname": "Unbound ref",
            "connectorid": None,  # unbound -> connectorId omitted -> skipped_invalid
            "statecode": 1,
        },
    ],
    "solutions": [
        {
            "uniquename": "ESS.HRSD",
            "version": "1.2.3",
            "_publisherid_value": "pub-1",
        },
        {
            "uniquename": None,  # no unique name -> dropped (cannot form natural key)
            "version": "9.9.9",
        },
    ],
    "msdyn_employeeselfservicetemplateconfigs": [
        {
            "msdyn_employeeselfservicetemplateconfigid": "tc-1",
            "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_Payslip",
            "msdyn_name": "Get Payslip",
        },
        {
            "msdyn_employeeselfservicetemplateconfigid": "tc-2",
            "msdyn_uniquename": None,  # no unique name -> dropped
            "msdyn_name": "Orphan",
        },
    ],
}

# BAP admin connections (subset of the real properties shape) -- two connections that
# reference the same connector plus a second connector, exercising de-duplication.
_FAKE_CONNECTIONS = [
    {"name": "conn-1", "properties": {"apiId": "/providers/Microsoft.PowerApps/apis/shared_service-now"}},
    {"name": "conn-2", "properties": {"apiId": "/providers/Microsoft.PowerApps/apis/shared_service-now"}},
    {"name": "conn-3", "properties": {"apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"}},
    {"name": "conn-4", "properties": {"apiId": ""}},  # no connector -> skipped
]

# Copilot Studio KnowledgeSourceComponent entries (internal gateway shape). The first is
# a SharePoint-backed source carrying a site URL; the second has no id -> dropped.
_FAKE_KNOWLEDGE_SOURCES = [
    {
        "$kind": "KnowledgeSourceComponent",
        "id": "ks-1",
        "displayName": "HR SharePoint",
        "knowledgeSource": {"$kind": "SharePointSource", "url": _SP_SITE_URL},
    },
    {
        "$kind": "KnowledgeSourceComponent",
        "displayName": "No-id source",  # no id/schemaName -> cannot form key -> dropped
    },
]


class _FakeGraphClient:
    """Stand-in for the kit's GraphClient (no network); records the query it received."""

    def __init__(self, rows=None, raises=None, sites=None):
        self._rows = rows if rows is not None else list(_FAKE_APPLICATIONS)
        self._raises = raises
        # Map of graph path -> site dict, for site-by-path resolution (SharePointSite).
        self._sites = sites if sites is not None else {}
        self.last_path = None
        self.last_params = None

    def get_all(self, path, params=None, *, raise_on_permission_error=False):
        self.last_path = path
        self.last_params = params
        if self._raises is not None:
            raise self._raises
        return list(self._rows)

    def get(self, path, params=None):
        return self._sites.get(path)


class _FakePVAClient:
    """Stand-in for the kit's PVAClient; returns canned knowledge-source components."""

    def __init__(self, components=None, raises=None):
        self._components = (
            components if components is not None else list(_FAKE_KNOWLEDGE_SOURCES)
        )
        self._raises = raises
        self.last_bot_id = None

    def get_knowledge_sources(self, bot_id):
        self.last_bot_id = bot_id
        if self._raises is not None:
            raise self._raises
        return list(self._components)


class _FakePPAdminClient:
    """Stand-in for the kit's PPAdminClient; resolves BAP env id + lists connections."""

    def __init__(self, connections=None, env_id=_BAP_ENV_ID):
        self._connections = (
            connections if connections is not None else list(_FAKE_CONNECTIONS)
        )
        self._env_id = env_id
        self.last_env_id = None

    def find_environment_id_by_dataverse_url(self, env_url):
        return self._env_id

    def get_connections(self, env_id):
        self.last_env_id = env_id
        if isinstance(self._connections, dict):
            return self._connections  # error sentinel passes through unchanged
        return list(self._connections)


@pytest.fixture
def platform(monkeypatch):
    """A DataverseBackedPlatform whose Dataverse + Graph clients are fully faked."""

    def _fake_query_all(env_url, token, entity_set, select, filter_expr=None):
        assert token == "dummy-token"
        return list(_FAKE_ROWS.get(entity_set, []))

    monkeypatch.setattr(auth, "authenticate", lambda env_url: "dummy-token")
    monkeypatch.setattr(auth, "query_all", _fake_query_all)
    return DataverseBackedPlatform(
        _ENV_URL,
        entra_app_id=_ENTRA_APP_ID,
        tenant_id=_TENANT_ID,
        bot_id=_BOT_ID,
        graph_client=_FakeGraphClient(
            sites={"/sites/contoso.sharepoint.com:/sites/HR": {"id": _SP_SITE_ID}}
        ),
        pva_client=_FakePVAClient(),
        pp_admin_client=_FakePPAdminClient(),
    )


class TestEnvironmentIdentity:
    def test_environment_id_derives_from_config_url(self, platform):
        # No Dataverse query -- identity comes from the endpoint (org unique name).
        assert platform.environment_id == _ENV_ID

    def test_list_environments_projects_5_3_shape(self, platform):
        items, complete = drain(platform.list_environments(page_size=100))
        assert complete is True
        assert len(items) == 1
        item = map_resource(Kind.ENVIRONMENT, items[0])
        assert item.natural_key == _ENV_ID
        assert item.attributes["environmentUrl"] == _ENV_URL


class TestConnections:
    def test_bound_connection_maps_to_5_3(self, platform):
        items, complete = drain(platform.list_connections(_ENV_ID, page_size=100))
        assert complete is True
        assert len(items) == 2

        bound = items[0]
        item = map_resource(Kind.CONNECTION, bound)
        assert item.natural_key == f"{_ENV_ID}:cr-1"
        assert item.attributes["connectorId"] == "shared_service-now"  # ref edge (§5.5)
        assert item.attributes["status"] == "Active"

    def test_unbound_connection_omits_connectorid_but_still_maps(self, platform):
        """``connectorId`` is optional in the server schema, so an unbound ref is valid.

        The reference edge is genuinely absent -- never silently defaulted (§6) -- but
        a connection reference with no connector is still a real resource worth
        recording, so it must not be dropped.
        """
        items, _ = drain(platform.list_connections(_ENV_ID, page_size=100))
        unbound = items[1]
        assert "connectorId" not in unbound  # never silently defaulted (§6)
        assert unbound["status"] == "Inactive"  # statecode != 0

        item = map_resource(Kind.CONNECTION, unbound)
        assert item.natural_key == f"{_ENV_ID}:cr-2"
        assert "connectorId" not in item.attributes


class TestExtensionPacks:
    def test_env_yields_one_pack_row_with_install_facts(self, platform):
        """The schema has no pack identity, so an environment gets exactly one row."""
        items, complete = drain(platform.list_extension_packs(_ENV_ID, page_size=100))
        assert complete is True
        assert len(items) == 1

        item = map_resource(Kind.EXTENSION_PACK, items[0])
        assert item.natural_key == _ENV_ID
        assert item.attributes["installed"] is True
        # "ESS.HRSD" is installed; nothing in the fixture mentions ITSM.
        assert item.attributes["hrsd"] is True
        assert item.attributes["itsm"] is False
        # The Workday scenario config names the ISV flavor.
        assert item.attributes["flavor"] == "Workday"

    def test_pack_attributes_survive_the_server_schema(self, platform):
        """Every emitted key must be one the Inventory schema models."""
        items, _ = drain(platform.list_extension_packs(_ENV_ID, page_size=100))
        dropped: list[str] = []
        map_resource(Kind.EXTENSION_PACK, items[0], dropped_out=dropped)
        assert dropped == []


class TestEntraApps:
    def test_agent_app_maps_to_5_3(self, platform):
        items, complete = drain(platform.list_entra_apps(page_size=100))
        assert complete is True
        assert len(items) == 1
        item = map_resource(Kind.ENTRA_APP, items[0])
        assert item.natural_key == _ENTRA_APP_ID
        assert item.attributes["appId"] == _ENTRA_APP_ID
        assert item.attributes["displayName"] == "ESS Agent App"
        assert item.attributes["objectId"] == "9d4e2c31-0000-4a11-9b7e-7c6f2d1a5e33"

    def test_query_is_scoped_to_configured_app_id(self, platform):
        drain(platform.list_entra_apps(page_size=100))
        graph = platform._graph  # the injected fake records its last query
        assert graph.last_path == "/applications"
        assert graph.last_params["$filter"] == f"appId eq '{_ENTRA_APP_ID}'"

    def test_missing_entra_app_id_raises_platform_error(self, monkeypatch):
        monkeypatch.setattr(auth, "authenticate", lambda env_url: "dummy-token")
        p = DataverseBackedPlatform(_ENV_URL, graph_client=_FakeGraphClient())
        with pytest.raises(PlatformError) as excinfo:
            drain(p.list_entra_apps(page_size=100))
        # The scope is reported Incomplete using this text, so it has to name the real
        # cause. /setup never provisions an Entra app -- pointing the operator at a
        # missing config value sends them looking for a key nothing writes.
        message = str(excinfo.value)
        assert "/connect" in message
        assert "retired" in message

    def test_graph_permission_error_becomes_platform_error(self, monkeypatch):
        monkeypatch.setattr(auth, "authenticate", lambda env_url: "dummy-token")
        faulty = _FakeGraphClient(raises=PermissionError("Graph returned HTTP 403"))
        p = DataverseBackedPlatform(
            _ENV_URL, entra_app_id=_ENTRA_APP_ID, graph_client=faulty
        )
        with pytest.raises(PlatformError):
            drain(p.list_entra_apps(page_size=100))


class TestConnectors:
    def test_distinct_connectors_from_connections(self, platform):
        items, complete = drain(platform.list_connectors(page_size=100))
        assert complete is True
        # Two connections share shared_service-now (de-duped) + one sharepointonline;
        # the connection with an empty apiId is skipped.
        by_id = {i["connectorId"]: i for i in items}
        assert set(by_id) == {"shared_service-now", "shared_sharepointonline"}
        item = map_resource(Kind.CONNECTOR, by_id["shared_service-now"])
        assert item.natural_key == "shared_service-now"
        # displayName is derived (drop shared_, de-slug, title-case).
        assert item.attributes["displayName"] == "Service Now"

    def test_connections_queried_with_resolved_bap_env_id(self, platform):
        drain(platform.list_connectors(page_size=100))
        assert platform._pp_admin.last_env_id == _BAP_ENV_ID

    def test_permission_error_sentinel_becomes_platform_error(self):
        pp = _FakePPAdminClient(connections={"_error": "insufficient_permissions"})
        p = DataverseBackedPlatform(
            _ENV_URL, tenant_id=_TENANT_ID, pp_admin_client=pp
        )
        with pytest.raises(PlatformError):
            drain(p.list_connectors(page_size=100))

    def test_unresolvable_bap_env_raises_platform_error(self):
        pp = _FakePPAdminClient(env_id=None)
        p = DataverseBackedPlatform(
            _ENV_URL, tenant_id=_TENANT_ID, pp_admin_client=pp
        )
        with pytest.raises(PlatformError):
            drain(p.list_connectors(page_size=100))


class TestKnowledgeSources:
    def test_component_maps_to_5_3(self, platform):
        items, complete = drain(platform.list_knowledge_sources(_ENV_ID, page_size=100))
        assert complete is True
        # The id-less component is dropped; only the SharePoint-backed one survives.
        assert len(items) == 1
        item = map_resource(Kind.KNOWLEDGE_SOURCE, items[0])
        assert item.natural_key == f"{_ENV_ID}:{_BOT_ID}:ks-1"
        assert item.attributes["displayName"] == "HR SharePoint"
        assert item.attributes["sourceType"] == "SharePointSource"

    def test_scoped_to_config_bot_id(self, platform):
        drain(platform.list_knowledge_sources(_ENV_ID, page_size=100))
        assert platform._pva.last_bot_id == _BOT_ID

    def test_missing_bot_id_raises_platform_error(self):
        p = DataverseBackedPlatform(
            _ENV_URL, tenant_id=_TENANT_ID, pva_client=_FakePVAClient()
        )
        with pytest.raises(PlatformError):
            drain(p.list_knowledge_sources(_ENV_ID, page_size=100))

    def test_gateway_error_becomes_platform_error(self):
        pva = _FakePVAClient(raises=RuntimeError("Island Gateway returned HTTP 500"))
        p = DataverseBackedPlatform(
            _ENV_URL, tenant_id=_TENANT_ID, bot_id=_BOT_ID, pva_client=pva
        )
        with pytest.raises(PlatformError):
            drain(p.list_knowledge_sources(_ENV_ID, page_size=100))


class TestSharePointSites:
    def test_site_from_knowledge_source_resolved_via_graph(self, platform):
        items, complete = drain(platform.list_sharepoint_sites(page_size=100))
        assert complete is True
        assert len(items) == 1
        item = map_resource(Kind.SHAREPOINT_SITE, items[0])
        assert item.natural_key == _SP_SITE_URL
        assert item.attributes["siteId"] == _SP_SITE_ID

    def test_site_dropped_when_graph_cannot_resolve_id(self):
        # Graph resolves nothing -> the site lacks a required siteId -> skipped.
        p = DataverseBackedPlatform(
            _ENV_URL,
            tenant_id=_TENANT_ID,
            bot_id=_BOT_ID,
            pva_client=_FakePVAClient(),
            graph_client=_FakeGraphClient(sites={}),
        )
        items, complete = drain(p.list_sharepoint_sites(page_size=100))
        assert complete is True
        assert items == []

    def test_missing_bot_id_raises_platform_error(self):
        p = DataverseBackedPlatform(
            _ENV_URL,
            tenant_id=_TENANT_ID,
            pva_client=_FakePVAClient(),
            graph_client=_FakeGraphClient(),
        )
        with pytest.raises(PlatformError):
            drain(p.list_sharepoint_sites(page_size=100))


class TestScenarioTemplates:
    def test_template_config_maps_to_5_3_and_drops_nameless(self, platform):
        items, complete = drain(
            platform.list_scenario_templates(_ENV_ID, page_size=100)
        )
        assert complete is True
        # The row with no uniquename is dropped; only the named one survives.
        assert len(items) == 1
        item = map_resource(Kind.SCENARIO_TEMPLATE, items[0])
        assert item.natural_key == f"{_ENV_ID}:msdyn_HRWorkdayHCMReferenceData_Payslip"
        # The Inventory schema models no displayName attribute for ScenarioTemplate,
        # so the name becomes the row's top-level label instead of an attribute.
        assert item.display_name == "Get Payslip"
        assert "displayName" not in item.attributes


class TestApiErrorTranslation:
    def test_api_error_becomes_platform_error(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise auth.APIError(message="boom", status_code=500)

        monkeypatch.setattr(auth, "authenticate", lambda env_url: "dummy-token")
        monkeypatch.setattr(auth, "query_all", _boom)
        p = DataverseBackedPlatform(_ENV_URL)
        with pytest.raises(PlatformError):
            drain(p.list_connections(_ENV_ID, page_size=100))
