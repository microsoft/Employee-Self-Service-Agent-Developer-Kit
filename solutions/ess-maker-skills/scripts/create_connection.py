# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Power Platform Connection Creator

PUTs a new connection via the per-environment Connectivity API.

OAuth-mode connections come back Unauthenticated — the user must complete
sign-in in the maker portal (the connector's own Entra app handles the
SAML federation to Workday). See step3.md "Auth-mode decision".

Usage:
    python scripts/create_connection.py \\
        --env-id <guid> --env-url <url> --connector shared_workdaysoap
    python scripts/create_connection.py \\
        --env-id <guid> --env-url <url> --connector shared_commondataserviceforapps

Exit codes: 0 success, 1 auth, 2 client error (4xx), 3 unexpected.
"""

import argparse
import datetime
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    print("ERROR: 'requests' required. Run: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(3)

from auth import discover_tenant
from pp_helpers import (
    SCOPES_BY_RING,
    acquire_browser_token,
    load_env_file,
    lookup_env,
    per_env_host,
    short_connector_name,
)


API_VERSION = "1"


def build_workday_params(env_map):
    """Construct connectionParametersSet.values for shared_workdaysoap `oauth` mode."""
    required = [
        "WORKDAY_BASE_URL",
        "WORKDAY_TENANT",
        "WORKDAY_OAUTH_TOKEN_URL",
        "WORKDAY_OAUTH_CLIENT_ID",
        "WORKDAY_ENTRA_APP_ID_URI",
    ]
    resolved = {}
    missing = []
    for key in required:
        v = lookup_env(env_map, key)
        if v:
            resolved[key] = v
        else:
            missing.append(key)

    if missing:
        print(
            f"ERROR: missing required Workday values from .env: {', '.join(missing)}\n"
            f"Accepted aliases per key are listed in SKILL.md Step 0.",
            file=sys.stderr,
        )
        sys.exit(2)

    values = {
        "token:ResourceUri": {"value": resolved["WORKDAY_ENTRA_APP_ID_URI"]},
        "token:WorkdayTokenUri": {"value": resolved["WORKDAY_OAUTH_TOKEN_URL"]},
        "token:WorkdayClientId": {"value": resolved["WORKDAY_OAUTH_CLIENT_ID"]},
        "baseUri": {"value": resolved["WORKDAY_BASE_URL"]},
        "tenantName": {"value": resolved["WORKDAY_TENANT"]},
    }

    rest_url = lookup_env(env_map, "WORKDAY_REST_URL")
    if rest_url:
        values["restBaseUri"] = {"value": rest_url}

    return values



def build_request_body(connector, auth_mode, display_name, env_id, values):
    """Construct the PUT request body for the Power Platform connections API."""
    body = {
        "properties": {
            "apiId": f"/providers/Microsoft.PowerApps/apis/{connector}",
            "displayName": display_name,
            "environment": {
                "id": f"/providers/Microsoft.PowerApps/environments/{env_id}",
                "name": env_id,
            },
        }
    }
    if values:
        body["properties"]["connectionParametersSet"] = {
            "name": auth_mode,
            "values": values,
        }
    return body


def main():
    parser = argparse.ArgumentParser(description="Create a Power Platform connection via the connectivity REST API")
    parser.add_argument("--env-id", required=True, help="Target environment GUID (for the per-env host)")
    parser.add_argument("--env-url", required=True, help="Dataverse env URL (used for tenant discovery)")
    parser.add_argument("--connector", required=True, help="Connector unique name, e.g. shared_workdaysoap")
    parser.add_argument("--ring", default="preprod", choices=list(SCOPES_BY_RING.keys()), help="Power Platform ring (preprod or prod). Drives scope and per-env host.")
    parser.add_argument("--auth-mode", default="oauth", help="Auth mode key (oauth | basic | oauth2generic | oauthapim). Default: oauth")
    parser.add_argument("--display-name", help="Connection display name. Default: derived from connector name.")
    parser.add_argument("--connection-id", help="Override the generated connection GUID")
    parser.add_argument("--params-file", help="JSON file with connectionParametersSet.values (overrides .env auto-resolution)")
    parser.add_argument("--env-file", default=".local/.env", help="Path to .env file (default: .local/.env)")
    parser.add_argument("--client-id", help="Custom Entra app client ID. If omitted, read from .env as ESS_DEVKIT_EMPHUB_CLIENT_ID.")
    parser.add_argument("--tenant", help="Entra tenant (GUID or domain). If omitted, discovered from --env-url.")
    parser.add_argument("--scope", help="OAuth scope. If omitted, derived from --ring.")
    args = parser.parse_args()

    # Load .env once for both connection params and client-id lookup.
    env_map = load_env_file(args.env_file)


    # Resolve client_id: --client-id > .env > error.
    client_id = args.client_id or lookup_env(env_map, "ESS_DEVKIT_EMPHUB_CLIENT_ID")
    if not client_id:
        print(
            "ERROR: no client ID for the ESS Dev Kit custom Entra app.\n"
            "Set ESS_DEVKIT_EMPHUB_CLIENT_ID in .local/.env, or pass --client-id.\n"
            "See README for app registration steps.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Resolve tenant: --tenant > discover from env_url.
    tenant = args.tenant or discover_tenant(args.env_url)
    if not tenant or tenant == "organizations":
        print(
            "ERROR: could not discover tenant from env URL. Pass --tenant explicitly.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Resolve scope: --scope > ring default.
    scope = args.scope or SCOPES_BY_RING[args.ring]

    # _warmup: cache the token and exit. Used by step1.md to front-load auth.
    if args.connector == "_warmup":
        token = acquire_browser_token(client_id, tenant, scope)
        print(json.dumps({"status": "ok", "scope": scope, "connector": "_warmup"}))
        sys.exit(0)

    # Resolve connection parameters.
    if args.params_file:
        with open(args.params_file, "r", encoding="utf-8") as f:
            values = json.load(f)
    elif args.connector == "shared_workdaysoap":
        values = build_workday_params(env_map)
    elif args.connector == "shared_commondataserviceforapps":
        # Dataverse: no parameters needed; auth is purely via the bearer flow.
        values = {}
    else:
        print(
            f"ERROR: no automatic param-resolution for connector '{args.connector}'.\n"
            f"Pass --params-file with a JSON document shaped like:\n"
            f"  {{\"paramName\": {{\"value\": \"...\"}}, ...}}",
            file=sys.stderr,
        )
        sys.exit(2)

    # Strip dashes for consistent URL path; uuid4().hex is already dash-free.
    if args.connection_id:
        connection_id = args.connection_id.replace("-", "").lower()
    else:
        connection_id = uuid.uuid4().hex

    # Timestamp in display name so re-runs are uniquely identifiable.
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    display_name = args.display_name or f"{short_connector_name(args.connector)}_{args.auth_mode}_{timestamp}"

    # Acquire token (browser-based interactive with caching).
    token = acquire_browser_token(client_id, tenant, scope)

    # Build URL + body.
    host = per_env_host(args.env_id, args.ring)
    url = (
        f"https://{host}/connectivity/connectors/{args.connector}"
        f"/connections/{connection_id}?api-version={API_VERSION}"
    )
    body = build_request_body(args.connector, args.auth_mode, display_name, args.env_id, values)

    print(f"PUT {url}", file=sys.stderr)

    try:
        resp = requests.put(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
            timeout=30,
        )
    except Exception as e:
        print(f"ERROR: request failed: {e}", file=sys.stderr)
        sys.exit(3)

    if resp.status_code in (200, 201):
        try:
            data = resp.json()
        except Exception:
            data = {}
        props = data.get("properties", {})
        statuses = props.get("statuses", [])

        # Prefer the token-target status (most informative for oauth connections).
        status_summary = "Unknown"
        target = None
        for s in statuses:
            if s.get("target") == "token":
                status_summary = s.get("status", "Unknown")
                target = "token"
                break
        else:
            if statuses:
                status_summary = statuses[0].get("status", "Unknown")
                target = statuses[0].get("target")

        out = {
            "connectionId": connection_id,
            "connectionUrl": url.split("?")[0],
            "connector": args.connector,
            "envId": args.env_id,
            "displayName": display_name,
            "status": status_summary,
            "statusTarget": target,
        }
        print(json.dumps(out, indent=2))
        sys.exit(0)
    elif resp.status_code == 401:
        print(f"ERROR: 401 auth rejected by API. Body: {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)
    elif 400 <= resp.status_code < 500:
        print(f"ERROR: PUT {resp.status_code}: {resp.text[:800]}", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"ERROR: PUT {resp.status_code}: {resp.text[:800]}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
