# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.plan_store — the local vs WeveNova-MCP persistence seam.

The MCP-backed store is exercised against a small in-memory fake that emulates
the ``weve-plan`` tool surface (plan read + task CRUD), so no network is needed.
An opt-in ``@pytest.mark.live`` test hits the real server when ``--run-live`` is
passed and ``PLANNER_MCP_URL`` is set.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

from planner import weve_mapping as wm
from planner.mcp_client import McpError
from planner.plan_model import Plan, new_task, plan_artifact, principal_pool
from planner.plan_store import (
    LocalPlanStore,
    McpPlanStore,
    PlanStoreError,
    create_project_plan,
    find_existing_plan_id,
    make_store,
    open_or_create_mcp_plan,
    resolve_plan_binding,
    resolve_project_binding,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "weve_project_plan.json")

PID = "proj-test-1"
PLID = "plan-test-1"


@pytest.fixture(autouse=True)
def _clear_planner_env(monkeypatch):
    """Keep discovery hermetic: a contributor's real ``PLANNER_MCP_*`` env must
    not steer the project/plan binding the resolution tests assert on."""
    for var in (
        "PLANNER_MCP_PROJECT_ID", "PLANNER_MCP_PLAN_ID", "PLANNER_MCP_TENANT_ID",
        "PLANNER_MCP_URL", "PLANNER_MCP_HEADERS", "PLANNER_STORE",
    ):
        monkeypatch.delenv(var, raising=False)


