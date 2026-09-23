from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from essmig.discovery import CaComponent
from essmig.reference import BaselineComponent, ReferenceSet

HR_PREFIX = "msdyn_copilotforemployeeselfservicehr"
DA_PREFIX = "gptagent_copilotforemployeeselfservicehr"

REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "reference"

requires_reference = pytest.mark.skipif(
    not (REFERENCE_ROOT / "hr" / "agent.yml").is_file(),
    reason="reference data not vendored; run `ess-ca-to-da vendor --ess-root <ESSVivaCopilot>`",
)


def ca_component(
    suffix: str,
    data: str,
    *,
    component_type: int = 9,
    name: str = "",
    solutions: tuple[str, ...] = ("msdyn_CopilotForEmployeeSelfServiceHR", "Active"),
    statecode: Any = 0,
) -> CaComponent:
    return CaComponent(
        component_id=f"{abs(hash(suffix)):032x}"[:32],
        schemaname=f"{HR_PREFIX}.{suffix}",
        name=name or suffix,
        component_type=component_type,
        data=data,
        statecode=statecode,
        layers=[{"msdyn_solutionname": solution} for solution in solutions],
    )


def layer(solution: str, **attributes: Any) -> dict[str, Any]:
    """A synthetic ``msdyn_componentlayers`` row with its attributes JSON-wrapped."""
    payload = [{"Key": key, "Value": value} for key, value in attributes.items()]
    return {
        "msdyn_solutionname": solution,
        "msdyn_componentjson": json.dumps({"Attributes": payload}),
    }


def reference_set(
    components: list[dict[str, Any]],
    baseline: dict[str, str] | None = None,
    *,
    overlays: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> ReferenceSet:
    return ReferenceSet(
        vertical="hr",
        agent={
            "kind": "BotDefinition",
            "entity": {"schemaName": DA_PREFIX},
            "components": components,
        },
        config=config or {"formatVersion": "1.0", "realm": "dev", "values": {}},
        package={"packageType": "templated", "publisher": "microsoftfirstparty"},
        overlays=overlays,
        baseline={
            suffix: BaselineComponent(
                suffix=suffix,
                schemaname=f"{HR_PREFIX}.{suffix}",
                component_type=9,
                solution="msdyn_CopilotForEmployeeSelfServiceHR",
                data=data,
            )
            for suffix, data in (baseline or {}).items()
        },
        provenance={},
    )


def dialog_component(suffix: str, dialog: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "kind": "DialogComponent",
        "managedProperties": {"isManaged": True, "isCustomizable": True},
        "state": "Active",
        "status": "Active",
        "schemaName": f"{DA_PREFIX}.{suffix}",
        "displayName": suffix,
        "dialog": dialog,
        **extra,
    }
