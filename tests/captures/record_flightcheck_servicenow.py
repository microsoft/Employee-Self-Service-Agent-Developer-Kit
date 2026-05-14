#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the ServiceNow Knowledge Microsoft 365 Copilot
Connector setup-validation API surface.

PURPOSE
=======

The ESS agent integrates with ServiceNow in two distinct ways:

  1. ServiceNow Knowledge (M365 Copilot Connector) — indexes ServiceNow
     KB articles into M365 Copilot Search. Setup is documented at:
     https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/servicenow

  2. ServiceNow HRSD/ITSM (Power Platform connector + topics + flows) —
     creates/updates tickets, looks up CMDB. Setup at:
     https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/servicenow-hrsd-itsm

THIS RECORDER targets the FIRST integration only — Knowledge connector
setup validation. It captures the API responses a future FlightCheck
check would consume to verify the customer's ServiceNow instance is
configured correctly per the Knowledge connector docs.

If you also want a cassette for HRSD/ITSM ticket flows, that's a
separate recording session (different tables, different concerns).

WHAT GETS CAPTURED
==================

Setup steps the doc requires, mapped to verifiable API calls:

  Task                                   | Endpoint(s) we capture
  ---------------------------------------|----------------------------------------
  1. OAuth Application Registry exists,  | GET /api/now/table/oauth_entity
     active, with right callback URL     |   filtered by type=external_client
                                         |
  -. Crawling service account exists,    | GET /api/now/table/sys_user?
     active, has the required role       |     sysparm_query=active=true
                                         |
  -. Crawling account can read           | GET /api/now/table/kb_knowledge?limit=1
     all required tables (this is THE    | GET /api/now/table/user_criteria?limit=1
     critical permissions check the      | GET /api/now/table/sys_user_group?limit=1
     doc warns about)                    | GET /api/now/table/sys_user_role?limit=1
                                         |
  2. ACL configured for REST_Endpoint    | GET /api/now/table/sys_security_acl?
     (only if Advanced Scripts are used) |     sysparm_query=type=REST_Endpoint
                                         |
  3. Scripted REST API exists            | GET /api/now/table/sys_ws_definition
     (only if Advanced Scripts are used) |
                                         |
  4. /user_criteria API resource defined | GET /api/now/table/sys_ws_operation?
     (only if Advanced Scripts are used) |     sysparm_query=relative_path=/user_criteria
                                         |
  -. Negative: 401 (bad credentials)     | GET /api/now/table/oauth_entity with bad pwd
                                         |
  -. Negative: 403 (no perm to read      | GET /api/now/table/user_criteria as a
     user_criteria) — the most common    |     limited-access user (only runs if
     misconfiguration                    |     SERVICENOW_LIMITED_USERNAME set)

USAGE
=====

    $env:SERVICENOW_INSTANCE_URL      = "https://devNNNNN.service-now.com"
    $env:SERVICENOW_USERNAME          = "admin"
    $env:SERVICENOW_PASSWORD          = "..."   # use a secret manager

    # OPTIONAL — for the 403 negative path. A second account that exists
    # in your dev instance but lacks read access to user_criteria. If
    # unset, the 403 negative test is skipped (cassette still useful).
    $env:SERVICENOW_LIMITED_USERNAME  = "limited_test_user"
    $env:SERVICENOW_LIMITED_PASSWORD  = "..."

    # OPTIONAL — narrows the OAuth registry lookup to a specific name.
    # If unset, lists ALL external_client OAuth entries (still useful).
    $env:SERVICENOW_OAUTH_REGISTRY_NAME = "Microsoft 365 Copilot Connector"

    python tests\\captures\\record_flightcheck_servicenow.py

Output: tests/fixtures/cassettes/flightcheck_servicenow.yaml

Get a free dev instance at https://developer.servicenow.com if you don't
have one. The dev instance comes with demo data — no real customer PII
involved. Tables we hit are admin-side, not user record content.

NOTE — Elevated security_admin role:
  Per the doc, "for all security related tasks in ServiceNow, the
  signed-in user with admin or security_admin role must elevate their
  access using 'Elevate role' option from the profile menu." If
  oauth_entity / sys_security_acl / sys_ws_definition return 403, the
  recorder account hasn't elevated. The cassette captures that 403,
  which is itself a valid setup-state shape (a check could detect
  "couldn't read OAuth registry — caller needs elevated security_admin").
