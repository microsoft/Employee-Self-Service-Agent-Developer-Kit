#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS Workday REST endpoint pre-flight diagnostic.

Validates the 9 Workday REST connector actions the Employee Self-Service
(ESS) agent calls at runtime, using the OAuth 2.0 Authorization Code
flow against a customer-registered Workday API Client. Same checkpoint
IDs (``WD-REST-AUTH`` / ``WD-REST-ME`` / ``WD-REST-001`` ... ``WD-REST-008``)
as the source PowerShell script (``Test-WorkdayRESTEndpoints.ps1`` from
ess-preflight-validator commits 5eb19bc and 9ed2055).

This script lives outside the FlightCheck runner intentionally. Workday
REST OAuth bootstrap is the chicken-and-egg auth problem documented in
``tests/fixtures/cassettes/INDEX.md`` (see "Workday WQL config-validation
pattern"): validating that the customer's Workday API Client is wired up
is hard to automate because the validator itself needs a registered API
Client to talk to Workday. The source repo accepts this and ships an
interactive customer-run script. We do the same — but use Python, and
default to a paste-the-URL UX so we don't have to ship a self-signed
TLS cert for the ``https://localhost`` redirect URI Workday expects.

Usage::

    python solutions/ess-maker-skills/scripts/diagnostics/test_workday_rest_endpoints.py

Prerequisites: register an OAuth API Client in Workday with
"Authorization Code" grant type and redirect URI
``https://localhost:8888/callback`` (or pass ``--redirect-uri`` to use
your own). See ``README.md`` in this directory for the full setup.

Secrets hygiene
---------------

The OAuth client secret, authorization code, access token, and refresh
token are NEVER logged. Employee PII returned by the endpoints
(name, email, business title, organization, manager) is redacted in the
JSON output by default; pass ``--include-pii`` to keep it for in-tenant
debugging. Do not paste the redacted JSON into public issues regardless
— Workday WIDs are tenant-internal identifiers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import http.server
import json
import os
import secrets as _stdlib_secrets
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import requests
from requests.exceptions import RequestException

DEFAULT_REDIRECT_URI = "https://localhost:8888/callback"
DEFAULT_OUTPUT_DIR = "workspace/flightcheck"

# Fields in the GetWorkerMe + collection responses we consider PII. Redacted
# by default in JSON output. Each entry is a JSON-path-ish dot string; nested
# access uses dict.get() and is forgiving of missing intermediates.
_PII_PATHS_WORKER = (
    "id",
    "descriptor",
    "primaryWorkEmail",
    "businessTitle",
    "primarySupervisoryOrganization.descriptor",
    "primarySupervisoryOrganization.id",
)


# ───────────────────────────────────────────────────────────────────────
# Result dataclass — same shape as the source PS PSCustomObject.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    id: str
    operation: str
    type: str   # "Auth" | "Identity" | "Read" | "Write"
    status: str  # "PASS" | "FAIL" | "WARN" | "SKIP"
    details: str = ""
    latency_ms: int = 0
    http_status: Optional[int] = None


@dataclass
class SuiteResult:
    timestamp: str
    tenant: str
    api_root: str
    worker_wid: Optional[str] = None
    results: list[CheckResult] = field(default_factory=list)

    def add(self, r: CheckResult) -> None:
        self.results.append(r)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warned(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "SKIP")


# ───────────────────────────────────────────────────────────────────────
# OAuth Authorization Code flow
# ───────────────────────────────────────────────────────────────────────


