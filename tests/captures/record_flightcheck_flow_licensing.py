#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record the cassette that backs the traditional-flow licensing pre-flight
(LIC-FLOW-001). One run captures every API surface the flow-classification
and connector-tier logic needs, against a real tenant, under VCR.py.

Why each call is here
---------------------
LIC-FLOW-001 has to answer two questions for the agent under check:

  1. Which Power Platform flows does the agent reference, and is each one
     a native Copilot Studio *agent flow* (runs under the agent identity,
     no end-user license) or a *traditional* Power Automate cloud flow
     (triggers per-user Power Automate / Power Apps licensing)?
  2. For each traditional flow, what connector tier do its connection
     references bind to? Premium / custom / on-prem-gateway connectors
     additionally require a Power Apps Premium (or standalone Power
     Automate Premium) SKU on every invoking user.

No single endpoint answers both. This recorder captures the set that,
together, lets the check classify deterministically:

  Power Automate Admin API (host: api.flow.microsoft.com)
  - GET /providers/Microsoft.ProcessSimple/scopes/admin/environments/{env}/v2/flows
        => the flow inventory (re-capture: the committed
           flightcheck_pp_admin.yaml still has the OLD api.powerapps.com
           host returning 404; production code now targets
           api.flow.microsoft.com — see pp_admin_client.FLOW_BASE).
  - GET /providers/Microsoft.ProcessSimple/scopes/admin/environments/{env}/flows/{id}
        => per-flow detail. The LIST response is a summary; the DETAIL
           response carries properties.connectionReferences (connector
           apiId per ref) and properties.definition (trigger kind),
           which is what distinguishes an agent flow from a cloud flow
           and what resolves each ref to a connector.

  PowerApps Admin API — NOT captured
  - The admin /apis connector catalog returns an empty list under admin
    scope. The connector tier ("Standard" / "Premium") and the
    custom-connector flag LIC-FLOW-001 needs are carried INLINE on each
    flow detail at
    properties.connectionReferences.<ref>.apiDefinition.properties.{tier,
    isCustomApi}, so no separate connector call is made.

  Dataverse record sharing (host: {env_url}) — LIC-FLOW-002 principals
  - GET /RetrieveSharedPrincipalsAndAccess(Target=@t)?@t={"@odata.id":"bots(<botId>)"}
        => the supported, resolved list of security principals (users /
           teams) the Copilot Studio agent is SHARED with, plus each
           one's access mask. Copilot Studio "Share" writes to the
           Dataverse `bot` record's sharing — so this documented
           function is exactly what the sharing pane reads. Backs
           LIC-FLOW-002's principal enumeration without any internal /
           unstable Copilot Studio API.
        See https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/retrievesharedprincipalsandaccess

  LIC-FLOW-002 resolves each principal to an Entra user via documented /
  validatable APIs that need no cassette: Dataverse systemusers / teams /
  teammemberships (documented) and Graph /users/{id}/licenseDetails +
  /groups/{id}/transitiveMembers (validatable via CSDL).

Output
------
tests/fixtures/cassettes/flightcheck_flow_licensing.yaml

Operator workflow
-----------------
1. Authenticate against your test tenant once (run flightcheck/cli.py
   interactively, or any recorder, to populate .local/.token_cache.bin).
   Use a tenant whose ESS agent references at least one traditional
   Power Automate cloud flow AND, ideally, one native agent flow, so the
   classification ground truth covers both branches.
2. $env:ESS_DATAVERSE_URL = "https://<your-tenant>.crm.dynamics.com"
3. python tests/captures/record_flightcheck_flow_licensing.py
4. Read the on-screen summary. Confirm:
   - the flow LIST returned 200 with >=1 flow,
   - at least one flow DETAIL shows properties.connectionReferences,
   - the connector catalog shows a `tier` field per connector,
   - the workflows table shows a `category` value per row, and tell me
     which category/clientdata value corresponds to an agent flow vs a
     traditional cloud flow (eyeball one of each you know),
   - msdyn_aipluginaction rows show a field that references a workflow id,
   - RetrieveSharedPrincipalsAndAccess returned a PrincipalAccesses list
     for an agent you have shared with at least one user/team.
5. Eyeball the cassette body for tenant-specific text the redactor
   missed (flow display names can carry customer/system names; the
   sharing response carries real principal GUIDs — confirm they're
   redacted/acceptable for a test tenant).
6. Commit tests/fixtures/cassettes/flightcheck_flow_licensing.yaml and
   tell me the shape confirmations from step 4 — I'll write the
   checks + mock + INDEX rows against the captured shapes.

This recorder is READ-ONLY (GET/list only) and never mutates tenant state.
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse

from _common import (
    announce,
    build_cassette,
    chdir_kit_root,
    confirm_or_exit,
    get_dataverse_url,
)

# Cap per-flow DETAIL captures so a tenant with hundreds of flows doesn't
# produce a multi-MB cassette. The first few flows are enough to pin the
# detail shape (connectionReferences + definition); the check itself will
# fetch detail per referenced flow at runtime, but for SHAPE validation a
# handful is plenty.
MAX_FLOW_DETAILS = 5


