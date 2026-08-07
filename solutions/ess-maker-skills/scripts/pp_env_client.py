# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit — Power Platform Environment API client.

Provides authenticated access to the per-environment Power Platform API host
(``{env}.environment.api.powerplatform.com``) that backs the Copilot Studio
"Connections" experience:

* ``.../powervirtualagents/bots/{schema}/channels/pva-studio/user-connections``
  — the agent's *flow invoker-connection binding* (what the Copilot Studio UI
  shows as Connected / NotConnected). This is DISTINCT from the Dataverse
  ``connectionreferences`` solution binding the maker sets in Copilot Studio.
* ``.../connectivity/connectors/{connector}/connections/{id}`` — the live
  connection object (used to read ``connectionParametersSet`` for sharing).

Authentication uses the Power Platform CLI ("pac") public client, which — unlike
the Azure CLI client used elsewhere in this kit — is pre-authorized for the
``https://api.powerplatform.com`` resource. A dedicated MSAL token cache
(``.local/.pac_token_cache.bin``) keeps this separate from the main cache.
"""

import os
import sys

try:
    import msal
except ImportError:
    print("ERROR: 'msal' package not found. Run: pip install msal")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)


# Power Platform CLI ("pac") public client. Pre-authorized for the Power
# Platform API resource; the kit's default Azure CLI client
# (51f81489-12ee-4a9e-aaae-a2591f45987d) is NOT (AADSTS65002).
PAC_CLIENT_ID = "9cee029c-6210-4654-90bb-17e6e9d36617"
PP_API_SCOPE = "https://api.powerplatform.com/.default"

API_VERSION = "2022-03-01-preview"

# Global Power Platform API host. Unlike the per-environment host used for
# user-connections / connectivity, the Application Management (appmanagement)
# API — used to install/uninstall Dynamics 365 application packages — is served
# from this single global endpoint.
GLOBAL_API_HOST = "api.powerplatform.com"

# Terminal states for an application-package install operation
# (GET .../operations/{operationId}).
TERMINAL_OPERATION_STATUSES = frozenset({"Succeeded", "Failed", "Canceled"})

_CACHE_PATH = os.path.join(".local", ".pac_token_cache.bin")


def env_api_host(env_id: str) -> str:
    """Derive the per-environment Power Platform API host from an environment id.

    The host is formed from the environment GUID with hyphens removed, split so
    the final two characters become the second DNS label::

        11a02d3a-172c-ef48-8b74-8e2975c2fb05
        -> 11a02d3a172cef488b748e2975c2fb.05.environment.api.powerplatform.com

    This host is global (not region-prefixed), even though a bot's
    ``runtimeEndpoints`` are region-prefixed.
    """
    compact = (env_id or "").replace("-", "")
    if len(compact) < 3:
        raise ValueError(f"invalid environment id: {env_id!r}")
    return f"{compact[:-2]}.{compact[-2:]}.environment.api.powerplatform.com"


class PPEnvClient:
    """Client for the per-environment Power Platform API (pac auth)."""

    def __init__(self, tenant_id: str, env_id: str):
        self.tenant_id = tenant_id
        self.env_id = env_id
        self.host = env_api_host(env_id)
        self._token: str | None = None

    # -- auth -------------------------------------------------------------
    def authenticate(self, interactive: bool = True) -> str | None:
        """Acquire a Power Platform API token.

        Tries the cached account silently first. When ``interactive`` is False
        (the flightcheck path) and no cached token is available, returns None
        instead of opening a browser — callers degrade to SKIPPED. When
        ``interactive`` is True (the action path), falls back to a browser
        sign-in.
        """
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "r") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            PAC_CLIENT_ID, authority=authority, token_cache=cache
        )

        result = None
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent([PP_API_SCOPE], account=accounts[0])

        if not result or "access_token" not in result:
            if not interactive:
                return None
            print("Opening browser for Power Platform sign-in...")
            result = app.acquire_token_interactive(
                [PP_API_SCOPE], prompt="select_account"
            )

        if cache.has_state_changed:
            os.makedirs(".local", exist_ok=True)
            with open(_CACHE_PATH, "w") as f:
                f.write(cache.serialize())

        if not result or "access_token" not in result:
            return None

        self._token = result["access_token"]
        return self._token

    def _headers(self, with_content_type: bool = False) -> dict:
        if not self._token:
            raise RuntimeError("PPEnvClient is not authenticated")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if with_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    # -- user-connections (flow invoker binding) --------------------------
    def _user_connections_url(self, bot_schema: str) -> str:
        return (
            f"https://{self.host}/powervirtualagents/bots/{bot_schema}"
            f"/channels/pva-studio/user-connections?api-version={API_VERSION}"
        )

    def get_user_connections(self, bot_schema: str) -> dict:
        """GET the agent's flow invoker-connection bindings."""
        resp = requests.get(
            self._user_connections_url(bot_schema),
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def set_user_connections(self, bot_schema: str, flow_bindings: dict) -> int:
        """POST flow invoker-connection bindings.

        ``flow_bindings`` maps a flow id to a list of connector dicts, each with
        ``connectorId`` / ``connectionId`` / ``connectionName``. Note the write
        shape differs from the GET response: here each flow id maps to a *direct
        array*, whereas the GET response nests connectors under
        ``flowBindings[id].connectors``.
        """
        resp = requests.post(
            self._user_connections_url(bot_schema),
            headers=self._headers(with_content_type=True),
            json={"flowBindings": flow_bindings},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.status_code

    # -- connection object (parameters for sharing) -----------------------
    def get_connection(self, connector_name: str, connection_id: str) -> dict:
        """GET the live connection object (includes connectionParametersSet)."""
        url = (
            f"https://{self.host}/connectivity/connectors/{connector_name}"
            f"/connections/{connection_id}"
            f"?$filter=environment eq '{self.env_id}'&api-version={API_VERSION}"
        )
        resp = requests.get(url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        return resp.json()

    # -- application packages (appmanagement, global host) ----------------
    def _appmgmt_base(self) -> str:
        return f"https://{GLOBAL_API_HOST}/appmanagement/environments/{self.env_id}"

    def list_application_packages(self) -> list[dict]:
        """GET the application packages this environment is entitled to install.

        Returns the ``value`` array; each entry carries ``uniqueName``, ``state``
        (``None`` = not installed, ``Installed``, ``Installing``, ``InstallFailed``,
        …), ``version`` and ``instancePackageId``.
        """
        url = f"{self._appmgmt_base()}/applicationPackages?api-version={API_VERSION}"
        resp = requests.get(url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        return (resp.json() or {}).get("value") or []

    def install_application_package(self, unique_name: str) -> dict:
        """POST to start installing an application package by unique name.

        Returns ``{"status_code", "operation_id", "body"}``. The operation id is
        read from the response body's ``lastOperation.operationId`` (falling back
        to the ``Operation-Location`` header). NOTE: this call is *not*
        idempotent server-side — re-posting on an already-installed package
        starts a fresh install operation — so callers must check
        :meth:`list_application_packages` state first.
        """
        url = (
            f"{self._appmgmt_base()}/applicationPackages/{unique_name}"
            f"/install?api-version={API_VERSION}"
        )
        resp = requests.post(
            url, headers=self._headers(with_content_type=True), json={}, timeout=120
        )
        resp.raise_for_status()
        body = {}
        try:
            body = resp.json()
        except ValueError:
            body = {}
        op_id = ((body.get("lastOperation") or {}).get("operationId")
                 or body.get("operationId")
                 or _operation_id_from_header(resp.headers.get("Operation-Location")))
        return {"status_code": resp.status_code, "operation_id": op_id, "body": body}

    def get_operation(self, operation_id: str) -> dict:
        """GET the status of an install operation (``status`` + ``statusMessage``)."""
        url = (
            f"{self._appmgmt_base()}/operations/{operation_id}"
            f"?api-version={API_VERSION}"
        )
        resp = requests.get(url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        return resp.json()
def connector_short_name(connector_id: str) -> str:
    """Return the connector's short name from its provider path.

    ``/providers/Microsoft.PowerApps/apis/shared_service-now`` -> ``shared_service-now``
    """
    return (connector_id or "").rstrip("/").rsplit("/", 1)[-1]


def iter_flow_connectors(user_connections: dict):
    """Yield ``(flow_id, connector_dict)`` pairs from a user-connections GET.

    Tolerates both the nested GET shape (``flowBindings[id].connectors``) and a
    direct-array shape (``flowBindings[id] == [...]``).
    """
    flow_bindings = (user_connections or {}).get("flowBindings") or {}
    for flow_id, entry in flow_bindings.items():
        if isinstance(entry, dict):
            connectors = entry.get("connectors") or []
        elif isinstance(entry, list):
            connectors = entry
        else:
            connectors = []
        for connector in connectors:
            yield flow_id, connector


def find_connector_flows(user_connections: dict, connector_name: str):
    """Return ``[(flow_id, connector_dict), ...]`` for a given connector name."""
    matches = []
    for flow_id, connector in iter_flow_connectors(user_connections):
        if connector_short_name(connector.get("connectorId", "")) == connector_name:
            matches.append((flow_id, connector))
    return matches


def connector_is_connected(connector: dict) -> bool:
    """True when a connector entry is bound and Connected."""
    return bool(connector.get("connectionId")) and (
        str(connector.get("status", "")).lower() == "connected"
    )


def _operation_id_from_header(operation_location: str | None) -> str | None:
    """Extract the operation id from an ``Operation-Location`` header URL.

    ``https://.../operations/18a6d34e-...?api-version=1`` -> ``18a6d34e-...``
    """
    if not operation_location:
        return None
    path = operation_location.split("?", 1)[0]
    marker = "/operations/"
    idx = path.find(marker)
    if idx == -1:
        return None
    return path[idx + len(marker):].strip("/") or None


def find_application_package(packages: list[dict], unique_name: str) -> dict | None:
    """Return the package entry whose ``uniqueName`` matches (case-insensitive)."""
    target = (unique_name or "").lower()
    for pkg in packages or []:
        if (pkg.get("uniqueName") or "").lower() == target:
            return pkg
    return None


def package_is_installed(package: dict | None) -> bool:
    """True when a package entry's ``state`` is ``Installed``."""
    return bool(package) and str(package.get("state", "")).lower() == "installed"


def operation_is_terminal(status: str | None) -> bool:
    """True when an install operation status is terminal (case-insensitive)."""
    return (status or "").lower() in {s.lower() for s in TERMINAL_OPERATION_STATUSES}


def operation_succeeded(status: str | None) -> bool:
    """True when an install operation status is ``Succeeded`` (case-insensitive)."""
    return (status or "").lower() == "succeeded"
