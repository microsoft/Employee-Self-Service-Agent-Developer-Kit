# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Synthetic local contracts; these tests make no vendor API calls."""

from datetime import datetime, timedelta, timezone
import json
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

import servicenow_kb_connect as connect
import servicenow_kb_contracts as contracts
from workday_connect_workbook import WorkdayConnectWorkbookError

BOT = "11111111-2222-4333-8444-555555555555"
TENANT = "22222222-3333-4444-8555-666666666666"
ENV = "33333333-4444-4555-8666-777777777777"
KB = "a" * 32
INSTANCE = "https://instance.example.com"
QUERY = f"active=true^workflow_state=published^kb_knowledge_base={KB}"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    agent_path = tmp_path / "workspace" / "agents" / "ess-hr"
    agent_path.mkdir(parents=True)
    (agent_path / "agent.mcs.yml").write_text("kind: GptComponent\n", encoding="utf-8")
    save(
        tmp_path / ".local" / "config.json",
        {
            "activeAgent": "ess-hr",
            "releaseLine": "da",
            "environmentId": ENV,
            "agents": [
                {
                    "slug": "ess-hr",
                    "botId": BOT,
                    "schemaName": "gptagent_copilotforemployeeselfservicehr",
                    "realm": "Dev",
                }
            ],
        },
    )
    save(
        tmp_path / ".local" / "setup" / "config.json",
        {
            "schema_version": 4,
            "environment": {"id": ENV, "tenant_id": TENANT},
            "agents": {
                BOT: {
                    "agent": {
                        "id": BOT,
                        "workspace_slug": "ess-hr",
                        "realm": "Dev",
                        "schema_name": "gptagent_copilotforemployeeselfservicehr",
                    },
                    "workspace": {
                        "folder": "workspace/agents/ess-hr",
                        "agent_path": "agent.mcs.yml",
                    },
                    "steps": {"SETUP-07": {"state": "done"}},
                    "connect_ready": False,
                }
            },
        },
    )
    return tmp_path


def begin(root, flow="simple", **changes):
    return connect.start(
        root,
        **{
            "instance": INSTANCE,
            "query": QUERY,
            "flow": flow,
            "hr_content": False,
            **changes,
        },
    )


def administrator_answers(owner, scope):
    result = dict.fromkeys(contracts.fields_for(owner, scope), "confirmed")
    if owner == "servicenow":
        result["Service principal object ID"] = ENV
        result["Assessment date"] = datetime.now(timezone.utc).date().isoformat()
        result["HR scoped reads"] = (
            "confirmed" if scope["hrContent"] else "not-applicable"
        )
        if scope["flow"] == "advanced":
            result["Advanced namespace"] = "1234567"
    else:
        result["Connection name"] = "ServiceNow Knowledge - HR"
        result["Audience"] = "organization-wide"
    return result


def submit(root, owner, **overrides):
    state = connect.read_json(root / connect.CONFIG_PATH)
    path = root / f"{owner}-return.xlsx"
    answers = {**administrator_answers(owner, state["scope"]), **overrides}
    contracts.write_handoff(path, owner, state["scope"], answers)
    return connect.import_handoff(root, owner, path)


def ready_admins(root, flow="simple"):
    begin(root, flow)
    assert submit(root, "servicenow")["accepted"]
    result = submit(root, "m365")
    assert result["accepted"]
    return verify_connection(root, result)


def verify_connection(root, result):
    return connect.confirm(
        root,
        "connection-ready",
        "confirmed",
        result["targetReference"],
        connect.values(result["state"], "m365")["Connection name"],
    )


def acceptance(state):
    result = dict.fromkeys(
        {
            "sourceAttached",
            "articleIndexed",
            "allowedNative",
            "allowedIndexed",
            "deniedNative",
            "deniedIndexed",
            "answerWithCitation",
            "exactSourceIsolated",
        },
        "confirmed",
    )
    result.update(
        targetReference=contracts.target_reference(state["scope"]),
        connectionName=connect.values(state, "m365")["Connection name"],
        articleNumber="KB0000012",
        knowledgeBaseId=KB,
        observedAt=datetime.now(timezone.utc).isoformat(),
    )
    return result


def guided_value(result):
    step = result["nextStep"]
    if step["owner"] == "validation":
        return acceptance(result["state"])[step["field"]]
    if step["checkpoint"]:
        return "confirmed"
    return administrator_answers(step["owner"], result["state"]["scope"])[step["field"]]


def walk_guided(root, result, *, stop=None):
    while result["nextStep"] and result["nextStep"]["id"] != stop:
        result = connect.confirm(
            root,
            result["nextStep"]["id"],
            guided_value(result),
            result["targetReference"],
            connect.values(result["state"], "m365").get("Connection name"),
        )
        assert result["accepted"], result
    return result


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_acceptance_time_is_automatic_and_preserved_on_resume(root, monkeypatch, flow):
    timestamp = "2000-01-02T03:04:05Z"
    monkeypatch.setattr(connect, "now", lambda: timestamp)
    pending = walk_guided(root, begin(root, flow), stop="answer-citation")
    assert "observation-time" not in pending["state"]["checkpoints"]
    finished = connect.confirm(
        root,
        "answer-citation",
        "confirmed",
        pending["targetReference"],
        connect.values(pending["state"], "m365")["Connection name"],
    )
    assert finished["status"] == "guided-validated"
    assert finished["nextStep"] is None
    observation = finished["state"]["checkpoints"]["observation-time"]
    assert observation["value"] == observation["recordedAt"] == timestamp
    assert connect.values(finished["state"], "validation")["observedAt"] == timestamp
    monkeypatch.setattr(connect, "now", lambda: "2001-01-02T03:04:05Z")
    resumed = begin(root, flow)
    assert resumed["state"]["checkpoints"]["observation-time"] == observation
    assert (
        resumed["state"]["evidence"]["validation"]
        == (finished["state"]["evidence"]["validation"])
    )


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_legacy_missing_acceptance_time_uses_recorded_completion_not_resume_time(
    root, monkeypatch, flow
):
    with monkeypatch.context() as legacy:
        legacy.setattr(connect, "complete_guided_validation", lambda state: None)
        legacy.setattr(connect, "now", lambda: "2000-01-02T03:04:05-08:00")
        pending = walk_guided(root, begin(root, flow), stop="observation-time")
    assert pending["nextStep"]["id"] == "observation-time"
    monkeypatch.setattr(connect, "now", lambda: "2001-01-02T03:04:05Z")
    resumed = begin(root, flow)
    assert resumed["status"] == "guided-validated"
    assert resumed["nextStep"] is None
    assert connect.values(resumed["state"], "validation")["observedAt"] == (
        "2000-01-02T11:04:05Z"
    )
    for step, checkpoint in pending["state"]["checkpoints"].items():
        assert resumed["state"]["checkpoints"][step] == checkpoint


def test_failed_acceptance_does_not_gain_automatic_completion_time(root):
    result = walk_guided(root, begin(root), stop="answer-citation")
    failed = connect.confirm(
        root,
        "answer-citation",
        "unverified",
        result["targetReference"],
        connect.values(result["state"], "m365")["Connection name"],
    )
    assert not failed["accepted"]
    assert "observation-time" not in failed["state"]["checkpoints"]
    assert not connect.values(failed["state"], "validation")
    resumed = begin(root)
    assert resumed["nextStep"]["id"] == "answer-citation"
    assert "observation-time" not in resumed["state"]["checkpoints"]


