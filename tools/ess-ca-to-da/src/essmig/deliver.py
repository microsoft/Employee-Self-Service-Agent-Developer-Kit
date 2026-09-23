"""Deliver the migrated package into a target Declarative Agent — the one write path.

Everything else in this tool is read-only. This module is the sole exception: when
the operator asks for it (``migrate --import``), it takes the ALM package the rest
of the tool built and imports it into a *specified* target Declarative Agent,
replacing that agent's content in the target environment's development ring.

The contract, from *ALM for Declarative Agents — Technical Design* (draft)::

    POST {api_base}/copilotstudio/tenants/{tenant}/environments/{environment}
         /minimalBots/alm/import?schemaName={schemaName}

with the package zip as the request body. ``schemaName`` must name the agent that
already exists in the target environment, so the import takes the *overwrite* path
— without it the API returns 409 when the agent already exists. Import is a clean
replace into **Dev only**; Test and Production are untouched until promoted.

.. warning::
   The import host, the request/response shape and the token audience are all from
   a draft design and have not been exercised against a live environment. The base
   URL (``--target-api-base`` / ``ESSMIG_TARGET_API_BASE``) and the token scope
   (``ESSMIG_TARGET_SCOPE``) are therefore overridable at runtime so the endpoint
   can be corrected without a code change. Re-confirm both before a customer run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from essmig.auth import TokenProvider

# The Power Platform API host that fronts the Copilot Studio ALM endpoints. A best
# guess against the draft design; override with --target-api-base when confirmed.
DEFAULT_API_BASE = "https://api.powerplatform.com"

_IMPORT_TIMEOUT_SECONDS = 300.0
_GUID_RE = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


class DeliveryError(ValueError):
    """The delivery target is not usable as given."""


@dataclass(frozen=True)
class ImportTarget:
    """Everything needed to address one target Declarative Agent for import."""

    tenant_id: str
    environment_id: str
    schema_name: str
    api_base: str = DEFAULT_API_BASE

    def __post_init__(self) -> None:
        if not _GUID_RE.match(self.tenant_id.strip()):
            raise DeliveryError(f"target tenant id is not a GUID: {self.tenant_id!r}")
        if not _GUID_RE.match(self.environment_id.strip()):
            raise DeliveryError(
                f"target environment id is not a GUID: {self.environment_id!r}"
            )
        if not self.schema_name.strip():
            raise DeliveryError("target schema name must not be empty.")
        parsed = urlparse(self.api_base.strip())
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise DeliveryError(f"target api base must be an HTTPS URL: {self.api_base!r}")

    @property
    def endpoint(self) -> str:
        base = self.api_base.rstrip("/")
        return (
            f"{base}/copilotstudio/tenants/{self.tenant_id}"
            f"/environments/{self.environment_id}/minimalBots/alm/import"
        )


@dataclass(frozen=True)
class ImportResult:
    """The outcome of an import attempt, for the report and the console."""

    ok: bool
    endpoint: str
    schema_name: str
    status: int | None = None
    detail: str = ""
    operation_url: str | None = None
    """Set when the import is accepted asynchronously (202) and tracked elsewhere."""

    def to_json(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "endpoint": self.endpoint,
            "schemaName": self.schema_name,
            "status": self.status,
            "detail": self.detail,
            "operationUrl": self.operation_url,
        }


def import_package(
    target: ImportTarget,
    package: bytes,
    token_provider: TokenProvider,
    *,
    client: httpx.Client | None = None,
) -> ImportResult:
    """Import ``package`` (the zip bytes) into ``target``. Returns, never raises on HTTP.

    A transport failure or any non-2xx response is captured in the returned
    :class:`ImportResult` rather than raised, so a failed delivery still produces a
    report rather than a stack trace.
    """
    endpoint = target.endpoint
    http = client or httpx.Client(timeout=_IMPORT_TIMEOUT_SECONDS)
    try:
        token = token_provider.get_token()
    except Exception as error:  # noqa: BLE001 — surfaced to the operator as a result
        return ImportResult(
            ok=False,
            endpoint=endpoint,
            schema_name=target.schema_name,
            detail=f"could not acquire a token for the target: {error}",
        )

    try:
        response = http.post(
            endpoint,
            params={"schemaName": target.schema_name},
            content=package,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/zip",
                "Accept": "application/json",
            },
        )
    except httpx.HTTPError as error:
        return ImportResult(
            ok=False,
            endpoint=endpoint,
            schema_name=target.schema_name,
            detail=f"request to the target failed: {error}",
        )

    ok = 200 <= response.status_code < 300
    operation = response.headers.get("Location") or response.headers.get(
        "Operation-Location"
    )
    return ImportResult(
        ok=ok,
        endpoint=endpoint,
        schema_name=target.schema_name,
        status=response.status_code,
        detail=_success_detail(response.status_code) if ok else _error_detail(response),
        operation_url=operation if ok else None,
    )


def _success_detail(status: int) -> str:
    if status == 202:
        return "Import accepted; it is being applied asynchronously."
    return "Import completed; the target Declarative Agent's Dev ring was replaced."


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] if text else f"HTTP {response.status_code} with no body."
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])[:300]
        if isinstance(body.get("message"), str):
            return str(body["message"])[:300]
    return str(body)[:300]