class FakeWeveClient:
    """Emulates the weve-plan MCP tools over an in-memory plan + task table.

    Mirrors the 3.x multi-plan surface: every plan/task tool takes ``projectId``
    /``planId`` (ignored here — one plan in the fake), plus the role-assigned
    create and dedicated state-transition tools.
    """

    def __init__(self, plan_doc: dict, tasks: list[dict] | None = None, *,
                 projects: list[dict] | None = None, plans: list[dict] | None = None) -> None:
        self.plan_doc = plan_doc
        self.tasks: dict[str, dict] = {}
        self._etag_seq = 0
        # Optional multi-plan discovery surface. When left as None the fake
        # synthesizes a single project/plan from ``plan_doc`` so the existing
        # task-focused tests keep working unchanged; the plan-lifecycle tests
        # pass explicit lists (e.g. a project with no plan yet).
        self.projects = projects
        self.plans = plans
        self.created_plan_args: dict | None = None
        for t in tasks or []:
            tid = t.get("TaskId") or str(uuid.uuid4())
            self.tasks[tid] = {**t, "TaskId": tid, "ETag": self._bump_etag()}
        self.calls: list[str] = []
        self.call_log: list[tuple[str, dict]] = []

    def _bump_etag(self) -> str:
        self._etag_seq += 1
        return f'W/"{self._etag_seq}"'

    def lifecycle_rules(self) -> dict:
        """The live lifecycle/concurrency contract the store loads once on init."""
        return {"planActivationRule": "Only the plan resource owner may activate it."}

    def call_tool(self, name: str, arguments=None):
        arguments = arguments or {}
        self.calls.append(name)
        self.call_log.append((name, arguments))
        if name == "get_project_plan":
            return self.plan_doc
        if name == "list_agent_configuration_projects":
            return {"value": self._projects()}
        if name == "get_agent_configuration_project":
            pid = arguments.get("projectId")
            for p in self._projects():
                if p.get("ProjectId") == pid:
                    return p
            projects = self._projects()
            return projects[0] if projects else {}
        if name == "list_project_plans":
            return {"value": self._plans()}
        if name == "create_project_plan":
            self.created_plan_args = arguments
            new_id = str(uuid.uuid4())
            plan_body = arguments.get("plan", {}) or {}
            self.plan_doc = {
                "PlanId": new_id,
                "ProjectId": arguments.get("projectId"),
                "Status": "Draft",
                "ETag": self._bump_etag(),
                "Context": list(plan_body.get("Context", []) or []),
                "AcceptanceCriteria": list(plan_body.get("AcceptanceCriteria", []) or []),
                "Outputs": [],
            }
            self.plans = [{"PlanId": new_id}]
            return {"PlanId": new_id}
        if name == "update_project_plan":
            self._check_plan_etag(arguments)
            patch = arguments.get("patch", {}) or {}
            if "Context" in patch:
                self.plan_doc["Context"] = patch["Context"]
            if "AcceptanceCriteria" in patch:
                self.plan_doc["AcceptanceCriteria"] = patch["AcceptanceCriteria"]
            self.plan_doc["ETag"] = self._bump_etag()
            return self.plan_doc
        if name == "list_project_plan_tasks":
            return {"value": list(self.tasks.values())}
        if name == "get_project_plan_task":
            tid = arguments["taskId"]
            if tid not in self.tasks:
                raise McpError(f"task {tid} not found")
            return self.tasks[tid]
        if name == "create_project_plan_task":
            tid = str(uuid.uuid4())
            self.tasks[tid] = {**arguments["task"], "TaskId": tid, "ETag": self._bump_etag()}
            return self.tasks[tid]
        if name == "create_role_assigned_project_plan_task":
            tid = str(uuid.uuid4())
            role = arguments["role"]
            self.tasks[tid] = {
                "TaskId": tid,
                "Title": arguments.get("title", ""),
                "Description": arguments.get("description", ""),
                "State": "NotStarted",
                "Produces": list(arguments.get("produces") or []),
                "Consumes": list(arguments.get("consumes") or []),
                "AssignedToType": "Role",
                "AssignedToId": role,
                "AssignedToRoleId": role,
                "ETag": self._bump_etag(),
            }
            return self.tasks[tid]
        if name == "update_project_plan_task":
            tid = arguments["taskId"]
            self._check_etag(tid, arguments)
            self.tasks[tid] = {
                **self.tasks.get(tid, {}), **arguments["patch"],
                "TaskId": tid, "ETag": self._bump_etag(),
            }
            return self.tasks[tid]
        if name == "set_project_plan_task_state":
            tid = arguments["taskId"]
            self._check_etag(tid, arguments)
            self.tasks[tid] = {
                **self.tasks.get(tid, {}), "State": arguments["state"],
                "TaskId": tid, "ETag": self._bump_etag(),
            }
            return self.tasks[tid]
        if name == "complete_project_plan_task":
            tid = arguments["taskId"]
            self._check_etag(tid, arguments)
            self.tasks[tid] = {
                **self.tasks.get(tid, {}), "State": "Completed",
                "TaskId": tid, "ETag": self._bump_etag(),
            }
            # WeveNova records the produced outputs on the plan ledger at completion.
            outs = self.plan_doc.setdefault("Outputs", [])
            for o in arguments.get("outputs", []) or []:
                outs.append({
                    "Key": o.get("key"),
                    "Kind": o.get("kind"),
                    "ProducedByTaskId": tid,
                    "State": "Active",
                    "InventoryRef": o.get("inventoryRef", ""),
                    "Attributes": [
                        {"Key": a["key"], "Value": a.get("value")}
                        for a in o.get("attributes", []) or []
                    ],
                })
            self.plan_doc["ETag"] = self._bump_etag()
            return self.tasks[tid]
        if name == "delete_project_plan_task":
            self._check_etag(arguments["taskId"], arguments)
            self.tasks.pop(arguments["taskId"], None)
            return {"deleted": arguments["taskId"]}
        raise McpError(f"unknown tool {name}")

    def _check_etag(self, tid: str, arguments: dict) -> None:
        """Model If-Match: a mutation must send the entity's current ETag."""
        current = self.tasks.get(tid, {}).get("ETag")
        if current and arguments.get("etag") != current:
            raise McpError(f"precondition failed: stale ETag for {tid}")

    def _check_plan_etag(self, arguments: dict) -> None:
        """Model If-Match on the plan itself for ``update_project_plan``."""
        current = self.plan_doc.get("ETag")
        if current and arguments.get("etag") != current:
            raise McpError("precondition failed: stale plan ETag")

    def _projects(self) -> list[dict]:
        """The discovery project list — explicit when provided, else a single
        project synthesized from ``plan_doc`` (its plan is the active plan)."""
        if self.projects is not None:
            return self.projects
        return [{
            "ProjectId": self.plan_doc.get("ProjectId"),
            "Name": "Test Project",
            "ActivePlanId": self.plan_doc.get("PlanId"),
            "TenantId": "tenant-1",
        }]

    def _plans(self) -> list[dict]:
        if self.plans is not None:
            return self.plans
        pid = self.plan_doc.get("PlanId")
        return [{"PlanId": pid}] if pid else []