@pytest.mark.parametrize("flow", ["simple", "advanced"])
@pytest.mark.parametrize("outcome", ["confirmed", "skipped"])
def test_grouped_denied_reader_action_records_both_outcomes_and_resumes(
    root, flow, outcome
):
    result = walk_guided(root, begin(root, flow), stop="denied-native")
    result = connect.confirm(
        root,
        "denied-reader",
        outcome,
        result["targetReference"],
        connect.values(result["state"], "m365")["Connection name"],
    )
    assert result["accepted"]
    assert result["nextStep"]["id"] == "source-attached"
    checkpoints = result["state"]["checkpoints"]
    assert "denied-reader" not in checkpoints
    assert checkpoints["denied-native"] == checkpoints["denied-indexed"]
    assert checkpoints["denied-native"]["value"] == outcome
    saved = begin(root, flow)
    assert saved["state"]["checkpoints"] == checkpoints
    finished = walk_guided(root, saved)
    assert finished["status"] == (
        "guided-complete-with-warnings" if outcome == "skipped" else "guided-validated"
    )
    evidence = connect.values(finished["state"], "validation")
    assert evidence["deniedNative"] == evidence["deniedIndexed"] == outcome
    warnings = [
        item
        for item in begin(root, flow)["warnings"]
        if item["step"] == "denied-reader"
    ]
    assert bool(warnings) == (outcome == "skipped")
    if outcome == "skipped":
        assert warnings[0]["status"] == "skipped"
        assert "not tested" in warnings[0]["message"]
        retested = connect.confirm(
            root,
            "denied-reader",
            "confirmed",
            finished["targetReference"],
            connect.values(finished["state"], "m365")["Connection name"],
        )
        assert retested["nextStep"]["id"] == "source-attached"
        assert not retested["warnings"]
        assert walk_guided(root, retested)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_grouped_denied_failure_cannot_be_bypassed_by_skip(root, flow):
    result = walk_guided(root, begin(root, flow), stop="denied-native")
    name = connect.values(result["state"], "m365")["Connection name"]
    failed = connect.confirm(
        root, "denied-reader", "unverified", result["targetReference"], name
    )
    assert not failed["accepted"]
    assert failed["status"] == "blocked"
    assert failed["nextStep"]["id"] == "denied-native"
    assert "denied-indexed" not in failed["state"]["checkpoints"]
    for step in ("allowed-indexed", "denied-native"):
        rechecked = connect.confirm(
            root, step, "confirmed", result["targetReference"], name
        )
        assert rechecked["status"] == "blocked"
    before = (root / connect.CONFIG_PATH).read_bytes()
    with pytest.raises(
        contracts.KnowledgeConnectError, match="reported validation failure"
    ):
        connect.confirm(
            root, "denied-reader", "skipped", result["targetReference"], name
        )
    assert (root / connect.CONFIG_PATH).read_bytes() == before
    skipped = acceptance(failed["state"])
    skipped.update(deniedNative="skipped", deniedIndexed="skipped")
    with pytest.raises(
        contracts.KnowledgeConnectError, match="reported validation failure"
    ):
        connect.accept(root, skipped)
    assert (root / connect.CONFIG_PATH).read_bytes() == before
    recovered = connect.confirm(
        root, "denied-reader", "confirmed", result["targetReference"], name
    )
    assert recovered["accepted"]
    assert walk_guided(root, recovered)["status"] == "guided-validated"


def test_optional_denied_action_keeps_scope_order_and_other_checks_required(root):
    result = walk_guided(root, begin(root), stop="allowed-indexed")
    name = connect.values(result["state"], "m365")["Connection name"]
    before = (root / connect.CONFIG_PATH).read_bytes()
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(
            root, "denied-reader", "skipped", result["targetReference"], name
        )
    with pytest.raises(contracts.KnowledgeConnectError, match="grouped denied-reader"):
        connect.confirm(
            root, "allowed-indexed", "skipped", result["targetReference"], name
        )
    assert (root / connect.CONFIG_PATH).read_bytes() == before
    result = walk_guided(root, result, stop="denied-native")
    before = (root / connect.CONFIG_PATH).read_bytes()
    with pytest.raises(contracts.KnowledgeConnectError, match="different target"):
        connect.confirm(root, "denied-reader", "skipped", "stale-target", name)
    with pytest.raises(contracts.KnowledgeConnectError, match="connection name"):
        connect.confirm(
            root,
            "denied-reader",
            "skipped",
            result["targetReference"],
            "Other connection",
        )
    with pytest.raises(contracts.KnowledgeConnectError, match="grouped denied-reader"):
        connect.confirm(
            root, "denied-native", "skipped", result["targetReference"], name
        )
    assert (root / connect.CONFIG_PATH).read_bytes() == before
    evidence = acceptance(result["state"])
    evidence["deniedNative"] = "skipped"
    with pytest.raises(contracts.KnowledgeConnectError, match="whole denied-reader"):
        contracts.validate_acceptance(evidence, result["state"]["scope"], name)


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_grouped_action_reuses_partial_legacy_denied_progress(root, flow):
    partial = walk_guided(root, begin(root, flow), stop="denied-indexed")
    resumed = begin(root, flow)
    assert resumed["state"]["checkpoints"] == partial["state"]["checkpoints"]
    assert resumed["nextStep"]["id"] == "denied-indexed"
    result = connect.confirm(
        root,
        "denied-reader",
        "confirmed",
        resumed["targetReference"],
        connect.values(resumed["state"], "m365")["Connection name"],
    )
    assert result["accepted"]
    assert result["nextStep"]["id"] == "source-attached"
    assert (
        result["state"]["checkpoints"]["denied-native"]
        == (partial["state"]["checkpoints"]["denied-native"])
    )
    assert walk_guided(root, result)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_guided_configuration_and_reader_cases_complete_without_workbooks(root, flow):
    result = walk_guided(
        root, connect.start(root, instance=INSTANCE, query=QUERY, flow=flow)
    )
    assert result["status"] == "guided-validated"
    assert result["nextStep"] is None
    assert not list(root.rglob("*.xlsx"))
    assert result["state"]["scope"]["hrContent"] is None
    evidence = result["state"]["evidence"]
    assert evidence["m365"]["values"]["Connection name"] == "ServiceNow Knowledge - HR"
    assert "Connection ID" not in evidence["m365"]["values"]
    assert (
        evidence["validation"]["values"]["connectionName"]
        == "ServiceNow Knowledge - HR"
    )
    assert evidence["servicenow"]["kind"] == "admin-confirmed"
    assert evidence["validation"]["kind"] == "maker-tested"
    assert (
        connect.start(root, instance=INSTANCE, query=QUERY, flow=flow)["state"][
            "evidence"
        ]
        == evidence
    )


@pytest.mark.parametrize(
    "name",
    ["HR Knowledge - ServiceNow", "ServiceNow (IT) / FAQs", "Microsoft Knowledge"],
)
def test_connection_names_support_display_text_and_cli_confirmation(root, capsys, name):
    result = walk_guided(root, begin(root), stop="connection-name")
    named = connect.confirm(root, "connection-name", name, result["targetReference"])
    assert named["accepted"]
    assert named["nextStep"]["id"] == "connection-ready"
    assert (
        connect.main(
            [
                "--root",
                str(root),
                "confirm",
                "--step",
                "connection-ready",
                "--value",
                "confirmed",
                "--target-reference",
                named["targetReference"],
                "--connection-name",
                name,
            ]
        )
        == 0
    )
    ready = json.loads(capsys.readouterr().out.split("SERVICENOW_KB_RESULT_JSON:")[1])
    assert walk_guided(root, ready)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
@pytest.mark.parametrize("version", [1, 2])
def test_old_id_progress_obtains_name_without_rewriting_history(root, flow, version):
    state = walk_guided(root, begin(root, flow))["state"]
    m365 = connect.values(state, "m365")
    m365.pop("Connection name")
    m365["Connection ID"] = "ServiceNowKB12345"
    observed = connect.values(state, "validation")
    observed.pop("connectionName")
    observed["connectionId"] = "ServiceNowKB12345"
    state["schemaVersion"] = version
    if version == 1:
        state.pop("checkpoints")
    save(root / connect.CONFIG_PATH, state)
    resumed = begin(root, flow)
    assert resumed["nextStep"]["id"] == "connection-name"
    assert resumed["missingFields"] == ["Connection name"]
    assert resumed["state"]["evidence"] == state["evidence"]
    assert resumed["state"]["checkpoints"] == state.get("checkpoints", {})
    with pytest.raises(contracts.KnowledgeConnectError, match="administrator"):
        connect.accept(root, observed)
    with pytest.raises(contracts.KnowledgeConnectError, match="connection name"):
        connect.confirm(
            root,
            "connection-ready",
            "confirmed",
            resumed["targetReference"],
            "ServiceNowKB12345",
        )
    named = connect.confirm(
        root, "connection-name", "ServiceNow Knowledge - HR", resumed["targetReference"]
    )
    assert connect.values(named["state"], "m365") == {
        **m365,
        "Connection name": "ServiceNow Knowledge - HR",
    }
    assert named["state"]["evidence"]["validation"] == state["evidence"]["validation"]
    assert named["state"]["evidence"]["servicenow"] == state["evidence"]["servicenow"]
    assert named["state"]["checkpoints"] == state.get("checkpoints", {})
    if version == 1:
        assert named["nextStep"]["id"] == "connection-ready"
        named = verify_connection(root, named)
    assert named["status"] == "guided-validated"
    updated = connect.confirm(
        root,
        "observation-time",
        datetime.now(timezone.utc).isoformat(),
        named["targetReference"],
        "ServiceNow Knowledge - HR",
    )
    assert updated["status"] == "guided-validated"
    assert "connectionId" not in connect.values(updated["state"], "validation")
    assert connect.values(updated["state"], "validation")["connectionName"] == (
        "ServiceNow Knowledge - HR"
    )


