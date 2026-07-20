# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Flow Registration Validation

Post-push readiness check: verifies that each agent flow in the active agent's
component map is fully registered and agent-invocable, mirroring the manual
5-step check. For every flow it confirms:

  1. Activated           (statecode=1, statuscode=2)
  2. Modern flow         (modernflowtype=1 / CopilotStudioFlow)
  3. Response=Skills      (all Response actions are kind:Skills)
  4. Flow-scoped connref  (at least one, bound to a connection)
  5. Topic link           (botcomponent_workflow link to a system topic)

This is a standalone, read-only capability — not run automatically by push. A
maker (or the agent, on their behalf) invokes it to confirm a deployment is
runtime-ready.

Usage:
    python scripts/validate.py
"""

import os
import sys

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8" \
            and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 — console reconfig is best-effort
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import authenticate, load_config, query_all, dataverse_get  # noqa: E402
from push import (  # noqa: E402
    load_component_map,
    _flow_response_kinds,
    _evaluate_flow_registration,
    _flow_connref_delete_filter,
)

_CHECK_LABELS = {
    "activated": "Activated (statecode=1/statuscode=2)",
    "modern_flow": "Modern flow (modernflowtype=1)",
    "response_skills": "Response actions are kind:Skills",
    "flow_scoped_connref": "Flow-scoped connection reference bound",
    "botcomponent_workflow_link": "Linked to a system topic",
}


def _gather_flow_facts(env_url, token, schema_name, workflowid):
    """Query Dataverse for one flow's registration facts."""
    wf = dataverse_get(
        env_url, token,
        f"workflows({workflowid})",
        {"$select": "statecode,statuscode,modernflowtype,clientdata,name"},
    )
    connrefs = query_all(
        env_url, token, "connectionreferences",
        "connectionreferenceid,connectionid",
        filter_expr=_flow_connref_delete_filter(schema_name, workflowid),
    )
    bound = sum(1 for c in connrefs if c.get("connectionid"))
    link = dataverse_get(
        env_url, token,
        f"workflows({workflowid})/botcomponent_workflow",
        {"$select": "botcomponentid,schemaname"},
    )
    linked = link.get("value", [])
    return {
        "name": wf.get("name"),
        "facts": dict(
            statecode=wf.get("statecode"),
            statuscode=wf.get("statuscode"),
            modernflowtype=wf.get("modernflowtype"),
            response_kinds=_flow_response_kinds(wf.get("clientdata") or ""),
            connref_bound_count=bound,
            link_count=len(linked),
        ),
        "linked_topics": [t.get("schemaname") for t in linked],
    }


def main():
    name_filter = sys.argv[1].lower() if len(sys.argv) > 1 else None

    config = load_config()
    env_url = config["dataverseEndpoint"]
    agent_dir = config["agent"]["folder"]
    schema_name = config["agent"]["schemaName"]

    component_map = load_component_map(agent_dir)
    flows = [
        (path, entry["workflowid"], entry.get("name", path))
        for path, entry in component_map.items()
        if entry.get("workflowid")
    ]
    if name_filter:
        flows = [
            f for f in flows
            if name_filter in f[2].lower() or name_filter in f[1].lower()
        ]
    if not flows:
        print("No matching flows found in the component map.")
        return

    print(f"Validating {len(flows)} flow(s) in {config['agent']['name']}...")
    print(
        "Note: these checks reflect ADK push-style registration. Flows "
        "installed via a solution / extension pack (e.g. the shared "
        "orchestrators) register their connection differently and may show "
        "NOT READY here without being broken. This check is for flows you "
        "authored and pushed.\n"
    )
    print("Authenticating to Dataverse...")
    token = authenticate(env_url)
    print("Authenticated.\n")

    all_ready = True
    for path, workflowid, _name in flows:
        try:
            gathered = _gather_flow_facts(
                env_url, token, schema_name, workflowid)
        except Exception as e:  # noqa: BLE001 — report + continue
            print(f"  ✗ {path}: could not read flow {workflowid}: {e}\n")
            all_ready = False
            continue

        report = _evaluate_flow_registration(**gathered["facts"])
        status = "READY" if report["ready"] else "NOT READY"
        mark = "✅" if report["ready"] else "❌"
        print(f"{mark} {gathered['name'] or path} [{status}]")
        for key, ok in report["checks"].items():
            print(f"     {'✓' if ok else '✗'} {_CHECK_LABELS[key]}")
        if gathered["linked_topics"]:
            print(f"     ↳ linked topic(s): "
                  f"{', '.join(gathered['linked_topics'])}")
        print("")
        all_ready = all_ready and report["ready"]

    if not all_ready:
        print("Some flows are not fully registered. If you authored + pushed "
              "the flow, run `python push.py --repair` (optionally pass a flow "
              "name) once the connector is reachable to complete registration.")
        sys.exit(1)
    print("All matching flows are registered and agent-invocable.")


if __name__ == "__main__":
    main()