def _mcp_store(client, summary_path, **kw):
    """Construct an McpPlanStore bound to the fake's single (project, plan)."""
    return McpPlanStore(client, summary_path, project_id=PID, plan_id=PLID, **kw)


def _fixture_doc() -> dict:
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --- local store ------------------------------------------------------------- #

def test_local_store_round_trip(tmp_path):
    plan_path = str(tmp_path / "plan.json")
    store = LocalPlanStore(plan_path)
    plan = Plan.new(objective="ESS HR ticketing")
    store.save(plan)
    assert os.path.exists(plan_path)
    assert os.path.exists(store.summary_path)          # .md rendered
    assert store.load().output_value_or_context("objective") == "ESS HR ticketing"


def test_make_store_selects_local(tmp_path):
    store = make_store(backend="local", plan_path=str(tmp_path / "plan.json"))
    assert isinstance(store, LocalPlanStore)


# --- mcp store: read --------------------------------------------------------- #

def test_mcp_store_load_maps_plan_and_tasks(tmp_path):
    doc = _fixture_doc()
    server_task = wm.task_to_weve(
        new_task("srv-1", "Set up Workday SSO", assigned_to=principal_pool("App/Cloud App Admin"),
                 produces=["workdayEntraApp"]),
        include_id=True,
    )
    client = FakeWeveClient(doc, tasks=[server_task])
    store = _mcp_store(client, str(tmp_path / "ESS-scenario-plan.md"))
    plan = store.load()
    assert plan.data["planId"] == doc["PlanId"]
    assert plan.output_value_or_context("scenario") == "HR-Ticketing"  # context read-through
    assert [t["title"] for t in plan.tasks] == ["Set up Workday SSO"]
    assert plan.tasks[0]["assignedTo"]["role"]["roleId"] == "App/Cloud App Admin"


# --- mcp store: task reconcile ----------------------------------------------- #

def test_mcp_store_save_creates_new_task(tmp_path):
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = Plan(wm.plan_from_weve(client.plan_doc, tasks=[]))
    plan.add_task(new_task("T1", "Run setup", assigned_to=principal_pool("Environment Maker"),
                           produces=["primaryEnvironment"]))
    notices = store.save(plan)
    # A pooled-role task is created through the dedicated role-assigned tool.
    assert "create_role_assigned_project_plan_task" in client.calls
    assert len(client.tasks) == 1
    created = next(iter(client.tasks.values()))
    assert created["Title"] == "Run setup"
    assert created["AssignedToRoleId"] == "Environment Maker"
    assert os.path.exists(store.summary_path)          # .md still rendered
    # The fixture's output isn't produced by a Completed task, so it's held
    # locally until its producer completes (pushed then via complete_project_plan_task).
    assert any("held locally" in n for n in notices)


def test_mcp_store_save_creates_plain_user_task(tmp_path):
    from planner.plan_model import principal_person
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = Plan(wm.plan_from_weve(client.plan_doc, tasks=[]))
    plan.add_task(new_task("T1", "Do it", assigned_to=principal_person("11111111-1111-1111-1111-111111111111")))
    store.save(plan)
    # A person-assigned (non-pooled) task uses the generic create.
    assert "create_project_plan_task" in client.calls
    assert "create_role_assigned_project_plan_task" not in client.calls