def test_legacy_id_workbook_remains_importable_but_name_is_still_required(
    root, monkeypatch
):
    begin(root)
    assert submit(root, "servicenow")["accepted"]
    state = connect.read_json(root / connect.CONFIG_PATH)
    answers = administrator_answers("m365", state["scope"])
    answers.pop("Connection name")
    answers["Connection ID"] = "ServiceNowKB12345"
    path = root / "legacy-m365.xlsx"
    with monkeypatch.context() as legacy:
        legacy.setattr(
            contracts,
            "M365_FIELDS",
            contracts.fields_for("m365", state["scope"], legacy_connection=True),
        )
        contracts.write_handoff(path, "m365", state["scope"], answers)
    result = connect.import_handoff(root, "m365", path)
    assert result["accepted"]
    assert result["nextStep"]["id"] == "connection-name"
    assert connect.values(result["state"], "m365") == answers
    named = connect.confirm(
        root, "connection-name", "ServiceNow Knowledge - HR", result["targetReference"]
    )
    assert named["nextStep"]["id"] == "connection-ready"


def test_changed_connection_name_requires_fresh_runtime_and_reader_checks(root):
    complete = walk_guided(root, begin(root))
    changed = connect.confirm(
        root, "connection-name", "ServiceNow - IT", complete["targetReference"]
    )
    assert changed["nextStep"]["id"] == "connection-ready"
    assert not connect.values(changed["state"], "validation")
    assert "connection-ready" not in changed["state"]["checkpoints"]
    assert (
        changed["state"]["evidence"]["servicenow"]
        == (complete["state"]["evidence"]["servicenow"])
    )
    assert walk_guided(root, changed)["status"] == "guided-validated"


def test_recording_name_removes_obsolete_id_blocker_but_not_unrelated_issues(root):
    state = walk_guided(root, begin(root), stop="connection-name")["state"]
    state["issues"]["m365"] = {
        "Connection ID": "Old ID check failed.",
        "Source permissions": "Separate permission review required.",
    }
    save(root / connect.CONFIG_PATH, state)
    resumed = begin(root)
    named = connect.confirm(
        root, "connection-name", "ServiceNow Knowledge - HR", resumed["targetReference"]
    )
    assert named["accepted"]
    assert named["state"]["issues"]["m365"] == {
        "Source permissions": "Separate permission review required."
    }
    assert named["status"] == "blocked"
    assert named["nextStep"]["id"] == "connection-ready"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
@pytest.mark.parametrize("access", ["unreadable", "unverified"])
def test_unresolved_property_access_waits_for_explicit_consent(root, flow, access):
    result = walk_guided(root, begin(root, flow), stop="property-reads")
    assert result["nextStep"]["requiresApproval"]
    result = connect.confirm(root, "property-reads", access, result["targetReference"])
    assert result["accepted"]
    assert result["nextStep"]["id"] == "property-reads"
    assert result["warnings"][0]["status"] == access
    assert not result["warnings"][0]["continuationApproved"]
    paused = begin(root, flow)
    assert paused["nextStep"]["id"] == "property-reads"
    assert paused["state"]["evidence"] == result["state"]["evidence"]
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(root, "hr-reads", "not-applicable", result["targetReference"])
    result = connect.confirm(
        root, "property-reads", "proceed-without-access", result["targetReference"]
    )
    assert result["accepted"]
    assert result["nextStep"]["id"] == "hr-reads"
    assert (
        connect.values(result["state"], "servicenow")["Permission property reads"]
        == "proceed-without-access"
    )
    warning = result["warnings"][0]
    assert warning["status"] == "proceed-without-access"
    assert warning["continuationApproved"]
    assert "defaults of true for both" in warning["message"]
    assert "block articles without explicit user criteria" in warning["message"]
    assert "No error is shown in the admin center" in warning["message"]
    assert "Consult your ServiceNow administrator" in warning["message"]
    assert "does not verify this access" in warning["message"]
    resumed = begin(root, flow)
    assert resumed["warnings"] == result["warnings"]
    assert resumed["nextStep"]["id"] == "hr-reads"
    result = walk_guided(root, resumed, stop="connection-ready")
    with pytest.raises(
        contracts.KnowledgeConnectError, match="administrator milestones"
    ):
        connect.accept(root, acceptance(result["state"]))
    result = walk_guided(root, result)
    assert result["status"] == "guided-validated"
    assert result["warnings"] == [warning]
    evidence = result["state"]["evidence"]
    resumed = begin(root, flow)
    assert resumed["warnings"] == [warning]
    assert resumed["state"]["evidence"] == evidence


def test_property_consent_clears_its_old_blocker_but_not_unrelated_issues(root):
    result = walk_guided(root, begin(root), stop="property-reads")
    result = connect.confirm(
        root, "property-reads", "blocked", result["targetReference"]
    )
    assert not result["accepted"]
    result = connect.confirm(
        root, "property-reads", "unreadable", result["targetReference"]
    )
    state = result["state"]
    checkpoints = state["checkpoints"].copy()
    state["issues"].setdefault("servicenow", {})["Common table reads"] = (
        "Separate unresolved issue."
    )
    save(root / connect.CONFIG_PATH, state)
    result = connect.confirm(
        root, "property-reads", "proceed-without-access", result["targetReference"]
    )
    assert result["accepted"]
    assert result["state"]["checkpoints"] == checkpoints
    assert result["state"]["issues"] == {
        "servicenow": {"Common table reads": "Separate unresolved issue."}
    }
    assert result["status"] == "blocked"
    assert result["warnings"]


def test_actual_property_verification_clears_only_the_deferred_warning(root):
    result = walk_guided(root, begin(root), stop="property-reads")
    result = connect.confirm(
        root, "property-reads", "unverified", result["targetReference"]
    )
    assert result["warnings"]
    result = connect.confirm(
        root, "property-reads", "confirmed", result["targetReference"]
    )
    assert result["accepted"]
    assert not result["warnings"]
    assert result["nextStep"]["id"] == "hr-reads"
    assert (
        connect.values(result["state"], "servicenow")["Permission property reads"]
        == "confirmed"
    )
    assert not begin(root)["warnings"]


def test_new_property_confirmation_rejects_automatic_deferral(root):
    result = walk_guided(root, begin(root), stop="property-reads")
    with pytest.raises(
        contracts.KnowledgeConnectError, match="reported property-access"
    ):
        connect.confirm(
            root, "property-reads", "proceed-without-access", result["targetReference"]
        )
    result = connect.confirm(
        root, "property-reads", "deferred-to-admin", result["targetReference"]
    )
    assert not result["accepted"]
    assert "explicit Yes" in result["stepError"]
    assert result["nextStep"]["id"] == "property-reads"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
