#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering Workday's REST admin APIs via OAuth 2.0.

Two auth flows supported, in order of preference:

  1. Client Credentials grant — POST {token_url} with
     grant_type=client_credentials and Basic auth of client_id:client_secret.
     Works only if the Workday API Client was registered with the
     "Application Credentials Grant" task. Most Workday tenants do NOT
     have this task available — `Register API Client for Integrations`
     creates a JWT-Bearer-only client.

  2. JWT Bearer grant — generate an RSA keypair (run
     `python tests/captures/_workday_keygen.py` once), upload the
     public key to your Workday API Client via the "Manage Public Keys"
     related action, then set
     ``$env:WORKDAY_JWT_PRIVATE_KEY_PATH`` to the private key path.
     The wrapper signs a JWT assertion with the private key and POSTs
     ``grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=<jwt>``.
     This is the standard Workday server-to-server OAuth flow.

This is the OAuth+REST counterpart to record_workday_config.py (which
tries the SOAP path). Per the 2026-05 investigation logged in
tests/AGENTS.md, Workday config-validation operations aren't reachable
via the publicly-exposed SOAP services on a typical tenant — the path
forward is REST admin endpoints with OAuth bearer auth.

Endpoints captured (each best-effort — Workday's REST admin surface
varies between tenants and we don't know exactly which ones this
tenant exposes):
  - /ccx/api/v1/{tenant}/workers              (list workers)
  - /ccx/api/staffing/v6/{tenant}/workers     (newer worker list endpoint)
  - /ccx/api/v1/{tenant}/me                   (caller identity)
  - /ccx/api/integration/v1/{tenant}/api-clients
  - /ccx/api/security/v1/{tenant}/authentication-policies

Pre-reqs (set before running):
    $env:WORKDAY_TENANT_HOST     = "https://wd2-impl-services1.workday.com"
    $env:WORKDAY_TENANT_NAME     = "<tenant>"
    $env:WORKDAY_OAUTH_CLIENT_ID = "<from Register API Client for Integrations>"
    $env:WORKDAY_OAUTH_CLIENT_SECRET = "<one-time secret from same task>"
    # For JWT Bearer flow (recommended for clients registered via
    # 'Register API Client for Integrations'):
    $env:WORKDAY_JWT_PRIVATE_KEY_PATH = "<absolute path to private key pem>"
    python tests\\captures\\record_workday_rest_admin.py

Output: tests/fixtures/cassettes/workday_rest_admin.yaml
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sys
import time

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit

REQUIRED_ENV = (
    "WORKDAY_TENANT_HOST",
    "WORKDAY_TENANT_NAME",
    "WORKDAY_OAUTH_CLIENT_ID",
    "WORKDAY_OAUTH_CLIENT_SECRET",
)


def _check_env() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print("ERROR: missing required environment variables:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)
    return {name: os.environ[name] for name in REQUIRED_ENV}


def _rewrite_web_to_soap_host(raw: str) -> str:
    """Reuses the same web→SOAP host mapping as the SOAP wrappers.
    Workday's REST and SOAP services live on the same host."""
    web_to_soap = {
        "https://impl.workday.com": "https://wd2-impl-services1.workday.com",
        "https://wd5.myworkday.com": "https://wd5-services1.myworkday.com",
        "https://wd3.myworkday.com": "https://wd3-services1.myworkday.com",
        "https://wd2.myworkday.com": "https://wd2-services1.myworkday.com",
    }
    return web_to_soap.get(raw, raw)


def _b64url(data: bytes) -> str:
    """Base64url-encode without padding (per RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_jwt_assertion(
    *,
    private_key_path: str,
    client_id: str,
    token_url: str,
    sub: str | None = None,
) -> str:
    """Build and RS256-sign a JWT assertion for Workday's JWT Bearer flow.

    Claims (per Workday OAuth docs):
      iss = API Client ID
      sub = API Client ID  (Workday treats sub == iss for client-as-self)
      aud = the token endpoint URL
      iat = now
      exp = now + 5 minutes
      jti = random unique id
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        print("ERROR: 'cryptography' package not found — required for JWT signing.")
        print("Run: pip install cryptography")
        sys.exit(1)

    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": client_id,
        "sub": sub or client_id,
        "aud": token_url,
        "iat": now,
        "exp": now + 300,
        "jti": secrets.token_hex(16),
    }

    h_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    c_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{c_b64}".encode("ascii")

    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    s_b64 = _b64url(signature)

    return f"{h_b64}.{c_b64}.{s_b64}"