def test_mcp_store_save_skips_unchanged_tasks(tmp_path):
    server_task = wm.task_to_weve(new_task("keep", "Same", assigned_to=principal_pool("WorkdayAdmin"),
                                           produces=["x"]), include_id=True)
    client = FakeWeveClient(_fixture_doc(), tasks=[server_task])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    client.calls.clear()
    store.save(plan)                    # nothing changed
    assert "update_project_plan_task" not in client.calls   # no no-op write
    assert "create_project_plan_task" not in client.calls
    assert "create_role_assigned_project_plan_task" not in client.calls
    assert "delete_project_plan_task" not in client.calls


def test_mcp_store_load_writes_local_cache(tmp_path):
    cache = tmp_path / "plan.json"
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    store = _mcp_store(client, str(tmp_path / "plan.md"), cache_path=str(cache))
    plan = store.load()
    assert cache.exists()                                    # WeveNova mirrored to local cache
    cached = json.loads(cache.read_text(encoding="utf-8"))
    assert cached["planId"] == plan.data["planId"]


def test_mcp_store_save_renders_md_from_weve_state(tmp_path):
    # After creating a task locally, the .md must reflect the WeveNova state —
    # i.e. the server-assigned TaskId, not the local placeholder id.
    md = tmp_path / "plan.md"
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    store = _mcp_store(client, str(md), cache_path=str(tmp_path / "plan.json"))
    plan = Plan(wm.plan_from_weve(client.plan_doc, tasks=[]))
    plan.add_task(new_task("LOCAL-TMP", "Run setup", assigned_to=principal_pool("Environment Maker")))
    store.save(plan)
    server_id = next(iter(client.tasks))                     # uuid the fake assigned
    rendered = md.read_text(encoding="utf-8")
    assert server_id in rendered                             # md generated from WeveNova
    assert "LOCAL-TMP" not in rendered                       # not the local placeholder


def test_mcp_store_save_state_change_uses_state_tool(tmp_path):
    server_task = wm.task_to_weve(new_task("keep", "Same", assigned_to=principal_pool("WorkdayAdmin")),
                                  include_id=True)
    client = FakeWeveClient(_fixture_doc(), tasks=[server_task])
    client.plan_doc["Status"] = "Active"        # task-state changes require an Active plan
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    task = next(t for t in plan.tasks if t["id"] == "keep")
    task["state"] = "Completed"
    client.calls.clear()
    store.save(plan)
    # A pure state transition is routed through the dedicated state tool, not a patch.
    assert "set_project_plan_task_state" in client.calls
    assert "update_project_plan_task" not in client.calls
    assert client.tasks["keep"]["State"] == "Completed"


def test_mcp_store_save_title_and_state_change_reads_fresh_etag(tmp_path):
    # Both a content field and the state change: PATCH first, then re-read the
    # fresh ETag before set-state, so the second call is not a stale If-Match.
    server_task = wm.task_to_weve(new_task("keep", "Old", assigned_to=principal_pool("WorkdayAdmin")),
                                  include_id=True)
    client = FakeWeveClient(_fixture_doc(), tasks=[server_task])
    client.plan_doc["Status"] = "Active"        # task-state changes require an Active plan
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    task = next(t for t in plan.tasks if t["id"] == "keep")
    task["title"] = "New"
    task["state"] = "Completed"
    client.calls.clear()
    store.save(plan)                    # must not raise a stale-ETag McpError
    assert "update_project_plan_task" in client.calls
    assert "get_project_plan_task" in client.calls          # re-read for a fresh etag
    assert "set_project_plan_task_state" in client.calls
    assert client.tasks["keep"]["Title"] == "New"
    assert client.tasks["keep"]["State"] == "Completed"


