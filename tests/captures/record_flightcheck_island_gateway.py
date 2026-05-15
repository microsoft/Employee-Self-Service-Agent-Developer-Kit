#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the Power Virtual Agents / Copilot Studio
"Island Gateway" REST API.

Island Gateway is the backend the Copilot Studio web editor calls to
manage bot components — including knowledge sources, topics, and
their crawl/sync status. A future FlightCheck check (e.g. CONFIG-013
"knowledge sources are healthy") would hit this same endpoint to
validate that crawl status is OK across the customer's agent.

Endpoint discovered via browser network trace:
    POST https://powervamg.{region}.gateway.prod.island.powerapps.com
         /api/botmanagement/v1/environments/{env_id}
         /bots/{bot_id}/content/botcomponents

    Request:  {"componentDeltaToken": "<base64 token>" or empty}
    Response: {"changeToken": "...", "botComponents": [...]}

The endpoint is a delta-sync API: pass an empty/null token on first
call to receive the full set of components. Subsequent calls with the
returned changeToken receive only what changed since.

Auth: Microsoft Entra (Azure AD) bearer token with audience
`96ff4394-9197-43aa-b393-6a41652e21f8` (the well-known Power Virtual
Agents Service first-party app). This recorder uses MSAL device-code
flow so any signed-in user can authenticate without needing a
pre-registered service principal or client secret. The Azure CLI
public client (well-known multi-tenant app) is used to initiate
the device code request.

Identity headers (passed alongside Authorization):
    x-cci-cdsbotid:        Dataverse bot ID (same as ESS_BOT_ID)
    x-cci-tenantid:        Entra tenant GUID
    x-cci-applicationsource: "Web" (matches PVA portal)
    x-ms-environment-id:   Power Platform environment GUID
    x-ms-user-agent:       PVA-Portal/1.0.0 (Web; ReactNative: false)

Pre-reqs:
    pip install -e .[test]   # for vcrpy + msal (msal comes via auth.py deps)

    $env:ESS_ENVIRONMENT_ID  = "<power platform env GUID>"
    $env:ESS_BOT_ID          = "<dataverse bot/agent GUID>"
    $env:ESS_TENANT_ID       = "<entra tenant GUID>"   # for MSAL authority
    # Optional — defaults to us-il107 (the region we discovered in trace):
    # $env:ESS_ISLAND_REGION = "us-il107"

    python tests\\captures\\record_flightcheck_island_gateway.py

The first run pops the device-code prompt:
    "To sign in, use a web browser to open https://microsoft.com/devicelogin
     and enter the code XXXXXXXX to authenticate."

Subsequent runs reuse the cached token (~/.copilot/island-gateway-msal-cache.bin)
until expiry.

Output: tests/fixtures/cassettes/island_gateway_botcomponents.yaml

⚠️ POST-RECORD SCRUB — bot display names:
The global redactor scrubs GUIDs, emails, and many JSON keys but NOT
the JSON key `name`, because `name` is too common (used by Graph
directoryRoles, Power Platform env IDs, etc. for non-PII values). The
`/bots` list response uses `name` for the customer-chosen agent display
name. After recording, this script runs a post-process pass to
substitute the bot names you pass via env vars `ESS_BOT_NAME_HR` and
`ESS_BOT_NAME_IT` (or whatever appears in the `name` field of the
returned bots) with placeholders. If you have agents with names other
than these defaults, set the env vars below or hand-edit the cassette
before committing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit

# Well-known Microsoft public client IDs. Either is acceptable for
# device-code flow against PVA Service — they're both pre-authorized
# multi-tenant clients with admin consent for many MS resources.
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

# Resource (audience) for Island Gateway / Power Virtual Agents Service.
# Discovered by decoding the JWT from a browser network trace —
# `aud` claim of an authenticated PVA portal request.
PVA_SERVICE_AUDIENCE = "96ff4394-9197-43aa-b393-6a41652e21f8"
PVA_SERVICE_SCOPE = f"{PVA_SERVICE_AUDIENCE}/.default"

# Default region — overridable via ESS_ISLAND_REGION. Workday-style
# region suffix observed in the captured trace. Different tenants
# may be hosted on different regional gateways (us-il102, eu-il103,
# etc.); a customer can find theirs by inspecting any PVA portal
# network call.
DEFAULT_REGION = "us-il107"

REQUIRED_ENV = ("ESS_ENVIRONMENT_ID", "ESS_BOT_ID", "ESS_TENANT_ID")
OPTIONAL_ENV = ("ESS_ISLAND_REGION",)

# MSAL token cache lives in the user's session folder so iterative
# recording during dev doesn't re-prompt for device code every run.
CACHE_PATH = Path.home() / ".copilot" / "island-gateway-msal-cache.bin"