@pytest.mark.parametrize("version", [1, 2])
def test_old_automatic_deferral_requires_consent_without_losing_observations(
    root, flow, version
):
    result = walk_guided(root, begin(root, flow), stop="property-reads")
    result = connect.confirm(
        root, "property-reads", "unreadable", result["targetReference"]
    )
    result = connect.confirm(
        root, "property-reads", "proceed-without-access", result["targetReference"]
    )
    result = walk_guided(root, result)
    state = result["state"]
    state["evidence"]["servicenow"]["values"]["Permission property reads"] = (
        "deferred-to-admin"
    )
    state["schemaVersion"] = version
    if version == 1:
        state.pop("checkpoints")
    save(root / connect.CONFIG_PATH, state)
    resumed = begin(root, flow)
    assert resumed["nextStep"]["id"] == "property-reads"
    assert resumed["status"] == "in-progress"
    assert not resumed["warnings"][0]["continuationApproved"]
    assert resumed["state"]["evidence"] == state["evidence"]
    assert resumed["state"]["checkpoints"] == state.get("checkpoints", {})
    with pytest.raises(contracts.KnowledgeConnectError, match="explicitly approve"):
        connect.accept(root, acceptance(state))
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(
            root,
            "allowed-indexed",
            "confirmed",
            resumed["targetReference"],
            connect.values(state, "m365")["Connection name"],
        )
    observed = connect.confirm(
        root, "property-reads", "unreadable", resumed["targetReference"]
    )
    assert observed["nextStep"]["id"] == "property-reads"
    assert observed["state"]["evidence"]["m365"] == state["evidence"]["m365"]
    assert (
        observed["state"]["evidence"]["validation"] == state["evidence"]["validation"]
    )
    approved = connect.confirm(
        root, "property-reads", "proceed-without-access", observed["targetReference"]
    )
    assert approved["warnings"][0]["continuationApproved"]
    assert approved["state"]["evidence"]["m365"] == state["evidence"]["m365"]
    assert (
        approved["state"]["evidence"]["validation"] == state["evidence"]["validation"]
    )
    assert approved["state"]["checkpoints"] == state.get("checkpoints", {})
    if version == 1:
        assert approved["nextStep"]["id"] == "connection-ready"
    else:
        assert approved["nextStep"] is None
        assert approved["status"] == "guided-validated"


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_legacy_verified_property_access_retains_evidence_without_warning(
    root, flow, version
):
    begin(root, flow)
    result = submit(root, "servicenow")
    state = result["state"]
    state["schemaVersion"] = version
    if version == 1:
        state.pop("checkpoints")
    save(root / connect.CONFIG_PATH, state)
    resumed = begin(root, flow)
    assert resumed["state"]["evidence"] == state["evidence"]
    assert not resumed["warnings"]
    assert (
        connect.values(resumed["state"], "servicenow")["Permission property reads"]
        == "confirmed"
    )


def test_partial_authentication_settings_resume_without_marking_auth_passed(root):
    result = walk_guided(root, begin(root), stop="integration-user")
    assert result["state"]["schemaVersion"] == 2
    assert "oidc-provider" in result["state"]["checkpoints"]
    assert "Federated Auth" not in connect.values(result["state"], "servicenow")
    resumed = begin(root)
    assert resumed["nextStep"]["id"] == "integration-user"
    assert resumed["state"]["checkpoints"] == result["state"]["checkpoints"]


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_permission_setup_precedes_draft_configuration_and_does_not_confirm_reads(
    root, flow
):
    result = walk_guided(root, begin(root, flow), stop="permission-setup")
    configured = connect.confirm(
        root, "permission-setup", "confirmed", result["targetReference"]
    )
    assert configured["nextStep"]["id"] == "identity-mapping"
    source = connect.values(configured["state"], "servicenow")
    for field in (
        "Common table reads",
        "Permission property reads",
        "HR scoped reads",
        "Simple attribute reads",
        "Federated Auth",
    ):
        assert field not in source
    resumed = begin(root, flow)
    assert resumed["state"]["checkpoints"] == configured["state"]["checkpoints"]
    before = (root / connect.CONFIG_PATH).read_bytes()
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(root, "table-reads", "confirmed", resumed["targetReference"])
    assert (root / connect.CONFIG_PATH).read_bytes() == before
    auth = walk_guided(root, resumed, stop="federated-auth")
    assert (
        set(contracts.fields_for("servicenow", auth["state"]["scope"]))
        - {"Federated Auth"}
        <= connect.values(auth["state"], "servicenow").keys()
    )
    draft = connect.confirm(
        root, "federated-auth", "confirmed", auth["targetReference"]
    )
    assert draft["nextStep"]["id"] == "connector-config"
    assert (
        connect.values(draft["state"], "servicenow")["Common table reads"]
        == "confirmed"
    )
    assert "connection-ready" not in draft["state"]["checkpoints"]
    reviewed = walk_guided(root, draft, stop="connector-config")
    assert set(contracts.fields_for("servicenow", reviewed["state"]["scope"])) <= (
        connect.values(reviewed["state"], "servicenow").keys()
    )


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_failed_access_validation_preserves_setup_but_blocks_connector_creation(
    root, flow
):
    result = walk_guided(root, begin(root, flow), stop="table-reads")
    failed = connect.confirm(
        root, "table-reads", "unverified", result["targetReference"]
    )
    assert not failed["accepted"]
    assert failed["status"] == "blocked"
    assert failed["nextStep"]["id"] == "table-reads"
    assert (
        failed["state"]["checkpoints"]["permission-setup"]
        == (result["state"]["checkpoints"]["permission-setup"])
    )
    assert "Federated Auth" not in connect.values(failed["state"], "servicenow")
    for checkpoint in ("oidc-provider", "integration-user", "integration-roles"):
        assert (
            failed["state"]["checkpoints"][checkpoint]
            == (result["state"]["checkpoints"][checkpoint])
        )
    assert "Common table reads" not in connect.values(failed["state"], "servicenow")
    assert not connect.values(failed["state"], "validation")
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(
            root, "connector-config", "confirmed", failed["targetReference"]
        )
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(root, "federated-auth", "confirmed", failed["targetReference"])
    assert walk_guided(root, failed)["status"] == "guided-validated"


@pytest.mark.parametrize(
    "flow,stop,next_step",
    [
        ("simple", "table-reads", "permission-setup"),
        ("simple", "simple-reads", "permission-setup"),
        ("simple", "federated-auth", "federated-auth"),
        ("advanced", "advanced-api", "advanced-api"),
        ("advanced", "advanced-security", "advanced-security"),
        ("advanced", "connector-config", "connector-config"),
    ],
)
def test_previous_step_order_resumes_without_rewriting_observations(
    root, monkeypatch, flow, stop, next_step
):
    old_order = [
        "scope-assessment",
        "assessment-date",
        "service-principal",
        "oidc-provider",
        "integration-user",
        "integration-roles",
        "table-reads",
        "property-reads",
        "identity-mapping",
        "hr-reads",
        "simple-reads",
        "advanced-api",
        "advanced-namespace",
        "advanced-security",
        "federated-auth",
    ]

    def previous_steps(scope):
        steps = contracts.configuration_steps(scope)
        source = [
            step
            for step in steps
            if step["owner"] == "servicenow" and step["id"] != "permission-setup"
        ]
        return sorted(source, key=lambda step: old_order.index(step["id"])) + [
            step for step in steps if step["owner"] != "servicenow"
        ]

    with monkeypatch.context() as legacy:
        legacy.setattr(connect, "configuration_steps", previous_steps)
        result = walk_guided(root, begin(root, flow), stop=stop)
    resumed = begin(root, flow)
    assert resumed["nextStep"]["id"] == next_step
    assert resumed["state"]["evidence"] == result["state"]["evidence"]
    assert resumed["state"]["checkpoints"] == result["state"]["checkpoints"]
    assert "permission-setup" not in resumed["state"]["checkpoints"]
    assert walk_guided(root, resumed)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_early_draft_resume_keeps_evidence_and_finishes_source_checks_first(
    root, monkeypatch, flow
):
    def previous_steps(scope):
        steps = contracts.configuration_steps(scope)
        draft = next(step for step in steps if step["id"] == "federated-auth")
        steps.remove(draft)
        table_index = next(
            index for index, step in enumerate(steps) if step["id"] == "table-reads"
        )
        steps.insert(table_index, draft)
        return steps

    with monkeypatch.context() as legacy:
        legacy.setattr(connect, "configuration_steps", previous_steps)
        partial = walk_guided(root, begin(root, flow), stop="table-reads")
    resumed = begin(root, flow)
    assert resumed["nextStep"]["id"] == "table-reads"
    assert resumed["state"]["evidence"] == partial["state"]["evidence"]
    assert resumed["state"]["checkpoints"] == partial["state"]["checkpoints"]
    reviewed = walk_guided(root, resumed, stop="connector-config")
    assert reviewed["nextStep"]["id"] == "connector-config"
    assert "Connection name" not in connect.values(reviewed["state"], "m365")
    assert "connection-ready" not in reviewed["state"]["checkpoints"]
    assert reviewed["state"]["checkpoints"] == partial["state"]["checkpoints"]
    assert walk_guided(root, reviewed)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_post_create_operation_requires_exact_connection_and_failure_keeps_it(
    root, flow
):
    draft = walk_guided(root, begin(root, flow), stop="connector-config")
    assert connect.values(draft["state"], "servicenow")["Federated Auth"] == "confirmed"
    assert "Connection name" not in connect.values(draft["state"], "m365")
    with pytest.raises(contracts.KnowledgeConnectError, match="connection name"):
        connect.confirm(root, "connection-ready", "confirmed", draft["targetReference"])
    created = walk_guided(root, draft, stop="connection-ready")
    connection_name = connect.values(created["state"], "m365")["Connection name"]
    before = (root / connect.CONFIG_PATH).read_bytes()
    for wrong_id in (None, "ServiceNowDifferent"):
        with pytest.raises(contracts.KnowledgeConnectError, match="connection name"):
            connect.confirm(
                root,
                "connection-ready",
                "confirmed",
                created["targetReference"],
                wrong_id,
            )
        assert (root / connect.CONFIG_PATH).read_bytes() == before
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(
            root,
            "test-article",
            "KB0000012",
            created["targetReference"],
            connection_name,
        )
    failed = connect.confirm(
        root,
        "connection-ready",
        "unverified",
        created["targetReference"],
        connection_name,
    )
    assert not failed["accepted"]
    assert failed["status"] == "blocked"
    assert failed["nextStep"]["id"] == "connection-ready"
    assert connect.values(failed["state"], "m365")["Connection name"] == connection_name
    assert connect.values(failed["state"], "servicenow") == connect.values(
        created["state"], "servicenow"
    )
    assert "Connection ready" not in connect.values(failed["state"], "m365")
    assert "connection-ready" not in failed["state"]["checkpoints"]
    assert not connect.values(failed["state"], "validation")
    recovered = verify_connection(root, begin(root, flow))
    assert recovered["nextStep"]["id"] == "test-article"
    assert walk_guided(root, recovered)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
