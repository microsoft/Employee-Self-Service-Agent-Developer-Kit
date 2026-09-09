# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""MinimalBot (Dataverse-free) agent install transport for the ESS Maker Kit.

Copilot Studio agents that run on Cosmos-backed "MinimalBot" environments have
no linked Dataverse database, so the BAP + Dataverse discovery that
``install_ess_agent.install_agent`` relies on — resolving a Power Platform
environment ID from a Dataverse URL and reading connections over BAP — cannot
reach them. Those environments live on the **TEST** Power Platform ring, the
same ring ``minimalbot_evaluation.py`` uses for evaluations.

This module installs the ESS Marketplace application package straight against
the TEST ring, addressing the environment by its ``environmentId`` GUID rather
than by a Dataverse URL. The install/poll orchestration itself is shared:
callers drive this client through
``install_ess_agent.install_agent_by_env_id``, which reuses the same
package-find / install / wait helpers as the Dataverse-linked path. This client
only provides the two REST calls those helpers need, on the TEST ring:

  * GET  {base}/appmanagement/environments/{env}/applicationPackages
  * POST {base}/appmanagement/environments/{env}/applicationPackages/{name}/install

The method signatures deliberately match the subset of
``flightcheck.powerplatform_client.PowerPlatformClient`` that the shared install
helpers call, so the two transports are interchangeable at the call site.
"""

from __future__ import annotations

from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - dependency guard mirrors siblings
    raise SystemExit("ERROR: 'requests' package not found. Run: pip install requests")

from minimalbot_evaluation import (
    PPAPI_BASE,
    _environment_id,
    _tenant_id,
    acquire_test_pp_token,
)

# The application-package management surface is stable at this version on the
# Power Platform API — the same version the Dataverse-linked client
# (flightcheck/powerplatform_client.py) pins for these routes.
APP_API_VERSION = "2024-10-01"


class MinimalBotInstallError(RuntimeError):
    """Raised when a Dataverse-free install operation cannot be completed."""


class MinimalBotInstallClient:
    """Install ESS Marketplace apps on the TEST ring without Dataverse/BAP.

    Signature-compatible with the subset of ``PowerPlatformClient`` that
    ``install_ess_agent``'s shared install helpers call:
    :meth:`list_environment_application_packages` and
    :meth:`install_application_package`. Construct with an ``environmentId``
    GUID (from ``.local/config.json`` via :meth:`from_config`), call
    :meth:`authenticate`, then hand the instance to
    ``install_ess_agent.install_agent_by_env_id``.
    """

    def __init__(self, environment_id: str, tenant_id: str):
        if not environment_id:
            raise MinimalBotInstallError(
                "environmentId is required for the Dataverse-free install path."
            )
        self.environment_id = environment_id
        self.tenant_id = tenant_id or "organizations"
        self._token: str | None = None
        self.signed_in_username: str | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "MinimalBotInstallClient":
        return cls(
            environment_id=_environment_id(config),
            tenant_id=_tenant_id(config),
        )

    # -- auth ---------------------------------------------------------------
    def authenticate(self) -> str:
        """Acquire a TEST Power Platform token, reusing the shared MSAL cache."""
        self._token, self.signed_in_username = acquire_test_pp_token(self.tenant_id)
        return self._token

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise MinimalBotInstallError("Call authenticate() first.")
        return {
            "Authorization": " ".join(("Bearer", self._token)),
            "Content-Type": "application/json",
        }

    # -- REST surface (matches PowerPlatformClient) -------------------------
    def list_environment_application_packages(
        self,
        environment_id: str,
    ) -> list | dict:
        """List Marketplace application packages available to the TEST env.

        Returns the ``value`` list from the API envelope, or an ``_error``
        marker dict on 401/403 so the caller can surface a permissions error
        the same way the Dataverse-linked client does.
        """
        url = (
            f"{PPAPI_BASE}/appmanagement/environments/{environment_id}"
            "/applicationPackages"
        )
        response = requests.get(
            url,
            headers=self._headers(),
            params={"api-version": APP_API_VERSION},
            timeout=120,
        )
        if response.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": response.status_code}
        response.raise_for_status()
        data = response.json() if response.content else {}
        if isinstance(data, dict):
            value = data.get("value")
            return value if isinstance(value, list) else data
        return data if isinstance(data, list) else []

    def install_application_package(
        self,
        environment_id: str,
        unique_name: str,
    ) -> dict:
        """Start installing a Marketplace application package on the TEST ring.

        This is an intentional durable tenant write. Callers must first read
        the package state and skip this POST when the package is installed or
        already installing (the shared ``install_ess_agent`` helper does so).
        """
        url = (
            f"{PPAPI_BASE}/appmanagement/environments/{environment_id}"
            f"/applicationPackages/{unique_name}/install"
        )
        response = requests.post(
            url,
            headers=self._headers(),
            params={"api-version": APP_API_VERSION},
            json={"payloadValue": ""},
            timeout=60,
        )
        if response.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": response.status_code}
        if response.status_code not in (200, 202):
            response.raise_for_status()
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            data = {}
        operation_id = (
            data.get("lastOperation", {}).get("operationId")
            if isinstance(data, dict)
            else None
        )
        return {
            **data,
            "_async": response.status_code == 202,
            "_operationId": operation_id,
        }
