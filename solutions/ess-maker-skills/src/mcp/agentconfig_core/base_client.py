# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Neutral AgentConfiguration client core shared by the landing-page and planner MCPs.

This module owns everything both AgentConfiguration MCP surfaces need and neither should
re-implement: bearer-token acquisition, the JWT claim decode, a single shared
httpx session, and the retrying ``_request``. ``AgentConfigClient`` (landing
page) and ``PlannerClient`` (planner) both inherit ``AgentConfigBaseClient``, each with its
own base URL and logger name.

Token acquisition, in priority order:
  1. AGENTCONFIG_ACCESS_TOKEN_FILE / AGENTCONFIG_ACCESS_TOKEN.
  2. MSAL public-client sign-in with a local form_post callback.

The tenant ID comes from the resolved token's ``tid`` claim and the caller
object id from ``oid``. The API still validates the token and enforces
authorization; the client decodes claims only to address tenant-scoped routes
and to scope "for the caller" queries to the signed-in principal.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import http.server
import json
import logging
import os
import random
import stat
import threading
import urllib.parse
import uuid
import webbrowser
from typing import Any, Optional

import httpx


logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_CLIENT_ID = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
_SCOPE = ["https://substrate.office.com/weve/.default"]
_AUTHORITY = "https://login.microsoftonline.com/organizations"
# Derived from this shared-core module's own location so every AgentConfiguration MCP
# (landing-page, planner) shares ONE MSAL cache and ONE interactive sign-in.
_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_STATE_DIR = os.path.join(_CORE_DIR, ".local")
_TOKEN_CACHE_PATH = os.path.join(_LOCAL_STATE_DIR, "msal_token_cache.bin")


