# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Live Dataverse-backed ``PlatformSurface`` for the tenant-inventory crawl.

Reuses the kit's existing Dataverse client (``scripts/auth.py``:
:func:`auth.authenticate` for a delegated admin token + :func:`auth.query_all` for
``@odata.nextLink``-paged Web API queries) to enumerate the **Dataverse-backed** kinds
live, satisfying the discovery crawler's ``PlatformSurface`` protocol
(``tenant_inventory_discovery.platform_clients``).

Wired today
-----------
- ``Environment``     -> the single configured environment (identity from config's
                         ``dataverseEndpoint``; no platform query)
- ``EntraApp``        -> Microsoft Graph ``/applications`` (the kit's ``GraphClient``),
                         scoped to the agent's ``entraAppId`` from config
- ``Connector``       -> distinct connectors used by the environment's connections
                         (BAP admin ``PPAdminClient.get_connections``)
- ``Connection``      -> Dataverse ``connectionreferences``
- ``SharePointSite``  -> Graph sites referenced by the agent's SharePoint knowledge
                         sources (``PVAClient`` -> ``GraphClient`` site-by-path)
- ``KnowledgeSource`` -> Copilot Studio bot knowledge sources (``PVAClient`` Island
                         Gateway), scoped to the agent's ``botId`` from config
- ``ExtensionPack``   -> Dataverse ``solutions``
- ``ScenarioTemplate``-> Dataverse ``msdyn_employeeselfservicetemplateconfigs``

All eight kinds enumerate live; a kind whose platform call fails raises ``PlatformError``
so the runner records that scope **incomplete** and the server-side reconcile never
sweeps it (completeness invariant, spec §7).

Single-environment crawl
------------------------
The kit's setup config binds **one** environment: ``.local/config.json`` stores its
``dataverseEndpoint`` (no Power Platform environment GUID). The environment identity is
therefore **derived from that config URL** (the org unique name) -- the skill never
"discovers" other environments. The bridge runs a **subset crawl**
(``environment_ids=[environment_id]``) so the tenant-root exemption (spec §6.3) keeps
the tenant-root kinds (``Environment``, ``EntraApp``, ``Connector``, ``SharePointSite``)
out of reconcile -- only the env-scoped kinds (``Connection``, ``KnowledgeSource``,
``ExtensionPack``, ``ScenarioTemplate``), fully enumerated, are reconciled.

Field mappings are grounded in the documented Dataverse system-table schemas
(see per-method ``Source (documented)`` citations) but the *choice* of which column maps
to each §5.3 attribute remains ``[verify Q-A]`` against the DesignSpec.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

import auth  # kit Dataverse client (same scripts/ directory)
from tenant_inventory_discovery.errors import PlatformError
from tenant_inventory_discovery.platform_clients import Page

# -- Dataverse entity sets + $select projections ---------------------------------------
# connectionreference: https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/connectionreference
_CONNECTION_ENTITY = "connectionreferences"
_CONNECTION_SELECT = (
    "connectionreferenceid,connectionreferencedisplayname,connectorid,statecode"
)
# solution: https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/solution
_SOLUTION_ENTITY = "solutions"
_SOLUTION_SELECT = "solutionid,uniquename,version,ismanaged,_publisherid_value"
_SOLUTION_FILTER = "isvisible eq true"
# application (Microsoft Graph v1.0): https://learn.microsoft.com/graph/api/resources/application
# Fields verified against the Graph v1.0 schema: appId (String, $filter eq),
# displayName (String), id (String, the directory object id).
_GRAPH_APPLICATIONS_PATH = "/applications"
_GRAPH_APPLICATIONS_SELECT = "appId,displayName,id"
# ESS scenario/template config table (kit-specific). Column names verified against the
# kit's own working script scripts/backup_template_configs.py.
_TEMPLATE_CONFIG_ENTITY = "msdyn_employeeselfservicetemplateconfigs"
_TEMPLATE_CONFIG_SELECT = (
    "msdyn_employeeselfservicetemplateconfigid,msdyn_uniquename,msdyn_name"
)

# Substring that marks an installed ESS extension-pack solution. The kit's own
# scenario/topic naming uses the `msdyn_...employeeselfservice...` family throughout
# (see scripts/setup.py and scripts/scan_config.py).
_ESS_PACK_MARKER = "employeeselfservice"

# ISV flavors an extension pack can target, longest-distinguishing marker first. Drawn
# from the kit's own detection in flightcheck/checks/external_systems.py.
_PACK_FLAVORS: tuple[tuple[str, str], ...] = (
    ("servicenow", "ServiceNow"),
    ("workday", "Workday"),
    ("successfactors", "SAP SuccessFactors"),
    ("sap", "SAP"),
)


def _pack_flavor(markers: str) -> str | None:
    """Name the ISV flavor an environment's pack targets, or ``None`` if ambiguous."""
    found = [label for marker, label in _PACK_FLAVORS if marker in markers]
    return found[0] if found else None


def _environment_id_from_url(env_url: str) -> str:
    """Derive a stable environment id from the Dataverse endpoint (org unique name).

    The kit's setup writes only ``dataverseEndpoint`` to ``.local/config.json`` (no
    Power Platform environment GUID), so -- like the kit's FlightCheck tooling -- the
    single environment's identity is derived from that URL. The org unique name is the
    first host label, e.g. ``https://org538df70b.crm.dynamics.com`` -> ``org538df70b``.
    It is stable across runs, so env-scoped natural keys compose identically every crawl.
    """
    host = urlsplit(env_url).hostname or ""
    label = host.split(".", 1)[0]
    if not label:
        raise PlatformError(f"Cannot derive an environment id from URL: {env_url!r}")
    return label


def _connector_id_from_api_id(api_id: str) -> str:
    """Extract the connector id from a Power Platform ``apiId`` reference.

    BAP connection records reference their connector as a resource path, e.g.
    ``/providers/Microsoft.PowerApps/apis/shared_service-now`` -> ``shared_service-now``
    (the same last-segment form used by ``live_egress_probe.py``).
    """
    if not api_id:
        return ""
    return api_id.rstrip("/").rsplit("/", 1)[-1]


def _connector_display_name(connector_id: str) -> str:
    """Derive a human-readable connector display name from its id.

    The BAP connection record carries the connector *id* but not a guaranteed connector
    *display name*, so we derive a stable, readable label (drop the ``shared_`` prefix,
    de-slug, title-case). ``[verify]`` -- prefer a catalog display name if a connector
    catalog surface is later wired.
    """
    label = connector_id
    if label.startswith("shared_"):
        label = label[len("shared_") :]
    label = label.replace("-", " ").replace("_", " ").strip()
    return label.title() or connector_id


def _knowledge_source_type(component: dict) -> str | None:
    """Best-effort ``sourceType`` for a Copilot Studio KnowledgeSourceComponent.

    ``[verify]`` -- the Island Gateway component shape is internal/undocumented, so we
    read a small set of likely-nested kind fields and fall back to ``None`` (the §5.3
    ``sourceType`` attribute is optional, so omitting it never fails the item).
    """
    for key in ("dataSourceType", "sourceType", "kind"):
        value = component.get(key)
        if isinstance(value, str) and value:
            return value
    nested = component.get("knowledgeSource")
    if isinstance(nested, dict):
        kind = nested.get("$kind") or nested.get("kind")
        if isinstance(kind, str) and kind:
            return kind
    return None


def _find_sharepoint_urls(obj: object) -> list[str]:
    """Recursively collect distinct ``*.sharepoint.com`` URLs from a component.

    ``[verify]`` -- the KnowledgeSourceComponent shape is internal, so rather than pin a
    field path we scan every string value for a SharePoint site URL. This is robust to
    the exact (unverified) field names the gateway uses.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, str):
            low = node.lower()
            if low.startswith("http") and ".sharepoint.com" in low:
                norm = node.rstrip("/")
                if norm not in seen:
                    seen.add(norm)
                    found.append(norm)
        elif isinstance(node, dict):
            for value in node.values():
                _walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                _walk(value)

    _walk(obj)
    return found


class DataverseBackedPlatform:
    """A live ``PlatformSurface`` over one Dataverse environment via ``auth.query_all``."""

    def __init__(
        self,
        env_url: str,
        *,
        environment_id: str | None = None,
        environment_name: str | None = None,
        entra_app_id: str | None = None,
        tenant_id: str | None = None,
        bot_id: str | None = None,
        token_provider: Callable[[], str] | None = None,
        graph_client: object | None = None,
        pva_client: object | None = None,
        pp_admin_client: object | None = None,
    ) -> None:
        self._env_url = env_url.rstrip("/")
        # Delegated admin token (spec §8). ``authenticate`` uses the MSAL silent cache,
        # so calling it per query is cheap and refreshes transparently.
        self._get_token = token_provider or (lambda: auth.authenticate(self._env_url))
        # Environment identity comes from config (the endpoint), NOT from a Dataverse
        # query -- there is exactly one configured environment and the skill must not
        # "discover" others (single-environment crawl).
        self._env_id = environment_id or _environment_id_from_url(self._env_url)
        self._env_name = environment_name or self._env_id
        # EntraApp (Microsoft Graph) input. The agent's app id comes from config; the
        # Entra tenant is resolved lazily from the Dataverse endpoint (see
        # ``_get_tenant_id``) -- config has no Entra tenant GUID. ``graph_client`` lets
        # tests inject a fake (a real one is built+authenticated lazily on first use).
        self._entra_app_id = entra_app_id
        self._tenant_id = tenant_id
        # KnowledgeSource / SharePointSite read the agent's Copilot Studio bot; Connector
        # reads the environment's connections via the BAP admin API. The ``*_client``
        # kwargs let tests inject fakes; real clients are built + authenticated lazily on
        # first use. ``_bap_env_id`` caches the resolved BAP environment id.
        self._bot_id = bot_id
        self._pva = pva_client
        self._pp_admin = pp_admin_client
        self._graph = graph_client
        self._bap_env_id: str | None = None

    # -- environment identity ----------------------------------------------------------

    @property
    def environment_id(self) -> str:
        """The environment id (from config) used to scope the subset crawl (spec §4)."""
        return self._env_id

    def _query(
        self, entity_set: str, select: str, filter_expr: str | None = None
    ) -> list[dict]:
        try:
            return auth.query_all(
                self._env_url, self._get_token(), entity_set, select, filter_expr
            )
        except auth.APIError as exc:
            # Translate to the crawler's platform-error type so the runner marks the
            # scope incomplete and excludes it from reconcile (spec §7).
            raise PlatformError(
                f"Dataverse enumeration of {entity_set} failed: {exc}"
            ) from exc

    def _get_tenant_id(self) -> str:
        """Resolve (and cache) the Entra tenant for Graph/PVA/BAP sign-in.

        The kit's ``config.json`` has no Entra tenant GUID (its ``tenant`` field is the
        *Workday* tenant slug, not an Azure AD authority), so -- exactly like
        ``auth.authenticate`` and the FlightCheck CLI -- the Entra tenant is derived from
        the Dataverse endpoint's auth challenge, falling back to the multi-tenant
        ``organizations`` authority. An explicitly-provided ``tenant_id`` (tests) wins.
        """
        if not self._tenant_id:
            try:
                self._tenant_id = auth.discover_tenant(self._env_url)
            except Exception:  # tenant discovery is best-effort (mirrors cli.py)
                self._tenant_id = "organizations"
        return self._tenant_id

    def _get_graph(self):
        """Return a ready (authenticated) Microsoft Graph client.

        An injected client (tests) is used as-is; otherwise the kit's ``GraphClient``
        is built from the resolved Entra tenant and authenticated once (MSAL silent
        cache, so only a cold start opens a browser). Cached for the run.
        """
        if self._graph is None:
            from flightcheck.graph_client import GraphClient

            client = GraphClient(self._get_tenant_id())
            client.authenticate()
            self._graph = client
        return self._graph

    def _get_pva(self):
        """Return a ready (authenticated) Copilot Studio Island Gateway client.

        An injected client (tests) is used as-is; otherwise the kit's ``PVAClient`` is
        built from the resolved Entra tenant + Dataverse endpoint and authenticated once
        (this discovers the PVA gateway URL and BAP env id). Cached for the run.
        """
        if self._pva is None:
            from flightcheck.pva_client import PVAClient

            client = PVAClient(self._get_tenant_id(), self._env_url)
            client.authenticate()
            self._pva = client
        return self._pva

    def _get_pp_admin(self):
        """Return a ready (authenticated) Power Platform (BAP) admin client.

        An injected client (tests) is used as-is; otherwise the kit's ``PPAdminClient``
        is built from the resolved Entra tenant and authenticated once (BAP-only; no
        Flow token). Cached for the run.
        """
        if self._pp_admin is None:
            from flightcheck.pp_admin_client import PPAdminClient

            client = PPAdminClient(self._get_tenant_id())
            client.authenticate(include_flow=False)
            self._pp_admin = client
        return self._pp_admin

    def _bap_environment_id(self) -> str:
        """Resolve (and cache) the BAP environment id for the configured Dataverse URL.

        BAP admin endpoints key on the BAP environment id, which is **not** the org
        unique name used for env-scoped natural keys -- so it is resolved separately via
        the admin client's Dataverse-URL match.
        """
        if self._bap_env_id is None:
            pp = self._get_pp_admin()
            bap_env_id = pp.find_environment_id_by_dataverse_url(self._env_url)
            if not bap_env_id:
                raise PlatformError(
                    "Could not resolve the BAP environment id for "
                    f"{self._env_url!r} (no admin access, or no matching environment)."
                )
            self._bap_env_id = bap_env_id
        return self._bap_env_id

    def _resolve_site_id(self, site_url: str) -> str | None:
        """Resolve a SharePoint site URL to its Graph ``site.id`` (or ``None``).

        Uses Graph ``GET /sites/{hostname}:/{server-relative-path}`` (documented:
        https://learn.microsoft.com/graph/api/site-getbypath). Any failure returns
        ``None`` so the site is skipped rather than aborting the whole scope -- the
        §5.3 ``siteId`` is required, so a site we cannot resolve simply drops out.
        """
        parts = urlsplit(site_url)
        host = parts.hostname
        if not host:
            return None
        path = (parts.path or "").rstrip("/")
        graph_path = f"/sites/{host}:{path}" if path else f"/sites/{host}"
        try:
            data = self._get_graph().get(graph_path)
        except Exception:
            return None
        if isinstance(data, dict):
            site_id = data.get("id")
            if site_id:
                return str(site_id)
        return None

    # -- tenant-root surfaces ----------------------------------------------------------

    def list_environments(self, page_size: int) -> Iterator[Page]:
        """The single configured environment (from config's ``dataverseEndpoint``).

        Identity is taken from config, not discovered from the platform: there is
        exactly one configured environment and the skill must not enumerate others
        (single-environment crawl). No Dataverse query is issued here.
        """
        yield Page(
            items=[
                {
                    "environmentId": self._env_id,
                    "displayName": self._env_name,
                    "environmentUrl": self._env_url,
                }
            ],
            is_last=True,
        )

    def list_entra_apps(self, page_size: int) -> Iterator[Page]:
        """The agent's Entra app registration -> §5.3 ``EntraApp`` (spec §4 row 2).

        Enumerated live from Microsoft Graph ``GET /applications`` via the kit's
        ``GraphClient``, scoped to the agent's ``appId`` from config (spec §4 names the
        source as "agent app registration(s)", not every app in the tenant).

        Source (validatable -- Graph v1.0 CSDL / MS Learn):
          https://learn.microsoft.com/graph/api/resources/application
          Fields used: appId (String, ``$filter eq``), displayName (String),
          id (String, the directory object id).

        ``publisherDomain`` / ``signInAudience`` are *not* projected: the Inventory
        schema does not model them for ``EntraApp``, so they would only be dropped
        before the upsert.
        """
        if not self._entra_app_id:
            raise PlatformError(
                "No Entra app registration is configured for this agent yet. It is "
                "provisioned by /connect (ServiceNow or Workday), not /setup -- run "
                "that first if you expect one. Nothing is retired for EntraApp until "
                "it can be read."
            )
        params = {
            "$filter": f"appId eq '{self._entra_app_id}'",
            "$select": _GRAPH_APPLICATIONS_SELECT,
        }
        try:
            graph = self._get_graph()
            rows = graph.get_all(
                _GRAPH_APPLICATIONS_PATH, params, raise_on_permission_error=True
            )
        except PlatformError:
            raise
        except Exception as exc:  # auth / permission / transport -> scope incomplete (§7)
            raise PlatformError(
                f"Microsoft Graph enumeration of applications failed: {exc}"
            ) from exc

        items: list[dict] = []
        for row in rows:
            app_id = row.get("appId")
            if not app_id:
                continue  # an app with no appId cannot form a natural key
            item: dict = {"appId": str(app_id)}
            display_name = row.get("displayName")
            if display_name:
                item["displayName"] = str(display_name)
            object_id = row.get("id")
            if object_id:
                item["objectId"] = str(object_id)
            items.append(item)
        yield Page(items=items, is_last=True)

    def list_connectors(self, page_size: int) -> Iterator[Page]:
        """Distinct connectors used by the environment's connections -> §5.3 ``Connector``.

        The kit has no standalone connector-catalog client, so the connectors are
        derived from the environment's connections (BAP admin
        ``.../environments/{env}/connections``): each connection references its connector
        as ``properties.apiId`` (e.g. ``.../apis/shared_service-now``). We project the
        **distinct** connectors actually in use -- the set an agent inventory cares about.

        Source (documented tier -- BAP/PowerApps admin connections):
          GET /providers/Microsoft.PowerApps/scopes/admin/environments/{env}/connections
          Field used: ``properties.apiId`` (connector resource path).
        ``[verify]`` -- ``displayName`` is derived from the connector id (the connection
        record does not guarantee a connector display name).
        """
        try:
            pp = self._get_pp_admin()
            bap_env_id = self._bap_environment_id()
            conns = pp.get_connections(bap_env_id)
        except PlatformError:
            raise
        except Exception as exc:  # auth / transport -> scope incomplete (§7)
            raise PlatformError(
                f"Power Platform enumeration of connections failed: {exc}"
            ) from exc

        if isinstance(conns, dict) and "_error" in conns:
            raise PlatformError(
                f"Power Platform connection listing failed: {conns.get('_error')}"
            )

        seen: dict[str, dict] = {}
        for conn in conns or []:
            props = conn.get("properties", {}) if isinstance(conn, dict) else {}
            connector_id = _connector_id_from_api_id(str(props.get("apiId", "")))
            if not connector_id or connector_id in seen:
                continue
            seen[connector_id] = {
                "connectorId": connector_id,
                "displayName": _connector_display_name(connector_id),
            }
        yield Page(items=list(seen.values()), is_last=True)

    def list_sharepoint_sites(self, page_size: int) -> Iterator[Page]:
        """SharePoint sites referenced by the agent's knowledge sources -> §5.3 ``SharePointSite``.

        Per the discovery decision, we inventory only the sites the agent actually uses:
        the SharePoint URLs found in its Copilot Studio knowledge sources (read via the
        Island Gateway), each resolved to its Graph ``site.id``. This keeps the crawl
        agent-relevant and avoids a tenant-wide ``Sites.Read.All`` enumeration.

        Source (documented tier -- Graph site-by-path):
          https://learn.microsoft.com/graph/api/site-getbypath
        ``[verify]`` -- the SharePoint URLs are extracted from the internal (undocumented)
        KnowledgeSourceComponent shape by scanning for ``*.sharepoint.com`` URLs.
        """
        if not self._bot_id:
            raise PlatformError(
                "SharePointSite discovery needs the agent's 'botId' (from config) to "
                "read its knowledge sources."
            )
        try:
            components = self._get_pva().get_knowledge_sources(self._bot_id)
        except PlatformError:
            raise
        except Exception as exc:  # auth / gateway -> scope incomplete (§7)
            raise PlatformError(
                f"Copilot Studio enumeration of knowledge sources failed: {exc}"
            ) from exc

        site_urls: list[str] = []
        seen_urls: set[str] = set()
        for component in components or []:
            if not isinstance(component, dict):
                continue
            for url in _find_sharepoint_urls(component):
                if url not in seen_urls:
                    seen_urls.add(url)
                    site_urls.append(url)

        items: list[dict] = []
        for url in site_urls:
            site_id = self._resolve_site_id(url)
            if not site_id:
                continue  # required §5.3 key unavailable -> skip this site
            items.append({"siteUrl": url, "siteId": site_id})
        yield Page(items=items, is_last=True)

    # -- env-scoped surfaces -----------------------------------------------------------

    def list_connections(self, environment_id: str, page_size: int) -> Iterator[Page]:
        """Connection references in the environment -> §5.3 ``Connection`` (spec §4 row 4).

        Source (documented):
          https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/connectionreference
          Columns used: connectionreferenceid (Edm.Guid), connectorid (Edm.String),
          connectionreferencedisplayname (Edm.String), statecode (Edm.Int32).
        """
        rows = self._query(_CONNECTION_ENTITY, _CONNECTION_SELECT)
        items: list[dict] = []
        for row in rows:
            item: dict = {
                "environmentId": environment_id,
                "connectionId": str(row["connectionreferenceid"]),
            }
            # connectorId is the reference edge (§5.5) + a required §5.3 key. When absent
            # (an unbound reference), omit it -- the mapper flags the item invalid and the
            # runner records it as skipped, never silently dropping a required key (§6).
            connector_id = row.get("connectorid")
            if connector_id:
                item["connectorId"] = str(connector_id)
            display_name = row.get("connectionreferencedisplayname")
            if display_name:
                item["displayName"] = str(display_name)
            statecode = row.get("statecode")
            if statecode is not None:
                item["status"] = "Active" if statecode == 0 else "Inactive"
            items.append(item)
        yield Page(items=items, is_last=True)

    def list_knowledge_sources(
        self, environment_id: str, page_size: int
    ) -> Iterator[Page]:
        """The agent bot's knowledge sources -> §5.3 ``KnowledgeSource`` (spec §4 row 6).

        Enumerated from Copilot Studio via the kit's ``PVAClient`` (Island Gateway
        ``.../bots/{botId}/content/botcomponents``, ``KnowledgeSourceComponent`` entries),
        scoped to the agent's ``botId`` from config.

        ``[verify]`` -- the gateway component shape is internal/undocumented: ``sourceId``
        maps from the component ``id`` (fallback ``schemaName``); ``sourceType`` is a
        best-effort nested kind; ``displayName`` from the component ``displayName``.
        """
        if not self._bot_id:
            raise PlatformError(
                "KnowledgeSource discovery needs the agent's 'botId' from config."
            )
        try:
            components = self._get_pva().get_knowledge_sources(self._bot_id)
        except PlatformError:
            raise
        except Exception as exc:  # auth / gateway -> scope incomplete (§7)
            raise PlatformError(
                f"Copilot Studio enumeration of knowledge sources failed: {exc}"
            ) from exc

        items: list[dict] = []
        for component in components or []:
            if not isinstance(component, dict):
                continue
            source_id = component.get("id") or component.get("schemaName")
            if not source_id:
                continue  # cannot form the (env|bot|source) natural key
            item: dict = {
                "environmentId": environment_id,
                "botId": str(self._bot_id),
                "sourceId": str(source_id),
            }
            display_name = component.get("displayName")
            if display_name:
                item["displayName"] = str(display_name)
            source_type = _knowledge_source_type(component)
            if source_type:
                item["sourceType"] = source_type
            items.append(item)
        yield Page(items=items, is_last=True)

    def list_extension_packs(
        self, environment_id: str, page_size: int
    ) -> Iterator[Page]:
        """The environment's ESS extension-pack install -> §5.3 ``ExtensionPack``.

        The server's ``ExtensionPack`` schema has **no identity attribute of its own**
        (``installed`` / ``hrsd`` / ``itsm`` / ``flavor`` / ``flowCount`` all describe a
        single environment's install), so this yields **at most one item per
        environment**, keyed on ``environmentId`` -- not one per solution.

        Sources (both already queried by this platform; no new endpoint):
          - solution: https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/solution
            ``uniquename`` identifies the installed extension-pack solutions.
          - the kit's ``msdyn_employeeselfservicetemplateconfigs`` table, whose
            ``msdyn_uniquename`` values carry the ``ServiceNowHRSD`` / ``ServiceNowITSM``
            scenario markers the kit's own FlightCheck uses to tell the packs apart
            (``flightcheck/checks/servicenow.py``).

        ``flowCount`` is deliberately omitted: counting cloud flows needs the BAP admin
        surface, which this platform does not hold. The attribute is optional, so
        omitting it is valid rather than guessed.
        """
        solution_names = [
            str(row.get("uniquename"))
            for row in self._query(_SOLUTION_ENTITY, _SOLUTION_SELECT, _SOLUTION_FILTER)
            if row.get("uniquename")
        ]
        scenario_names = [
            str(row.get("msdyn_uniquename"))
            for row in self._query(_TEMPLATE_CONFIG_ENTITY, _TEMPLATE_CONFIG_SELECT)
            if row.get("msdyn_uniquename")
        ]

        markers = " ".join(solution_names + scenario_names).lower()
        hrsd = "hrsd" in markers
        itsm = "itsm" in markers
        installed = any(
            _ESS_PACK_MARKER in name.lower() for name in solution_names
        ) or bool(scenario_names)

        item: dict = {
            "environmentId": environment_id,
            "installed": installed,
            "hrsd": hrsd,
            "itsm": itsm,
        }
        flavor = _pack_flavor(markers)
        if flavor:
            item["flavor"] = flavor
        yield Page(items=[item], is_last=True)

    def list_scenario_templates(
        self, environment_id: str, page_size: int
    ) -> Iterator[Page]:
        """ESS scenario/template configs in the environment -> §5.3 ``ScenarioTemplate``.

        Enumerated from the kit's Dataverse table
        ``msdyn_employeeselfservicetemplateconfigs`` (spec §4 row 8), the same table the
        kit's ``scripts/backup_template_configs.py`` reads.

        Source (kit table -- columns verified against ``backup_template_configs.py``):
          msdyn_uniquename (Edm.String -> uniqueName / natural key),
          msdyn_name (Edm.String -> the row's displayName).

        ``msdyn_name`` becomes the row's top-level display name rather than an
        attribute: the Inventory schema does not model ``displayName`` (or a
        ``scenarioName``) for ``ScenarioTemplate``.
        """
        rows = self._query(_TEMPLATE_CONFIG_ENTITY, _TEMPLATE_CONFIG_SELECT)
        items: list[dict] = []
        for row in rows:
            unique_name = row.get("msdyn_uniquename")
            if not unique_name:
                continue  # a config with no unique name cannot form a natural key
            item: dict = {
                "environmentId": environment_id,
                "uniqueName": str(unique_name),
            }
            name = row.get("msdyn_name")
            if name:
                item["displayName"] = str(name)
            items.append(item)
        yield Page(items=items, is_last=True)