@pytest.mark.parametrize("version", [1, 2])
def test_legacy_auth_and_ready_claims_cannot_bypass_post_create_verification(
    root, flow, version
):
    complete = walk_guided(root, begin(root, flow))
    legacy = complete["state"]
    if version == 1:
        legacy["schemaVersion"] = 1
        legacy.pop("checkpoints")
    else:
        legacy["checkpoints"].pop("connection-ready")
    save(root / connect.CONFIG_PATH, legacy)
    resumed = begin(root, flow)
    assert resumed["status"] == "in-progress"
    assert resumed["nextMilestone"] == "m365"
    assert resumed["nextStep"]["id"] == "connection-ready"
    assert resumed["state"]["evidence"] == legacy["evidence"]
    assert resumed["state"]["checkpoints"] == legacy.get("checkpoints", {})
    assert "connection-ready" not in resumed["state"]["checkpoints"]
    with pytest.raises(contracts.KnowledgeConnectError, match="post-Create"):
        connect.accept(root, acceptance(resumed["state"]))
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(
            root,
            "answer-citation",
            "confirmed",
            resumed["targetReference"],
            connect.values(resumed["state"], "m365")["Connection name"],
        )
    verified = verify_connection(root, resumed)
    assert verified["status"] == "guided-validated"
    assert connect.values(verified["state"], "validation") == connect.values(
        legacy, "validation"
    )


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_legacy_read_failure_retains_setup_provenance_without_retaining_read_pass(
    root, flow
):
    result = ready_admins(root, flow)
    source = result["state"]["evidence"]["servicenow"]
    failed = connect.confirm(
        root, "table-reads", "unverified", result["targetReference"]
    )
    assert not failed["accepted"]
    assert failed["nextStep"]["id"] == "table-reads"
    assert "Common table reads" not in connect.values(failed["state"], "servicenow")
    setup = failed["state"]["checkpoints"]["permission-setup"]
    assert setup["kind"] == source["kind"]
    assert setup["recordedAt"] == source["recordedAt"]
    assert setup["value"] == "confirmed"
    assert not connect.values(failed["state"], "m365")
    assert walk_guided(root, failed)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
@pytest.mark.parametrize(
    "stop", ["article-indexed", "allowed-indexed", "denied-indexed"]
)
def test_failed_index_checks_block_new_ess_steps_without_recreating_connection(
    root, flow, stop
):
    result = walk_guided(root, begin(root, flow), stop=stop)
    assert "source-attached" not in result["state"]["checkpoints"]
    failed = connect.confirm(
        root,
        stop,
        "unverified",
        result["targetReference"],
        connect.values(result["state"], "m365")["Connection name"],
    )
    assert not failed["accepted"]
    assert failed["nextStep"]["id"] == stop
    assert connect.values(failed["state"], "m365") == connect.values(
        result["state"], "m365"
    )
    before = (root / connect.CONFIG_PATH).read_bytes()
    for step in ("source-attached", "source-isolated", "answer-citation"):
        with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
            connect.confirm(
                root,
                step,
                "confirmed",
                failed["targetReference"],
                connect.values(failed["state"], "m365")["Connection name"],
            )
        assert (root / connect.CONFIG_PATH).read_bytes() == before
    assert walk_guided(root, failed)["status"] == "guided-validated"


@pytest.mark.parametrize("flow", ["simple", "advanced"])
@pytest.mark.parametrize(
    "stop", ["article-indexed", "allowed-native", "denied-indexed"]
)
def test_old_ess_first_progress_resumes_index_checks_without_rewriting_history(
    root, monkeypatch, flow, stop
):
    old_order = [
        "test-article",
        "test-kb",
        "source-attached",
        "article-indexed",
        "source-isolated",
        "allowed-native",
        "allowed-indexed",
        "denied-native",
        "denied-indexed",
        "answer-citation",
        "observation-time",
    ]

    def previous_steps(scope):
        steps = contracts.configuration_steps(scope)
        return [step for step in steps if step["owner"] != "validation"] + sorted(
            (step for step in steps if step["owner"] == "validation"),
            key=lambda step: old_order.index(step["id"]),
        )

    with monkeypatch.context() as legacy:
        legacy.setattr(connect, "configuration_steps", previous_steps)
        partial = walk_guided(root, begin(root, flow), stop=stop)
    resumed = begin(root, flow)
    assert resumed["nextStep"]["id"] == stop
    assert resumed["status"] == "in-progress"
    assert resumed["state"]["evidence"] == partial["state"]["evidence"]
    assert resumed["state"]["checkpoints"] == partial["state"]["checkpoints"]
    before = (root / connect.CONFIG_PATH).read_bytes()
    with pytest.raises(contracts.KnowledgeConnectError, match="preceding"):
        connect.confirm(
            root,
            "answer-citation",
            "confirmed",
            resumed["targetReference"],
            connect.values(resumed["state"], "m365")["Connection name"],
        )
    assert (root / connect.CONFIG_PATH).read_bytes() == before
    finished = walk_guided(root, resumed)
    assert finished["status"] == "guided-validated"
    for step in ("source-attached", "source-isolated"):
        if step in partial["state"]["checkpoints"]:
            assert (
                finished["state"]["checkpoints"][step]
                == (partial["state"]["checkpoints"][step])
            )


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_guided_confirmation_rejects_skips_wrong_flow_and_stale_scope(root, flow):
    result = begin(root, flow)
    before = (root / connect.CONFIG_PATH).read_bytes()
    for step, reference in (
        ("connection-name", result["targetReference"]),
        ("scope-assessment", "stale"),
        (
            "advanced-api" if flow == "simple" else "simple-reads",
            result["targetReference"],
        ),
    ):
        with pytest.raises(contracts.KnowledgeConnectError):
            connect.confirm(root, step, "confirmed", reference)
        assert (root / connect.CONFIG_PATH).read_bytes() == before


def test_invalid_direct_answer_clears_old_completion_and_dependent_steps(root):
    complete = walk_guided(root, begin(root))
    rejected = connect.confirm(root, "connection-name", "", complete["targetReference"])
    assert not rejected["accepted"]
    assert rejected["status"] == "blocked"
    assert rejected["nextStep"]["id"] == "connection-name"
    assert not connect.values(rejected["state"], "validation")
    assert "Connection ready" not in connect.values(rejected["state"], "m365")
    assert connect.values(rejected["state"], "servicenow") == connect.values(
        complete["state"], "servicenow"
    )
    fixed = walk_guided(root, rejected)
    assert fixed["status"] == "guided-validated"


