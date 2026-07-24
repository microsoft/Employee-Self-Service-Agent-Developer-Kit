#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record the cassette that backs the INFRA-002 live network probe.

INFRA-002 answers "can Power Platform's OWN egress reach the HR system?"
(a firewall/allowlist question a local TCP probe can't answer) by temporarily
creating a Power Platform cloud flow that issues a HEAD request to the target
from Power Platform's service boundary, reading the reachability result, and
deleting the flow (net-zero). See:
  - solutions/ess-maker-skills/scripts/flightcheck/flow_probe.py
  - solutions/ess-maker-skills/scripts/flightcheck/checks/infrastructure.py
    (check_hr_system_reachability)

This recorder runs the PRODUCTION probe (flow_probe.run_live_probe) end-to-end
so the captured shapes are exactly what the check consumes. One run captures
the two `validated`-tier surfaces INFRA-002 depends on:

  Power Automate — trigger callback URL (host: api.flow.microsoft.com)
  - POST /providers/Microsoft.ProcessSimple/environments/{env}/flows/{flow}
         /triggers/manual/listCallbackUrl?api-version=2016-11-01
        => {"value": "<SAS-signed invoke URL>"} for the activated flow's
           `manual` trigger. Issued by PPAdminClient.list_callback_url.

  Logic Apps — trigger invoke (host: regional *.logic.azure.com gateway)
  - POST {callbackUrl}
        => the flow's own Response body (reachable / http_status /
           redirect_location / ...). Issued by flow_probe.trigger_and_read.
           A 302 login redirect counts as reachable; a redirect to a Workday
           /invalid-url page counts as reachable-but-invalid-instance.

The run also exercises the Dataverse `workflow` create / activate / delete
(documented tier) so the cassette contains the full lifecycle; the delete
keeps the environment net-zero.

Target URL resolution (first match wins):
  1. ESS_PROBE_TARGET_URL environment variable
  2. baseUrl / restBaseUrl / soapBaseUrl in .local/connect/workday/config.json

Pre-reqs:
    pip install -e .[test]
    # Dataverse env whose egress you want to test, e.g.:
    $env:ESS_DATAVERSE_URL = "https://orgXXXX.crm.dynamics.com"
    # Optional target override (else read from the Workday connect config):
    $env:ESS_PROBE_TARGET_URL = "https://impl.workday.com/<tenant>"

    python tests\\captures\\record_flightcheck_infra002.py

Output: tests/fixtures/cassettes/flightcheck_infra002.yaml

⚠️ POST-RECORD SCRUB — the trigger callback URL is a SAS-signed secret. The
shared `_common` redactor now scrubs the `sig=` SAS signature automatically
(REDACT_REGEX), but still eyeball the cassette to confirm the `sig=` value in
BOTH the `listCallbackUrl` response body and the invoke request URI reads
`sig=REDACTED_SAS_SIGNATURE`, and that no `Authorization` bearer headers
survive. (The flow is deleted at end-of-run, so the URL is inert either way.)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# scripts/ is on sys.path via the kit; add it for standalone execution.
_KIT_SCRIPTS = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
sys.path.insert(0, str(_KIT_SCRIPTS))

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit, get_dataverse_url


def _resolve_target_url() -> str | None:
    """Resolve the HR-system URL to probe (env override, then connect config)."""
    override = (os.environ.get("ESS_PROBE_TARGET_URL") or "").strip()
    if override:
        return override
    try:
        path = os.path.join(".local", "connect", "workday", "config.json")
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:  # noqa: BLE001 — missing/invalid config → no target
        return None
    if not isinstance(cfg, dict):
        return None
    for key in ("baseUrl", "restBaseUrl", "soapBaseUrl"):
        val = str(cfg.get(key) or "").strip()
        if val:
            return val
    return None


def main() -> None:
    announce("flightcheck_infra002 (INFRA-002 live network probe)")

    env_url = get_dataverse_url()
    if not env_url:
        print("ERROR: set ESS_DATAVERSE_URL to the target environment's Dataverse URL.")
        sys.exit(1)

    # auth.py / pp_admin_client.py use relative paths (.local token cache),
    # and _resolve_target_url reads the .local connect config — resolve the
    # target AFTER chdir so the relative path is correct.
    chdir_kit_root()

    target_url = _resolve_target_url()
    if not target_url:
        print(
            "ERROR: no target URL. Set ESS_PROBE_TARGET_URL, or baseUrl in "
            ".local/connect/workday/config.json (run /connect for Workday)."
        )
        sys.exit(1)

    print(f"  Dataverse URL: {env_url}")
    print(f"  Probe target : HEAD {target_url}")
    print("  Surfaces:      listCallbackUrl (POST) + trigger invoke (POST) + "
          "Dataverse workflow create/activate/delete")
    print()
    print("  NOTE: this creates and DELETES a temporary Power Platform flow "
          "(net-zero).")
    print()
    confirm_or_exit()

    import auth
    from flightcheck import flow_probe
    from flightcheck.pp_admin_client import PPAdminClient

    tenant_id = auth.discover_tenant(env_url)

    # Dataverse token (workflow create / activate / delete).
    dv_token = auth.authenticate(env_url)

    # BAP / PowerApps / Flow admin client (listCallbackUrl uses the Flow token).
    pp = PPAdminClient(tenant_id=tenant_id)
    pp.authenticate()

    with build_cassette("flightcheck_infra002"):
        env_id = pp.find_environment_id_by_dataverse_url(env_url)
        if not env_id:
            print("  ABORT: could not resolve BAP environment id for that Dataverse URL.")
            return
        print(f"  BAP env id: {env_id}")

        try:
            verdict = flow_probe.run_live_probe(
                env_url=env_url,
                dv_token=dv_token,
                pp_admin=pp,
                env_id=env_id,
                target_url=target_url,
            )
        except flow_probe.FlowProbeError as exc:
            print(f"  PROBE FAILED (still recorded up to the failure): {exc}")
            return

        print("  Verdict:")
        for key in ("reachable", "instance_valid", "access", "http_status",
                    "redirect_location", "deleted"):
            print(f"    {key:18}= {verdict.get(key)}")
        if not verdict.get("deleted"):
            print(f"    cleanup_note      = {verdict.get('cleanup_note')}")

    print()
    print("=" * 78)
    print("Cassette written: tests/fixtures/cassettes/flightcheck_infra002.yaml")
    print("=" * 78)
    print()
    print("NEXT STEPS — confirm these before committing:")
    print("  1. The cassette contains a POST .../triggers/manual/listCallbackUrl")
    print("     returning 200 with a `value` URL.")
    print("  2. It contains the subsequent POST to that callback URL (200 or 302).")
    print("  3. The `sig=` SAS signature is REDACTED in both the response body and")
    print("     the invoke request URI (see the POST-RECORD SCRUB warning above).")
    print("  4. `deleted` was True (the temporary flow was cleaned up net-zero).")
    print("  5. To also capture the BAD (invalid-instance) shape, re-run with")
    print("     ESS_PROBE_TARGET_URL set to a bogus instance path (e.g. append")
    print("     /this-instance-does-not-exist) into a SEPARATE cassette if the")
    print("     BAD-state test needs its own fixture.")


if __name__ == "__main__":
    main()
