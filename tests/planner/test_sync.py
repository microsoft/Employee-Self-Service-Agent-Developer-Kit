# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.sync — the pure mapping seam between the local plan
document and the planner service wire shape.

Pure logic (no network, no file IO except the CLI round-trip on a temp plan), so
exempt from the FlightCheck cassette policy per tests/AGENTS.md.
"""

from __future__ import annotations

import json

import pytest

from planner import cli, sync
from planner.plan_model import (
    ACCEPTANCE_GROUP,
    STREAM_GROUP,
    Plan,
    new_task,
    principal_person,
    principal_pool,
)

HR_AGENT = "EmployeeSelfServiceHRDA"
PAUL = "00000000-0000-0000-0000-0000000000b1"


def _run(*argv: str) -> int:
    return cli.main(list(argv))


def _plan() -> Plan:
    plan = Plan.new(objective="Stand up ESS on Workday")
    plan.set_configuring_agent_name(HR_AGENT)
    plan.set_context("acceptance.1", "Employees can file PTO", group=ACCEPTANCE_GROUP)
    plan.set_context("system.hr", "Workday", group="system")
    plan.add_task(
        new_task(
            "t1",
            "Configure Workday",
            description="Wire the Workday connection",
            assigned_to=principal_pool("WorkdayAdmin"),
            produces=["workdayConnection"],
        )
    )
    plan.add_task(
        new_task("t2", "Owned task", assigned_to=principal_person(PAUL, "ServiceNowAdmin"))
    )
    return plan


# --------------------------------------------------------------------------- #
# Export — local plan -> service create body
# --------------------------------------------------------------------------- #

def test_export_requires_agent_name():
    plan = Plan.new(objective="x")  # no configuringAgentName set
    with pytest.raises(ValueError, match="configuringAgentName is required"):
        sync.to_remote_plan_body(plan)


def test_export_rejects_invalid_agent_name():
    plan = Plan.new(objective="x")
    with pytest.raises(ValueError, match="invalid configuringAgentName"):
        sync.to_remote_plan_body(plan, configuring_agent_name="NotAnAgent")


def test_export_agent_name_arg_overrides_stored():
    plan = _plan()
    body = sync.to_remote_plan_body(plan, configuring_agent_name="EmployeeSelfServiceITDA")
    assert body["configuringAgentName"] == "EmployeeSelfServiceITDA"


def test_export_emits_only_allowed_top_level_fields():
    body = sync.to_remote_plan_body(_plan())
    assert set(body) <= {"configuringAgentName", "acceptanceCriteria", "context", "tasks"}
    assert body["configuringAgentName"] == HR_AGENT


def test_export_promotes_acceptance_criteria_out_of_context():
    body = sync.to_remote_plan_body(_plan())
    assert body["acceptanceCriteria"] == ["Employees can file PTO"]
    groups = {entry.get("group") for entry in body["context"]}
    assert ACCEPTANCE_GROUP not in groups
    # The acceptance entry is not double-counted in context.
    assert all(entry["key"] != "acceptance.1" for entry in body["context"])


def test_export_context_drops_provenance_keeps_shape():
    body = sync.to_remote_plan_body(_plan())
    system = next(e for e in body["context"] if e["key"] == "system.hr")
    assert system == {"key": "system.hr", "value": "Workday", "group": "system"}
    assert "provenance" not in system


def test_export_task_body_omits_local_only_fields():
    task = _plan().tasks[0]
    body = sync.to_remote_task_body(task)
    for forbidden in ("id", "state", "checklist", "remoteId", "etag", "assignedTo"):
        assert forbidden not in body
    assert body["title"] == "Configure Workday"
    assert body["description"] == "Wire the Workday connection"
    assert body["produces"] == ["workdayConnection"]


def test_export_assignee_pool():
    body = sync.to_remote_task_body(
        new_task("x", "t", assigned_to=principal_pool("WorkdayAdmin"))
    )
    assert body["assignedToType"] == "Role"
    # Exported as the backend wire display name so it matches the attestation grant.
    assert body["assignedToId"] == "Workday administrator"
    assert body["assignedToRoleId"] == "Workday administrator"


def test_export_assignee_person_for_role():
    body = sync.to_remote_task_body(
        new_task("x", "t", assigned_to=principal_person(PAUL, "ServiceNowAdmin"))
    )
    assert body["assignedToId"] == PAUL
    # The grounding role rides along as the wire display name too, for parity.
    assert body["assignedToRoleId"] == "ServiceNow Administrator"
    # A person owner leaves assignedToType implicit (defaults to User server-side).
    assert "assignedToType" not in body


def test_export_assignee_pool_canonicalizes_compact_to_wire():
    # The live defect: a pooled task stored with the compact id must go out as the
    # wire display name, or the service's caller-expansion never matches the grant.
    body = sync.to_remote_task_body(
        new_task("x", "t", assigned_to=principal_pool("EntraPowerPlatformAdministrator"))
    )
    assert body["assignedToId"] == "Power Platform Administrator"
    assert body["assignedToRoleId"] == "Power Platform Administrator"


def test_export_assignee_pool_passes_non_attestable_role_through():
    # A role outside the closed attestable set can't be canonicalized; keep it
    # verbatim rather than silently dropping the maker's intent.
    body = sync.to_remote_task_body(
        new_task("x", "t", assigned_to=principal_pool("SomeFutureRole"))
    )
    assert body["assignedToId"] == "SomeFutureRole"
    assert body["assignedToRoleId"] == "SomeFutureRole"


def test_export_assignee_plain_person():
    body = sync.to_remote_task_body(new_task("x", "t", assigned_to=principal_person(PAUL)))
    assert body["assignedToId"] == PAUL
    assert "assignedToRoleId" not in body
    assert "assignedToType" not in body


def test_export_unassigned_emits_no_assignee():
    body = sync.to_remote_task_body(new_task("x", "t"))
    assert not any(k.startswith("assignedTo") for k in body)


def test_export_omits_empty_optionals():
    plan = Plan.new()
    plan.set_configuring_agent_name(HR_AGENT)
    body = sync.to_remote_plan_body(plan)
    assert body == {"configuringAgentName": HR_AGENT}


# --------------------------------------------------------------------------- #
# Vocabulary bridges
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "local,remote",
    [("NotStarted", "NotStarted"), ("InProgress", "InProgress"),
     ("Completed", "Completed"), ("Blocked", "Cancelled")],
)
def test_local_to_remote_state(local, remote):
    assert sync.local_to_remote_state(local) == remote


@pytest.mark.parametrize(
    "raw,expected",
    [("Cancelled", "Blocked"), ("cancelled", "Blocked"), ("InProgress", "InProgress"),
     (3, "Blocked"), (0, "NotStarted"), (2, "Completed"),
     ("garbage", "garbage"), (None, "NotStarted"), (True, "NotStarted")],
)
def test_remote_task_state(raw, expected):
    assert sync.remote_task_state(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("Active", "Active"), ("active", "Active"), (0, "Draft"), (3, "Archived"),
     (None, "Draft"), ("weird", "weird")],
)
def test_remote_plan_status(raw, expected):
    assert sync.remote_plan_status(raw) == expected


# --------------------------------------------------------------------------- #
# Import — service entities -> local plan document
# --------------------------------------------------------------------------- #

def _remote_plan(**over):
    entity = {
        "planId": "plan-1",
        "projectId": "proj-1",
        "configuringAgentName": HR_AGENT,
        "status": "Active",
        "acceptanceCriteria": ["File PTO", "Reset password"],
        "context": [{"key": "system.hr", "value": "Workday", "group": "system"}],
        "outputs": [],
        "etag": "W/1",
    }
    entity.update(over)
    return entity


def _remote_tasks():
    return {
        "value": [
            {
                "taskId": "rt-1",
                "title": "Configure Workday",
                "description": "do it",
                "state": "InProgress",
                "assignedTo": {"type": "Role", "id": "WorkdayAdmin"},
                "assignedToRoleId": "WorkdayAdmin",
                "produces": ["workdayConnection"],
                "etag": "W/task-1",
            },
            {
                "taskId": "rt-2",
                "title": "Blocked one",
                "state": "Cancelled",
                "assignedTo": {"type": "User", "id": PAUL},
                "assignedToRoleId": "ServiceNowAdmin",
            },
        ]
    }


def test_hydrate_basic_fields():
    data = sync.hydrate_from_remote(_remote_plan(), _remote_tasks())
    assert data["planId"] == "plan-1"
    assert data["projectId"] == "proj-1"
    assert data["configuringAgentName"] == HR_AGENT
    assert data["status"] == "Active"
    assert data["etag"] == "W/1"
    assert data["syncedAt"]  # stamped


def test_hydrate_is_case_insensitive():
    entity = {
        "PlanId": "p", "ProjectId": "pr", "ConfiguringAgentName": HR_AGENT,
        "Status": "Draft", "ETag": "W/9",
    }
    data = sync.hydrate_from_remote(entity, {"value": []})
    assert data["planId"] == "p"
    assert data["projectId"] == "pr"
    assert data["etag"] == "W/9"


def test_hydrate_task_state_bridge_and_ids():
    data = sync.hydrate_from_remote(_remote_plan(), _remote_tasks())
    by_id = {t["id"]: t for t in data["tasks"]}
    assert by_id["rt-1"]["state"] == "InProgress"
    assert by_id["rt-1"]["remoteId"] == "rt-1"
    assert by_id["rt-1"]["etag"] == "W/task-1"
    # Cancelled bridges to the local Blocked vocabulary.
    assert by_id["rt-2"]["state"] == "Blocked"


def test_hydrate_reconstructs_principals():
    data = sync.hydrate_from_remote(_remote_plan(), _remote_tasks())
    by_id = {t["id"]: t for t in data["tasks"]}
    pool = by_id["rt-1"]["assignedTo"]
    assert pool["type"] == "Role" and pool["role"]["roleId"] == "WorkdayAdmin"
    owner = by_id["rt-2"]["assignedTo"]
    assert owner["type"] == "User" and owner["user"]["oid"] == PAUL
    assert owner["role"]["roleId"] == "ServiceNowAdmin"


def test_hydrate_pool_from_flat_fields_only():
    # No expanded principal, only the flat role id -> still an open pool.
    tasks = [{"taskId": "rt-9", "title": "t", "assignedToRoleId": "WorkdayAdmin"}]
    data = sync.hydrate_from_remote(_remote_plan(), tasks)
    principal = data["tasks"][0]["assignedTo"]
    assert principal["type"] == "Role" and principal["role"]["roleId"] == "WorkdayAdmin"


def test_hydrate_pool_normalizes_wire_name_to_compact():
    # The service returns the wire display name; the local model keys roles by the
    # compact id (local matching is an exact string compare), so fold it home.
    tasks = [
        {
            "taskId": "rt-pp",
            "title": "t",
            "assignedTo": {"type": "Role", "id": "Power Platform Administrator"},
            "assignedToRoleId": "Power Platform Administrator",
        }
    ]
    data = sync.hydrate_from_remote(_remote_plan(), tasks)
    principal = data["tasks"][0]["assignedTo"]
    assert principal["type"] == "Role"
    assert principal["role"]["roleId"] == "EntraPowerPlatformAdministrator"


def test_role_pool_survives_export_import_round_trip_as_compact():
    # Local compact id -> export wire name -> import back to the same compact id,
    # so a published-and-rehydrated plan stays uniform for local role matching.
    body = sync.to_remote_task_body(
        new_task("rt", "t", assigned_to=principal_pool("EntraPowerPlatformAdministrator"))
    )
    assert body["assignedToId"] == "Power Platform Administrator"
    remote = {"taskId": "rt", "title": "t", **body}
    data = sync.hydrate_from_remote(_remote_plan(), [remote])
    principal = data["tasks"][0]["assignedTo"]
    assert principal["role"]["roleId"] == "EntraPowerPlatformAdministrator"


def test_hydrate_unassigned_task():
    tasks = [{"taskId": "rt-0", "title": "t"}]
    data = sync.hydrate_from_remote(_remote_plan(), tasks)
    assert data["tasks"][0]["assignedTo"] == {}


def test_hydrate_demotes_acceptance_into_context_group():
    data = sync.hydrate_from_remote(_remote_plan(), {"value": []})
    acceptance = [e for e in data["context"] if e.get("group") == ACCEPTANCE_GROUP]
    assert [e["value"] for e in acceptance] == ["File PTO", "Reset password"]
    keys = [e["key"] for e in acceptance]
    assert keys == ["acceptance.1", "acceptance.2"]  # unique + stable


def test_hydrate_outputs_list_to_dict():
    entity = _remote_plan(outputs=[{
        "key": "workdayConnection",
        "kind": "Connection",
        "producedByTaskId": "rt-1",
        "attributes": [{"key": "connectionId", "value": "abc", "description": "drop me"}],
        "state": "Active",
    }])
    data = sync.hydrate_from_remote(entity, _remote_tasks())
    output = data["outputs"][0]
    assert output["kind"] == "Connection"
    assert output["attributes"] == {"connectionId": "abc"}  # list flattened, description dropped


def test_hydrate_empty_collection_does_not_resurrect_embedded_tasks():
    # An explicit empty collection is the service authoritatively saying "no
    # tasks" — it must NOT fall back to the plan's embedded agentPlanTasks
    # expansion (only task_entities=None does that). Otherwise a task deleted
    # upstream would be resurrected on the next pull.
    entity = _remote_plan(agentPlanTasks=[{"taskId": "rt-stale", "title": "Stale"}])
    data = sync.hydrate_from_remote(entity, {"value": []})
    assert data["tasks"] == []


def test_hydrate_uses_embedded_tasks_when_no_collection_given():
    entity = _remote_plan(agentPlanTasks=[{"taskId": "rt-e", "title": "Embedded"}])
    data = sync.hydrate_from_remote(entity)  # task_entities omitted
    assert [t["id"] for t in data["tasks"]] == ["rt-e"]


def test_hydrate_result_is_valid():
    data = sync.hydrate_from_remote(_remote_plan(), _remote_tasks())
    assert Plan(data).validate() == []


def test_hydrate_rejects_non_dict_plan():
    with pytest.raises(ValueError, match="must be a service Plan object"):
        sync.hydrate_from_remote([1, 2, 3])


# --------------------------------------------------------------------------- #
# Round-trip + stamp
# --------------------------------------------------------------------------- #

def test_export_then_hydrate_preserves_core():
    plan = _plan()
    body = sync.to_remote_plan_body(plan)
    # Simulate the service echoing the create body back with server-assigned ids.
    echoed_tasks = []
    for index, task_body in enumerate(body["tasks"], start=1):
        echoed = dict(task_body)
        echoed["taskId"] = f"srv-{index}"
        echoed_tasks.append(echoed)
    plan_entity = {
        "planId": "srv-plan",
        "projectId": "srv-proj",
        "configuringAgentName": body["configuringAgentName"],
        "status": "Draft",
        "acceptanceCriteria": body["acceptanceCriteria"],
        "context": body["context"],
    }
    data = sync.hydrate_from_remote(plan_entity, {"value": echoed_tasks})

    assert data["configuringAgentName"] == HR_AGENT
    assert [t["title"] for t in data["tasks"]] == ["Configure Workday", "Owned task"]
    acceptance = [e["value"] for e in data["context"] if e.get("group") == ACCEPTANCE_GROUP]
    assert acceptance == ["Employees can file PTO"]
    pool = data["tasks"][0]["assignedTo"]
    assert pool["type"] == "Role" and pool["role"]["roleId"] == "WorkdayAdmin"
    owner = data["tasks"][1]["assignedTo"]
    assert owner["type"] == "User" and owner["user"]["oid"] == PAUL
    assert Plan(data).validate() == []


def _streamed_plan() -> Plan:
    plan = Plan.new(objective="Stand up ESS on Workday")
    plan.set_configuring_agent_name(HR_AGENT)
    plan.add_task(
        new_task("t1", "Configure Workday", stream="Workday",
                 assigned_to=principal_pool("WorkdayAdmin"))
    )
    plan.add_task(new_task("t2", "Author HR topic", stream="Authoring"))
    plan.add_task(new_task("t3", "No stream task"))
    return plan


def test_export_carries_task_stream_as_context():
    body = sync.to_remote_plan_body(_streamed_plan())
    # Top-level shape is unchanged (stream rides inside the allowed context field).
    assert set(body) <= {"configuringAgentName", "acceptanceCriteria", "context", "tasks"}
    carriers = {e["key"]: e["value"] for e in body["context"] if e.get("group") == STREAM_GROUP}
    assert carriers == {"stream:Configure Workday": "Workday", "stream:Author HR topic": "Authoring"}
    # Tasks with no stream contribute no carrier.
    assert "stream:No stream task" not in carriers


def test_export_then_hydrate_preserves_task_stream():
    plan = _streamed_plan()
    body = sync.to_remote_plan_body(plan)
    echoed_tasks = []
    for index, task_body in enumerate(body["tasks"], start=1):
        echoed = dict(task_body)
        echoed["taskId"] = f"srv-{index}"
        echoed_tasks.append(echoed)
    plan_entity = {
        "planId": "srv-plan",
        "configuringAgentName": body["configuringAgentName"],
        "status": "Draft",
        "context": body["context"],
    }
    data = sync.hydrate_from_remote(plan_entity, {"value": echoed_tasks})

    streams = {t["title"]: t.get("stream", "") for t in data["tasks"]}
    assert streams == {"Configure Workday": "Workday", "Author HR topic": "Authoring", "No stream task": ""}
    # The carrier group is an internal vehicle — it never lands in local context.
    assert all(e.get("group") != STREAM_GROUP for e in data["context"])
    assert Plan(data).validate() == []


def test_reexport_after_hydrate_does_not_duplicate_stream_carriers():
    body = sync.to_remote_plan_body(_streamed_plan())
    echoed_tasks = [dict(tb, taskId=f"srv-{i}") for i, tb in enumerate(body["tasks"], start=1)]
    data = sync.hydrate_from_remote(
        {"configuringAgentName": body["configuringAgentName"], "status": "Draft",
         "context": body["context"]},
        {"value": echoed_tasks},
    )
    reexported = sync.to_remote_plan_body(Plan(data))
    carriers = [e for e in reexported["context"] if e.get("group") == STREAM_GROUP]
    # Re-derived from the tasks, not echoed from context — so still exactly two.
    assert sorted(e["value"] for e in carriers) == ["Authoring", "Workday"]


def test_export_rejects_duplicate_streamed_title():
    # A stream carrier joins back to its task by title (the local id isn't sent).
    # Two tasks sharing a title would silently merge their grouping on pull, so a
    # streamed task with a non-unique title is refused rather than corrupt the plan.
    plan = Plan.new(objective="Stand up ESS on Workday")
    plan.set_configuring_agent_name(HR_AGENT)
    plan.add_task(new_task("t1", "Configure Workday", stream="Workday",
                           assigned_to=principal_pool("WorkdayAdmin")))
    plan.add_task(new_task("t2", "Configure Workday"))  # same title, poisons the carrier
    with pytest.raises(ValueError, match="distinct titles"):
        sync.to_remote_plan_body(plan)


def test_export_accepts_legacy_cea_agent_name():
    # A new plan only ever chooses a declarative-agent bundle, but a shared plan
    # authored earlier that already names a custom-engine-agent must keep exporting.
    plan = _plan()
    body = sync.to_remote_plan_body(plan, configuring_agent_name="EmployeeSelfServiceHRCEA")
    assert body["configuringAgentName"] == "EmployeeSelfServiceHRCEA"


def test_stamp_remote_ids():
    plan = _plan()
    sync.stamp_remote_ids(plan, project_id="proj-x", plan_id="plan-x", plan_etag="W/7")
    assert plan.data["projectId"] == "proj-x"
    assert plan.data["planId"] == "plan-x"
    assert plan.data["etag"] == "W/7"
    assert plan.data["syncedAt"]


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #

def test_cli_set_agent_name(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    assert _run("--plan", plan_path, "set-agent-name", "--name", HR_AGENT) == 0
    assert Plan.load(plan_path).configuring_agent_name == HR_AGENT


def test_cli_set_agent_name_rejects_cea_choice(tmp_path):
    # The ESS agent ships as a declarative agent, so a new plan is only offered the
    # DA names — the CLI refuses a custom-engine-agent bundle at the choice boundary.
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    with pytest.raises(SystemExit):
        _run("--plan", plan_path, "set-agent-name", "--name", "EmployeeSelfServiceHRCEA")


def test_cli_export_remote_plan(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init", "--objective", "ESS")
    _run("--plan", plan_path, "set-agent-name", "--name", HR_AGENT)
    _run("--plan", plan_path, "add-task", "--id", "t1", "--title", "Do it", "--role", "WorkdayAdmin")
    capsys.readouterr()  # drain setup output so only the export JSON remains
    assert _run("--plan", plan_path, "export-remote-plan") == 0
    body = json.loads(capsys.readouterr().out)
    assert body["configuringAgentName"] == HR_AGENT
    assert body["tasks"][0]["title"] == "Do it"


def test_cli_export_remote_plan_errors_without_agent_name(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    rc = _run("--plan", plan_path, "export-remote-plan")
    assert rc == 1
    assert "configuringAgentName is required" in capsys.readouterr().err


def test_cli_import_remote_plan_roundtrip(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    payload = {
        "plan": _remote_plan(),
        "tasks": _remote_tasks(),
    }
    input_file = tmp_path / "remote.json"
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    assert _run("--plan", plan_path, "import-remote-plan", "--input", str(input_file)) == 0
    plan = Plan.load(plan_path)
    assert plan.data["planId"] == "plan-1"
    assert plan.configuring_agent_name == HR_AGENT
    assert {t["id"] for t in plan.tasks} == {"rt-1", "rt-2"}
    # The Markdown view is regenerated alongside plan.json.
    assert (tmp_path / "ESS-scenario-plan.md").exists()


def _tool_dump(payload) -> str:
    """Mimic a Copilot CLI tool-result spill: the payload followed by the trailing
    ``{"result": "<stringified payload>"}`` envelope the runtime appends."""
    return json.dumps(payload) + "\n" + json.dumps({"result": json.dumps(payload)})


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('  \n  {"a": 1}', {"a": 1}),
        ('\ufeff{"a": 1}', {"a": 1}),
        # Payload followed by the trailing {"result": "<stringified>"} envelope.
        ('{"a": 1}\n{"result": "{\\"a\\": 1}"}', {"a": 1}),
        # A lone envelope (object or JSON-encoded string) is unwrapped.
        ('{"result": {"a": 1}}', {"a": 1}),
        ('{"result": "{\\"a\\": 1}"}', {"a": 1}),
    ],
)
def test_extract_json_payload(text, expected):
    assert sync.extract_json_payload(text) == expected


def test_extract_json_payload_keeps_plan_tasks_object():
    # A {plan, tasks} combined object is not a lone {"result": ...} envelope, so it
    # must pass through untouched.
    obj = {"plan": {"planId": "p"}, "tasks": {"value": []}}
    assert sync.extract_json_payload(json.dumps(obj)) == obj


def test_extract_json_payload_rejects_empty():
    with pytest.raises(ValueError):
        sync.extract_json_payload("   ")


def test_cli_import_remote_plan_from_tool_dumps(tmp_path):
    # The raw get_project_plan / list_project_plan_tasks dumps each carry a trailing
    # envelope; the CLI must extract the payload without a hand-built {plan, tasks}.
    plan_path = str(tmp_path / "plan.json")
    plan_file = tmp_path / "plan.dump.txt"
    tasks_file = tmp_path / "tasks.dump.txt"
    plan_file.write_text(_tool_dump(_remote_plan()), encoding="utf-8")
    tasks_file.write_text(_tool_dump(_remote_tasks()), encoding="utf-8")

    assert _run(
        "--plan", plan_path, "import-remote-plan",
        "--plan-file", str(plan_file), "--tasks-file", str(tasks_file),
    ) == 0
    plan = Plan.load(plan_path)
    assert plan.data["planId"] == "plan-1"
    assert {t["id"] for t in plan.tasks} == {"rt-1", "rt-2"}


def test_cli_import_remote_plan_input_tolerates_envelope(tmp_path):
    # Even the combined --input path is read past a trailing envelope.
    plan_path = str(tmp_path / "plan.json")
    input_file = tmp_path / "remote.json"
    input_file.write_text(
        _tool_dump({"plan": _remote_plan(), "tasks": _remote_tasks()}),
        encoding="utf-8",
    )
    assert _run("--plan", plan_path, "import-remote-plan", "--input", str(input_file)) == 0
    assert Plan.load(plan_path).data["planId"] == "plan-1"


def test_cli_import_remote_plan_tasks_file_requires_plan_file(tmp_path, capsys):
    plan_path = str(tmp_path / "plan.json")
    tasks_file = tmp_path / "tasks.dump.txt"
    tasks_file.write_text(_tool_dump(_remote_tasks()), encoding="utf-8")
    assert _run(
        "--plan", plan_path, "import-remote-plan", "--tasks-file", str(tasks_file),
    ) == 1
    assert "requires --plan-file" in capsys.readouterr().err


def test_cli_stamp_remote(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    _run("--plan", plan_path, "init")
    _run("--plan", plan_path, "set-agent-name", "--name", HR_AGENT)
    assert _run(
        "--plan", plan_path, "stamp-remote",
        "--project-id", "proj-1", "--plan-id", "plan-1", "--etag", "W/1",
    ) == 0
    plan = Plan.load(plan_path)
    assert plan.data["projectId"] == "proj-1"
    assert plan.data["planId"] == "plan-1"
    assert plan.data["etag"] == "W/1"