def test_mcp_store_save_completes_task_with_outputs_in_one_bulk_call(tmp_path):
    # A task going Completed that produced outputs is finished through
    # complete_project_plan_task, which carries ALL its Active outputs in a single
    # (bulk) call — NOT set_project_plan_task_state, and not one call per output.
    server_task = wm.task_to_weve(
        new_task("setup", "Run setup", assigned_to=principal_pool("Environment Maker"),
                 produces=["primaryEnvironment"]),
        include_id=True,
    )
    client = FakeWeveClient(_fixture_doc(), tasks=[server_task])
    client.plan_doc["Status"] = "Active"
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    plan.add_output(plan_artifact(
        "primaryEnvironment", "Environment",
        {"environmentId": "env-1", "environmentUrl": "https://org.crm.dynamics.com"},
        produced_by_task_id="setup",
    ))
    task = next(t for t in plan.tasks if t["id"] == "setup")
    task["state"] = "Completed"
    client.calls.clear()
    store.save(plan)

    completes = [a for (n, a) in client.call_log if n == "complete_project_plan_task"]
    assert len(completes) == 1                                  # bulk: exactly one call
    outs = completes[0]["outputs"]
    assert [o["key"] for o in outs] == ["primaryEnvironment"]   # all outputs in that one call
    assert outs[0]["kind"] == "Environment"                     # completion enum shape
    assert {"key": "environmentId", "value": "env-1"} in outs[0]["attributes"]
    assert completes[0].get("etag")                             # If-Match carried
    # NotStarted must move to InProgress before completing; never a Completed set-state.
    states = [a["state"] for (n, a) in client.call_log if n == "set_project_plan_task_state"]
    assert states == ["InProgress"]
    assert client.tasks["setup"]["State"] == "Completed"
    # WeveNova recorded the output on the plan ledger at completion.
    assert any(o.get("Key") == "primaryEnvironment" for o in client.plan_doc.get("Outputs", []))


def test_mcp_store_save_completed_without_outputs_uses_state_tool(tmp_path):
    # A task with no produced outputs still completes through the plain state tool.
    server_task = wm.task_to_weve(
        new_task("t", "No outputs", assigned_to=principal_pool("WorkdayAdmin")),
        include_id=True,
    )
    client = FakeWeveClient(_fixture_doc(), tasks=[server_task])
    client.plan_doc["Status"] = "Active"
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    next(t for t in plan.tasks if t["id"] == "t")["state"] = "Completed"
    client.calls.clear()
    store.save(plan)
    assert "complete_project_plan_task" not in client.calls
    states = [a["state"] for (n, a) in client.call_log if n == "set_project_plan_task_state"]
    assert states == ["Completed"]


def test_mcp_store_save_updates_existing_task(tmp_path):
    server_task = wm.task_to_weve(new_task("keep", "Old title",
                                           assigned_to=principal_pool("WorkdayAdmin")), include_id=True)
    client = FakeWeveClient(_fixture_doc(), tasks=[server_task])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    # the server task loaded with id "keep"; retitle it and save
    task = next(t for t in plan.tasks if t["id"] == "keep")
    task["title"] = "New title"
    store.save(plan)
    assert "update_project_plan_task" in client.calls
    assert client.tasks["keep"]["Title"] == "New title"
    # the PATCH carried the current ETag as If-Match
    patches = [a for (n, a) in client.call_log if n == "update_project_plan_task"]
    assert patches and patches[0].get("etag")


def test_mcp_store_save_deletes_removed_task(tmp_path):
    a = wm.task_to_weve(new_task("a", "A", assigned_to=principal_pool("WorkdayAdmin")), include_id=True)
    b = wm.task_to_weve(new_task("b", "B", assigned_to=principal_pool("WorkdayAdmin")), include_id=True)
    client = FakeWeveClient(_fixture_doc(), tasks=[a, b])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    plan.data["tasks"] = [t for t in plan.tasks if t["id"] == "a"]   # drop b
    store.save(plan)
    assert "delete_project_plan_task" in client.calls
    assert set(client.tasks) == {"a"}


def test_mcp_store_load_degrades_when_tasks_unavailable(tmp_path):
    # Plan read works but the tasks collection is down -> load the plan-level
    # view with no tasks + a warning, rather than failing outright.
    class TasksDown:
        def __init__(self, doc):
            self.doc = doc
        def lifecycle_rules(self):
            return {}
        def call_tool(self, name, arguments=None):
            if name == "get_project_plan":
                return self.doc
            raise McpError("Upstream GET ... /tasks returned 404 Not Found")

    store = _mcp_store(TasksDown(_fixture_doc()), str(tmp_path / "plan.md"))
    plan = store.load()
    assert plan.data["planId"]           # plan-level still read
    assert plan.tasks == []
    assert any("tasks unavailable" in w for w in store.warnings)