def test_failed_reader_case_preserves_earlier_observations_for_targeted_retry(root):
    complete = walk_guided(root, begin(root))
    rejected = connect.confirm(
        root,
        "denied-indexed",
        "allowed",
        complete["targetReference"],
        connect.values(complete["state"], "m365")["Connection name"],
    )
    assert rejected["nextStep"]["id"] == "denied-indexed"
    assert not connect.values(rejected["state"], "validation")
    assert (
        rejected["state"]["checkpoints"]["allowed-native"]
        == complete["state"]["checkpoints"]["allowed-native"]
    )
    assert "answer-citation" not in rejected["state"]["checkpoints"]
    assert walk_guided(root, rejected)["status"] == "guided-validated"


def test_version_one_resume_migrates_without_fabricating_admin_subchecks(root):
    result = ready_admins(root)
    complete = connect.accept(root, acceptance(result["state"]))
    legacy = complete["state"]
    legacy["schemaVersion"] = 1
    legacy.pop("checkpoints")
    save(root / connect.CONFIG_PATH, legacy)
    resumed = begin(root)
    assert resumed["state"]["schemaVersion"] == 2
    assert resumed["state"]["checkpoints"] == {}
    assert resumed["state"]["evidence"] == legacy["evidence"]
    assert resumed["status"] == "in-progress"
    assert resumed["nextStep"]["id"] == "connection-ready"
    resumed = verify_connection(root, resumed)
    assert resumed["status"] == "guided-validated"
    rejected = connect.confirm(
        root,
        "denied-indexed",
        "allowed",
        resumed["targetReference"],
        connect.values(resumed["state"], "m365")["Connection name"],
    )
    assert not rejected["accepted"]
    assert rejected["nextStep"]["id"] == "denied-indexed"
    assert walk_guided(root, rejected)["status"] == "guided-validated"


def test_source_identity_change_invalidates_partial_and_downstream_configuration(root):
    complete = walk_guided(root, begin(root))
    changed = connect.confirm(
        root, "service-principal", TENANT, complete["targetReference"]
    )
    assert changed["nextStep"]["id"] == "oidc-provider"
    assert changed["state"]["checkpoints"] == {}
    assert not connect.values(changed["state"], "m365")
    assert not connect.values(changed["state"], "validation")
    assert "Federated Auth" not in connect.values(changed["state"], "servicenow")


def test_query_change_does_not_reuse_partial_scoped_observations(root):
    partial = walk_guided(root, begin(root), stop="integration-user")
    assert partial["state"]["checkpoints"]
    changed = begin(root, query="active=true^workflow_state=published")
    assert changed["state"]["checkpoints"] == {}
    assert changed["nextStep"]["id"] == "scope-assessment"


@pytest.mark.parametrize(
    "step,value",
    [
        ("hr-reads", "unverified"),
        ("test-kb", "b" * 32),
        ("observation-time", "2099-01-01T00:00:00Z"),
    ],
)
def test_required_applicability_and_acceptance_context_cannot_be_skipped(
    root, step, value
):
    result = walk_guided(root, begin(root), stop=step)
    rejected = connect.confirm(
        root,
        step,
        value,
        result["targetReference"],
        connect.values(result["state"], "m365").get("Connection name"),
    )
    assert rejected["status"] == "blocked"
    assert rejected["nextStep"]["id"] == step
    assert not connect.values(rejected["state"], "validation")


def test_cli_records_an_observation_without_a_handoff_file(root, capsys):
    result = begin(root)
    assert (
        connect.main(
            [
                "--root",
                str(root),
                "confirm",
                "--step",
                "scope-assessment",
                "--value",
                "confirmed",
                "--target-reference",
                result["targetReference"],
            ]
        )
        == 0
    )
    assert '"id": "service-principal"' in capsys.readouterr().out


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_scope_confirmation_automatically_records_utc_date_and_skips_question(
    root, monkeypatch, flow
):
    result = begin(root, flow)
    stamp = "2026-01-04T00:05:00Z"
    monkeypatch.setattr(connect, "now", lambda: stamp)
    confirmed = connect.confirm(
        root, "scope-assessment", "confirmed", result["targetReference"]
    )
    source = confirmed["state"]["evidence"]["servicenow"]
    assert source["recordedAt"] == stamp
    assert source["values"]["Assessment date"] == "2026-01-04"
    assert confirmed["nextStep"]["id"] == "service-principal"
    monkeypatch.setattr(connect, "now", lambda: "2026-01-05T00:05:00Z")
    repeated = connect.confirm(
        root, "scope-assessment", "confirmed", confirmed["targetReference"]
    )
    assert connect.values(repeated["state"], "servicenow")["Assessment date"] == (
        "2026-01-04"
    )


def test_scope_confirmation_preserves_legacy_historical_date_and_acceptance(root):
    ready_admins(root)
    submit(root, "servicenow", **{"Assessment date": "2020-12-31"})
    ready = verify_connection(root, submit(root, "m365"))
    complete = connect.accept(root, acceptance(ready["state"]))
    legacy = complete["state"]
    legacy["schemaVersion"] = 1
    legacy.pop("checkpoints")
    save(root / connect.CONFIG_PATH, legacy)
    reconfirmed = connect.confirm(
        root, "scope-assessment", "confirmed", complete["targetReference"]
    )
    assert connect.values(reconfirmed["state"], "servicenow")["Assessment date"] == (
        "2020-12-31"
    )
    for owner in ("m365", "validation"):
        assert reconfirmed["state"]["evidence"][owner] == legacy["evidence"][owner]
    assert reconfirmed["status"] == "in-progress"
    assert reconfirmed["nextStep"]["id"] == "connection-ready"
    assert verify_connection(root, reconfirmed)["status"] == "guided-validated"


def test_failed_scope_assessment_does_not_automatically_record_a_date(root):
    result = begin(root)
    failed = connect.confirm(
        root, "scope-assessment", "unverified", result["targetReference"]
    )
    assert failed["status"] == "blocked"
    assert "Assessment date" not in connect.values(failed["state"], "servicenow")


def test_reconfirming_scope_resolves_a_missing_legacy_date_blocker(root):
    begin(root)
    missing = submit(root, "servicenow", **{"Assessment date": ""})
    assert missing["nextStep"]["id"] == "assessment-date"
    fixed = connect.confirm(
        root, "scope-assessment", "confirmed", missing["targetReference"]
    )
    assert fixed["status"] == "in-progress"
    assert fixed["nextStep"]["id"] == "connector-config"
    assert fixed["state"]["issues"] == {}


def test_changing_legacy_test_article_clears_old_acceptance_and_reader_cases(root):
    result = ready_admins(root)
    complete = connect.accept(root, acceptance(result["state"]))
    changed = connect.confirm(
        root,
        "test-article",
        "KB0000030",
        complete["targetReference"],
        connect.values(complete["state"], "m365")["Connection name"],
    )
    assert not connect.values(changed["state"], "validation")
    assert changed["nextStep"]["id"] == "test-kb"
    assert changed["state"]["checkpoints"]["test-article"]["value"] == "KB0000030"


def test_reader_confirmation_rejects_missing_or_wrong_connection_without_writing(root):
    result = walk_guided(root, begin(root), stop="test-article")
    before = (root / connect.CONFIG_PATH).read_bytes()
    for connection_name in (None, "ServiceNowDifferent"):
        with pytest.raises(contracts.KnowledgeConnectError, match="connection name"):
            connect.confirm(
                root,
                "test-article",
                "KB0000012",
                result["targetReference"],
                connection_name,
            )
        assert (root / connect.CONFIG_PATH).read_bytes() == before


def test_malformed_checkpoint_cannot_contradict_completed_reader_acceptance(root):
    complete = walk_guided(root, begin(root))
    malformed = complete["state"]
    malformed["checkpoints"]["test-article"]["value"] = "KB0000030"
    with pytest.raises(contracts.KnowledgeConnectError, match="contradicts"):
        connect.validate_state(malformed)


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_new_and_reused_flow_complete_only_after_exact_reader_tests(root, flow):
    result = ready_admins(root, flow)
    assert result["status"] == "in-progress"
    assert result["nextMilestone"] == "validation"
    validated = connect.accept(root, acceptance(result["state"]))
    assert validated["status"] == "guided-validated"
    assert connect.values(validated["state"], "validation")
    assert validated["state"]["evidence"]["validation"]["kind"] == "maker-tested"
    resumed = begin(root, flow)
    assert resumed["status"] == "guided-validated"
    assert resumed["state"]["evidence"] == validated["state"]["evidence"]


