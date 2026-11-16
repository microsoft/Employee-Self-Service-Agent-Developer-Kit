# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only flow registration diagnostics."""

import json


def _flow_connref_delete_filter(agent_schema, workflowid):
    """OData ``$filter`` selecting a flow's flow-scoped connection references.

    Select references named ``{agent_schema}.{workflowid}.{connector}``.
    This function constructs a read filter and performs no deletion.
    """
    prefix = f"{agent_schema}.{workflowid}.".replace("'", "''")
    return f"startswith(connectionreferencelogicalname,'{prefix}')"



def _flow_response_kinds(clientdata):
    """List the ``kind`` of every Response action in a flow's clientdata.

    Used by the readiness report. Returns ``[]`` on invalid JSON.
    """
    try:
        data = json.loads(clientdata)
    except (ValueError, TypeError):
        return []
    kinds = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "Response":
                kinds.append(node.get("kind"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return kinds



def _evaluate_flow_registration(*, statecode, statuscode, modernflowtype,
                                response_kinds, connref_bound_count,
                                link_count):
    """Compose the agent-invocability checks for a created flow.

    Returns ``{"ready": bool, "checks": {name: bool}}``. Mirrors the manual
    5-step registration check: the flow must be Activated, a modern
    (CopilotStudio) flow, have all Response actions as kind:Skills, have at
    least one bound flow-scoped connection reference, and be linked to a system
    topic via botcomponent_workflow.
    """
    checks = {
        "activated": statecode == 1 and statuscode == 2,
        "modern_flow": modernflowtype == 1,
        "response_skills": (
            len(response_kinds) > 0
            and all(k == "Skills" for k in response_kinds)
        ),
        "flow_scoped_connref": connref_bound_count > 0,
        "botcomponent_workflow_link": link_count > 0,
    }
    return {"ready": all(checks.values()), "checks": checks}