def test_mcp_store_load_raises_when_plan_unreadable(tmp_path):
    class PlanDown:
        def lifecycle_rules(self):
            return {}
        def call_tool(self, name, arguments=None):
            raise McpError("Upstream GET ... returned 503")

    from planner.plan_store import PlanStoreError
    store = _mcp_store(PlanDown(), str(tmp_path / "plan.md"))
    with pytest.raises(PlanStoreError):
        store.load()


# --- mcp store: project/plan resolution + first-plan create (Bug 1) --------- #

def test_resolve_project_binding_single_project():
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    pid, project, tenant = resolve_project_binding(client)
    assert pid == _fixture_doc()["ProjectId"]
    assert tenant == "tenant-1"
    assert "list_agent_configuration_projects" in client.calls


def test_resolve_project_binding_multiple_requires_choice():
    client = FakeWeveClient(_fixture_doc(), tasks=[], projects=[
        {"ProjectId": "p1", "Name": "One"}, {"ProjectId": "p2", "Name": "Two"},
    ])
    with pytest.raises(PlanStoreError):
        resolve_project_binding(client)


def test_find_existing_plan_id_active_then_single_then_none():
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    # ActivePlanId wins with no extra lookup.
    assert find_existing_plan_id(
        client, project_id="p", project={"ActivePlanId": "pl-active"}
    ) == "pl-active"
    # No active -> the project's single plan.
    client.plans = [{"PlanId": "only-plan"}]
    assert find_existing_plan_id(client, project_id="p", project={}) == "only-plan"
    # No plans at all -> None (the signal that init should create the first plan).
    client.plans = []
    assert find_existing_plan_id(client, project_id="p", project={}) is None


def test_find_existing_plan_id_multiple_without_active_raises():
    client = FakeWeveClient(_fixture_doc(), tasks=[], plans=[{"PlanId": "a"}, {"PlanId": "b"}])
    with pytest.raises(PlanStoreError):
        find_existing_plan_id(client, project_id="p", project={})


def test_create_project_plan_returns_id_and_sends_project():
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    plan_id = create_project_plan(client, project_id="proj-9", objective="Deploy ESS in Bangalore")
    assert plan_id                                          # a PlanId came back
    assert client.created_plan_args["projectId"] == "proj-9"
    # The live tool requires a `plan` entity body (not a bare `objective` scalar);
    # the objective is seeded as an `objective` Context entry so it round-trips.
    plan_body = client.created_plan_args["plan"]
    objective_entries = [c for c in plan_body["Context"] if c.get("Key") == "objective"]
    assert objective_entries and objective_entries[0]["Value"] == "Deploy ESS in Bangalore"


def test_create_project_plan_seeds_no_context_without_objective():
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    create_project_plan(client, project_id="proj-9")
    # No objective -> an empty plan entity body (still a valid `plan` object).
    assert client.created_plan_args["plan"] == {}


def test_resolve_plan_binding_raises_when_no_plans():
    # A project that exists but has no plan yet -> the classic init catch-22 that
    # open_or_create_mcp_plan exists to break.
    client = FakeWeveClient(_fixture_doc(), tasks=[],
                            projects=[{"ProjectId": "p", "Name": "Fresh"}], plans=[])
    with pytest.raises(PlanStoreError) as ei:
        resolve_plan_binding(client)
    assert "no plans" in str(ei.value)


def _use_fake_client(monkeypatch, client):
    """Make make_store / open_or_create_mcp_plan use the in-memory fake."""
    import planner.plan_store as ps
    monkeypatch.setattr(ps, "client_from_config", lambda *a, **k: client)


def test_open_or_create_mcp_plan_creates_first_plan(monkeypatch, tmp_path):
    # Fresh project: it exists, but has no plan yet.
    client = FakeWeveClient(_fixture_doc(), tasks=[],
                            projects=[{"ProjectId": "proj-1", "Name": "Fresh"}], plans=[])
    _use_fake_client(monkeypatch, client)
    store, created = open_or_create_mcp_plan(
        plan_path=str(tmp_path / "plan.json"), objective="Deploy ESS in Bangalore",
    )
    assert created is True
    assert isinstance(store, McpPlanStore)
    assert client.created_plan_args["projectId"] == "proj-1"
    assert store.plan_id                                    # bound to the newly created plan
    assert "create_project_plan" in client.calls


