# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow flow invoker-connection binding (SN-FLOWCONN-001).

Verifies the state the Copilot Studio **Connections** experience shows as
"Connected" / "Not connected" for the agent's ServiceNow-backed flows. This is a
DISTINCT object from the Dataverse solution ``connectionreferences`` binding
checked by ``SN-CONN-001`` / ``DV-CONN-001``:

  * ``connectionreferences`` (Dataverse) — the solution's connection reference
    pointing at a connection id. The maker binds it in Copilot Studio;
    ``SN-DV-CONN-001`` verifies the Dataverse side. A reference can be fully bound +
    the connection Connected while the agent still cannot invoke the flow.
  * **flow invoker-connection binding** (this check) — a per-flow
    ``flowBindings[<flowId>].connectors[]`` record on the Power Platform
    environment API. When its ``connectionId`` is null / ``status`` is
    ``NotConnected`` the Copilot Studio UI shows the connection as not connected
    and the flow cannot run, *regardless of* the Dataverse reference state.

The gap: nothing in the base setup writes the flow invoker binding, so an
otherwise fully-bound ServiceNow reference can still surface as "Not connected".
The maker establishes it in Copilot Studio; this checkpoint verifies it.

Design invariants (per ``scripts/flightcheck/AGENTS.md``):
  * **Never raise** — the single emitter is wrapped so any failure degrades to a
    WARNING for this checkpoint instead of aborting the run.
  * **One CheckResult per checkpoint.**
  * **Reads documented fields only** (``flowBindings[].connectors[].connectionId``
    / ``.status`` from the user-connections GET) and degrades gracefully
    (SKIPPED) when the environment id, bot schema, or a Power Platform token is
    unavailable — it never triggers an interactive sign-in from within a check.
  * **Every** ``CheckResult`` declares ``roles=``.