def _check_env() -> dict[str, str]:
    """Return env or print missing list and exit."""
    missing = [n for n in REQUIRED_ENV if not os.environ.get(n)]
    if missing:
        print("ERROR: missing required env vars:")
        for n in missing:
            print(f"  {n}")
        print()
        print("Set them in the current PowerShell session, e.g.:")
        for n in missing:
            print(f'  $env:{n} = "<value>"')
        print()
        print("See record_flightcheck_island_gateway.py docstring for details.")
        sys.exit(1)
    env = {n: os.environ[n] for n in REQUIRED_ENV}
    for n in OPTIONAL_ENV:
        if os.environ.get(n):
            env[n] = os.environ[n]
    return env


def _acquire_token(tenant_id: str) -> str | None:
    """
    Acquire a bearer token for the PVA Service audience via MSAL
    device-code flow. Caches the token to CACHE_PATH so subsequent
    runs (within token lifetime) skip the device prompt.
    """
    try:
        import msal
    except ImportError:
        print("ERROR: msal package is not installed.")
        print("Install it with:  pip install msal")
        return None

    # Load any cached account/token from disk.
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        try:
            cache.deserialize(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  WARN: token cache unreadable ({exc!s}); ignoring.")

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.PublicClientApplication(
        AZURE_CLI_CLIENT_ID,
        authority=authority,
        token_cache=cache,
    )

    accounts = app.get_accounts()
    result = None
    if accounts:
        # Try silent first — uses cached refresh token if still valid.
        print(f"  Using cached account: {accounts[0].get('username')}")
        result = app.acquire_token_silent([PVA_SERVICE_SCOPE], account=accounts[0])

    if not result:
        # No cached token — prompt for device code.
        print("  Initiating device-code sign-in...")
        flow = app.initiate_device_flow(scopes=[PVA_SERVICE_SCOPE])
        if "user_code" not in flow:
            print(f"  ERROR: failed to start device flow: {flow}")
            return None
        # The message includes the URL and code for the user to enter.
        print()
        print(f"  >>> {flow['message']}")
        print()
        result = app.acquire_token_by_device_flow(flow)

    # Persist the cache so the next run can use it without re-auth.
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if cache.has_state_changed:
            CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")
    except Exception as exc:
        print(f"  WARN: failed to persist token cache: {exc!s}")

    if "access_token" not in result:
        print(f"  ERROR: token acquisition failed: "
              f"{result.get('error')}: {result.get('error_description', '')[:300]}")
        return None

    return result["access_token"]


def main() -> None:
    announce("Island Gateway (Copilot Studio bot components)")

    env = _check_env()
    region = env.get("ESS_ISLAND_REGION", DEFAULT_REGION)
    bot_id = env["ESS_BOT_ID"]
    env_id = env["ESS_ENVIRONMENT_ID"]
    tenant_id = env["ESS_TENANT_ID"]

    base_url = f"https://powervamg.{region}.gateway.prod.island.powerapps.com"
    endpoint = (
        f"{base_url}/api/botmanagement/v1/environments/{env_id}"
        f"/bots/{bot_id}/content/botcomponents"
    )

    print(f"  Authority:    https://login.microsoftonline.com/{tenant_id}")
    print(f"  Audience:     {PVA_SERVICE_AUDIENCE}  (PVA Service)")
    print(f"  Endpoint:     POST {endpoint}")
    print(f"  Cache:        {CACHE_PATH}")
    print()

    confirm_or_exit()
    chdir_kit_root()

    import requests

    print("  Step 1: acquiring access token (MSAL device code or cache)...")
    with build_cassette("island_gateway_botcomponents"):
        token = _acquire_token(tenant_id)
        if not token:
            print("  ABORT: no access token; cannot make API call.")
            return
        print(f"  Step 1: OK (received {len(token)}-char access token)")
        print()

        # Identity headers observed in the browser trace. The PVA
        # gateway uses x-cci-* (CCI = Conversational Cloud Interface,
        # the Copilot Studio backend's name) and x-ms-* for routing
        # and audit context.
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-cci-applicationsource": "Web",
            "x-cci-cdsbotid": bot_id,
            "x-cci-tenantid": tenant_id,
            "x-ms-environment-id": env_id,
            "x-ms-user-agent": "PVA-Portal/1.0.0 (Web; ReactNative: false)",
            "Origin": "https://copilotstudio.microsoft.com",
            "Referer": "https://copilotstudio.microsoft.com/",
        }

        # Step 2: list all bots in the environment. This is a separate
        # snapshot endpoint (not delta-based) that returns provisioning
        # metadata for every agent in the env — name, region, language,
        # lastPublishedVersion, isManaged, provisioningStatus, etc.
        # Perfect for "is the ESS agent published correctly" checks.
        bots_url = f"{base_url}/api/botmanagement/v1/environments/{env_id}/bots"
        print(f"  Step 2: GET {bots_url}")
        try:
            r = requests.get(bots_url, headers=headers, timeout=60)
        except requests.RequestException as exc:
            print(f"    Request ERROR: {exc!s}")
            return
        print(f"    -> HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"    body[:300]: {r.text[:300]}")
            print("  ABORT: bot list call failed.")
            return
        try:
            bots_payload = r.json()
        except ValueError:
            print(f"    response not JSON: {r.text[:200]}")
            return
        if isinstance(bots_payload, list):
            print(f"    Bots in environment: {len(bots_payload)}")
            for b in bots_payload[:5]:
                if not isinstance(b, dict):
                    continue
                print(f"      - {b.get('name')!r:50}  region={b.get('region')}  "
                      f"managed={b.get('isManaged')}  status={b.get('provisioningStatus')}")
        else:
            print(f"    Unexpected shape: {type(bots_payload).__name__}")
        print()

        # Step 3: full bot-component sync. POST with empty deltaToken
        # returns ALL components wrapped in BotComponentInsert envelopes.
        # Each envelope's `component` field is the real component (topic,
        # knowledge source, etc.) with its own $kind discriminator.
        print(f"  Step 3: POST {endpoint}  (full bot-component sync)")
        body = {"componentDeltaToken": ""}
        try:
            r = requests.post(endpoint, json=body, headers=headers, timeout=60)
        except requests.RequestException as exc:
            print(f"    Request ERROR: {exc!s}")
            return
        print(f"    -> HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"    body[:500]: {r.text[:500]}")
            print("  ABORT: component sync failed.")
            return
        try:
            payload = r.json()
        except ValueError:
            print(f"    response not JSON: {r.text[:300]}")
            return

        keys = sorted(payload.keys())
        print(f"    Top-level response keys: {keys}")
        comp_changes = payload.get("botComponentChanges") or []
        env_var_changes = payload.get("environmentVariableChanges") or []
        bot_meta = payload.get("bot")
        print(f"    bot metadata: {'present' if bot_meta else 'absent'}")
        print(f"    botComponentChanges: {len(comp_changes)}")
        print(f"    environmentVariableChanges: {len(env_var_changes)}")

        # Tally components by their TRUE type — the inner component's
        # $kind, not the outer envelope. Each row in
        # botComponentChanges is shaped as:
        #   {"$kind": "BotComponentInsert", "component": {"$kind": "<TYPE>", ...}}
        # Common TYPEs: DialogComponent (topics), KnowledgeSourceComponent,
        # GenerativeActionsComponent, EnvironmentVariableComponent, etc.
        type_counts: dict[str, int] = {}
        envelope_counts: dict[str, int] = {}
        for ch in comp_changes:
            if not isinstance(ch, dict):
                continue
            envelope = ch.get("$kind") or "(unknown-envelope)"
            envelope_counts[envelope] = envelope_counts.get(envelope, 0) + 1
            inner = ch.get("component") or {}
            t = inner.get("$kind") if isinstance(inner, dict) else "(no-component)"
            type_counts[t or "(no-kind)"] = type_counts.get(t or "(no-kind)", 0) + 1
        if envelope_counts:
            print(f"    Components by envelope $kind:")
            for k, n in sorted(envelope_counts.items(), key=lambda kv: -kv[1]):
                print(f"      {n:>4}  {k}")
        if type_counts:
            print(f"    Components by inner $kind (the actual type):")
            for k, n in sorted(type_counts.items(), key=lambda kv: -kv[1]):
                print(f"      {n:>4}  {k}")

    print()
    print("Cassette written. Inspect tests/fixtures/cassettes/island_gateway_botcomponents.yaml")
    print("for any leftover identifying data before committing. The redactor")
    print("catches GUIDs, emails, and tokens; eyeball it for anything else (real")
    print("knowledge source URLs, real customer instance names, etc.).")

    # Post-record scrub: replace customer bot display names. The global
    # redactor doesn't touch the JSON key `name` (too common to scrub
    # safely across all cassettes). We do a per-recorder substitution
    # here based on the bot names we actually saw in step 2's response.
    cassette_path = Path("tests/fixtures/cassettes/island_gateway_botcomponents.yaml")
    if cassette_path.exists() and isinstance(bots_payload, list):
        import re as _re
        text = cassette_path.read_text(encoding="utf-8")
        scrubbed_count = 0
        for i, b in enumerate(bots_payload):
            if not isinstance(b, dict):
                continue
            real_name = b.get("name")
            if not real_name:
                continue
            placeholder = f"MockBot_{i+1:02d}"
            # YAML may line-wrap long strings; split on whitespace and
            # build a regex that tolerates whitespace where the original
            # had whitespace.
            parts = _re.escape(real_name).split(r"\ ")
            pattern = r"\s+".join(parts) if len(parts) > 1 else _re.escape(real_name)
            new_text, n = _re.subn(pattern, placeholder, text)
            if n > 0:
                print(f"  scrubbed bot name {real_name!r} -> {placeholder!r} ({n} occurrences)")
                text = new_text
                scrubbed_count += n
        if scrubbed_count > 0:
            cassette_path.write_text(text, encoding="utf-8")
            print(f"  Total scrubs: {scrubbed_count}. Cassette updated.")
        else:
            print(f"  No bot-name scrubs needed (or names not found in cassette text).")


if __name__ == "__main__":
    main()