class _LocalhostCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures ``?code=...&state=...`` from the redirect, stores it on the
    server, and serves a small HTML page so the user knows they can close
    the browser tab.
    """

    captured: dict[str, str] = {}

    # Quiet down the noisy default access log; we don't want OAuth params
    # echoed to stderr where they'd end up in CI logs.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802 — stdlib API name
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            self.__class__.captured["code"] = params["code"][0]
        if "state" in params:
            self.__class__.captured["state"] = params["state"][0]
        if "error" in params:
            self.__class__.captured["error"] = params["error"][0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            b"<html><body><h2>You can close this tab.</h2>"
            b"<p>The Workday REST diagnostic captured the authorization "
            b"code; switch back to your terminal.</p></body></html>"
        )
        self.wfile.write(body)


def _generate_state() -> str:
    return _stdlib_secrets.token_urlsafe(24)


def _start_loopback_server(host: str, port: int) -> socketserver.TCPServer:
    """Bind a tiny HTTP server on ``host:port`` for the OAuth redirect.

    Only safe when ``redirect_uri`` is ``http://localhost...`` — TLS
    termination on stdlib http.server is brittle and the customer's
    Workday API Client config is what dictates which scheme is in use.
    """
    server = socketserver.TCPServer((host, port), _LocalhostCallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _exchange_code_for_token(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST to Workday's token endpoint. Returns parsed JSON on 200,
    or raises ``RuntimeError`` with a redacted error string on failure.

    We use HTTP Basic auth (RFC 6749 §2.3.1) because that's what the
    source PS does — Workday's REST OAuth accepts both Basic and
    body-encoded client credentials and Basic is the safer default.
    """
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    resp = requests.post(
        token_url,
        data=body,
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        # Don't echo the raw body — it can contain the code or hints
        # about what the secret looked like. Keep only status + a
        # generic error class taken from JSON if present.
        err_class = ""
        try:
            err_class = resp.json().get("error", "")
        except (ValueError, KeyError):
            pass
        raise RuntimeError(
            f"token endpoint returned HTTP {resp.status_code}"
            + (f" ({err_class})" if err_class else "")
        )
    return resp.json()


def acquire_oauth_token(
    *,
    workday_tenant: str,
    workday_host: str,
    authorize_host: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    listen: bool = False,
    browser_opener=webbrowser.open,
    paste_prompt=input,
) -> str:
    """Perform the OAuth 2.0 Authorization Code flow and return the access token.

    Default flow (no ``--listen``): open the browser, tell the user to
    copy the redirect URL from the address bar, parse the code and
    state out of it. Works for the conventional Workday API Client
    config with ``https://localhost:...`` redirect URI without needing
    a TLS cert.

    Listen flow (``--listen`` AND ``redirect_uri`` starts with
    ``http://localhost``): bind a tiny HTTP loopback server, wait for
    the browser to hit it, capture code and state automatically.
    """
    parsed = urllib.parse.urlparse(redirect_uri)
    use_listener = listen and parsed.scheme == "http" and parsed.hostname in (
        "localhost", "127.0.0.1",
    )

    state = _generate_state()
    auth_url = (
        f"https://{authorize_host}/{workday_tenant}/authorize"
        f"?response_type=code"
        f"&client_id={urllib.parse.quote(client_id, safe='')}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&state={urllib.parse.quote(state, safe='')}"
    )

    server: Optional[socketserver.TCPServer] = None
    captured: dict[str, str] = {}
    if use_listener:
        _LocalhostCallbackHandler.captured = captured
        host = parsed.hostname or "localhost"
        port = parsed.port or 8888
        server = _start_loopback_server(host, port)
        print(f"  Listening for OAuth callback on http://{host}:{port}...")

    print()
    print("  Opening browser for Workday OAuth login...")
    browser_opener(auth_url)

    if use_listener:
        try:
            assert server is not None
            deadline = time.monotonic() + 300  # 5 minutes
            while time.monotonic() < deadline and "code" not in captured:
                time.sleep(0.25)
        finally:
            assert server is not None
            server.shutdown()
            server.server_close()
        if "error" in captured:
            raise RuntimeError(f"Workday returned error '{captured['error']}'")
        if "code" not in captured:
            raise RuntimeError("Timed out waiting for OAuth callback")
        code = captured["code"]
        returned_state = captured.get("state", "")
    else:
        print()
        print("  After signing in, the browser will redirect to a URL that")
        print("  starts with your redirect URI (it may show a connection")
        print(f"  error — that's expected because Workday redirects to {redirect_uri}).")
        print("  Copy the FULL URL from the address bar and paste it below.")
        print()
        raw = paste_prompt("  Paste redirect URL (or just the code): ").strip()
        code, returned_state = _parse_code_from_paste(raw)

    if returned_state and returned_state != state:
        raise RuntimeError("OAuth state mismatch (possible CSRF or stale paste). Aborting.")

    token_url = f"https://{workday_host}/ccx/oauth2/{workday_tenant}/token"
    token_json = _exchange_code_for_token(
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
    )
    access_token = token_json.get("access_token")
    if not access_token:
        raise RuntimeError("Workday token response had no access_token")
    return access_token


def _parse_code_from_paste(raw: str) -> tuple[str, str]:
    """Extract ``code`` and ``state`` from a pasted redirect URL or raw code."""
    if "?" in raw or raw.startswith("http"):
        parsed = urllib.parse.urlparse(raw)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        if not code:
            raise RuntimeError("Pasted URL did not contain ?code=...")
        return code, state
    return raw, ""


# ───────────────────────────────────────────────────────────────────────
# REST helpers
# ───────────────────────────────────────────────────────────────────────


def _invoke_workday_rest(
    *,
    api_root: str,
    tenant: str,
    bearer_token: str,
    module: str,
    version: str,
    resource: str,
    method: str = "GET",
    query_params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[Optional[int], Any, int, str]:
    """Single REST request. Returns ``(status_code, json_or_none, latency_ms, error_or_empty)``."""
    url = f"{api_root}/{module}/{version}/{tenant}/{resource.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Accept": "application/json",
    }
    started = time.monotonic()
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, params=query_params or {}, timeout=timeout)
        else:
            resp = requests.request(
                method, url, headers={**headers, "Content-Type": "application/json"},
                params=query_params or {}, json=body, timeout=timeout,
            )
    except RequestException as e:
        return None, None, int((time.monotonic() - started) * 1000), str(e)
    latency_ms = int((time.monotonic() - started) * 1000)
    payload: Any = None
    try:
        payload = resp.json() if resp.content else None
    except ValueError:
        payload = None
    return resp.status_code, payload, latency_ms, ""


