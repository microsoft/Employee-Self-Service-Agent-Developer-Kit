# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"
_CONNECT = _SOLUTION / "src" / "skills" / "connect"


def test_workday_contract_uses_generic_lifecycle() -> None:
    contract = json.loads(
        (_CONNECT / "workday" / "contract.json").read_text(encoding="utf-8")
    )

    assert contract["provider"] == "workday"
    assert [phase["id"] for phase in contract["phases"]] == [
        "discovery",
        "agent-wiring",
        "validation",
    ]
    wiring = contract["phases"][1]
    assert wiring["mutates"] is True
    assert wiring["requiredRole"] == "Environment Maker"
    assert wiring["rollbackPushGlob"] == "topics/user-context-setup.mcs.yml"
    assert "attestedRoleScope" not in contract

    entry = (_CONNECT / "workday" / "SKILL.md").read_text(encoding="utf-8")
    assert "connect/shared/lifecycle-runner.md" in entry
    assert "connect/workday/contract.json" in entry


def test_lifecycle_runner_requires_reverification_and_rollback() -> None:
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )

    assert "Live re-verification on resume" in runner
    assert "permission-gate.md" in runner
    assert "--revert-reason" in runner
    assert "rollbackPushGlob" in runner
    assert 'ACTION_RESULT = "applied"' not in runner
    assert '**`"applied"`**' in runner
    assert '**`"recorded"`**' in runner
    assert '**`"cancelled"`**' in runner
    assert 'actionExecution: "every-invocation"' in runner
    assert "Non-mutating actions do not run a role" in runner
    assert "contiguous prefix" in runner
    assert "clear `actionApplied`/`lastActionAt`" in runner
    assert "fresh gate and fresh rollback" in runner
    assert "must never be reused after drift" in runner
    assert "attestedRoleScope: \"lifecycle\"" in runner
    assert "roleAttestations.{requiredRole}" in runner
    assert "Accepting the plan does not claim a\nrole" in runner
    assert "Never reuse `roleAttestations` for this mode" in runner
    assert "different provider or agent slug" in runner
    assert "missing `roleAttestations` object" in runner
    assert "Do not infer an attestation from `attested`" in runner
    assert "actual current status values" in runner
    assert "provider plan passed" not in runner


def test_servicenow_hrsd_contract_uses_generic_lifecycle() -> None:
    contract = json.loads(
        (_CONNECT / "servicenow-da-hrsd" / "contract.json").read_text(
            encoding="utf-8"
        )
    )

    assert contract["provider"] == "servicenow-da-hrsd"
    assert contract["attestedRoleScope"] == "lifecycle"
    assert [phase["id"] for phase in contract["phases"]] == [
        "topics",
        "credential",
        "agent-connection",
        "parameter-sharing",
        "publish",
        "test",
    ]
    assert contract["phases"][2]["actionExecution"] == "every-invocation"
    assert contract["phases"][3]["actionExecution"] == "every-invocation"
    assert contract["phases"][5]["actionExecution"] == "every-invocation"
    assert contract["phases"][5]["mutates"] is False
    assert contract["phases"][5]["completionStatuses"] == ["Manual"]

    workday = json.loads(
        (_CONNECT / "workday" / "contract.json").read_text(encoding="utf-8")
    )
    assert all("actionExecution" not in phase for phase in workday["phases"])
    assert "attestedRoleScope" not in workday


def test_hrsd_lifecycle_reuses_one_attested_role_per_agent() -> None:
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )
    contract = json.loads(
        (_CONNECT / "servicenow-da-hrsd" / "contract.json").read_text(
            encoding="utf-8"
        )
    )

    mutating = [phase for phase in contract["phases"] if phase["mutates"]]
    assert {phase["gateMode"] for phase in mutating} == {"attested"}
    assert {phase["requiredRole"] for phase in mutating} == {
        "ESS Maker / Agent Developer"
    }
    assert runner.count("roleAttestations.{requiredRole}") >= 2
    assert "without asking again" in runner
    assert '`provider` exactly equals `PROVIDER`' in runner
    assert '`agentSlug` exactly equals `AGENT_SLUG`' in runner

    schema = (_CONNECT / "shared" / "lifecycle-contract-schema.md").read_text(
        encoding="utf-8"
    )
    assert "first mutating phase" in schema
    assert "Later mutating phases" in schema
    assert "later resumes" in schema
    assert "Explicit lifecycle reset/reinitialization" in schema
    assert "`gateMode: \"programmatic\"` always executes its role query" in schema


def test_cea_workday_routing_is_package_gated() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")

    assert "--checkpoint WD-PKG-001" in route
    assert "Passed` + simplified-install result" in route
    assert "Passed` + full / legacy result" in route
    assert "Never start a lifecycle from an\n  inconclusive package check" in route
    assert "connect/workday/SKILL.md" in route
    assert "Shared provider setup state is not agent connection state" in route


def test_workday_wiring_uses_installed_identity_and_explicit_result() -> None:
    action = (
        _CONNECT / "workday" / "actions" / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")

    assert ".local/agents/{AGENT_SLUG}/topics/" in action
    assert "workspace/agents/{AGENT_SLUG}/topics/" in action
    assert 'ACTION_RESULT = "cancelled"' in action
    assert 'ACTION_RESULT = "applied"' in action


def test_declarative_agents_do_not_enter_cea_lifecycle() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")

    assert "releaseLine: \"da\"" in route
    assert "gptagent_copilotforemployeeselfservicehr" in route
    assert "gptagent_copilotforemployeeselfserviceit" in route
    assert "WD-DA-PKG-001" in route
    assert "Do not create CEA Workday lifecycle state" in route
    assert "setup/workday-da/SKILL.md" in route
