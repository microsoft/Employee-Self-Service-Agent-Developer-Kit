# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Preview, activate, and verify the managed Workday runtime cloud flows."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Mapping

from auth import authenticate, query_all, update_record
from bind_workday_da_connections import (
    DATAVERSE_LOGICAL_NAME,
    WORKDAY_LOGICAL_NAME,
    query_runtime_references,
)
from workday_da_contract import load_definition


PLAN_MARKER = "WORKDAY_DA_FLOW_ACTIVATION_PLAN_JSON:"
APPLIED_MARKER = "WORKDAY_DA_FLOWS_ACTIVATED_JSON:"
FAILED_MARKER = "WORKDAY_DA_FLOW_ACTIVATION_FAILED_JSON:"
ACTIVE_STATE = 1
ACTIVE_STATUS = 2
CLOUD_FLOW_CATEGORY = 5


class WorkdayDAFlowActivationError(RuntimeError):
    """Raised when managed Workday flows cannot be activated safely."""


def _flow_names(
    package_flavor: str,
    *,
    definition: Mapping[str, Any],
) -> list[str]:
    try:
        package = definition["packages"][package_flavor]
    except KeyError as exc:
        raise WorkdayDAFlowActivationError(
            f"Unknown Workday package flavor: {package_flavor}."
        ) from exc
    names = package.get("flowNames")
    if not isinstance(names, list) or not names:
        raise WorkdayDAFlowActivationError(
            f"Package flavor {package_flavor} has no reviewed flow catalog; "
            "activate its flows manually."
        )
    return [str(name) for name in names]


def _query_target_flows(
    environment_url: str,
    token: str,
    flow_names: list[str],
    *,
    query: Callable[..., list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    filter_expr = " or ".join(
        f"name eq '{name.replace(chr(39), chr(39) * 2)}'"
        for name in flow_names
    )
    rows = query(
        environment_url,
        token,
        "workflows",
        "workflowid,name,statecode,statuscode,category",
        filter_expr,
    )
    grouped: dict[str, list[dict[str, Any]]] = {
        name: [] for name in flow_names
    }
    for row in rows:
        observed = str(row.get("name") or "").casefold()
        for expected in grouped:
            if observed == expected.casefold():
                grouped[expected].append(row)
    invalid = {
        name: len(matches)
        for name, matches in grouped.items()
        if len(matches) != 1
    }
    if invalid:
        raise WorkdayDAFlowActivationError(
            "Expected exactly one installed Workday flow for each reviewed "
            f"name; observed {json.dumps(invalid, sort_keys=True)}."
        )
    resolved = {name: matches[0] for name, matches in grouped.items()}
    non_cloud = [
        name
        for name, row in resolved.items()
        if row.get("category") != CLOUD_FLOW_CATEGORY
    ]
    if non_cloud:
        raise WorkdayDAFlowActivationError(
            "Refusing to activate non-cloud workflow records: "
            + ", ".join(sorted(non_cloud))
        )
    return resolved


def activate_workday_flows(
    environment_url: str,
    package_flavor: str,
    *,
    apply: bool,
    preferred_username: str | None = None,
    definition: Mapping[str, Any] | None = None,
    token_provider: Callable[..., str] = authenticate,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    updater: Callable[..., bool] = update_record,
) -> dict[str, Any]:
    """Preview or activate the reviewed flows for one Workday package."""
    environment_url = environment_url.rstrip("/")
    active_definition = definition or load_definition()
    flow_names = _flow_names(
        package_flavor,
        definition=active_definition,
    )
    token = token_provider(
        environment_url,
        preferred_username=preferred_username,
    )
    references = query_runtime_references(
        environment_url,
        token,
        query=query,
    )
    unbound = [
        logical_name
        for logical_name in (
            WORKDAY_LOGICAL_NAME,
            DATAVERSE_LOGICAL_NAME,
        )
        if not references[logical_name].get("connectionid")
    ]
    if unbound:
        raise WorkdayDAFlowActivationError(
            "Workday runtime connection references must be bound before flow "
            "activation: " + ", ".join(unbound)
        )

    flows = _query_target_flows(
        environment_url,
        token,
        flow_names,
        query=query,
    )
    changes = [
        {
            "name": name,
            "currentState": {
                "statecode": flows[name].get("statecode"),
                "statuscode": flows[name].get("statuscode"),
            },
            "action": (
                "unchanged"
                if flows[name].get("statecode") == ACTIVE_STATE
                and flows[name].get("statuscode") == ACTIVE_STATUS
                else "activate"
            ),
        }
        for name in flow_names
    ]
    result = {
        "environmentUrl": environment_url,
        "packageFlavor": package_flavor,
        "mode": "apply" if apply else "preview",
        "changes": changes,
    }
    if not apply:
        return result

    for change in changes:
        if change["action"] == "unchanged":
            continue
        workflow_id = flows[change["name"]].get("workflowid")
        if not workflow_id:
            raise WorkdayDAFlowActivationError(
                f"{change['name']} has no workflowid."
            )
        updater(
            environment_url,
            token,
            "workflows",
            workflow_id,
            {"statecode": ACTIVE_STATE, "statuscode": ACTIVE_STATUS},
        )

    verified = _query_target_flows(
        environment_url,
        token,
        flow_names,
        query=query,
    )
    not_active = [
        name
        for name, row in verified.items()
        if row.get("statecode") != ACTIVE_STATE
        or row.get("statuscode") != ACTIVE_STATUS
    ]
    if not_active:
        raise WorkdayDAFlowActivationError(
            "Post-write verification found Workday flows that are not active: "
            + ", ".join(sorted(not_active))
        )
    result["verified"] = True
    return result


def main() -> None:
    definition = load_definition()
    parser = argparse.ArgumentParser(
        description=(
            "Preview, activate, and verify the managed Workday runtime flows."
        )
    )
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--package-flavor",
        choices=sorted(definition["packages"]),
        required=True,
    )
    parser.add_argument("--preferred-username")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    marker = APPLIED_MARKER if args.apply else PLAN_MARKER
    try:
        result = activate_workday_flows(
            args.url,
            args.package_flavor,
            apply=args.apply,
            preferred_username=args.preferred_username,
            definition=definition,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"{FAILED_MARKER}{json.dumps({'error': str(error)})}")
        sys.exit(1)
    print(f"{marker}{json.dumps(result, sort_keys=True)}")


if __name__ == "__main__":
    main()