# ───────────────────────────────────────────────────────────────────────
# Endpoint catalog (ported from source $readOperations / $writeOperations)
# ───────────────────────────────────────────────────────────────────────


def _build_read_operations(worker_id: str, search_term: str) -> list[dict[str, Any]]:
    return [
        {"id": "WD-REST-001", "name": "GetWorkerInboxTasks", "module": "common",
         "version": "v1", "resource": f"workers/{worker_id}/inboxTasks",
         "query": {"limit": "5"}, "check_field": "data"},
        {"id": "WD-REST-002", "name": "GetWorkerPaySlips", "module": "common",
         "version": "v1", "resource": f"workers/{worker_id}/paySlips",
         "query": {"limit": "5"}, "check_field": "data"},
        {"id": "WD-REST-003", "name": "SearchWorkers", "module": "common",
         "version": "v1", "resource": "workers",
         "query": {"search": search_term, "limit": "5"}, "check_field": "data"},
        {"id": "WD-REST-004", "name": "GetWorkerDirectReports", "module": "common",
         "version": "v1", "resource": f"workers/{worker_id}/directReports",
         "query": {}, "check_field": "data"},
        {"id": "WD-REST-005", "name": "GetSupervisoryOrganizationsManaged",
         "module": "common", "version": "v1",
         "resource": f"workers/{worker_id}/supervisoryOrganizationsManaged",
         "query": {}, "check_field": "data"},
        {"id": "WD-REST-006", "name": "GetFeedbackTemplates",
         "module": "performanceEnablement", "version": "v5",
         "resource": "values/feedbackTemplate/feedbackTemplate/",
         "query": {}, "check_field": "data"},
    ]


def _build_write_operations(worker_id: str) -> list[dict[str, Any]]:
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    return [
        {"id": "WD-REST-007", "name": "TransferEmployee", "module": "common",
         "version": "v1", "resource": f"workers/{worker_id}/jobChanges",
         "method": "POST",
         "body": {
             "supervisoryOrganization": {"id": "test-validation-only"},
             "jobChangeReason": {"id": "test-validation-only"},
             "effective": future,
             "moveManagersTeam": False,
         }},
        {"id": "WD-REST-008", "name": "RequestFeedback",
         "module": "performanceEnablement", "version": "v5",
         "resource": f"workers/{worker_id}/requestedFeedbackOnWorkerEvents",
         "method": "POST",
         "body": {
             "feedbackResponders": [{"id": worker_id}],
             "feedbackConfidential": False,
             "showFeedbackProviderName": True,
             "expirationDate": future,
         }},
    ]


def _classify_failure(status_code: int | None, op_type: str) -> tuple[str, str]:
    """Map an HTTP status to (status, details) per source PS semantics."""
    if status_code == 401:
        return "FAIL", "401 Unauthorized — token expired or invalid"
    if status_code == 403:
        return "FAIL", "403 Forbidden — OAuth client missing required security domain"
    if status_code == 404:
        return "FAIL", "404 Not Found — endpoint path may differ for this tenant"
    if op_type == "Write" and status_code in (400, 422):
        return "PASS", f"HTTP {status_code} (expected — minimal body, endpoint reachable + auth OK)"
    if status_code is None:
        return "FAIL", "network error"
    return "FAIL", f"HTTP {status_code}"


