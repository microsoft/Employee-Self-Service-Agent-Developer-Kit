# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Connect-owned policy for accepting Workday DA readiness results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


PHASE_ORDER = (
    "preflight",
    "entra",
    "workday-admin",
    "connections",
    "runtime",
    "employee-validation",
)


@dataclass(frozen=True)
class CheckpointPolicy:
    phase_id: str
    manual_evidence: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProfilePolicy:
    phase_id: str
    checkpoints: tuple[str, ...]
    families: Mapping[str, int]
    clients: tuple[str, ...]


CHECKPOINT_POLICIES: dict[str, CheckpointPolicy] = {
    "ENV-001": CheckpointPolicy("preflight"),
    "ENV-002": CheckpointPolicy("preflight"),
    "ENV-009": CheckpointPolicy("runtime"),
    "ENV-CAPACITY-001": CheckpointPolicy("preflight"),
    "DA-AGENT-001": CheckpointPolicy("preflight"),
    "DA-CONTENT-001": CheckpointPolicy("preflight"),
    "WD-DA-PKG-001": CheckpointPolicy("connections"),
    "WD-DA-FLOW-001": CheckpointPolicy("runtime"),
    "WD-ENTRA-SCOPE-001": CheckpointPolicy("entra"),
    "WD-ENTRA-CONSENT-001": CheckpointPolicy("entra"),
    "WD-ASSIGN-001": CheckpointPolicy("entra"),
    "WD-ENTRA-NAMEID-001": CheckpointPolicy("entra"),
    "WD-ENTRA-SIGNOPT-001": CheckpointPolicy(
        "entra",
        (("entra", "administrator-configuration-verified"),),
    ),
    "WD-CONN-010": CheckpointPolicy(
        "entra",
        (
            ("entra", "administrator-configuration-verified"),
            ("workday-admin", "administrator-response-validated"),
        ),
    ),
    "WD-CONN-102": CheckpointPolicy("entra"),
    "WD-API-CLIENT-001": CheckpointPolicy(
        "workday-admin",
        (("workday-admin", "administrator-response-validated"),),
    ),
    "WD-TENANT-001": CheckpointPolicy(
        "workday-admin",
        (("workday-admin", "administrator-response-validated"),),
    ),
    "WD-SEC-003": CheckpointPolicy(
        "workday-admin",
        (("workday-admin", "administrator-response-validated"),),
    ),
    "WD-NET-001": CheckpointPolicy(
        "workday-admin",
        (("workday-admin", "administrator-response-validated"),),
    ),
    "WD-CONN-AUTH-001": CheckpointPolicy(
        "connections",
        (("connections", "physical-connections-verified"),),
    ),
    "DV-CONN-001": CheckpointPolicy("runtime"),
    "DA-CONN": CheckpointPolicy("runtime"),
    "WD-CONN-012": CheckpointPolicy("runtime"),
    "WD-CONN-013": CheckpointPolicy("runtime"),
    "WD-DA-AUTH-001": CheckpointPolicy("runtime"),
    "WD-REST-001": CheckpointPolicy("runtime"),
    "WD-REST-002": CheckpointPolicy("runtime"),
    "WD-DA-TOPIC-001": CheckpointPolicy("runtime"),
    "WD-DA-WIRING-001": CheckpointPolicy("runtime"),
    "WD-DA-ATTACH-001": CheckpointPolicy(
        "runtime",
        (("runtime", "flow-attachment-confirmed"),),
    ),
    "WD-DA-RUN-001": CheckpointPolicy("employee-validation"),
}


PROFILE_POLICIES: dict[str, ProfilePolicy] = {
    "workday-da:setup-readiness": ProfilePolicy(
        phase_id="preflight",
        checkpoints=(
            "DA-AGENT-001",
            "DA-CONTENT-001",
        ),
        families={},
        clients=("agentbuilder",),
    ),
    "workday-da:external-prerequisites": ProfilePolicy(
        phase_id="workday-admin",
        checkpoints=(
            # Privileged Entra checks remain in the independent registry until
            # role-aware execution can invoke them with the correct account.
            "WD-ENTRA-SIGNOPT-001",
            "WD-API-CLIENT-001",
            "WD-TENANT-001",
            "WD-NET-001",
        ),
        families={},
        clients=(),
    ),
    "workday-da:package-ready": ProfilePolicy(
        phase_id="connections",
        checkpoints=("WD-DA-PKG-001",),
        families={},
        clients=("dataverse",),
    ),
    "workday-da:dataverse-ready": ProfilePolicy(
        phase_id="runtime",
        checkpoints=(
            "WD-DA-PKG-001",
            "WD-DA-FLOW-001",
            "DV-CONN-001",
        ),
        families={},
        clients=("dataverse",),
    ),
    "workday-da:post-connection": ProfilePolicy(
        phase_id="runtime",
        checkpoints=(
            "WD-DA-PKG-001",
            "WD-DA-FLOW-001",
            "WD-CONN-012",
            "WD-DA-AUTH-001",
            "DV-CONN-001",
            "WD-REST-001",
        ),
        families={},
        clients=("dataverse",),
    ),
    "workday-da:post-agent-wiring": ProfilePolicy(
        phase_id="runtime",
        checkpoints=(
            "WD-DA-TOPIC-001",
            "WD-DA-WIRING-001",
            "WD-DA-ATTACH-001",
            "WD-REST-002",
        ),
        families={},
        clients=("agentbuilder",),
    ),
    "workday-da:post-runtime": ProfilePolicy(
        phase_id="employee-validation",
        checkpoints=("WD-DA-FLOW-001", "WD-DA-RUN-001"),
        families={},
        clients=("dataverse", "pp_admin"),
    ),
    "workday-da:final": ProfilePolicy(
        phase_id="employee-validation",
        checkpoints=(
            "DA-AGENT-001",
            "DA-CONTENT-001",
            "WD-DA-PKG-001",
            "WD-DA-FLOW-001",
            "WD-ENTRA-SIGNOPT-001",
            "WD-API-CLIENT-001",
            "WD-TENANT-001",
            "WD-CONN-012",
            "WD-DA-AUTH-001",
            "DV-CONN-001",
            "WD-REST-001",
            "WD-REST-002",
            "WD-NET-001",
            "WD-DA-TOPIC-001",
            "WD-DA-WIRING-001",
            "WD-DA-ATTACH-001",
            "WD-DA-RUN-001",
        ),
        families={},
        clients=("agentbuilder", "dataverse", "pp_admin"),
    ),
}


PHASE_REQUIRED_PROFILES: dict[str, tuple[str, ...]] = {
    phase_id: tuple(
        profile_name
        for profile_name, policy in PROFILE_POLICIES.items()
        if policy.phase_id == phase_id
    )
    for phase_id in PHASE_ORDER
}

CHECKPOINT_PHASES = {
    checkpoint_id: policy.phase_id
    for checkpoint_id, policy in CHECKPOINT_POLICIES.items()
}

MANUAL_EVIDENCE = {
    checkpoint_id: policy.manual_evidence
    for checkpoint_id, policy in CHECKPOINT_POLICIES.items()
    if policy.manual_evidence
}


def checkpoint_phase(checkpoint_id: str, fallback: str) -> str:
    if checkpoint_id.startswith("DA-CONN-"):
        return "runtime"
    policy = CHECKPOINT_POLICIES.get(checkpoint_id)
    return policy.phase_id if policy is not None else fallback


def manual_evidence_for(
    checkpoint_id: str,
) -> tuple[tuple[str, str], ...]:
    policy = CHECKPOINT_POLICIES.get(checkpoint_id)
    return policy.manual_evidence if policy is not None else ()