def test_open_or_create_mcp_plan_reuses_existing_plan(monkeypatch, tmp_path):
    client = FakeWeveClient(_fixture_doc(), tasks=[])       # synthesized active plan
    _use_fake_client(monkeypatch, client)
    store, created = open_or_create_mcp_plan(plan_path=str(tmp_path / "plan.json"))
    assert created is False
    assert store.plan_id == _fixture_doc()["PlanId"]
    assert "create_project_plan" not in client.calls        # never recreates an existing plan


# --- mcp store: plan-level context reconcile (read-write, Bug 3) ------------ #

def test_mcp_store_save_pushes_context_and_criteria(tmp_path):
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    plan.set_context("market", "IN", group="market")        # change existing context
    plan.set_context("acceptanceCriteria:Latency < 2s", "Latency < 2s",
                     group="acceptanceCriteria")            # add a new acceptance criterion
    client.calls.clear()
    store.save(plan)
    assert "update_project_plan" in client.calls            # plan-level write happened
    patches = [a for (n, a) in client.call_log if n == "update_project_plan"]
    assert patches and patches[0].get("etag")               # carried the plan ETag as If-Match
    pushed = patches[0]["patch"]
    assert any(c["Key"] == "market" and c["Value"] == "IN" for c in pushed["Context"])
    assert "Latency < 2s" in pushed["AcceptanceCriteria"]
    # Acceptance criteria travel in their own list, never duplicated into Context.
    assert all(c.get("Group") != "acceptanceCriteria" for c in pushed["Context"])


def test_mcp_store_save_skips_plan_write_when_context_unchanged(tmp_path):
    client = FakeWeveClient(_fixture_doc(), tasks=[])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    client.calls.clear()
    store.save(plan)                                         # nothing changed
    assert "update_project_plan" not in client.calls        # no no-op plan write


def test_mcp_store_save_plan_context_degrades_on_read_failure(tmp_path):
    # If the plan can't be re-read to diff, plan-context sync degrades to a
    # notice rather than raising (task reconcile already succeeded).
    server_task = wm.task_to_weve(
        new_task("keep", "Same", assigned_to=principal_pool("WorkdayAdmin")), include_id=True)
    client = FakeWeveClient(_fixture_doc(), tasks=[server_task])
    store = _mcp_store(client, str(tmp_path / "plan.md"))
    plan = store.load()
    plan.set_context("market", "IN", group="market")

    real_call = client.call_tool

    def flaky(name, arguments=None):
        if name == "get_project_plan":
            raise McpError("Upstream GET plan returned 503")
        return real_call(name, arguments)

    client.call_tool = flaky
    notices = store.save(plan)
    assert any("plan context not synced" in n for n in notices)


# --- opt-in live smoke ------------------------------------------------------- #

@pytest.mark.live
def test_mcp_store_live_reads_plan(tmp_path):
    """Opt-in (``--run-live`` + ``PLANNER_MCP_URL``): the real weve-plan server
    returns a plan the store can map and render."""
    if not os.environ.get("PLANNER_MCP_URL"):
        pytest.skip("set PLANNER_MCP_URL (and PLANNER_MCP_HEADERS) to run the live MCP smoke")
    store = make_store(backend="mcp", plan_path=str(tmp_path / "plan.json"))
    plan = store.load()
    assert plan.data["planId"]                       # plan-level read from WeveNova
    assert plan.data["projectId"]
    # When the tasks collection is reachable the plan is fully valid; while it is
    # unavailable, load degrades (empty tasks) and outputs may reference unloaded
    # tasks — so assert the store surfaced that rather than requiring validity.
    if getattr(store, "warnings", []):
        assert any("tasks unavailable" in w for w in store.warnings)
    else:
        assert plan.validate() == []
    md = plan.render_summary()
    assert "## " in md