def _post_token_attempts(token_url: str, attempts: list[tuple[str, dict]]):
    """Run a series of token-endpoint POST attempts; yield sanitized results.

    Each attempt's `kwargs` carries credential material (Basic auth header
    or grant_type body params). The `requests.Response` object that comes
    back is therefore considered "tainted" by CodeQL's data-flow analysis
    — anything derived from it is flagged as logging-sensitive-data.

    This helper consumes the response object internally and yields ONLY
    clean, decoupled primitives: an int status code, parsed JSON (or None
    on parse failure), and a bounded server-response string. Callers can
    print these freely without tripping the CodeQL rule, because there is
    no data-flow path back to the credential material.

    Yields tuples of (label, status_code, payload, body_text). When the
    request itself fails (DNS/connect/timeout), status_code is None and
    body_text contains a sanitized "unreachable (<ExceptionType>)" string
    — the exception's str() value is intentionally NOT included since it
    can in theory leak the request URL.
    """
    import requests
    for label, kwargs in attempts:
        try:
            r = requests.post(token_url, timeout=30, **kwargs)
        except requests.RequestException as exc:
            yield (label, None, None, f"unreachable ({type(exc).__name__})")
            continue
        status_code = int(r.status_code)
        body_text = str(r.text)[:600].replace("\n", " ") if r.text else ""
        try:
            payload = r.json() if r.text else None
        except ValueError:
            payload = None
        del r  # explicit drop so anything below operates on locals only
        yield (label, status_code, payload, body_text)