def test_missing_answers_preserve_valid_siblings_and_skip_them_on_resume(root):
    begin(root)
    partial = submit(
        root, "servicenow", **{"Federated Auth": "", "Common table reads": "unverified"}
    )
    assert partial["accepted"] is False
    assert set(partial["fieldErrors"]) == {"Federated Auth", "Common table reads"}
    assert "Identity mapping" in connect.values(partial["state"], "servicenow")
    correction = root / "correction.xlsx"
    connect.handoff(root, "servicenow", correction)
    answers = contracts.read_handoff(
        correction, "servicenow", partial["state"]["scope"]
    )
    assert answers["Identity mapping"] == "confirmed"
    assert answers["Federated Auth"] == ""
    assert submit(root, "servicenow")["accepted"]


@pytest.mark.parametrize("flow", ["simple", "advanced"])
def test_cli_start_without_hrsd_question_requires_administrator_review(root, flow):
    assert (
        connect.main(
            [
                "--root",
                str(root),
                "start",
                "--instance",
                INSTANCE,
                "--query",
                QUERY,
                "--flow",
                flow,
            ]
        )
        == 0
    )
    state = connect.read_json(root / connect.CONFIG_PATH)
    assert state["scope"]["hrContent"] is None
    workbook = root / "unassessed-hr.xlsx"
    connect.handoff(root, "servicenow", workbook)
    with ZipFile(workbook) as archive:
        worksheet = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
    assert "Administrator assessment" in worksheet
    assert (
        contracts.read_handoff(workbook, "servicenow", state["scope"])[
            "HR scoped reads"
        ]
        == ""
    )
    partial = submit(root, "servicenow", **{"HR scoped reads": ""})
    assert partial["accepted"] is False
    assert "HR scoped reads" in partial["missingFields"]
    with pytest.raises(contracts.KnowledgeConnectError, match="ServiceNow"):
        connect.handoff(root, "m365", root / "premature-m365.xlsx")


@pytest.mark.parametrize("hr_answer", ["confirmed", "not-applicable"])
def test_administrator_can_resolve_unassessed_hrsd_without_maker_question(
    root, hr_answer
):
    connect.start(root, instance=INSTANCE, query=QUERY, flow="simple")
    assert submit(root, "servicenow", **{"HR scoped reads": hr_answer})["accepted"]
    state = verify_connection(root, submit(root, "m365"))["state"]
    assert connect.accept(root, acceptance(state))["status"] == "guided-validated"


@pytest.mark.parametrize("hr_content", [True, False])
def test_omitting_hrsd_on_resume_preserves_previous_classification_and_acceptance(
    root, hr_content
):
    begin(root, hr_content=hr_content)
    submit(root, "servicenow")
    state = verify_connection(root, submit(root, "m365"))["state"]
    connect.accept(root, acceptance(state))
    before = connect.read_json(root / connect.CONFIG_PATH)
    assert (
        connect.main(
            [
                "--root",
                str(root),
                "start",
                "--instance",
                INSTANCE,
                "--query",
                QUERY,
                "--flow",
                "simple",
            ]
        )
        == 0
    )
    after = connect.read_json(root / connect.CONFIG_PATH)
    assert after["scope"] == before["scope"]
    assert after["evidence"] == before["evidence"]
    assert after["issues"] == before["issues"]


def test_omitted_hrsd_does_not_reuse_classification_after_content_scope_change(root):
    ready_admins(root)
    changed = connect.start(
        root,
        instance=INSTANCE,
        query="active=true^workflow_state=published",
        flow="simple",
    )
    assert changed["state"]["scope"]["hrContent"] is None
    assert "HR scoped reads" in changed["missingFields"]
    assert not connect.values(changed["state"], "m365")


def test_previously_known_hrsd_scope_still_requires_applicable_reads(root):
    begin(root, hr_content=True)
    resumed = connect.start(root, instance=INSTANCE, query=QUERY, flow="simple")
    assert resumed["state"]["scope"]["hrContent"] is True
    rejected = submit(root, "servicenow", **{"HR scoped reads": "not-applicable"})
    assert not rejected["accepted"]
    assert "HR scoped reads" in rejected["fieldErrors"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("Service principal object ID", contracts.CONNECTOR_APP_ID),
        ("Service principal object ID", "not-a-guid"),
        ("Federated Auth", "client_secret=private-value"),
        ("Federated Auth", "eyJheader.eyJpayload.signature"),
        ("Assessment date", "9999-01-01"),
        ("Advanced namespace", "/api/123/user_criteria_v2"),
        ("HR scoped reads", "not-applicable"),
    ],
)
def test_bad_admin_answers_remain_blocked_without_retaining_values(root, field, value):
    begin(root, "advanced", hr_content=True)
    result = submit(root, "servicenow", **{field: value})
    assert not result["accepted"]
    assert field in result["fieldErrors"]
    assert field not in connect.values(result["state"], "servicenow")
    if "secret" in value or "eyJ" in value:
        assert value not in (root / connect.CONFIG_PATH).read_text(encoding="utf-8")
        assert value not in json.dumps(result)


def test_cannot_skip_servicenow_or_complete_on_ready_connection(root):
    begin(root)
    with pytest.raises(contracts.KnowledgeConnectError, match="ServiceNow"):
        connect.handoff(root, "m365", root / "m365.xlsx")
    with pytest.raises(contracts.KnowledgeConnectError, match="administrator"):
        connect.accept(root, {})
    result = ready_admins(root)
    assert result["nextMilestone"] == "validation"
    assert result["status"] != "guided-validated"


@pytest.mark.parametrize(
    "field,value",
    [
        ("targetReference", "different"),
        ("connectionName", "OtherConnection"),
        ("knowledgeBaseId", "b" * 32),
        ("deniedIndexed", "failed"),
        ("allowedNative", "unverified"),
        ("answerWithCitation", "not-tested"),
        ("exactSourceIsolated", "unverified"),
        ("observedAt", "2026-01-01"),
    ],
)
def test_failed_or_mismatched_acceptance_revokes_previous_completion(
    root, field, value
):
    state = ready_admins(root)["state"]
    evidence = acceptance(state)
    assert connect.accept(root, evidence)["status"] == "guided-validated"
    evidence[field] = value
    rejected = connect.accept(root, evidence)
    assert rejected["status"] == "blocked"
    assert not connect.values(rejected["state"], "validation")
    assert connect.main(["--root", str(root), "status"]) == 1


def test_changing_flow_keeps_only_healthy_shared_prerequisites(root):
    result = ready_admins(root)
    old_path = root / "servicenow-return.xlsx"
    changed = begin(root, "advanced")
    kept = connect.values(changed["state"], "servicenow")
    assert kept["Federated Auth"] == "confirmed"
    assert "Simple attribute reads" not in kept
    assert "Scope assessment" not in kept
    assert not connect.values(changed["state"], "m365")
    with pytest.raises(contracts.KnowledgeConnectError, match="different|unsupported"):
        connect.import_handoff(root, "servicenow", old_path)
    assert result["targetReference"] != changed["targetReference"]


def test_scope_and_instance_changes_invalidate_dependencies(root):
    ready_admins(root)
    changed = begin(root, query="active=true^workflow_state=published")
    assert "Scope assessment" not in connect.values(changed["state"], "servicenow")
    assert not connect.values(changed["state"], "m365")
    reset = begin(root, instance="https://other.example.com")
    assert reset["state"]["evidence"] == {}


def test_reopen_clears_only_affected_owner_and_downstream(root):
    state = ready_admins(root)["state"]
    connect.accept(root, acceptance(state))
    reopened = connect.reopen(root, "m365", "Connection ready")
    assert connect.values(reopened["state"], "servicenow") == connect.values(
        state, "servicenow"
    )
    assert "Connection name" in connect.values(reopened["state"], "m365")
    assert "Connection ready" not in connect.values(reopened["state"], "m365")
    assert not connect.values(reopened["state"], "validation")
    assert submit(root, "m365")["accepted"]


