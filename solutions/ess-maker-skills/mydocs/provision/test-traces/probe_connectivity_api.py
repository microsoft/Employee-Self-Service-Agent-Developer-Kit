# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Preprod Connectivity API Probe

Tries the Power Platform Preprod connectivity API with several Microsoft
first-party client app IDs to identify which one(s) have the delegated
permissions needed to read/write connections in a Preprod environment.

Context: the /provision skill's step3-new.md needs to create connections
programmatically. The PAC CLI app ID (51f81489...) used elsewhere in the
kit returns 403 InsufficientDelegatedPermissions on the connectivity API.
Different Microsoft first-party app IDs have different baked-in delegated
permission sets, so swapping the client_id may unblock us without needing
a custom Entra app registration.

Usage:
    # Try the top candidate (PowerApps Studio):
    python scripts/probe_connectivity_api.py --env-id <preprod-env-guid>

    # Try a specific candidate:
    python scripts/probe_connectivity_api.py --env-id <id> --client-id <guid>

    # Try every known candidate sequentially:
    python scripts/probe_connectivity_api.py --env-id <id> --all

What it reports for each client_id:
    - MSAL token acquisition: ok / failed-and-why
    - GET connections call: HTTP status + first 300 chars of body
    - Verdict: works / 403-no-permission / 401-bad-audience / other

Exit code 0 if at least one client_id returned 200. Non-zero otherwise.

The script writes per-client token caches under .local/.probe_cache_{prefix}.bin
to avoid re-prompting on subsequent runs.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import msal
    import requests
except ImportError:
    print("ERROR: msal and requests required. Run: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(2)


# Candidate client IDs to try against the Preprod connectivity API.
# The first entry is the ESS Dev Kit's custom Entra app registration in the
# EmployeeHub tenant with Connectivity.Connections.Read+Write delegated
# permissions granted. The remaining entries are Microsoft first-party apps
# kept for reference; they were tested and either reject public-client flows
# or lack the connectivity permissions.
CANDIDATE_CLIENTS = [
    ("42222862-e2ae-4d1c-9be2-96dc1992f4da", "ESS Dev Kit (custom Entra app, EmployeeHub)"),
    ("60f38cf4-a0bf-4fdf-b0b5-14d3131bc031", "PowerApps Studio (closed: confidential client)"),
    ("a3475900-ccec-4a69-98f5-a65cd5dc5306", "Power Platform Admin Center"),
    ("9fdce4ac-de76-4790-a02a-2b3e1ab6c4d8", "Power Apps Maker Portal"),
    ("1fec8e78-bce4-4aaf-ab1b-5451cc387264", "Power Apps Mobile"),
    ("4ea34d20-c1f3-409e-9c3c-9e92c5e29862", "make.powerapps.com (older)"),
    ("47b4d97f-de43-4ace-878a-0f1f4f2c5c8c", "PP Admin (older)"),
    ("51f81489-12ee-4a9e-aaae-a2591f45987d", "PAC CLI (lacks Connectivity perms)"),
]

# Target audience for the connectivity API. Note: the Prod and Preprod
# Power Platform APIs are SEPARATE Entra resources with different App IDs.
# An app permission registered for one does not work for the other. Default
# here is Prod scope; pass --scope to override.
DEFAULT_SCOPE = "https://api.powerplatform.com/.default"
DEFAULT_TENANT = "EmployeeHub.onmicrosoft.com"
API_VERSION = "1"


def build_authority(tenant):
    """Build the MSAL authority URL from a tenant identifier.

    Accepts either a verified domain (e.g. EmployeeHub.onmicrosoft.com) or
    a tenant GUID. MSAL resolves either form to the underlying tenant.
    """
    return f"https://login.microsoftonline.com/{tenant}"


def per_env_host(env_id):
    """Build the per-environment API host for Preprod.

    The Microsoft Learn doc says the format is "{first 30}.{last 2}", but
    empirically for Preprod the working host uses "{first 31}.{last 1}".
    Confirmed by:
      - The user's network capture from the maker portal: 31+1
      - The connector metadata response's "host" field: 31+1
      - The "{first 30}.{last 2}" format returns DNS NameResolutionError

    The Microsoft doc example is for Prod and may not apply to Preprod
    routing, or the doc is simply outdated.
    """
    no_dashes = env_id.replace("-", "")
    return f"{no_dashes[:31]}.{no_dashes[31:]}.environment.api.preprod.powerplatform.com"


def probe_one(client_id, label, env_id, tenant, scope):
    """Try MSAL auth + connectivity API call for one client_id. Return result dict."""
    result = {
        "clientId": client_id,
        "label": label,
        "tokenAcquired": False,
        "tokenError": None,
        "httpStatus": None,
        "body": None,
        "verdict": None,
    }

    # Per-client token cache so we do not re-prompt across candidates.
    cache_dir = ".local"
    cache_path = os.path.join(cache_dir, f".probe_cache_{client_id[:8]}.bin")
    cache = msal.SerializableTokenCache()
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            cache.deserialize(f.read())

    authority = build_authority(tenant)
    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)

    # Try silent first (uses cached refresh token if present).
    accounts = app.get_accounts()
    token_result = None
    if accounts:
        token_result = app.acquire_token_silent([scope], account=accounts[0])

    if not token_result or "access_token" not in token_result:
        print(f"  Device-code sign-in required for {label}...", file=sys.stderr)
        try:
            flow = app.initiate_device_flow(scopes=[scope])
            if "user_code" not in flow:
                err = flow.get("error", "unknown")
                desc = flow.get("error_description", "")
                result["tokenError"] = f"device-flow init failed: {err}: {desc}"[:300]
                result["verdict"] = "auth-failed"
                return result
            # The "message" field already contains the URL + code in human-readable form.
            print(f"  >>> {flow['message']}", file=sys.stderr)
            token_result = app.acquire_token_by_device_flow(flow)
        except Exception as e:
            result["tokenError"] = f"device-flow exception: {e}"[:300]
            result["verdict"] = "auth-failed"
            return result

    if "access_token" not in token_result:
        err = token_result.get("error", "unknown")
        desc = token_result.get("error_description", "")
        result["tokenError"] = f"{err}: {desc}"[:300]
        result["verdict"] = "auth-failed"
        return result

    result["tokenAcquired"] = True
    token = token_result["access_token"]

    # Persist the cache.
    if cache.has_state_changed:
        os.makedirs(cache_dir, exist_ok=True)
        try:
            os.chmod(cache_dir, 0o700)
        except OSError:
            pass
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(cache_path, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cache.serialize())
        finally:
            try:
                os.chmod(cache_path, 0o600)
            except OSError:
                pass

    # Hit the per-env connectivity API. The maker portal's actual endpoint
    # pattern is: GET https://{envid-no-dashes}.e.environment.api.preprod
    # .powerplatform.com/connectivity/connectors/shared_workdaysoap?
    # $filter=environment eq '{envid-with-dashes}'&api-version=1
    #
    # We probe the same endpoint pattern. 200 here means our auth works
    # against this surface and we can build the POST /connections call next.
    host = per_env_host(env_id)
    filter_expr = f"environment eq '{env_id}'"
    url = (
        f"https://{host}/connectivity/connectors/shared_workdaysoap"
        f"?$filter={requests.utils.quote(filter_expr)}&api-version={API_VERSION}"
    )
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
    except Exception as e:
        result["body"] = f"request failed: {e}"
        result["verdict"] = "network-error"
        return result

    result["httpStatus"] = resp.status_code

    if resp.status_code == 200:
        try:
            data = resp.json()
            count = len(data.get("value", []))
            result["body"] = f"OK: {count} connections in env"
        except Exception:
            result["body"] = "OK but body not JSON"
        result["verdict"] = "works"
    elif resp.status_code == 401:
        result["body"] = resp.text[:300]
        result["verdict"] = "401-bad-audience"
    elif resp.status_code == 403:
        result["body"] = resp.text[:300]
        result["verdict"] = "403-no-permission"
    elif resp.status_code == 404:
        result["body"] = resp.text[:300]
        result["verdict"] = "404-not-found"
    else:
        result["body"] = resp.text[:300]
        result["verdict"] = f"http-{resp.status_code}"

    return result