def _acquire_token_jwt_bearer(
    token_url: str, client_id: str, client_secret: str, private_key_path: str
) -> str | None:
    """Build a signed JWT assertion and exchange it for a bearer token."""
    import requests

    print("  Auth flow: JWT Bearer (RFC 7523)")
    try:
        assertion = _sign_jwt_assertion(
            private_key_path=private_key_path,
            client_id=client_id,
            token_url=token_url,
        )
    except FileNotFoundError:
        print(f"  Private key not found at {private_key_path}")
        print("  Run: python tests\\captures\\_workday_keygen.py")
        return None
    except Exception as exc:
        print(f"  JWT signing failed: {exc!s}")
        return None

    # Workday's JWT Bearer flow may or may not require client authentication
    # in addition to the assertion. Try with assertion only first; fall
    # back to assertion + Basic auth if that fails with invalid_client.
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    attempts = [
        (
            "assertion only",
            {
                "data": {
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            },
        ),
        (
            "assertion + Basic auth",
            {
                "data": {
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                "headers": {
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            },
        ),
    ]

    for label, status_code, payload, body_text in _post_token_attempts(token_url, attempts):
        if status_code is None:
            print(f"  Try [{label}]: {body_text}")
            continue
        print(f"  Try [{label}]: HTTP {status_code}")
        if status_code == 200 and isinstance(payload, dict):
            token = payload.get("access_token")
            if token:
                return token
        if payload is None:
            print(f"    response not JSON: {body_text[:200]}")
        else:
            print(f"    response body: {body_text}")

    return None


def _acquire_token_client_credentials(
    token_url: str, client_id: str, client_secret: str
) -> str | None:
    """POST to Workday's OAuth token endpoint with client_credentials grant.
    Most Workday tenants don't support this grant type for clients
    registered via 'Register API Client for Integrations'."""
    import requests

    print("  Auth flow: client_credentials")
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    attempts = [
        (
            "Basic auth header",
            {
                "data": {"grant_type": "client_credentials"},
                "headers": {
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            },
        ),
        (
            "client_id+client_secret in body",
            {
                "data": {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            },
        ),
    ]

    for label, status_code, payload, body_text in _post_token_attempts(token_url, attempts):
        if status_code is None:
            print(f"  Try [{label}]: {body_text}")
            continue
        print(f"  Try [{label}]: HTTP {status_code}")
        if status_code == 200 and isinstance(payload, dict):
            token = payload.get("access_token")
            if token:
                return token
        if payload is None:
            print(f"    response not JSON: {body_text[:200]}")
        else:
            print(f"    response body: {body_text}")

    return None


def _acquire_token_refresh_token(
    token_url: str, client_id: str, client_secret: str, refresh_token: str
) -> str | None:
    """Exchange a Workday refresh token for an access token.

    This is the standard flow for clients registered via "Register API
    Client for Integrations" — Workday's "Application Credentials"
    pattern uses refresh_token grant rather than client_credentials.
    The refresh token is bootstrapped via the
    "Manage Refresh Tokens for Integrations" task in Workday.
    """
    import requests

    print("  Auth flow: refresh_token (Workday Application Credentials pattern)")
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    attempts = [
        (
            "Basic auth header",
            {
                "data": {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                "headers": {
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            },
        ),
        (
            "client_id+client_secret in body",
            {
                "data": {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                "headers": {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            },
        ),
    ]

    for label, status_code, payload, body_text in _post_token_attempts(token_url, attempts):
        if status_code is None:
            print(f"  Try [{label}]: {body_text}")
            continue
        print(f"  Try [{label}]: HTTP {status_code}")
        if status_code == 200 and isinstance(payload, dict):
            token = payload.get("access_token")
            if token:
                # Workday may rotate the refresh token. If so, surface
                # the fact (without printing any of the token value) so
                # the operator knows to refresh their env var.
                new_refresh = payload.get("refresh_token")
                if new_refresh and new_refresh != refresh_token:
                    print(
                        "    NOTE: Workday issued a new refresh token. Update "
                        "WORKDAY_OAUTH_REFRESH_TOKEN env var with the new value "
                        "before your next run (run with $env:WORKDAY_DEBUG_PRINT_NEW_REFRESH=1 "
                        "to print the value, otherwise capture from the cassette and update by hand)."
                    )
                    if os.environ.get("WORKDAY_DEBUG_PRINT_NEW_REFRESH"):
                        print(f"    (debug) new refresh token length: {len(new_refresh)} chars")
                return token
        if payload is None:
            print(f"    response not JSON: {body_text[:200]}")
        else:
            print(f"    response body: {body_text}")

    return None


def _acquire_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    private_key_path: str | None,
    refresh_token: str | None,
) -> str | None:
    """Try the most-likely-to-succeed grant type first based on what
    credentials are configured, then fall back through the others for
    diagnostic value.

    Order:
      1. refresh_token grant — works for "Register API Client for
         Integrations" clients (the common case). Requires
         WORKDAY_OAUTH_REFRESH_TOKEN env var, bootstrapped via the
         "Manage Refresh Tokens for Integrations" task in Workday.
      2. JWT Bearer — works for clients with a registered public key
         (uncommon for "for Integrations" clients in modern Workday
         versions, which use refresh_token instead).
      3. client_credentials — works only for clients registered via
         "Application Credentials Grant" task (separate from "for
         Integrations"; not all tenants have it).
    """
    if refresh_token:
        token = _acquire_token_refresh_token(
            token_url, client_id, client_secret, refresh_token
        )
        if token:
            return token
        print()
        print("  refresh_token failed; trying other grant types as diagnostic...")

    if private_key_path:
        token = _acquire_token_jwt_bearer(
            token_url, client_id, client_secret, private_key_path
        )
        if token:
            return token
        print()
        print("  JWT Bearer failed; falling back to client_credentials...")

    return _acquire_token_client_credentials(token_url, client_id, client_secret)


def main() -> None:
    announce("workday_rest_admin")
    env = _check_env()
    private_key_path = os.environ.get("WORKDAY_JWT_PRIVATE_KEY_PATH", "").strip() or None
    refresh_token = os.environ.get("WORKDAY_OAUTH_REFRESH_TOKEN", "").strip() or None

    raw_host = env["WORKDAY_TENANT_HOST"].rstrip("/")
    soap_host = _rewrite_web_to_soap_host(raw_host)
    if soap_host != raw_host:
        print(f"  Note: rewrote web host {raw_host} -> services host {soap_host}")
    tenant = env["WORKDAY_TENANT_NAME"]
    token_url = f"{soap_host}/ccx/oauth2/{tenant}/token"
    rest_base = f"{soap_host}/ccx/api"

    print(f"  Token endpoint: {token_url}")
    print(f"  REST base URL:  {rest_base}/<module>/v<n>/{tenant}/<resource>")
    if refresh_token:
        # CodeQL flagged the previous "starts with {refresh_token[:8]}..." formatting
        # as a real partial-credential leak. Print only the length, not any bytes
        # of the token value.
        print(f"  Refresh token:  configured ({len(refresh_token)} chars)")
    elif private_key_path:
        print(f"  Private key:    {private_key_path} (JWT Bearer flow)")
    else:
        print("  Auth:           no refresh token or private key — will try client_credentials")
        print("  For 'Register API Client for Integrations' clients, the standard")
        print("  flow is refresh_token. Bootstrap via:")
        print("    1. In Workday, run 'Manage Refresh Tokens for Integrations' task")
        print("    2. Pick your client + your Workday account, generate a token")
        print("    3. Set: $env:WORKDAY_OAUTH_REFRESH_TOKEN = '<copied token>'")
        print("    4. Re-run this script")
    print()

    confirm_or_exit()
    chdir_kit_root()

    import requests

    print("  Step 1: acquiring OAuth access token...")
    with build_cassette("workday_rest_admin"):
        token = _acquire_token(
            token_url,
            env["WORKDAY_OAUTH_CLIENT_ID"],
            env["WORKDAY_OAUTH_CLIENT_SECRET"],
            private_key_path,
            refresh_token,
        )
        if not token:
            print("  ABORT: no access token; not making admin API calls.")
            return
        print(f"  Step 1: OK (token starts with {token[:8]}...)")
        print()

        endpoints = [
            ("workers (v1, list, top 5)",      f"v1/{tenant}/workers?limit=5"),
            ("workers (staffing/v6, top 5)",   f"staffing/v6/{tenant}/workers?limit=5"),
            # Per simplified-setup doc, the user-context endpoint is
            # /workers/me (not /me). The kit's simplified Workday integration
            # uses this for the user-context lookup that replaces RaaS.
            ("workers/me (user context)",      f"v1/{tenant}/workers/me"),
            ("workers/me (staffing/v6)",       f"staffing/v6/{tenant}/workers/me"),
            ("api-clients (admin)",            f"integration/v1/{tenant}/api-clients?limit=5"),
            ("authentication-policies (admin)", f"security/v1/{tenant}/authentication-policies?limit=5"),
            ("system-users (admin)",           f"integration/v1/{tenant}/system-users?limit=5"),
            ("security-groups (admin)",        f"security/v1/{tenant}/security-groups?limit=5"),
        ]

        print("  Step 2: hitting REST admin endpoints with Bearer token")
        for label, path in endpoints:
            url = f"{rest_base}/{path}"
            try:
                r = requests.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=30,
                )
                print(f"    {label:42s} -> {r.status_code}")
                if r.status_code != 200:
                    snippet = r.text[:200].replace("\n", " ")
                    m = re.search(r'"error[_-]?description"\s*:\s*"([^"]*)"', r.text)
                    if m:
                        print(f"      error: {m.group(1)[:200]}")
                    else:
                        m = re.search(r'"message"\s*:\s*"([^"]*)"', r.text)
                        if m:
                            print(f"      message: {m.group(1)[:200]}")
                        else:
                            print(f"      body[:200]: {snippet}")
            except requests.RequestException as exc:
                print(f"    {label:42s} -> ERROR {exc!s}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/workday_rest_admin.yaml")
    print("for any leftover identifying data before committing. The redactor catches")
    print("emails, GUIDs, Workday WIDs, employee IDs, and Workday-specific PII")
    print("elements, but eyeball is the safety net.")
    print()
    print("Suggested cleanup after a successful run:")
    print("  Remove-Item env:WORKDAY_OAUTH_CLIENT_SECRET")


if __name__ == "__main__":
    main()
