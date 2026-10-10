# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Power Platform API Client

Provides authenticated access to the Power Platform API for FlightCheck
licensing checks and the foundation setup environment/application workflow.

This is a DIFFERENT host and audience from the BAP admin client in
``pp_admin_client.py``:

  - BAP (pp_admin_client.py): ``https://api.bap.microsoft.com`` /
    ``https://service.powerapps.com//.default``
  - This client:             the target ring's Power Platform API audience /
    ``.default`` scope

Authentication reuses the same MSAL token cache as auth.py /
graph_client.py / pp_admin_client.py (``.local/.token_cache.bin``).

API contract tier: ``documented`` — see the per-surface entries in the
"API tier registry" in ``tests/fixtures/cassettes/INDEX.md``. Response shapes
are verified against the Microsoft Learn references cited on each method.
"""

import os
import sys

from agentbuilder import RING_CONFIG

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

try:
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
except ImportError:
    print("ERROR: 'urllib3' / 'requests' not found. Run: pip install requests")
    sys.exit(1)


# Shared first-party public client used across the kit's MSAL flows.
CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

# Billing-policy endpoints are stable at this version (MS Learn).
API_VERSION = "2024-10-01"

# Module-level session with bounded retry-with-backoff for 429/5xx, mirroring
# pp_admin_client.py. Read-only verbs only; FlightCheck never mutates state.
_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    respect_retry_after_header=True,
)
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


def _request_id(response) -> str | None:
    """Return the first correlation identifier exposed by the service."""
    return (
        response.headers.get("x-ms-request-id")
        or response.headers.get("request-id")
        or response.headers.get("x-ms-correlation-request-id")
    )


def _error_result(response, error: str) -> dict:
    """Build a safe error observation without copying the response body."""
    result = {
        "_error": error,
        "_status": response.status_code,
    }
    request_id = _request_id(response)
    if request_id:
        result["_request_id"] = request_id
    return result


class PowerPlatformClient:
    """Power Platform API client for billing-policy / PayG queries."""

    def __init__(self, tenant_id: str, *, ring: str = "prod"):
        normalized_ring = str(ring).strip().casefold()
        config = RING_CONFIG.get(normalized_ring)
        if config is None:
            raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
        self.tenant_id = tenant_id
        self.ring = normalized_ring
        self.base_url = str(config["audience"]).rstrip("/")
        self.scope = f"{self.base_url}/.default"
        self._token: str | None = None
        self.signed_in_username: str | None = None

    def authenticate(self, preferred_username: str | None = None) -> str:
        """Acquire a Power Platform API access token.

        Uses the shared MSAL cache so the operator's existing sign-in is
        reused silently when possible, falling back to interactive.
        """
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join(".local", ".token_cache.bin")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            CLIENT_ID, authority=authority, token_cache=cache
        )

        accounts = app.get_accounts()
        result = None
        preferred = str(preferred_username or "").casefold()
        selected_account = next(
            (
                account
                for account in accounts
                if str(account.get("username") or "").casefold() == preferred
            ),
            accounts[0] if accounts and not preferred else None,
        )
        if selected_account:
            result = app.acquire_token_silent(
                [self.scope],
                account=selected_account,
            )
        if not result or "access_token" not in result:
            print("Opening browser for Power Platform API sign-in...")
            selected_account = None
            interactive_options = (
                {"login_hint": preferred_username}
                if preferred_username
                else {"prompt": "select_account"}
            )
            result = app.acquire_token_interactive(
                [self.scope],
                **interactive_options,
            )
        if "access_token" not in result:
            # Don't echo error_description - it can include tenant IDs and
            # internal flow details (CWE-209). Mirrors the auth.py pattern.
            error = result.get("error", "unknown_error")
            raise RuntimeError(f"Power Platform API auth failed ({error}).")

        if cache.has_state_changed:
            os.makedirs(".local", exist_ok=True)
            try:
                os.chmod(".local", 0o700)
            except OSError:
                pass  # Windows ignores chmod for directories
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            fd = os.open(cache_path, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cache.serialize())

        self._token = result["access_token"]
        claims = result.get("id_token_claims", {}) or {}
        self.signed_in_username = (
            claims.get("preferred_username")
            or claims.get("upn")
            or (selected_account or {}).get("username")
        )
        return self._token

    @property
    def headers(self) -> dict:
        if not self._token:
            raise RuntimeError("Call authenticate() first")
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _get_all(self, path: str, params: dict | None = None) -> list | dict:
        """Paginate through a Power Platform API collection.

        Follows the same contract as ``pp_admin_client._get_all``:

        - On 401/403 returns an explicit insufficient-permissions observation
          with the status and service request ID when available, so callers
          do not mistake a swallowed auth error for an empty list.
        - On 404 returns ``[]`` — a 404 on a billing-policy sub-collection
          (e.g. ``.../environments``) means "nothing linked", not an error.
          The environments endpoint documents 404 as a valid response.
        - Paginates via ``@odata.nextLink``.
        """
        items: list = []
        url = f"{self.base_url}{path}"
        while url:
            resp = _SESSION.get(url, headers=self.headers, params=params, timeout=60)
            if resp.status_code in (401, 403):
                return _error_result(resp, "insufficient_permissions")
            if resp.status_code == 404:
                return items
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = (
                data.get("@odata.nextLink")
                or data.get("@odata.nextlink")
                or data.get("nextLink")
            )
            params = None
        return items

    def list_environments_for_user(self) -> list | dict:
        """List environments available to the authenticated user.

        Microsoft Learn:
        https://learn.microsoft.com/en-us/rest/api/power-platform/environmentmanagement/environments/list-environments-for-user
        """
        return self._get_all(
            "/environmentmanagement/environments",
            params={"api-version": API_VERSION},
        )

    def list_billing_policies(self) -> list | dict:
        """List all billing policies for the tenant.

        MS Learn (documented tier):
        https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/billing-policy/list-billing-policies

        GET /licensing/billingPolicies?api-version=2024-10-01

        Each item is a ``BillingPolicyResponseModel``:
        ``{id, name, status ("Enabled"|"Disabled"), location,
        billingInstrument: {id, resourceGroup, subscriptionId},
        createdBy, createdOn, lastModifiedBy, lastModifiedOn}``.

        Returns the list, or a ``{"_error": ...}`` sentinel on 401/403.
        """
        return self._get_all(
            "/licensing/billingPolicies",
            params={"api-version": API_VERSION},
        )

    def list_policy_environments(self, billing_policy_id: str) -> list | dict:
        """List environments linked to a billing policy.

        MS Learn (documented tier):
        https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/billing-policy-environment/list-billing-policy-environments

        GET /licensing/billingPolicies/{billingPolicyId}/environments?api-version=2024-10-01

        Each item is a ``BillingPolicyEnvironmentResponseModelV1``:
        ``{billingPolicyId, environmentId}``.

        Returns the list (``[]`` when none / 404), or a ``{"_error": ...}``
        sentinel on 401/403.
        """
        return self._get_all(
            f"/licensing/billingPolicies/{billing_policy_id}/environments",
            params={"api-version": API_VERSION},
        )

    def get_environment_entitlements(self, environment_id: str) -> dict:
        """Get environment-scoped capacity and Pay-as-you-go entitlements.

        Microsoft Learn:
        https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/entitlement/get-many-environment-entitlements

        GET /licensing/environments/{environmentId}/entitlements?api-version=2024-10-01

        Returns an evidence envelope containing the documented
        ``EnvironmentEntitlementResponseModel[]`` plus the HTTP status and
        service request ID. Expected 401, 403, and 404 responses are returned
        as explicit error observations; other unsuccessful responses surface.
        """
        url = (
            f"{self.base_url}/licensing/environments/"
            f"{environment_id}/entitlements"
        )
        resp = _SESSION.get(
            url,
            headers=self.headers,
            params={"api-version": API_VERSION},
            timeout=60,
        )
        if resp.status_code in (401, 403):
            return _error_result(resp, "insufficient_permissions")
        if resp.status_code == 404:
            return _error_result(resp, "not_found")
        if resp.status_code == 204:
            data = []
        else:
            resp.raise_for_status()
            data = resp.json()
        result = {
            "items": data,
            "_status": resp.status_code,
        }
        request_id = _request_id(resp)
        if request_id:
            result["_request_id"] = request_id
        return result

    def list_environment_application_packages(
        self,
        environment_id: str,
    ) -> list | dict:
        """List Marketplace application packages available to an environment.

        Microsoft Learn:
        https://learn.microsoft.com/en-us/rest/api/power-platform/appmanagement/applications/get-environment-application-package
        """
        return self._get_all(
            f"/appmanagement/environments/{environment_id}/applicationPackages",
            params={"api-version": API_VERSION},
        )

    def list_maker_evaluation_test_sets(
        self,
        environment_id: str,
        bot_id: str,
    ) -> list | dict:
        """List Copilot Studio maker evaluation test sets for an agent.

        Microsoft Learn:
        https://learn.microsoft.com/rest/api/power-platform/copilotstudio/bots/list-maker-evaluation-test-sets
        """
        return self._get_all(
            (
                f"/copilotstudio/environments/{environment_id}/bots/{bot_id}"
                "/api/makerevaluation/testsets"
            ),
            params={"api-version": API_VERSION},
        )

    def run_maker_evaluation_test_set(
        self,
        environment_id: str,
        bot_id: str,
        test_set_id: str,
        body: dict,
    ) -> dict:
        """Start one asynchronous Copilot Studio maker evaluation run.

        Microsoft Learn:
        https://learn.microsoft.com/rest/api/power-platform/copilotstudio/bots/run-maker-evaluation-test-set
        """
        url = (
            f"{self.base_url}/copilotstudio/environments/{environment_id}"
            f"/bots/{bot_id}/api/makerevaluation/testsets/{test_set_id}/run"
        )
        resp = _SESSION.post(
            url,
            headers={**self.headers, "Content-Type": "application/json"},
            params={"api-version": API_VERSION},
            json=body,
            timeout=120,
        )
        if resp.status_code in (401, 403):
            return _error_result(resp, "insufficient_permissions")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def list_maker_evaluation_test_runs(
        self,
        environment_id: str,
        bot_id: str,
    ) -> list | dict:
        """List prior Copilot Studio maker evaluation runs for an agent.

        Microsoft Learn:
        https://learn.microsoft.com/rest/api/power-platform/copilotstudio/bots/list-maker-evaluation-test-runs
        """
        return self._get_all(
            (
                f"/copilotstudio/environments/{environment_id}/bots/{bot_id}"
                "/api/makerevaluation/testruns"
            ),
            params={"api-version": API_VERSION},
        )

    def get_maker_evaluation_test_run(
        self,
        environment_id: str,
        bot_id: str,
        run_id: str,
    ) -> dict:
        """Get status and case-level results for one maker evaluation run.

        Microsoft Learn:
        https://learn.microsoft.com/rest/api/power-platform/copilotstudio/bots/get-maker-evaluation-test-run
        """
        url = (
            f"{self.base_url}/copilotstudio/environments/{environment_id}"
            f"/bots/{bot_id}/api/makerevaluation/testruns/{run_id}"
        )
        resp = _SESSION.get(
            url,
            headers=self.headers,
            params={"api-version": API_VERSION},
            timeout=120,
        )
        if resp.status_code in (401, 403):
            return _error_result(resp, "insufficient_permissions")
        if resp.status_code == 404:
            return _error_result(resp, "not_found")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def install_application_package(
        self,
        environment_id: str,
        unique_name: str,
    ) -> dict:
        """Start installing a Marketplace application package.

        Microsoft Learn:
        https://learn.microsoft.com/en-us/rest/api/power-platform/appmanagement/applications/install-application-package

        This is an intentional durable tenant write. Callers must first read
        the package state and skip this POST when the package is installed or
        already installing. The module-level retry policy excludes POST, so a
        lost response is never replayed automatically.
        """
        url = (
            f"{self.base_url}/appmanagement/environments/{environment_id}"
            f"/applicationPackages/{unique_name}/install"
        )
        resp = _SESSION.post(
            url,
            headers={**self.headers, "Content-Type": "application/json"},
            params={"api-version": API_VERSION},
            json={"payloadValue": ""},
            timeout=60,
        )
        if resp.status_code in (401, 403):
            return _error_result(resp, "insufficient_permissions")
        if resp.status_code not in (200, 202):
            resp.raise_for_status()

        data = resp.json() if resp.content else {}
        if not isinstance(data, dict):
            data = {}
        operation_id = (
            data.get("lastOperation", {}).get("operationId")
            if isinstance(data, dict)
            else None
        )
        return {
            **data,
            "_async": resp.status_code == 202,
            "_operationId": operation_id,
        }