"""

from __future__ import annotations

import os
import sys
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from _common import announce, build_cassette, confirm_or_exit

REQUIRED_ENV = ("SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD")
OPTIONAL_ENV = (
    "SERVICENOW_LIMITED_USERNAME",
    "SERVICENOW_LIMITED_PASSWORD",
    "SERVICENOW_OAUTH_REGISTRY_NAME",
)


def _check_env() -> tuple[dict[str, str], dict[str, str]]:
    """Return (metadata, secrets) split.

    `metadata` carries non-sensitive values that are safe to print
    (instance URL, usernames, OAuth registry name filter). `secrets`
    carries password values that must never be printed or logged.

    The split exists to satisfy the CodeQL "Clear-text logging of
    sensitive information" rule. If both groups were returned in one
    dict, CodeQL's data-flow analysis would taint every print() that
    referenced any field of the dict, even fields that hold only
    non-sensitive metadata. Same pattern as production
    `solutions/.../checks/workday.py`.
    """
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print("ERROR: missing required environment variables:")
        for m in missing:
            print(f"  - {m}")
        print()
        print("Set them and re-run. See the docstring at the top of this file.")
        sys.exit(1)
    metadata: dict[str, str] = {
        "instance":  os.environ["SERVICENOW_INSTANCE_URL"],
        "username":  os.environ["SERVICENOW_USERNAME"],
    }
    secrets: dict[str, str] = {
        "password":  os.environ["SERVICENOW_PASSWORD"],
    }
    if os.environ.get("SERVICENOW_LIMITED_USERNAME"):
        metadata["limited_username"] = os.environ["SERVICENOW_LIMITED_USERNAME"]
    if os.environ.get("SERVICENOW_LIMITED_PASSWORD"):
        secrets["limited_password"] = os.environ["SERVICENOW_LIMITED_PASSWORD"]
    if os.environ.get("SERVICENOW_OAUTH_REGISTRY_NAME"):
        metadata["oauth_registry_name"] = os.environ["SERVICENOW_OAUTH_REGISTRY_NAME"]
    return metadata, secrets


def main() -> None:
    announce("flightcheck_servicenow (Knowledge connector setup validation)")
    # Two-dict return keeps secrets off the taint graph for any code
    # that only consumes metadata. See _check_env docstring.
    metadata, secrets = _check_env()

    instance = metadata["instance"].rstrip("/")
    headers = {"Accept": "application/json"}

    if not instance.lower().startswith("https://"):
        print(f"ERROR: SERVICENOW_INSTANCE_URL must use https:// (got {instance!r}).")
        sys.exit(1)

    # Prints are intentionally driven by `metadata` only — never by
    # `secrets` directly or by any object whose construction reads
    # from `secrets`. See _check_env docstring.
    print(f"  Instance: {instance}")
    print(f"  Account:  {metadata['username']}")
    if "oauth_registry_name" in metadata:
        print(f"  OAuth registry name filter: {metadata['oauth_registry_name']!r}")
    if "limited_username" in metadata:
        print(f"  Limited account: {metadata['limited_username']}  (used for 403 negative)")
    else:
        print("  No SERVICENOW_LIMITED_USERNAME — 403 negative path will be SKIPPED.")
    print()

    confirm_or_exit()

    # Build auth objects ONLY here, after all metadata-only prints are
    # done. These objects taint anything they touch, so we keep them
    # contained to _do().
    auth = HTTPBasicAuth(metadata["username"], secrets["password"])

    def _do(label: str, path: str, *, auth_override=None, expect_status: int = 200):
        url = f"{instance}/api/now/table/{path}"
        try:
            r = requests.get(url, auth=auth_override or auth, headers=headers, timeout=30)
            # Sanitize tainted response data into clean local primitives
            # BEFORE any print(). status_code is an int, body_text is a
            # bounded server-returned string. Neither carries credentials,
            # but CodeQL needs the explicit decoupling to drop the taint.
            status_code = int(r.status_code)
            body_text = str(r.text)[:200] if r.text else ""
            try:
                body_json = r.json()
            except ValueError:
                body_json = None
            del r  # explicit drop so anything below operates on locals only

            ok = status_code == expect_status
            marker = "OK " if ok else "!! "
            print(f"  {marker}{label:55} -> {status_code} (expected {expect_status})")
            if not ok and status_code in (400, 401, 403, 404):
                if body_json is not None and isinstance(body_json, dict):
                    err = body_json.get("error")
                    msg = err.get("message", "") if isinstance(err, dict) else str(err)
                    print(f"     body: {str(msg)[:200]}")
                else:
                    print(f"     body[:200]: {body_text}")
            if ok and status_code == 200 and body_json is not None and isinstance(body_json, dict):
                n = len(body_json.get("result", []))
                print(f"     records returned: {n}")
        except requests.RequestException as exc:
            print(f"  ?? {label}: REQUEST ERROR — {exc!s}")

    with build_cassette("flightcheck_servicenow"):
        # ---- Step 1: OAuth Application Registry (Task 1 from the doc) ----
        # The OAuth registry holds the client_id/client_secret used by the
        # M365 Copilot Connector. The doc requires the callback URL be
        # `https://gcs.office.com/v1.0/admin/oauth/callback` (commercial)
        # or the GCC equivalent. Active=true.
        oauth_path = (
            "oauth_entity?sysparm_query=type=external_client"
            "&sysparm_fields=name,client_id,redirect_url,active,refresh_lifetime,"
            "access_token_lifetime,sys_id&sysparm_limit=20"
        )
        if env.get("SERVICENOW_OAUTH_REGISTRY_NAME"):
            name_filter = quote(metadata["oauth_registry_name"], safe="")
            oauth_path = (
                "oauth_entity?sysparm_query=type=external_client"
                f"^name={name_filter}&sysparm_fields=name,client_id,redirect_url,"
                "active,refresh_lifetime,access_token_lifetime,sys_id&sysparm_limit=5"
            )
        _do("[Task 1] OAuth Application Registry list", oauth_path)

        # ---- Service account validation ----
        # The crawling account must exist + be active. We can't dynamically
        # know the account name, but we can list active users with admin/
        # security-relevant roles to surface the candidate accounts.
        _do(
            "[--] Service account: list active users (top 5)",
            "sys_user?sysparm_query=active=true&sysparm_limit=5"
            "&sysparm_fields=user_name,name,active,roles",
        )

        # ---- Critical: crawling account read access to required tables ----
        # The MOST important set per the doc. Each call answers "can this
        # account read this table?" — 200 = yes, 403 = no, and 403 on
        # user_criteria is the #1 misconfiguration the doc calls out.
        # We use limit=1 so we don't slurp tables; just probe access.
        _do(
            "[Critical] kb_knowledge read access (knowledge articles)",
            "kb_knowledge?sysparm_limit=1&sysparm_fields=number,short_description",
        )
        _do(
            "[Critical] user_criteria read access (THE permissions table)",
            "user_criteria?sysparm_limit=1&sysparm_fields=name",
        )
        _do(
            "[Critical] sys_user_group read access (referenced in user_criteria)",
            "sys_user_group?sysparm_limit=1&sysparm_fields=name",
        )
        _do(
            "[Critical] sys_user_role read access (referenced in user_criteria)",
            "sys_user_role?sysparm_limit=1&sysparm_fields=name",
        )

        # ---- Tasks 2-4: Advanced Scripts setup (optional per doc) ----
        # If the customer doesn't use Advanced Scripts, these will be
        # absent (200 with empty result, NOT a failure). Capture the
        # empty-result shape so the check can distinguish "not        # configured" from "configuration broken". The doc says these tasks are
        # "required ONLY if Advanced Scripts are in place".
        _do(
            "[Task 2] REST_Endpoint ACLs (Advanced Scripts only)",
            "sys_security_acl?sysparm_query=type=REST_Endpoint"
            "&sysparm_fields=name,operation,active,role&sysparm_limit=10",
        )
        _do(
            "[Task 3] Scripted REST APIs (Advanced Scripts only)",
            "sys_ws_definition?sysparm_query=active=true"
            "&sysparm_fields=name,api_id,namespace,active&sysparm_limit=10",
        )
        _do(
            "[Task 4] Scripted REST API resource at /user_criteria (Advanced Scripts only)",
            "sys_ws_operation?sysparm_query=relative_path=/user_criteria"
            "&sysparm_fields=name,relative_path,http_method,active&sysparm_limit=5",
        )

        # ---- Negative path 1: bad password -> 401 ----
        # Captures the unauthenticated response shape. A check that
        # claims "auth works" must see this 401 to assert the opposite.
        _do(
            "[Negative] bad password (expect 401)",
            "oauth_entity?sysparm_limit=1",
            auth_override=HTTPBasicAuth(metadata["username"], "deliberately-wrong"),
            expect_status=401,
        )

        # ---- Negative path 2: account missing user_criteria role (403) ----
        # The MOST informative negative  captures the response shape when
        # the crawling account exists but lacks read access to user_criteria.
        # This is the failure mode the doc warns about most loudly.
        # Skipped if SERVICENOW_LIMITED_USERNAME isn't set; cassette is
        # still useful without it.
        if "limited_username" in metadata and "limited_password" in secrets:
            limited_auth = HTTPBasicAuth(
                metadata["limited_username"],
                secrets["limited_password"],
            )
            _do(
                "[Negative] limited account reading user_criteria (expect 403)",
                "user_criteria?sysparm_limit=1",
                auth_override=limited_auth,
                expect_status=403,
            )
        else:
            print("  -- [Negative] 403 user_criteria check SKIPPED (no limited creds set).")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/flightcheck_servicenow.yaml")
    print("for any leftover identifying data before committing.")
    print("The redactor scrubs GUIDs, emails, and dev instance hostnames")
    print("(devNNNNN.service-now.com -> devmocktenant.service-now.com).")
    print("Eyeball the cassette for: real user_name strings, real OAuth")
    print("registry names, real role names  none of those are auto-scrubbed.")


if __name__ == "__main__":
    main()