def main():
    parser = argparse.ArgumentParser(description="Probe Preprod connectivity API with candidate client IDs")
    parser.add_argument("--env-id", required=True, help="Preprod env GUID (e.g. 87b98cf3-70b5-...)")
    parser.add_argument("--client-id", help="Override: try only this single client ID")
    parser.add_argument("--tenant", default=DEFAULT_TENANT, help=f"Entra tenant (domain or GUID). Default: {DEFAULT_TENANT}")
    parser.add_argument("--scope", default=DEFAULT_SCOPE, help=f"OAuth scope. Default: {DEFAULT_SCOPE}. For Preprod resource, use https://api.preprod.powerplatform.com/.default")
    parser.add_argument("--all", action="store_true", help="Try every candidate, do not stop on first success")
    args = parser.parse_args()

    if args.client_id:
        candidates = [(args.client_id, "user-specified")]
    elif args.all:
        candidates = CANDIDATE_CLIENTS
    else:
        # Default: try top candidate only (PowerApps Studio).
        candidates = CANDIDATE_CLIENTS[:1]

    host = per_env_host(args.env_id)
    print(f"\nProbing https://{host}/connectivity/connectors/shared_workdaysoap", file=sys.stderr)
    print(f"Tenant: {args.tenant}", file=sys.stderr)
    print(f"Scope: {args.scope}", file=sys.stderr)
    print(f"API version: {API_VERSION}\n", file=sys.stderr)

    results = []
    for client_id, label in candidates:
        print(f"=== {label} ({client_id}) ===", file=sys.stderr)
        result = probe_one(client_id, label, args.env_id, args.tenant, args.scope)
        results.append(result)

        # Print human summary to stderr.
        verdict = result["verdict"]
        http = result["httpStatus"]
        body = (result["body"] or "")[:300]
        print(f"  verdict: {verdict}", file=sys.stderr)
        if http is not None:
            print(f"  http: {http}", file=sys.stderr)
        if body:
            print(f"  body: {body}", file=sys.stderr)
        print("", file=sys.stderr)

        if verdict == "works" and not args.all:
            break

    # Machine-readable summary on stdout.
    print(json.dumps(results, indent=2))

    any_works = any(r["verdict"] == "works" for r in results)
    sys.exit(0 if any_works else 1)


if __name__ == "__main__":
    main()
