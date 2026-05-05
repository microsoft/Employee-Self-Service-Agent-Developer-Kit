# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit — PVA (Island Gateway) Client

Provides authenticated access to the Copilot Studio Island Gateway API
for reading bot component status (including knowledge source crawl/index status).

Authentication uses the same MSAL cache as auth.py / graph_client.py.
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


CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

# PVA app ID — used as the token audience for the Island Gateway API
PVA_SCOPE = "96ff4394-9197-43aa-b393-6a41652e21f8/.default"

# BAP API for discovering the gateway URL
BAP_SCOPE = "https://api.bap.microsoft.com/.default"
BAP_BASE = "https://api.bap.microsoft.com"


class PVAClient:
    """Copilot Studio Island Gateway API client."""

    def __init__(self, tenant_id: str, env_url: str):
        self.tenant_id = tenant_id
        self.env_url = env_url
        self._pva_token: str | None = None
        self._gateway_url: str | None = None
        self._bap_env_id: str | None = None

    def authenticate(self) -> str:
        """Acquire a PVA access token and discover gateway URL."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join("my", ".token_cache.bin")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            CLIENT_ID, authority=authority, token_cache=cache
        )

        # Get PVA token
        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent([PVA_SCOPE], account=accounts[0])

        if not result or "access_token" not in result:
            print("Opening browser for PVA sign-in...")
            result = app.acquire_token_interactive(
                [PVA_SCOPE], prompt="select_account"
            )

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown"))
            raise RuntimeError(f"PVA auth failed: {error}")

        self._pva_token = result["access_token"]

        # Get BAP token for gateway discovery
        bap_result = None
        if accounts:
            bap_result = app.acquire_token_silent([BAP_SCOPE], account=accounts[0])
        if not bap_result or "access_token" not in bap_result:
            bap_result = app.acquire_token_interactive(
                [BAP_SCOPE], prompt="select_account"
            )

        if cache.has_state_changed:
            os.makedirs("my", exist_ok=True)
            with open(cache_path, "w") as f:
                f.write(cache.serialize())

        # Discover gateway URL from BAP
        if bap_result and "access_token" in bap_result:
            self._discover_gateway(bap_result["access_token"])

        return self._pva_token

    def _discover_gateway(self, bap_token: str):
        """Find the PVA gateway URL and BAP environment ID for this environment."""
        headers = {"Authorization": f"Bearer {bap_token}", "Accept": "application/json"}

        # List environments and find the one matching our Dataverse URL
        url = (
            f"{BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments"
            "?api-version=2021-04-01"
        )
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code in (401, 403):
                # Try non-admin endpoint
                url = (
                    f"{BAP_BASE}/providers/Microsoft.BusinessAppPlatform/environments"
                    "?api-version=2021-04-01"
                )
                resp = requests.get(url, headers=headers, timeout=30)
            if not resp.ok:
                return
        except Exception:
            return

        # Extract the org name from our env_url for matching
        # e.g., "https://orgb78b4a3b.crm.dynamics.com" → "orgb78b4a3b"
        org_match = self.env_url.split("//")[1].split(".")[0] if "//" in self.env_url else ""

        envs = resp.json().get("value", [])
        for env in envs:
            props = env.get("properties", {})
            linked = props.get("linkedEnvironmentMetadata", {})
            instance_url = linked.get("instanceUrl", "")
            if org_match and org_match in instance_url:
                self._bap_env_id = env.get("name")
                runtime = props.get("runtimeEndpoints", {})
                self._gateway_url = runtime.get("microsoft.PowerVirtualAgents")
                break

    @property
    def is_configured(self) -> bool:
        """True if gateway URL and BAP env ID were discovered."""
        return bool(self._pva_token and self._gateway_url and self._bap_env_id)

    def get_knowledge_sources(self, bot_id: str) -> list[dict]:
        """
        Fetch knowledge source components from the Island Gateway API.

        Returns a list of KnowledgeSourceComponent dicts with fields:
        - displayName, id, state, status, configuration, etc.
        """
        if not self.is_configured:
            return []

        url = (
            f"{self._gateway_url}/api/botmanagement/v1"
            f"/environments/{self._bap_env_id}"
            f"/bots/{bot_id}/content/botcomponents"
        )
        headers = {
            "Authorization": f"Bearer {self._pva_token}",
            "Content-Type": "application/json",
            "x-ms-client-tenant-id": self.tenant_id,
            "x-cci-tenantid": self.tenant_id,
            "x-cci-bapenvironmentid": self._bap_env_id,
            "x-cci-cdsbotid": bot_id,
        }

        resp = requests.post(url, headers=headers, json={}, timeout=60)
        if not resp.ok:
            raise RuntimeError(
                f"Island Gateway returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()

        # Extract KnowledgeSourceComponent entries
        knowledge_sources = []
        for change in data.get("botComponentChanges", []):
            comp = change.get("component", {})
            if comp.get("$kind") == "KnowledgeSourceComponent":
                knowledge_sources.append(comp)

        return knowledge_sources
