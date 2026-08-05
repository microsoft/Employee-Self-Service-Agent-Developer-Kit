# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the auto-handoff target-agent check
(TOPIC-020, emitted per enabled handoff topic as ``TOPIC-020-{N:03d}``).

The check (``solutions/ess-maker-skills/scripts/flightcheck/checks/
agent_handoff.py``) is conditional: it only validates ENABLED
(``status == "Active"``) handoff topics. A handoff topic is identified by
the presence of a ``SetVariable`` node assigning ``Topic.HandoffAgentId``
(not by its schemaName, because makers clone/rename the template or enable
an accelerator). For each such topic it confirms the assigned id is a
concrete value rather than the shipped ``"AgentIdentifier"`` placeholder.

These tests build a minimal fake PVA (Island Gateway) client that returns
canned DialogComponent records. PVA is not mocked through a registry module
— the check just calls ``runner.pva.get_dialog_components(bot_id)`` and reads
``runner.pva.is_configured``, so a duck-typed stand-in is sufficient (same
approach as ``test_graph_connector_kb.py``, which also drives the Island
Gateway client inline).

Every field of the inline DialogComponent below is grounded in the validated
cassette ``tests/fixtures/cassettes/island_gateway_botcomponents.yaml``
(interaction index 2, POST .../content/botcomponents). The captured handoff
topic — component ``$kind == "DialogComponent"``, ``schemaName ==
"msdyn_copilotforemployeeselfservicehr.topic.Agenthandoff-scenarioname"`` —
ships ``status == "Inactive"`` with the SetVariable node:

    {"$kind": "SetVariable", "id": "setVariable_7l2dng",
     "variable": "Topic.HandoffAgentId",
     "value": {"$kind": "ValueExpression",
               "expressionText": "\\"AgentIdentifier\\""}}

The tests flip the captured ``status`` (Inactive -> Active) and vary the
captured ``expressionText`` value; both are real captured fields, so no mock
shape is invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flightcheck.checks.agent_handoff import run_handoff_topic_checks

FAKE_BOT_ID = "00000000-0000-0000-0000-000000003333"

# schemaName of the captured handoff auto-template topic (cassette
# interaction 2 -> botComponentChanges[*].component with $kind
# "DialogComponent" and this schemaName).
HANDOFF_SCHEMA_NAME = "msdyn_copilotforemployeeselfservicehr.topic.Agenthandoff-scenarioname"


# ───────────────────────────────────────────────────────────────────────
# Fakes
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _FakePVA:
    """Stand-in for the Island Gateway client. Returns a canned list of
    DialogComponent dicts when ``get_dialog_components`` is called.

    The check never imports the real PVA class — it just calls
    ``runner.pva.get_dialog_components(bot_id)`` and checks
    ``runner.pva.is_configured``, so a duck-typed stand-in is enough.
    """

    dialog_components: list[dict[str, Any]] = field(default_factory=list)
    is_configured: bool = True

    def get_dialog_components(self, bot_id: str) -> list[dict[str, Any]]:
        return list(self.dialog_components)


@dataclass
class _MinimalRunner:
    pva: Any
    config: dict[str, Any]


# ───────────────────────────────────────────────────────────────────────
# Grounded inline builders (cassette island_gateway_botcomponents.yaml)
# ───────────────────────────────────────────────────────────────────────


