# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from connect_lifecycle import LifecycleDecisionError, decide_next_step, main


_SOLUTION = (
    Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"
)


def _write_contract_fixture(
    root: Path,
    *,
    provider: str = "servicenow-da-itsm",
    resume_action: bool = True,
    preflight_every_invocation: bool = False,
    initialization_command: str | None = None,
) -> None:
    contract_dir = root / "src" / "skills" / "connect" / provider
    contract_dir.mkdir(parents=True)
    (contract_dir / "contract.json").write_text(
        json.dumps(
            {
                "contractRevision": 1,
                "provider": provider,
                **(
                    {"stateInitializationCommand": initialization_command}
                    if initialization_command is not None
                    else {}
                ),
                "phases": [
                    {
                        "id": "preflight",
                        "checkpoints": ["PRE-001"],
                        **(
                            {
                                "actionDoc": "actions/preflight.md",
                                "actionExecution": "every-invocation",
                            }
                            if preflight_every_invocation
                            else {}
                        ),
                    },
                    {
                        "id": "topics",
                        "mode": "current",
                        "checkpoints": ["TOPICS-001"],
                        "actionDoc": "actions/prepare-topics.md",
                        "actionExecution": "once",
                        **(
                            {"resumeActionWhenIncomplete": True}
                            if resume_action
                            else {}
                        ),
                    },
                    {
                        "id": "publish",
                        "checkpoints": ["PUB-001"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_fixture(
    root: Path,
    *,
    provider: str = "servicenow-da-itsm",
    resume_action: bool = True,
    action_applied: bool = True,
    phase_status: str = "in-progress",
    preflight_every_invocation: bool = False,
) -> None:
    _write_contract_fixture(
        root,
        provider=provider,
        resume_action=resume_action,
        preflight_every_invocation=preflight_every_invocation,
    )
    state_path = (
        root
        / ".local"
        / "connect"
        / provider
        / "agents"
        / "employee-self-service-it"
        / "lifecycle.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "provider": provider,
                "agentSlug": "employee-self-service-it",
                "attested": True,
                "acceptedContractRevision": 1,
                "phases": {
                    "preflight": {
                        "status": "done",
                        "checkpointResults": {"PRE-001": "Passed"},
                    },
                    "topics": {
                        "status": phase_status,
                        "actionApplied": action_applied,
                        "lastActionAt": "2026-10-08T01:20:00Z",
                        "checkpointResults": {
                            "TOPICS-001": "NotConfigured"
                        },
                    },
                    "publish": {
                        "status": "pending",
                        "checkpointResults": {},
                    },
                },
                "transactions": {
                    "topics": {
                        "operation-1": {
                            "status": "committed",
                            "before": {"total": 13},
                            "after": {"total": 13, "active": 13},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("provider", ["servicenow-da-itsm", "workday"])
def test_missing_state_requires_plan_without_creating_connect_state(
    tmp_path: Path,
    provider: str,
) -> None:
    _write_contract_fixture(tmp_path, provider=provider)
    connect_root = tmp_path / ".local" / "connect"

    result = decide_next_step(
        tmp_path,
        provider=provider,
        agent_slug="employee-self-service-it",
    )

    assert result == {
        "schemaVersion": "connect.lifecycle-next.v1",
        "decision": "plan-required",
        "provider": provider,
        "agentSlug": "employee-self-service-it",
        "contractRevision": 1,
        "stateExists": False,
        "planReason": "first-run",
        "stateInitializationRequired": True,
        "stateInitializationCommand": None,
    }
    assert not connect_root.exists()


def test_missing_state_cli_emits_plan_required_without_writes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_contract_fixture(tmp_path)
    connect_root = tmp_path / ".local" / "connect"

    assert main(
        [
            "next-step",
            "--provider",
            "servicenow-da-itsm",
            "--agent-slug",
            "employee-self-service-it",
            "--root",
            str(tmp_path),
        ]
    ) == 0

    output = capsys.readouterr().out.strip()
    payload = json.loads(output.split(":", 1)[1])
    assert payload["decision"] == "plan-required"
    assert payload["contractRevision"] == 1
    assert payload["stateExists"] is False
    assert payload["planReason"] == "first-run"
    assert payload["stateInitializationRequired"] is True
    assert not connect_root.exists()


def test_missing_state_renders_exact_initialization_command(
    tmp_path: Path,
) -> None:
    _write_contract_fixture(
        tmp_path,
        initialization_command=(
            "python init.py --agent {agentSlug} "
            "--revision {contractRevision}"
        ),
    )

    result = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
    )

    assert result["stateInitializationCommand"] == (
        "python init.py --agent employee-self-service-it --revision 1"
    )


@pytest.mark.parametrize(
    ("provider", "agent_slug", "message"),
    [
        ("../servicenow-da-itsm", "employee-self-service-it", "Provider key"),
        ("servicenow-da-itsm", "../employee-self-service-it", "Agent slug"),
    ],
)
def test_missing_state_rejects_unsafe_identity_before_path_resolution(
    tmp_path: Path,
    provider: str,
    agent_slug: str,
    message: str,
) -> None:
    with pytest.raises(LifecycleDecisionError, match=message):
        decide_next_step(
            tmp_path,
            provider=provider,
            agent_slug=agent_slug,
        )
    assert not (tmp_path / ".local" / "connect").exists()


@pytest.mark.parametrize(
    ("contract_update", "message"),
    [
        ({"provider": "workday"}, "provider identity"),
        ({"contractRevision": 0}, "positive integer"),
        ({"contractRevision": True}, "positive integer"),
    ],
)
def test_missing_state_requires_valid_contract(
    tmp_path: Path,
    contract_update: dict[str, object],
    message: str,
) -> None:
    _write_contract_fixture(tmp_path)
    contract_path = (
        tmp_path
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da-itsm"
        / "contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.update(contract_update)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(LifecycleDecisionError, match=message):
        decide_next_step(
            tmp_path,
            provider="servicenow-da-itsm",
            agent_slug="employee-self-service-it",
        )
    assert not (tmp_path / ".local" / "connect").exists()


def test_malformed_existing_state_fails_closed_without_replacement(
    tmp_path: Path,
) -> None:
    _write_contract_fixture(tmp_path)
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / "servicenow-da-itsm"
        / "agents"
        / "employee-self-service-it"
        / "lifecycle.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{not-json", encoding="utf-8")
    before = state_path.read_bytes()

    with pytest.raises(LifecycleDecisionError, match="invalid JSON"):
        decide_next_step(
            tmp_path,
            provider="servicenow-da-itsm",
            agent_slug="employee-self-service-it",
        )

    assert state_path.read_bytes() == before


def test_incomplete_once_phase_requires_provider_action(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    result = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
        verified_phases=frozenset({"preflight"}),
    )

    assert result["decision"] == "run-action"
    assert result["phase"] == {
        "id": "topics",
        "mode": "current",
        "status": "in-progress",
        "checkpoints": ["TOPICS-001"],
        "actionExecution": "once",
        "actionApplied": True,
        "resumeActionWhenIncomplete": True,
        "actionDoc": "actions/prepare-topics.md",
        "preserveHistoricalActionEvidence": True,
    }


@pytest.mark.parametrize(
    ("provider", "agent_slug"),
    (
        ("servicenow-da-hrsd", "employee-self-service-hr"),
        ("servicenow-da-itsm", "employee-self-service-it"),
    ),
)
def test_real_credential_contract_reruns_action_after_reverify_drift(
    tmp_path: Path,
    provider: str,
    agent_slug: str,
) -> None:
    contract = json.loads(
        (
            _SOLUTION
            / "src"
            / "skills"
            / "connect"
            / provider
            / "contract.json"
        ).read_text(encoding="utf-8")
    )
    contract_path = (
        tmp_path
        / "src"
        / "skills"
        / "connect"
        / provider
        / "contract.json"
    )
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    phases = {}
    verified_phases = set()
    credential_seen = False
    for phase in contract["phases"]:
        phase_id = phase["id"]
        if phase_id == "credential":
            credential_seen = True
            phases[phase_id] = {
                "status": "in-progress",
                "actionApplied": True,
                "lastActionAt": "2026-10-28T00:00:00Z",
                "checkpointResults": {
                    phase["checkpoints"][0]: "NotConfigured"
                },
            }
        elif credential_seen:
            phases[phase_id] = {
                "status": "pending",
                "checkpointResults": {},
            }
        else:
            verified_phases.add(phase_id)
            phases[phase_id] = {
                "status": "done",
                "actionApplied": True,
                "checkpointResults": {
                    checkpoint: "Passed"
                    for checkpoint in phase["checkpoints"]
                },
            }

    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / provider
        / "agents"
        / agent_slug
        / "lifecycle.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "provider": provider,
                "agentSlug": agent_slug,
                "attested": True,
                "acceptedContractRevision": contract["contractRevision"],
                "phases": phases,
            }
        ),
        encoding="utf-8",
    )

    result = decide_next_step(
        tmp_path,
        provider=provider,
        agent_slug=agent_slug,
        verified_phases=frozenset(verified_phases),
    )

    assert result["decision"] == "run-action"
    assert result["phase"]["id"] == "credential"
    assert result["phase"]["actionApplied"] is True
    assert result["phase"]["resumeActionWhenIncomplete"] is True
    assert result["phase"]["actionDoc"].endswith("prepare-credential.md")
    assert result["phase"]["preserveHistoricalActionEvidence"] is True


@pytest.mark.parametrize(
    ("provider", "agent_slug", "completed_before", "expected_phase"),
    (
        (
            "servicenow-da-hrsd",
            "employee-self-service-hr",
            {"preflight"},
            "plugin-prerequisites",
        ),
        (
            "servicenow-da-hrsd",
            "employee-self-service-hr",
            {"preflight", "plugin-prerequisites"},
            "entra-registration",
        ),
        (
            "servicenow-da-itsm",
            "employee-self-service-it",
            {"preflight"},
            "entra-registration",
        ),
    ),
)
def test_real_contract_orders_shared_identity_inside_entra_action(
    tmp_path: Path,
    provider: str,
    agent_slug: str,
    completed_before: set[str],
    expected_phase: str,
) -> None:
    contract = json.loads(
        (
            _SOLUTION
            / "src"
            / "skills"
            / "connect"
            / provider
            / "contract.json"
        ).read_text(encoding="utf-8")
    )
    contract_path = (
        tmp_path
        / "src"
        / "skills"
        / "connect"
        / provider
        / "contract.json"
    )
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    phases = {}
    for phase in contract["phases"]:
        phase_id = phase["id"]
        phases[phase_id] = {
            "status": "done" if phase_id in completed_before else "pending",
            "checkpointResults": {},
        }
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / provider
        / "agents"
        / agent_slug
        / "lifecycle.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "provider": provider,
                "agentSlug": agent_slug,
                "attested": True,
                "acceptedContractRevision": contract["contractRevision"],
                "phases": phases,
            }
        ),
        encoding="utf-8",
    )

    result = decide_next_step(
        tmp_path,
        provider=provider,
        agent_slug=agent_slug,
        verified_phases=frozenset(completed_before),
    )

    assert result["decision"] == "run-action"
    assert result["phase"]["id"] == expected_phase
    if expected_phase == "entra-registration":
        assert result["phase"]["actionDoc"].endswith(
            "guide-entra-registration.md"
        )
    else:
        assert result["phase"]["actionDoc"].endswith(
            "verify-plugin-prerequisites.md"
        )


def test_action_runs_at_most_once_per_invocation(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    result = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
        executed_actions=frozenset({"topics"}),
        verified_phases=frozenset({"preflight"}),
    )

    assert result["decision"] == "run-checkpoints"
    assert result["phase"]["id"] == "topics"


def test_provider_without_resume_flag_keeps_once_semantics(
    tmp_path: Path,
) -> None:
    _write_fixture(
        tmp_path,
        provider="workday",
        resume_action=False,
    )

    result = decide_next_step(
        tmp_path,
        provider="workday",
        agent_slug="employee-self-service-it",
        verified_phases=frozenset({"preflight"}),
    )

    assert result["decision"] == "run-checkpoints"


def test_plan_revision_mismatch_returns_plan_required(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    state_path = (
        tmp_path
        / ".local/connect/servicenow-da-itsm/agents/"
        "employee-self-service-it/lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["acceptedContractRevision"] = 0
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
    )

    assert result["decision"] == "plan-required"
    assert result["stateExists"] is True
    assert result["planReason"] == "revision-reapproval"
    assert result["stateInitializationRequired"] is False
    assert result["stateInitializationCommand"] is None
    assert result["acceptedContractRevision"] == 0


def test_done_prefix_must_be_live_verified_before_current_phase(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path)

    result = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
    )

    assert result["decision"] == "run-checkpoints"
    assert result["phase"]["id"] == "preflight"
    assert result["phase"]["mode"] == "reverify-done"


def test_done_prefix_every_invocation_action_runs_before_checkpoint(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path, preflight_every_invocation=True)

    action = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
    )
    checkpoint = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
        executed_actions=frozenset({"preflight"}),
    )

    assert action["decision"] == "run-action"
    assert action["phase"]["id"] == "preflight"
    assert action["phase"]["mode"] == "reverify-done"
    assert checkpoint["decision"] == "run-checkpoints"
    assert checkpoint["phase"]["id"] == "preflight"


def test_complete_when_every_phase_done(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    state_path = (
        tmp_path
        / ".local/connect/servicenow-da-itsm/agents/"
        "employee-self-service-it/lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for phase in state["phases"].values():
        phase["status"] = "done"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    not_verified = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
    )
    result = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
        verified_phases=frozenset({"preflight", "topics", "publish"}),
    )

    assert not_verified["decision"] == "run-checkpoints"
    assert result["decision"] == "complete"


def test_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    state_path = (
        tmp_path
        / ".local/connect/servicenow-da-itsm/agents/"
        "employee-self-service-it/lifecycle.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["agentSlug"] = "other-agent"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(LifecycleDecisionError, match="agent identity"):
        decide_next_step(
            tmp_path,
            provider="servicenow-da-itsm",
            agent_slug="employee-self-service-it",
        )


def test_cli_emits_structured_next_action(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_fixture(tmp_path)

    assert main(
        [
            "next-step",
            "--provider",
            "servicenow-da-itsm",
            "--agent-slug",
            "employee-self-service-it",
            "--root",
            str(tmp_path),
            "--verified-phase",
            "preflight",
        ]
    ) == 0

    output = capsys.readouterr().out.strip()
    assert output.startswith("DA_LIFECYCLE_NEXT_JSON:")
    payload = json.loads(output.split(":", 1)[1])
    assert payload["decision"] == "run-action"
    assert payload["phase"]["actionDoc"] == "actions/prepare-topics.md"


def test_documented_verified_phase_sequence_advances_without_loop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_fixture(tmp_path)

    assert main(
        [
            "next-step",
            "--provider",
            "servicenow-da-itsm",
            "--agent-slug",
            "employee-self-service-it",
            "--root",
            str(tmp_path),
        ]
    ) == 0
    preflight = json.loads(
        capsys.readouterr().out.strip().split(":", 1)[1]
    )
    assert preflight["decision"] == "run-checkpoints"
    assert preflight["phase"]["id"] == "preflight"
    assert preflight["phase"]["mode"] == "reverify-done"

    assert main(
        [
            "next-step",
            "--provider",
            "servicenow-da-itsm",
            "--agent-slug",
            "employee-self-service-it",
            "--root",
            str(tmp_path),
            "--verified-phase",
            "preflight",
        ]
    ) == 0
    topics_action = json.loads(
        capsys.readouterr().out.strip().split(":", 1)[1]
    )
    assert topics_action["decision"] == "run-action"
    assert topics_action["phase"]["id"] == "topics"

    assert main(
        [
            "next-step",
            "--provider",
            "servicenow-da-itsm",
            "--agent-slug",
            "employee-self-service-it",
            "--root",
            str(tmp_path),
            "--verified-phase",
            "preflight",
            "--executed-action",
            "topics",
        ]
    ) == 0
    topics_checkpoint = json.loads(
        capsys.readouterr().out.strip().split(":", 1)[1]
    )
    assert topics_checkpoint["decision"] == "run-checkpoints"
    assert topics_checkpoint["phase"]["id"] == "topics"


def test_failed_reverification_does_not_mark_phase_verified(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path)

    first = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
    )
    repeated = decide_next_step(
        tmp_path,
        provider="servicenow-da-itsm",
        agent_slug="employee-self-service-it",
    )

    assert first["phase"]["id"] == "preflight"
    assert repeated["phase"]["id"] == "preflight"
    assert repeated["phase"]["mode"] == "reverify-done"


def test_actual_it_done_prefix_requires_all_verified_markers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = "servicenow-da-itsm"
    slug = "employee-self-service-it"
    phase_ids = (
        "preflight",
        "entra-registration",
        "servicenow-oidc",
        "credential",
        "topics",
        "portal-url",
        "agent-connection",
        "test",
        "publish",
    )
    contract_path = (
        tmp_path / "src/skills/connect" / provider / "contract.json"
    )
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(
        json.dumps(
            {
                "contractRevision": 1,
                "provider": provider,
                "phases": [
                    {
                        "id": phase_id,
                        "checkpoints": [f"CHECK-{phase_id}"],
                        **(
                            {
                                "actionDoc": "actions/admin-preflight.md",
                                "actionExecution": "every-invocation",
                            }
                            if phase_id == "preflight"
                            else {
                                "actionDoc": "actions/prepare-topics.md",
                                "actionExecution": "once",
                                "resumeActionWhenIncomplete": True,
                            }
                            if phase_id == "topics"
                            else {}
                        ),
                    }
                    for phase_id in phase_ids
                ],
            }
        ),
        encoding="utf-8",
    )
    state_path = (
        tmp_path
        / ".local/connect"
        / provider
        / "agents"
        / slug
        / "lifecycle.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "provider": provider,
                "agentSlug": slug,
                "attested": True,
                "acceptedContractRevision": 1,
                "phases": {
                    phase_id: {
                        "status": (
                            "done"
                            if phase_id
                            in {
                                "preflight",
                                "entra-registration",
                                "servicenow-oidc",
                                "credential",
                            }
                            else "in-progress"
                            if phase_id == "topics"
                            else "pending"
                        ),
                        "actionApplied": phase_id == "topics",
                        "checkpointResults": {},
                    }
                    for phase_id in phase_ids
                },
            }
        ),
        encoding="utf-8",
    )

    assert main(
        [
            "next-step",
            "--provider",
            provider,
            "--agent-slug",
            slug,
            "--root",
            str(tmp_path),
            "--executed-action",
            "preflight",
        ]
    ) == 0
    missing_markers = json.loads(
        capsys.readouterr().out.strip().split(":", 1)[1]
    )
    assert missing_markers["decision"] == "run-checkpoints"
    assert missing_markers["phase"]["id"] == "preflight"
    assert missing_markers["phase"]["mode"] == "reverify-done"

    args = [
        "next-step",
        "--provider",
        provider,
        "--agent-slug",
        slug,
        "--root",
        str(tmp_path),
        "--executed-action",
        "preflight",
    ]
    for phase_id in (
        "preflight",
        "entra-registration",
        "servicenow-oidc",
        "credential",
    ):
        args.extend(["--verified-phase", phase_id])
    assert main(args) == 0
    complete_prefix = json.loads(
        capsys.readouterr().out.strip().split(":", 1)[1]
    )
    assert complete_prefix["decision"] == "run-action"
    assert complete_prefix["phase"]["id"] == "topics"
    assert complete_prefix["phase"]["preserveHistoricalActionEvidence"] is True