def _bot_ids_from_config(auth_mod) -> list[str]:
    """Return the configured agent bot IDs from .local/config.json.

    Supports both the multi-agent shape (``agents: [{botId}]``) and the
    older single-agent shape (``agent: {botId}``). Returns [] if config
    can't be loaded or carries no botId — the recorder just skips the
    sharing captures in that case.
    """
    try:
        cfg = auth_mod.load_config()
    except SystemExit:
        return []
    ids: list[str] = []
    for agent in cfg.get("agents", []) or []:
        bid = agent.get("botId")
        if bid:
            ids.append(bid)
    single = (cfg.get("agent") or {}).get("botId")
    if single and single not in ids:
        ids.append(single)
    return ids





def main() -> None:
    announce("flightcheck_flow_licensing")

    env_url = get_dataverse_url()
    confirm_or_exit()

    # auth.py / pp_admin_client.py use relative paths (.local token cache).
    chdir_kit_root()

    import auth
    from flightcheck.pp_admin_client import PPAdminClient

    tenant_id = auth.discover_tenant(env_url)

    # Dataverse token (workflows + msdyn_aiplugin* tables).
    dv_token = auth.authenticate(env_url)

    # BAP/PowerApps/Flow admin client (flows + connectors).
    pp = PPAdminClient(tenant_id=tenant_id)
    pp.authenticate()

    with build_cassette("flightcheck_flow_licensing"):
        # Resolve env_id by matching the Dataverse host against the BAP
        # environment list (derive_environment_id has a known bug — see
        # record_flightcheck_pp_admin.py).
        envs = pp.get_environments()
        target_host = (urlparse(env_url).hostname or "").lower()
        env_id = None
        for e in envs:
            instance_url = (
                e.get("properties", {})
                .get("linkedEnvironmentMetadata", {})
                .get("instanceUrl", "")
            )
            host = (urlparse(instance_url).hostname or "").lower()
            if host == target_host:
                env_id = e.get("name")
                break
        if not env_id:
            print(f"ERROR: no BAP environment matched Dataverse host {target_host!r}.")
            sys.exit(1)
        print("  Resolved env_id by instanceUrl match")

        def _try(label, fn):
            try:
                result = fn()
                count = len(result) if isinstance(result, (list, dict)) else "?"
                print(f"  {label}: {count}")
                return result
            except Exception as exc:
                print(f"  {label}: SKIPPED — {type(exc).__name__}: {exc!s}")
                return None

        # ---- Power Automate flow inventory (correct host) ----
        flows = _try("/v2/flows (list)", lambda: pp.get_flows(env_id))

        # ---- Per-flow detail (connectionReferences + definition) ----
        flow_ids: list[str] = []
        if isinstance(flows, list):
            for f in flows:
                fid = f.get("name") or f.get("id", "").rsplit("/", 1)[-1]
                if fid:
                    flow_ids.append(fid)
        for i, fid in enumerate(flow_ids[:MAX_FLOW_DETAILS]):
            _try(f"/flows/{{id}} detail [{i + 1}]", lambda fid=fid: pp.get_flow(env_id, fid))
        if len(flow_ids) > MAX_FLOW_DETAILS:
            print(
                f"  (capped flow-detail captures at {MAX_FLOW_DETAILS} of "
                f"{len(flow_ids)} flows)"
            )

        # ---- Connector catalog: NOT captured ----
        # The admin /apis endpoint returns an empty catalog under admin
        # scope; the connector tier (Premium/Standard) + custom-connector
        # signal LIC-FLOW-001 needs is carried INLINE on each flow detail's
        # connectionReferences.<ref>.apiDefinition.properties.{tier,isCustomApi},
        # so no separate connector call is needed.

        # ---- Dataverse record sharing (LIC-FLOW-002 principal source) ----
        bot_ids = _bot_ids_from_config(auth)
        if not bot_ids:
            print(
                "  sharing: SKIPPED — no botId in .local/config.json "
                "(run /setup, or capture LIC-FLOW-001 surfaces only)"
            )
        for i, bot_id in enumerate(bot_ids):
            _try(
                f"RetrieveSharedPrincipalsAndAccess(bot)[{i + 1}]",
                lambda bot_id=bot_id: auth.retrieve_shared_principals_and_access(
                    env_url, dv_token, bot_id
                ),
            )

    print()
    print("=" * 78)
    print("Cassette written: tests/fixtures/cassettes/flightcheck_flow_licensing.yaml")
    print("=" * 78)
    print()
    print("NEXT STEPS — confirm these shapes and report back:")
    print("  1. /v2/flows returned 200 with >=1 flow.")
    print("  2. >=1 flow detail shows properties.connectionReferences.")
    print("  3. /apis connectors show a `tier` field (Standard/Premium).")
    print("  4. /workflows rows show `category` (and tell me which")
    print("     category/clientdata = agent flow vs traditional cloud flow),")
    print("     and msdyn_aipluginactions rows show a workflow-id reference.")
    print("  5. RetrieveSharedPrincipalsAndAccess returned PrincipalAccesses")
    print("     for a shared agent (the LIC-FLOW-002 principal source).")
    print()
    print("Then eyeball the cassette for un-redacted tenant text and commit it.")


if __name__ == "__main__":
    main()