def _handoff_dialog_component(
    *,
    schema_name: str = HANDOFF_SCHEMA_NAME,
    display_name: str = "Mock Display Name",
    status: str = "Active",
    expression_text: str = '"AgentIdentifier"',
    value_node: dict[str, Any] | None = None,
    include_setvariable: bool = True,
) -> dict[str, Any]:
    """Build a handoff DialogComponent as returned by
    ``PVAClient.get_dialog_components`` (the inner ``component`` dict of a
    ``BotComponentInsert`` change).

    Shape is copied from the captured handoff topic in the validated cassette
    ``island_gateway_botcomponents.yaml`` (interaction 2): component
    ``$kind == "DialogComponent"``; ``dialog.$kind == "AdaptiveDialog"``;
    ``dialog.beginDialog.$kind == "OnRecognizedIntent"`` with an ``actions``
    list; the ``SetVariable`` node on ``Topic.HandoffAgentId`` sits directly
    in ``actions``.

    ``status`` and ``expression_text`` are the two captured field VALUES the
    tests vary — the cassette ships ``status == "Inactive"`` and
    ``expressionText == '"AgentIdentifier"'``.

    ``value_node`` overrides the entire SetVariable ``value`` dict for tests
    that need a non-literal assignment (e.g. a ``variableReference`` value,
    whose shape is grounded in the same cassette's sibling SetVariables:
    ``{"$kind": "ValueExpression", "variableReference": "System.User.FirstName"}``).
    When ``None`` the value defaults to the captured literal shape
    ``{"$kind": "ValueExpression", "expressionText": expression_text}``.
    """
    actions: list[dict[str, Any]] = []
    if include_setvariable:
        value = value_node if value_node is not None else {
            "$kind": "ValueExpression",
            "expressionText": expression_text,
        }
        actions.append(
            {
                "$kind": "SetVariable",
                "id": "setVariable_7l2dng",
                "variable": "Topic.HandoffAgentId",
                "value": value,
            }
        )
    return {
        "$kind": "DialogComponent",
        "schemaName": schema_name,
        "displayName": display_name,
        "status": status,
        "state": "mc",
        "dialog": {
            "$kind": "AdaptiveDialog",
            "beginDialog": {
                "$kind": "OnRecognizedIntent",
                "id": "main",
                "actions": actions,
            },
        },
    }


def _non_handoff_dialog_component(
    *,
    schema_name: str = "msdyn_copilotforemployeeselfservicehr.topic.Greeting",
    status: str = "Active",
) -> dict[str, Any]:
    """A non-handoff DialogComponent (different schemaName, no handoff
    marker), used to confirm the gate ignores unrelated topics. Same
    envelope shape as the captured DialogComponents in the cassette.
    """
    return {
        "$kind": "DialogComponent",
        "schemaName": schema_name,
        "displayName": "Greeting",
        "status": status,
        "state": "mc",
        "dialog": {
            "$kind": "AdaptiveDialog",
            "beginDialog": {"$kind": "OnRecognizedIntent", "id": "main", "actions": []},
        },
    }


def _build_runner(*, pva: Any, bot_id: str | None = FAKE_BOT_ID) -> _MinimalRunner:
    agent: dict[str, Any] = {}
    if bot_id is not None:
        agent["botId"] = bot_id
    return _MinimalRunner(pva=pva, config={"agent": agent})


def _result_by_id(results, checkpoint_id):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, f"expected exactly one {checkpoint_id}, got {len(matches)}"
    return matches[0]


# ───────────────────────────────────────────────────────────────────────
# Gating
# ───────────────────────────────────────────────────────────────────────


class TestGating:
    def test_no_components_returns_empty(self):
        runner = _build_runner(pva=_FakePVA(dialog_components=[]))
        assert run_handoff_topic_checks(runner) == []

    def test_inactive_handoff_topic_is_gated_out(self):
        # Cassette OOTB state: handoff topic present but status "Inactive".
        comp = _handoff_dialog_component(status="Inactive")
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        assert run_handoff_topic_checks(runner) == []

    def test_non_handoff_topic_is_ignored(self):
        comp = _non_handoff_dialog_component(status="Active")
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        assert run_handoff_topic_checks(runner) == []

    def test_pva_none_returns_empty(self):
        runner = _build_runner(pva=None)
        assert run_handoff_topic_checks(runner) == []

    def test_pva_not_configured_returns_empty(self):
        comp = _handoff_dialog_component(status="Active")
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp], is_configured=False))
        assert run_handoff_topic_checks(runner) == []

    def test_missing_bot_id_returns_empty(self):
        comp = _handoff_dialog_component(status="Active")
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]), bot_id=None)
        assert run_handoff_topic_checks(runner) == []

    def test_get_dialog_components_raising_returns_empty(self):
        @dataclass
        class _RaisingPVA:
            is_configured: bool = True

            def get_dialog_components(self, bot_id: str):
                raise RuntimeError("gateway down")

        runner = _build_runner(pva=_RaisingPVA())
        assert run_handoff_topic_checks(runner) == []


# ───────────────────────────────────────────────────────────────────────
# Good state — concrete target agent id
# ───────────────────────────────────────────────────────────────────────