"""

from __future__ import annotations

import os
import sys

from ..runner import CheckResult, Priority, Role, Status

# scripts/ is on sys.path when FlightCheck runs (cli.py inserts it); the shared
# Power Platform environment client (pp_env_client.py) lives there.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from pp_env_client import (  # noqa: E402
    PPEnvClient,
    connector_is_connected,
    find_connector_flows,
)

_CATEGORY = "ServiceNow Flow Binding"
_CHECKPOINT = "SN-FLOWCONN-001"
_DESCRIPTION = (
    "The agent's ServiceNow flow invoker-connection binding is Connected "
    "(Copilot Studio 'Connections' shows the ServiceNow connection as connected)."
)
_MAKER_ROLES = [Role.ESS_MAKER.value]
_CONNECTOR_NAME = "shared_service-now"
_REMEDIATION = (
    "Connect the ServiceNow flow invoker connection in "
    "Copilot Studio > your agent > Settings > Connections and connect the "
    "ServiceNow connection."
)


# ─────────────────────────────────────────────────────────────────────
# Pure helpers.
# ─────────────────────────────────────────────────────────────────────
def _bot_schema(config) -> str | None:
    """Resolve the active agent's Dataverse schema name from ``.local/config.json``.

    The bot schema keys the user-connections endpoint. The kit stores the
    active agent under ``agents[]`` (with ``activeAgent`` naming the slug); older
    shapes put it under a top-level ``schemaName`` or an ``agent`` object.
    """
    if not isinstance(config, dict):
        return None
    agents = config.get("agents") or []
    active = config.get("activeAgent")
    if active:
        for agent in agents:
            if agent.get("slug") == active and agent.get("schemaName"):
                return agent["schemaName"]
    if config.get("schemaName"):
        return config["schemaName"]
    agent = config.get("agent") or {}
    if agent.get("schemaName"):
        return agent["schemaName"]
    for agent in agents:
        if agent.get("schemaName"):
            return agent["schemaName"]
    return None


def _tenant_id(runner) -> str | None:
    tenant = getattr(runner, "tenant_id", None)
    if tenant:
        return tenant
    env_url = getattr(runner, "env_url", None)
    if not env_url:
        return None
    try:
        from auth import discover_tenant

        return discover_tenant(env_url)
    except Exception:  # noqa: BLE001 — tenant discovery is best-effort here
        return None


def _skip(result: str, remediation: str = "") -> list[CheckResult]:
    return [
        CheckResult(
            checkpoint_id=_CHECKPOINT,
            category=_CATEGORY,
            priority=Priority.HIGH.value,
            status=Status.SKIPPED.value,
            description=_DESCRIPTION,
            result=result,
            remediation=remediation,
            roles=_MAKER_ROLES,
        )
    ]


# ─────────────────────────────────────────────────────────────────────
# The checkpoint.
# ─────────────────────────────────────────────────────────────────────
def _check_flow_binding(runner) -> list[CheckResult]:
    config = getattr(runner, "config", None)
    schema = _bot_schema(config)
    if not schema:
        return _skip(
            "Could not resolve the agent's Dataverse schema name from "
            ".local/config.json, so the flow invoker binding could not be read."
        )

    env_id = getattr(runner, "env_id", None)
    if not env_id:
        return _skip(
            "The Power Platform environment id was not resolved, so the flow "
            "invoker binding could not be read.",
            remediation=(
                "Re-run with Power Platform admin sign-in, or pass "
                "--environment-id <guid>."
            ),
        )

    tenant_id = _tenant_id(runner)
    if not tenant_id:
        return _skip(
            "Could not resolve the tenant id, so the flow invoker binding "
            "could not be read."
        )

    client = PPEnvClient(tenant_id, env_id)
    token = client.authenticate(interactive=False)
    if not token:
        return _skip(
            "No cached Power Platform API token is available. This checkpoint "
            "does not open a browser from within a check.",
            remediation=(
                "This check needs a cached Power Platform API token. Sign in to "
                "the Power Platform (e.g. via the Azure CLI or Copilot Studio) so "
                "a token is available, then re-run FlightCheck. The connection can "
                "also be confirmed manually in Copilot Studio > Settings > "
                "Connections."
            ),
        )

    data = client.get_user_connections(schema)
    sn_flows = find_connector_flows(data, _CONNECTOR_NAME)

    if not sn_flows:
        return [
            CheckResult(
                checkpoint_id=_CHECKPOINT,
                category=_CATEGORY,
                priority=Priority.HIGH.value,
                status=Status.NOT_CONFIGURED.value,
                description=_DESCRIPTION,
                result=(
                    "No ServiceNow flow invoker connection was found for this "
                    "agent. The ServiceNow extension pack flows may not be "
                    "installed, or they reference a different connector."
                ),
                remediation=(
                    "Install the ServiceNow extension pack (S6.1), then connect "
                    "the ServiceNow connection in Copilot Studio > your agent > "
                    "Settings > Connections."
                ),
                roles=_MAKER_ROLES,
            )
        ]

    not_connected = [
        flow_id for flow_id, connector in sn_flows
        if not connector_is_connected(connector)
    ]

    if not not_connected:
        return [
            CheckResult(
                checkpoint_id=_CHECKPOINT,
                category=_CATEGORY,
                priority=Priority.HIGH.value,
                status=Status.PASSED.value,
                description=_DESCRIPTION,
                result=(
                    f"The ServiceNow flow invoker connection is Connected across "
                    f"all {len(sn_flows)} flow(s) that use it."
                ),
                roles=_MAKER_ROLES,
            )
        ]

    return [
        CheckResult(
            checkpoint_id=_CHECKPOINT,
            category=_CATEGORY,
            priority=Priority.HIGH.value,
            status=Status.FAILED.value,
            description=_DESCRIPTION,
            result=(
                f"The ServiceNow flow invoker connection is NOT connected for "
                f"{len(not_connected)} of {len(sn_flows)} flow(s) "
                f"(flow id(s): {', '.join(sorted(not_connected))}). Copilot "
                "Studio will show the ServiceNow connection as not connected and "
                "these flows cannot run."
            ),
            remediation=_REMEDIATION,
            roles=_MAKER_ROLES,
        )
    ]


def run_servicenow_flow_binding_checks(runner) -> list[CheckResult]:
    """Emit SN-FLOWCONN-001 behind a never-raise guard."""
    try:
        return _check_flow_binding(runner)
    except Exception as e:  # noqa: BLE001 — a check must never abort the run
        return [
            CheckResult(
                checkpoint_id=_CHECKPOINT,
                category=_CATEGORY,
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=_DESCRIPTION,
                result=f"Unable to run {_CHECKPOINT}: {type(e).__name__}: {e}",
                remediation=(
                    "Re-run FlightCheck; if this persists, report the checkpoint "
                    f"ID ({_CHECKPOINT}) and the error above."
                ),
                roles=_MAKER_ROLES,
            )
        ]