# ───────────────────────────────────────────────────────────────────────
# PII / secrets redaction
# ───────────────────────────────────────────────────────────────────────


def _redact_worker_fields(obj: Any) -> Any:
    """Strip PII fields from a worker-shaped response copy. Returns a new
    structure; the input is not mutated.

    Best-effort: ESS Workday REST responses use ``descriptor`` for the
    display name and ``id`` for the WID, plus a handful of contact and
    org fields. We walk the structure and overwrite those by name.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("descriptor", "primaryWorkEmail", "businessTitle"):
                out[k] = "[REDACTED]"
            elif k == "id" and isinstance(v, str):
                out[k] = "[REDACTED-WID]"
            else:
                out[k] = _redact_worker_fields(v)
        return out
    if isinstance(obj, list):
        return [_redact_worker_fields(v) for v in obj]
    return obj


# ───────────────────────────────────────────────────────────────────────
# Suite execution
# ───────────────────────────────────────────────────────────────────────


def _resolve_worker_identity(
    suite: SuiteResult, api_root: str, tenant: str, bearer_token: str,
    user_supplied_worker_id: Optional[str], user_supplied_search: Optional[str],
) -> tuple[Optional[str], Optional[str], dict[str, Any] | None]:
    """Call ``workers/me`` and parse out the WID + a search term for use
    by subsequent read tests. Returns ``(worker_id, search_term, full_response)``.

    The full response is stashed only so callers can include a redacted
    summary in the JSON output; it must not leak through ``print``.
    """
    status_code, payload, latency_ms, err = _invoke_workday_rest(
        api_root=api_root, tenant=tenant, bearer_token=bearer_token,
        module="common", version="v1", resource="workers/me",
    )
    if status_code == 200 and isinstance(payload, dict) and payload.get("id"):
        worker_id = payload["id"]
        descriptor = payload.get("descriptor", "")
        search_term = (user_supplied_search
                       or (descriptor.split(" ")[0] if descriptor else worker_id))
        suite.add(CheckResult(
            id="WD-REST-ME", operation="GetWorkerMe", type="Identity",
            status="PASS", details=f"WID and identity returned ({latency_ms}ms)",
            latency_ms=latency_ms, http_status=status_code,
        ))
        return (user_supplied_worker_id or worker_id), search_term, payload

    status, details = _classify_failure(status_code, "Identity")
    if err:
        details = f"network error: {err}"
    suite.add(CheckResult(
        id="WD-REST-ME", operation="GetWorkerMe", type="Identity",
        status=status, details=details, latency_ms=latency_ms,
        http_status=status_code,
    ))
    return None, None, None


def _run_read_operations(
    suite: SuiteResult, api_root: str, tenant: str, bearer_token: str,
    worker_id: str, search_term: str,
) -> None:
    for op in _build_read_operations(worker_id, search_term):
        status_code, payload, latency_ms, err = _invoke_workday_rest(
            api_root=api_root, tenant=tenant, bearer_token=bearer_token,
            module=op["module"], version=op["version"],
            resource=op["resource"], query_params=op["query"],
        )
        if status_code is not None and 200 <= status_code < 300:
            has_field = isinstance(payload, dict) and op["check_field"] in payload
            if has_field:
                total = payload.get("total") if isinstance(payload, dict) else None
                detail = f"OK, total={total}" if total is not None else "OK"
                suite.add(CheckResult(
                    id=op["id"], operation=op["name"], type="Read",
                    status="PASS", details=detail, latency_ms=latency_ms,
                    http_status=status_code,
                ))
            else:
                suite.add(CheckResult(
                    id=op["id"], operation=op["name"], type="Read",
                    status="WARN",
                    details=f"Endpoint reachable but no '{op['check_field']}' in response",
                    latency_ms=latency_ms, http_status=status_code,
                ))
        else:
            status, details = _classify_failure(status_code, "Read")
            if err:
                details = f"network error: {err}"
            suite.add(CheckResult(
                id=op["id"], operation=op["name"], type="Read",
                status=status, details=details, latency_ms=latency_ms,
                http_status=status_code,
            ))


def _run_write_operations(
    suite: SuiteResult, api_root: str, tenant: str, bearer_token: str,
    worker_id: str, include_write_tests: bool,
) -> None:
    write_ops = _build_write_operations(worker_id)
    if not include_write_tests:
        for op in write_ops:
            suite.add(CheckResult(
                id=op["id"], operation=op["name"], type="Write",
                status="SKIP", details="Skipped (use --include-write-tests to enable)",
            ))
        return

    for op in write_ops:
        status_code, _payload, latency_ms, err = _invoke_workday_rest(
            api_root=api_root, tenant=tenant, bearer_token=bearer_token,
            module=op["module"], version=op["version"], resource=op["resource"],
            method=op["method"], body=op["body"],
        )
        if status_code is not None and 200 <= status_code < 300:
            suite.add(CheckResult(
                id=op["id"], operation=op["name"], type="Write",
                status="PASS", details="Endpoint reachable, auth accepted (HTTP 2xx)",
                latency_ms=latency_ms, http_status=status_code,
            ))
            continue
        status, details = _classify_failure(status_code, "Write")
        if err:
            details = f"network error: {err}"
        suite.add(CheckResult(
            id=op["id"], operation=op["name"], type="Write",
            status=status, details=details, latency_ms=latency_ms,
            http_status=status_code,
        ))


# ───────────────────────────────────────────────────────────────────────
# Output
# ───────────────────────────────────────────────────────────────────────


def _print_summary(suite: SuiteResult) -> None:
    print()
    print("=" * 64)
    print("  WORKDAY REST DIAGNOSTIC — SUMMARY")
    print("=" * 64)
    print(f"  Total:   {len(suite.results)} checks")
    print(f"  Passed:  {suite.passed}")
    print(f"  Failed:  {suite.failed}")
    print(f"  Warned:  {suite.warned}")
    print(f"  Skipped: {suite.skipped}")
    print()
    for r in suite.results:
        marker = {"PASS": "  ✓", "FAIL": "  ✗", "WARN": "  ~", "SKIP": "  -"}.get(r.status, "  ?")
        print(f"{marker} [{r.id}] {r.operation:36s} {r.status:5s} {r.details}")
    print()


def _write_json_output(
    suite: SuiteResult, output_dir: str, *, me_response: dict | None,
    include_pii: bool,
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(output_dir, f"workday-rest-{stamp}.json")

    me_section: Any = None
    if me_response is not None:
        me_section = me_response if include_pii else _redact_worker_fields(me_response)

    body = {
        "timestamp": suite.timestamp,
        "tenant": suite.tenant,
        "api_root": suite.api_root,
        "worker_wid": suite.worker_wid if include_pii else (
            "[REDACTED-WID]" if suite.worker_wid else None
        ),
        "totals": {
            "checks": len(suite.results),
            "passed": suite.passed,
            "failed": suite.failed,
            "warned": suite.warned,
            "skipped": suite.skipped,
        },
        "include_pii": include_pii,
        "results": [asdict(r) for r in suite.results],
        "workers_me_response": me_section,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)
    return out_path


# ───────────────────────────────────────────────────────────────────────
# Entry point
# ───────────────────────────────────────────────────────────────────────


def _prompt_missing(args: argparse.Namespace) -> argparse.Namespace:
    """Interactive prompts for the values the source PS prompts for."""
    if not args.workday_tenant:
        args.workday_tenant = input("Enter Workday Tenant (e.g., contoso_impl1): ").strip()
    if not args.workday_host:
        default = "wd2-impl-services1.workday.com"
        v = input(f"Enter Workday REST API Host [{default}]: ").strip()
        args.workday_host = v or default
    if not args.authorize_host:
        default = "impl.workday.com"
        v = input(f"Enter Workday Authorize Host [{default}]: ").strip()
        args.authorize_host = v or default
    if not args.oauth_client_id:
        args.oauth_client_id = input(
            "Enter OAuth Client ID (from Workday > Register API Client): "
        ).strip()
    if not args.oauth_client_secret:
        args.oauth_client_secret = getpass.getpass("Enter OAuth Client Secret: ")
    return args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="test_workday_rest_endpoints.py",
        description=(
            "Validate the 9 Workday REST connector actions ESS uses at runtime, "
            "via OAuth 2.0 Authorization Code flow."
        ),
    )
    parser.add_argument("--workday-tenant",
                        help="Workday tenant name (e.g. contoso_impl1)")
    parser.add_argument("--workday-host",
                        help="Workday REST API host (e.g. wd2-impl-services1.workday.com)")
    parser.add_argument("--authorize-host",
                        help="Workday OAuth authorize host (e.g. impl.workday.com)")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI,
                        help="OAuth redirect URI configured in the API client "
                             f"(default: {DEFAULT_REDIRECT_URI}).")
    parser.add_argument("--oauth-client-id",
                        help="OAuth Client ID from Workday > Register API Client.")
    parser.add_argument("--oauth-client-secret",
                        help="OAuth Client Secret. Prompted securely if omitted.")
    parser.add_argument("--test-worker-id", default=None,
                        help="Worker ID to use for employee-specific reads. "
                             "Default: WID returned by GetWorkerMe.")
    parser.add_argument("--search-term", default=None,
                        help="Search term for SearchWorkers. Default: first "
                             "word of GetWorkerMe descriptor.")
    parser.add_argument("--include-write-tests", action="store_true",
                        help="Include TransferEmployee + RequestFeedback. "
                             "Skipped by default. Use ONLY in test tenants.")
    parser.add_argument("--listen", action="store_true",
                        help="Spin up an HTTP loopback server for the OAuth "
                             "callback. Only valid when --redirect-uri starts "
                             "with http://localhost; otherwise falls back to "
                             "the paste-the-URL flow.")
    parser.add_argument("--include-pii", action="store_true",
                        help="Keep employee PII (name, email, WID, etc.) in "
                             "the JSON output. Default: PII is redacted. Use "
                             "ONLY in your own tenant for debugging.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help=f"Where to write the JSON result file (default: {DEFAULT_OUTPUT_DIR}).")
    parser.add_argument("--print-help-only", action="store_true",
                        help=argparse.SUPPRESS)  # used by smoke tests

    args = parser.parse_args(argv)
    if args.print_help_only:
        return 0

    args = _prompt_missing(args)
    if not all([args.workday_tenant, args.workday_host, args.authorize_host,
                args.oauth_client_id, args.oauth_client_secret]):
        print("ERROR: Missing required parameter.", file=sys.stderr)
        return 2

    api_root = f"https://{args.workday_host}/ccx/api"
    suite = SuiteResult(
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
        tenant=args.workday_tenant,
        api_root=api_root,
    )

    print()
    print("=" * 64)
    print("  Workday REST Endpoint Diagnostic")
    print("  Auth: OAuth 2.0 Authorization Code")
    print("=" * 64)
    print(f"  Tenant:        {args.workday_tenant}")
    print(f"  API Root:      {api_root}")
    print(f"  Authorize:     https://{args.authorize_host}/{args.workday_tenant}/authorize")
    print(f"  Redirect URI:  {args.redirect_uri}")
    print(f"  Write Tests:   {'ENABLED' if args.include_write_tests else 'SKIPPED'}")
    print()

    # Step 1: OAuth
    try:
        bearer_token = acquire_oauth_token(
            workday_tenant=args.workday_tenant,
            workday_host=args.workday_host,
            authorize_host=args.authorize_host,
            client_id=args.oauth_client_id,
            client_secret=args.oauth_client_secret,
            redirect_uri=args.redirect_uri,
            listen=args.listen,
        )
        suite.add(CheckResult(
            id="WD-REST-AUTH", operation="OAuth Token (AuthCode)", type="Auth",
            status="PASS", details="Access token acquired",
        ))
    except Exception as e:
        suite.add(CheckResult(
            id="WD-REST-AUTH", operation="OAuth Token (AuthCode)", type="Auth",
            status="FAIL", details=str(e),
        ))
        _print_summary(suite)
        path = _write_json_output(suite, args.output_dir, me_response=None,
                                  include_pii=args.include_pii)
        print(f"  Results: {path}")
        return 1

    # Step 2: identity
    worker_id, search_term, me_resp = _resolve_worker_identity(
        suite, api_root, args.workday_tenant, bearer_token,
        args.test_worker_id, args.search_term,
    )
    if not worker_id:
        _print_summary(suite)
        path = _write_json_output(suite, args.output_dir, me_response=None,
                                  include_pii=args.include_pii)
        print(f"  Results: {path}")
        return 1
    suite.worker_wid = worker_id

    # Step 3: reads
    _run_read_operations(suite, api_root, args.workday_tenant, bearer_token,
                         worker_id, search_term or worker_id)

    # Step 4: writes
    _run_write_operations(suite, api_root, args.workday_tenant, bearer_token,
                          worker_id, args.include_write_tests)

    _print_summary(suite)
    path = _write_json_output(suite, args.output_dir, me_response=me_resp,
                              include_pii=args.include_pii)
    print(f"  Results: {path}")
    return 1 if suite.failed else 0


if __name__ == "__main__":
    sys.exit(main())