class TestGoodConfig:
    def test_concrete_agent_id_passes(self):
        comp = _handoff_dialog_component(status="Active", expression_text='"my-gpt-agent-42"')
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        results = run_handoff_topic_checks(runner)
        assert len(results) == 1
        r = _result_by_id(results, "TOPIC-020-001")
        assert r.status == "Passed"
        assert r.category == "Agent Handoff"
        assert r.priority == "High"

    def test_multiple_enabled_topics_get_indexed_ids(self):
        c1 = _handoff_dialog_component(status="Active", expression_text='"agent-one"')
        c2 = _handoff_dialog_component(
            schema_name="msdyn_copilotforemployeeselfservicehr.topic.Agenthandoff-second",
            status="Active",
            expression_text='"AgentIdentifier"',
        )
        runner = _build_runner(pva=_FakePVA(dialog_components=[c1, c2]))
        results = run_handoff_topic_checks(runner)
        assert len(results) == 2
        assert _result_by_id(results, "TOPIC-020-001").status == "Passed"
        assert _result_by_id(results, "TOPIC-020-002").status == "Failed"


# ───────────────────────────────────────────────────────────────────────
# Bad state — placeholder still present
# ───────────────────────────────────────────────────────────────────────


class TestPlaceholderStillSet:
    def test_placeholder_value_fails(self):
        comp = _handoff_dialog_component(status="Active", expression_text='"AgentIdentifier"')
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        r = _result_by_id(run_handoff_topic_checks(runner), "TOPIC-020-001")
        assert r.status == "Failed"
        assert "AgentIdentifier" in r.result
        assert "Topic.HandoffAgentId" in r.result
        # Remediation offers both paths: set a real id, or disable the topic.
        assert "Set Handoff Agent ID" in r.remediation
        assert "disable the topic" in r.remediation
        assert r.doc_link.endswith("agent-handoff.md")

    def test_blank_value_fails(self):
        comp = _handoff_dialog_component(status="Active", expression_text='""')
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        r = _result_by_id(run_handoff_topic_checks(runner), "TOPIC-020-001")
        assert r.status == "Failed"
        assert "blank" in r.result
        assert "AgentIdentifier" not in r.result
        assert "Topic.HandoffAgentId" in r.result
        assert "disable the topic" in r.remediation


# ───────────────────────────────────────────────────────────────────────
# Identity is the HandoffAgentId SetVariable, not the schemaName
# ───────────────────────────────────────────────────────────────────────


class TestHandoffIdentity:
    def test_handoff_named_topic_without_setvariable_is_ignored(self):
        # A component that merely carries the handoff schemaName but has no
        # SetVariable assigning Topic.HandoffAgentId is not a handoff topic
        # by definition (identity is the variable, not the name), so it is
        # not flagged.
        comp = _handoff_dialog_component(status="Active", include_setvariable=False)
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        assert run_handoff_topic_checks(runner) == []

    def test_renamed_clone_with_placeholder_fails(self):
        # The core #152 case: a maker CLONES the sample template, RENAMES it
        # (so the schemaName no longer contains "agenthandoff"), enables it,
        # but leaves the placeholder. Keying on the schemaName would skip
        # this; keying on the SetVariable catches it.
        comp = _handoff_dialog_component(
            schema_name="msdyn_copilotforemployeeselfservicehr.topic.RouteToWorkday",
            display_name="Route to Workday",
            status="Active",
            expression_text='"AgentIdentifier"',
        )
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        r = _result_by_id(run_handoff_topic_checks(runner), "TOPIC-020-001")
        assert r.status == "Failed"
        assert "AgentIdentifier" in r.result

    def test_enabled_accelerator_prefixed_placeholder_fails(self):
        # Handoff Accelerators (Workday / ServiceNow) ship a system-prefixed
        # placeholder, e.g. "ServiceNowAgentIdentifier" (observed on live OOTB
        # ServiceNow accelerators), with a schemaName that does not contain
        # "agenthandoff". An enabled accelerator left on its own placeholder
        # must FAIL, not silently pass.
        comp = _handoff_dialog_component(
            schema_name="msdyn_copilotforemployeeselfservice.topic.ServiceNowITSMEmployeeHandoffScenarios",
            display_name="ServiceNow ITSM Employee Handoff Scenarios",
            status="Active",
            expression_text='"ServiceNowAgentIdentifier"',
        )
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        r = _result_by_id(run_handoff_topic_checks(runner), "TOPIC-020-001")
        assert r.status == "Failed"
        assert "ServiceNowAgentIdentifier" in r.result

    def test_enabled_accelerator_concrete_id_passes(self):
        # A renamed/configured accelerator with a real prefixed-GUID target id
        # (observed live as e.g. "T_<guid>...") must PASS.
        comp = _handoff_dialog_component(
            schema_name="msdyn_copilotforemployeeselfserviceit.topic.ServiceNowITSMEmployeeHandoffScenariosCopy",
            display_name="Alternative ServiceNow ITSM Employee Handoff Scenarios",
            status="Active",
            expression_text='"T_e1871622-17c8-d06a-b128-28cae5867b15.90e587d7-0995-4a6d-bfff-2e770b4df23d"',
        )
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        r = _result_by_id(run_handoff_topic_checks(runner), "TOPIC-020-001")
        assert r.status == "Passed"


