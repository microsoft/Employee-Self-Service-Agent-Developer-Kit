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
    assert wiring["rollbackPushGlobFromAction"] is True
    assert "rollbackPushGlob" not in wiring
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
    assert (
        "clear\n   `actionApplied`/`lastActionAt`/`rollbackPushGlob`"
        in runner
    )
    assert "fresh gate\n   and fresh rollback checkpoint" in runner
    assert "must never be reused after drift" in runner
    assert "`actionApplied`/`lastActionAt`/`rollbackPushGlob`" in runner
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
    assert ".local/connect/workday-da/config.json" in route
    assert "`scope.agent.slug` and `scope.agent.botId` exactly" in route


def test_workday_wiring_uses_installed_identity_and_explicit_result() -> None:
    action = (
        _CONNECT / "workday" / "actions" / "wire-user-context-redirect.md"
    ).read_text(encoding="utf-8")

    assert "workspace/agents/{AGENT_SLUG}/.component-map.json" in action
    assert "workspace/agents/{AGENT_SLUG}/{USER_CONTEXT_TOPIC_PATH}" in action
    assert 'ACTION_RESULT = "cancelled"' in action
    assert 'ACTION_RESULT = "applied"' in action
    assert "ACTION_ROLLBACK_PUSH_GLOB" in action
    assert "install-workday-extension-pack.md" not in action


def test_connect_contract_action_docs_and_rollback_scopes_are_valid() -> None:
    contracts = sorted(_CONNECT.glob("*/contract.json"))
    assert contracts

    for contract_path in contracts:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        for phase in contract["phases"]:
            action_doc = phase.get("actionDoc")
            if action_doc:
                assert (_SOLUTION / action_doc).is_file()

            has_static_scope = "rollbackPushGlob" in phase
            has_dynamic_scope = phase.get("rollbackPushGlobFromAction") is True
            assert not (has_static_scope and has_dynamic_scope)
            if phase.get("rollbackLabel"):
                assert has_static_scope or has_dynamic_scope


def test_dynamic_rollback_scope_is_persisted_and_reused_exactly() -> None:
    runner = (_CONNECT / "shared" / "lifecycle-runner.md").read_text(
        encoding="utf-8"
    )
    schema = (_CONNECT / "shared" / "lifecycle-contract-schema.md").read_text(
        encoding="utf-8"
    )

    assert "ACTION_ROLLBACK_PUSH_GLOB" in runner
    assert "phases.{id}.rollbackPushGlob" in runner
    assert "no wildcard characters" in runner
    assert '--only "{ROLLBACK_PUSH_GLOB}"' in runner
    assert "remove\n  `rollbackPushGlob`" in runner
    assert "rollbackPushGlobFromAction" in schema
    assert "ACTION_ROLLBACK_PUSH_GLOB" in schema


def test_declarative_agents_do_not_enter_cea_lifecycle() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")

    assert "releaseLine: \"da\"" in route
    assert "gptagent_copilotforemployeeselfservicehr" in route
    assert "gptagent_copilotforemployeeselfserviceit" in route
    assert "WD-DA-PKG-001" in route
    assert "Do not create CEA Workday lifecycle state" in route
    assert "setup/workday-da/SKILL.md" in route