class AgentConfigApiError(RuntimeError):
    """Raised when the production AgentConfiguration API rejects a request."""

    def __init__(self, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


def _resolve_token() -> str:
    """Resolve a token without writing it to logs or MCP configuration."""
    token_file = os.environ.get("AGENTCONFIG_ACCESS_TOKEN_FILE", "")
    if token_file:
        if not os.path.isfile(token_file):
            raise ValueError(
                f"AGENTCONFIG_ACCESS_TOKEN_FILE={token_file!r} does not exist"
            )
        with open(token_file, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
        if not token:
            raise ValueError(
                f"AGENTCONFIG_ACCESS_TOKEN_FILE={token_file!r} is empty"
            )
        return token

    token = os.environ.get("AGENTCONFIG_ACCESS_TOKEN", "").strip()
    if token:
        return token

    return acquire_token_msal_interactive()


class _FormPostCaptureHandler(http.server.BaseHTTPRequestHandler):
    """Capture one OAuth form_post callback from the local loopback listener."""

    captured: dict[str, str] = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        _FormPostCaptureHandler.captured = {
            key: values[0] for key, values in params.items() if values
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body>Signed in. You can close this tab.</body></html>"
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def _load_msal_cache() -> Any:
    import msal

    cache = msal.SerializableTokenCache()
    if os.path.exists(_TOKEN_CACHE_PATH):
        with open(_TOKEN_CACHE_PATH, "r", encoding="utf-8") as handle:
            cache.deserialize(handle.read())
    return cache


def _save_msal_cache(cache: Any) -> None:
    if not cache.has_state_changed:
        return

    os.makedirs(_LOCAL_STATE_DIR, exist_ok=True)
    try:
        os.chmod(_LOCAL_STATE_DIR, 0o700)
    except OSError:
        pass

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(_TOKEN_CACHE_PATH, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(cache.serialize())
    finally:
        try:
            os.chmod(_TOKEN_CACHE_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def acquire_token_msal_interactive() -> str:
    """Acquire a delegated AgentConfiguration token through cached or interactive MSAL auth."""
    import msal

    cache = _load_msal_cache()
    app = msal.PublicClientApplication(
        _CLIENT_ID,
        authority=_AUTHORITY,
        token_cache=cache,
    )

    accounts = app.get_accounts()
    result = app.acquire_token_silent(_SCOPE, account=accounts[0]) if accounts else None
    if not result or "access_token" not in result:
        result = _acquire_token_interactive_form_post(app)

    _save_msal_cache(cache)
    if "access_token" not in result:
        error = result.get("error", "unknown_error")
        description = result.get("error_description", "")
        raise ValueError(f"MSAL sign-in failed ({error}): {description}")
    return result["access_token"]


def _acquire_token_interactive_form_post(app: Any) -> dict[str, Any]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _FormPostCaptureHandler)
    redirect_uri = f"http://localhost:{server.server_port}"
    flow = app.initiate_auth_code_flow(
        scopes=_SCOPE,
        redirect_uri=redirect_uri,
        response_mode="form_post",
        prompt="select_account",
    )

    _FormPostCaptureHandler.captured = {}
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print(f"Opening browser for AgentConfiguration sign-in ({redirect_uri}) ...")
    webbrowser.open(flow["auth_uri"])
    thread.join(timeout=300)
    server.server_close()

    if not _FormPostCaptureHandler.captured:
        return {
            "error": "timeout",
            "error_description": "No sign-in callback received within 300 seconds.",
        }

    return app.acquire_token_by_auth_code_flow(
        flow,
        _FormPostCaptureHandler.captured,
    )


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode a JWT's payload segment without verifying its signature.

    The API validates the token and enforces authorization; the client decodes
    claims only to address tenant-scoped routes (``tid``) and to scope "for the
    caller" queries to the signed-in principal (``oid``).
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(
            "AGENTCONFIG_ACCESS_TOKEN does not look like a JWT "
            "(expected three dot-separated segments)"
        )
    payload_segment = parts[1]
    padded = payload_segment + "=" * (-len(payload_segment) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(
            f"Could not decode AGENTCONFIG_ACCESS_TOKEN payload: {error}"
        ) from error


def _decode_tenant_id_from_jwt(token: str) -> str:
    """Decode and validate the tenant ID (``tid``) used to address the route."""
    tenant_id = _decode_jwt_payload(token).get("tid")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("AGENTCONFIG_ACCESS_TOKEN payload has no 'tid' claim")
    try:
        return str(uuid.UUID(tenant_id))
    except ValueError as error:
        raise ValueError(
            "AGENTCONFIG_ACCESS_TOKEN payload has an invalid 'tid' claim"
        ) from error


def _decode_object_id_from_jwt(token: str) -> Optional[str]:
    """Best-effort decode of the caller's Entra object id (``oid`` claim).

    Used to scope "tasks for the caller" queries to the signed-in principal
    without taking the identity as a tool argument. Returns ``None`` when the
    token is opaque or carries no ``oid`` claim.
    """
    try:
        payload = _decode_jwt_payload(token)
    except ValueError:
        return None
    object_id = payload.get("oid")
    if isinstance(object_id, str) and object_id:
        return object_id
    return None


class AgentConfigBaseClient:
    """Neutral AgentConfiguration client core shared by the landing-page and planner MCPs.

    Owns everything both surfaces need and neither should re-implement: MSAL/
    bearer token acquisition, the JWT claim decode, a single shared httpx
    session, and the retrying ``_request``. Subclasses supply their own base URL
    and logger name and layer their domain routes on top; they never duplicate
    auth or transport. ``AgentConfigApiError`` and ``_TOKEN_CACHE_PATH`` live
    here so both MCPs raise one error type and share one interactive sign-in.
    """

    def __init__(
        self,
        *,
        base_url: str,
        logger_name: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._logger = logging.getLogger(logger_name)
        self._token = _resolve_token()
        self.tenant_id = _decode_tenant_id_from_jwt(self._token)
        self.max_retries = 3
        self.timeout = 30.0
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} base_url={self.base_url!r} "
            f"tenant_id={self.tenant_id!r}>"
        )

    def _transform_response(self, payload: Any) -> Any:
        """Surface-specific response key transform; identity in the neutral core.

        The landing-page client overrides this to apply its PascalCase→camelCase
        conversion. The planner and role surfaces keep the default because their
        bodies carry user keys that must not be rewritten.
        """
        return payload

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout,
                    verify=True,
                    transport=self._transport,
                    follow_redirects=False,
                )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        transform_payload: bool = True,
        idempotent: Optional[bool] = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a request with bounded retry for transient responses.

        ``transform_payload`` controls the landing-page camelCase/PascalCase key
        conversion applied to the response body. It defaults to ``True`` so the
        EmployeeAgents surface is unchanged; the planner and role surfaces pass
        ``False`` because their responses carry user keys that must not be
        rewritten.

        ``idempotent`` gates whether an *ambiguous* transient failure — a 502/
        503/504 gateway error or a network ``RequestError`` that may have landed
        server-side after committing — is safe to replay. It defaults to
        retry-safe (``True``) so the shared default never silently drops retry
        coverage as new call sites are added; a call site that would genuinely
        duplicate on replay (an unkeyed create) passes ``idempotent=False`` to
        opt out, and that unsafe create is surfaced instead of retried so a
        committed-but-unacknowledged POST is never duplicated. A 429 is always
        retried because the service rejects it before doing any work.
        """
        # Default to retry-safe so the landing-page surface keeps its original
        # retry-on-transient behavior; only call sites that would genuinely
        # duplicate on replay (unkeyed creates) opt out with idempotent=False.
        retry_safe = True if idempotent is None else idempotent
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            client = await self._ensure_client()
            try:
                response = await client.request(method, path, **kwargs)
                if response.status_code == 429 or response.status_code in (
                    502,
                    503,
                    504,
                ):
                    if response.status_code != 429 and not retry_safe:
                        # An ambiguous gateway failure on a non-idempotent
                        # request (typically an unkeyed create) may already have
                        # committed server-side; replaying it risks a duplicate,
                        # so surface it instead of retrying.
                        response.raise_for_status()
                    wait = (2**attempt) + random.uniform(0, 1)
                    last_error = AgentConfigApiError(
                        f"Transient HTTP {response.status_code}"
                    )
                    self._logger.warning(
                        "Retryable HTTP %d (attempt %d/%d), waiting %.1fs",
                        response.status_code,
                        attempt + 1,
                        self.max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                response.raise_for_status()
                if response.status_code == 204:
                    return {"success": True}
                payload = response.json()
                return (
                    self._transform_response(payload)
                    if transform_payload
                    else payload
                )

            except httpx.HTTPStatusError as error:
                code = ""
                message = ""
                try:
                    body = error.response.json()
                except (json.JSONDecodeError, UnicodeDecodeError):
                    body = None
                if isinstance(body, dict):
                    code_candidate = body.get("Code")
                    if isinstance(code_candidate, str):
                        code = code_candidate
                    message_candidate = body.get("Message")
                    if isinstance(message_candidate, str):
                        message = message_candidate
                if not code:
                    code = "HttpError"
                if not message:
                    message = f"HTTP {error.response.status_code}"
                raise AgentConfigApiError(
                    f"{code}: {message}",
                    http_status=error.response.status_code,
                ) from error

            except httpx.RequestError as error:
                last_error = error
                if retry_safe and attempt < self.max_retries - 1:
                    await asyncio.sleep((2**attempt) + random.uniform(0, 1))
                    continue
                raise

        raise AgentConfigApiError(f"Maximum retries exceeded: {last_error}")