# ───────────────────────────────────────────────────────────────────────
# Non-literal assignment (variable reference / PowerFx formula) → MANUAL
# ───────────────────────────────────────────────────────────────────────


class TestReferenceOrExpressionValue:
    """PR #218 review point 2 — a handoff id assigned via a variable
    reference or a PowerFx formula (no quoted string literal) must NOT be
    reported as a false-positive blank/placeholder FAILED.

    Before the fix, ``_resolved_agent_id`` read only ``expressionText`` and
    treated a missing/non-literal value as ``""`` -> "blank" -> FAILED, which
    fails a correctly-configured topic. The check now returns MANUAL: the
    value is definitively not the shipped placeholder literal, but the kit
    cannot statically resolve what the expression evaluates to at runtime, so
    the operator must confirm the resolved target id. MANUAL does not fail
    readiness.

    The ``variableReference`` value-node shape is grounded in the validated
    cassette ``island_gateway_botcomponents.yaml``, whose sibling SetVariables
    use ``{"$kind": "ValueExpression", "variableReference": "System.User.FirstName"}``.
    """

    def test_variable_reference_value_is_manual_not_failed(self):
        comp = _handoff_dialog_component(
            status="Active",
            value_node={
                "$kind": "ValueExpression",
                "variableReference": "Global.ESS_HandoffAgentId",
            },
        )
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        r = _result_by_id(run_handoff_topic_checks(runner), "TOPIC-020-001")
        assert r.status == "Manual"
        # Must not be the old false-positive blank/placeholder FAILED text.
        assert "blank" not in r.result
        assert "AgentIdentifier" not in r.result
        # result names the observed dynamic shape; remediation says how to fix.
        assert "reference" in r.result.lower() or "expression" in r.result.lower()
        assert "Topic.HandoffAgentId" in r.result
        assert "GPT ID" in r.remediation
        assert "disable the topic" in r.remediation
        assert r.doc_link.endswith("agent-handoff.md")

    def test_nonliteral_expression_formula_is_manual(self):
        # expressionText present but NOT a quoted string literal — a PowerFx
        # formula the kit cannot statically resolve to a concrete id.
        comp = _handoff_dialog_component(
            status="Active",
            expression_text='If(Global.UseWorkday, "T_workday", "T_servicenow")',
        )
        runner = _build_runner(pva=_FakePVA(dialog_components=[comp]))
        r = _result_by_id(run_handoff_topic_checks(runner), "TOPIC-020-001")
        assert r.status == "Manual"
        assert "blank" not in r.result

    def test_reference_topic_does_not_fail_readiness_with_placeholder_sibling(self):
        # A reference-configured topic (MANUAL) alongside a still-placeholder
        # topic (FAILED): the reference one must not be swept into FAILED.
        c1 = _handoff_dialog_component(
            status="Active",
            value_node={
                "$kind": "ValueExpression",
                "variableReference": "Global.ESS_HandoffAgentId",
            },
        )
        c2 = _handoff_dialog_component(
            schema_name="msdyn_copilotforemployeeselfservicehr.topic.Agenthandoff-second",
            status="Active",
            expression_text='"AgentIdentifier"',
        )
        runner = _build_runner(pva=_FakePVA(dialog_components=[c1, c2]))
        results = run_handoff_topic_checks(runner)
        assert len(results) == 2
        assert _result_by_id(results, "TOPIC-020-001").status == "Manual"
        assert _result_by_id(results, "TOPIC-020-002").status == "Failed"