@pytest.mark.parametrize("realm", ["Test", "Prod", "Production", ""])
def test_non_dev_or_unknown_realm_refuses_before_progress_write(root, realm):
    path = root / ".local" / "setup" / "config.json"
    setup = connect.read_json(path)
    setup["agents"][BOT]["agent"]["realm"] = realm
    save(path, setup)
    with pytest.raises(contracts.KnowledgeConnectError, match="Development"):
        begin(root)
    assert not (root / connect.CONFIG_PATH).exists()


def test_selected_agent_is_explicit_and_ambiguity_cannot_borrow_identity(root):
    path = root / ".local" / "config.json"
    config = connect.read_json(path)
    config["agents"].append(config["agents"][0])
    save(path, config)
    with pytest.raises(contracts.KnowledgeConnectError, match="Select a native"):
        begin(root)
    assert not (root / connect.CONFIG_PATH).exists()


def test_it_supported_without_runtime_ready_marker(root):
    local = root / ".local" / "config.json"
    config = connect.read_json(local)
    config["agents"][0]["schemaName"] = "gptagent_copilotforemployeeselfserviceit"
    save(local, config)
    canonical = root / ".local" / "setup" / "config.json"
    setup = connect.read_json(canonical)
    setup["agents"][BOT]["agent"]["schema_name"] = config["agents"][0]["schemaName"]
    save(canonical, setup)
    assert begin(root)["state"]["scope"]["target"]["schemaName"].endswith("it")


@pytest.mark.parametrize(
    "query",
    [
        "active=true^NQworkflow_state=published",
        "active=true^workflow_state=published^kb_knowledge_base=javascript:danger()",
        "active=false^workflow_state=published",
    ],
)
def test_unsupported_or_broadened_queries_are_not_silently_rewritten(root, query):
    with pytest.raises(contracts.KnowledgeConnectError, match="Content query"):
        begin(root, query=query)
    assert not (root / connect.CONFIG_PATH).exists()


def test_unknown_flow_and_wrong_environment_refuse_before_write(root):
    with pytest.raises(contracts.KnowledgeConnectError, match="explicit"):
        begin(root, "unknown")
    local = root / ".local" / "config.json"
    config = connect.read_json(local)
    config["environmentId"] = BOT
    save(local, config)
    with pytest.raises(contracts.KnowledgeConnectError, match="environments differ"):
        begin(root)
    assert not (root / connect.CONFIG_PATH).exists()


def test_target_change_revalidates_without_redoing_source_setup(root):
    state = ready_admins(root)["state"]
    connect.accept(root, acceptance(state))
    setup_path = root / ".local" / "setup" / "config.json"
    setup = connect.read_json(setup_path)
    setup["environment"]["id"] = BOT
    save(setup_path, setup)
    config_path = root / ".local" / "config.json"
    config = connect.read_json(config_path)
    config["environmentId"] = BOT
    save(config_path, config)
    with pytest.raises(contracts.KnowledgeConnectError, match="target changed"):
        connect.accept(root, acceptance(state))
    resumed = begin(root)
    assert connect.values(resumed["state"], "servicenow") == connect.values(
        state, "servicenow"
    )
    assert connect.values(resumed["state"], "m365") == connect.values(state, "m365")
    assert not connect.values(resumed["state"], "validation")


def rewrite_worksheet(path, mutation):
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    name = "xl/worksheets/sheet2.xml"
    sheet = ET.fromstring(members[name])
    mutation(sheet)
    members[name] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for member, contents in members.items():
            archive.writestr(member, contents)


@pytest.mark.parametrize(
    "malformation", ["formula", "duplicate", "unknown", "missing", "wrong-context"]
)
def test_real_excel_import_rejects_tampered_structure_before_accepting_evidence(
    root, malformation
):
    state = begin(root)["state"]
    path = root / "tampered.xlsx"
    contracts.write_handoff(
        path,
        "servicenow",
        state["scope"],
        administrator_answers("servicenow", state["scope"]),
    )
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

    def mutate(sheet):
        rows = sheet.findall(f".//{namespace}row")
        if malformation == "formula":
            cell = rows[-1].findall(f"{namespace}c")[-1]
            ET.SubElement(cell, f"{namespace}f").text = "1+1"
        elif malformation in {"duplicate", "unknown"}:
            label = rows[-1].find(f".//{namespace}t")
            label.text = (
                "Target reference"
                if malformation == "duplicate"
                else "Unexpected field"
            )
        elif malformation == "missing":
            sheet.find(f"{namespace}sheetData").remove(rows[-1])
        else:
            rows[1].findall(f"{namespace}c")[-1].find(
                f".//{namespace}t"
            ).text = "different"

    rewrite_worksheet(path, mutate)
    with pytest.raises((contracts.KnowledgeConnectError, WorkdayConnectWorkbookError)):
        connect.import_handoff(root, "servicenow", path)
    assert connect.read_json(root / connect.CONFIG_PATH)["evidence"] == {}


def test_atomic_failure_preserves_previous_state_and_lock_cleanup(root, monkeypatch):
    begin(root)
    before = (root / connect.CONFIG_PATH).read_bytes()

    def fail_replace(*_args):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(connect.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace"):
        begin(root, instance="https://other.example.com")
    assert (root / connect.CONFIG_PATH).read_bytes() == before
    assert not (root / connect.CONFIG_PATH).with_suffix(".lock").exists()
    assert not list((root / connect.CONFIG_PATH).parent.glob("*.tmp"))


def test_concurrent_operation_refuses_without_deleting_owners_lock(root):
    begin(root)
    with connect.transaction(root):
        with pytest.raises(
            contracts.KnowledgeConnectError, match="owns the progress lock"
        ):
            begin(root)
        assert (root / connect.CONFIG_PATH).with_suffix(".lock").exists()


def test_output_workbook_is_not_overwritten(root):
    begin(root)
    path = root / "admin.xlsx"
    connect.handoff(root, "servicenow", path)
    before = path.read_bytes()
    with pytest.raises(contracts.KnowledgeConnectError, match="already exists"):
        connect.handoff(root, "servicenow", path)
    assert path.read_bytes() == before


def test_future_acceptance_and_extra_secret_fields_are_rejected(root):
    state = ready_admins(root)["state"]
    evidence = acceptance(state)
    evidence["observedAt"] = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat()
    assert connect.accept(root, evidence)["status"] == "blocked"
    evidence = acceptance(state)
    evidence["access_token"] = "private-value"
    rejected = connect.accept(root, evidence)
    assert rejected["status"] == "blocked"
    assert "private-value" not in json.dumps(rejected)


def test_malformed_persisted_schema_does_not_reset_or_pass(root):
    begin(root)
    path = root / connect.CONFIG_PATH
    malformed = connect.read_json(path)
    malformed["schemaVersion"] = 999
    save(path, malformed)
    before = path.read_bytes()
    assert connect.main(["--root", str(root), "status"]) == 1
    with pytest.raises(contracts.KnowledgeConnectError, match="schema"):
        begin(root)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "workspace_change",
    [
        {"agent_path": ".."},
        {"agent_path": "missing.mcs.yml"},
        {"folder": ".."},
    ],
)
def test_canonical_workspace_paths_fail_closed(root, workspace_change):
    path = root / ".local" / "setup" / "config.json"
    setup = connect.read_json(path)
    setup["agents"][BOT]["workspace"].update(workspace_change)
    save(path, setup)
    with pytest.raises(contracts.KnowledgeConnectError, match="canonical workspace"):
        begin(root)
    assert not (root / connect.CONFIG_PATH).exists()


def test_malformed_target_and_workspace_step_emit_explicit_errors(root, capsys):
    config_path = root / ".local" / "config.json"
    config = connect.read_json(config_path)
    schema = config["agents"][0]["schemaName"]
    config["agents"][0]["schemaName"] = []
    save(config_path, config)
    assert connect.main(["--root", str(root), "preflight"]) == 1
    assert "SERVICENOW_KB_ERROR_JSON" in capsys.readouterr().out
    config["agents"][0]["schemaName"] = schema
    save(config_path, config)
    path = root / ".local" / "setup" / "config.json"
    setup = connect.read_json(path)
    setup["agents"][BOT]["steps"]["SETUP-07"] = "done"
    save(path, setup)
    assert connect.main(["--root", str(root), "preflight"]) == 1
    assert "SERVICENOW_KB_ERROR_JSON" in capsys.readouterr().out
