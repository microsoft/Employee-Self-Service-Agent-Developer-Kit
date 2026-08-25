# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.roles_cli — the decoupled /roles CLI surface (pure logic /
in-memory fake, no network).

Verifies the extracted commands are wired on the roles CLI (not the planner CLI),
that the offline `roles` listing renders the verbatim ids, and that `attest`
threads the person/role through to the attestation client.
"""

from __future__ import annotations

from planner import mcp_client, roles_cli
from planner.attest import AttestationClient
from planner.mcp_client import McpError

PLAN = "17aeb22e-02bb-4729-8097-4adeae4313a1"
PROJECT = "003ab3c7-544f-435d-89c2-7970b7c2e6bf"
TENANT = "af8c5344-6ea5-443d-8d17-11df9512ae7c"
SUBJECT = "11111111-2222-3333-4444-555555555555"


class _FakeToolClient:
    """Minimal MCP tool emulation for the attest path, including the plan's tasks
    so the post-attest pool-assignment can be exercised end to end."""

    def __init__(self, tasks=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        # keyed by TaskId; each holds the raw WeveNova task shape + an ETag
        self.tasks: dict[str, dict] = {t["TaskId"]: dict(t) for t in (tasks or [])}

    def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if name == "attest_plan_role":
            return {
                "AssignmentId": "assign-1",
                "Role": arguments["role"],
                "SubjectId": arguments["subjectId"],
                "Status": "Active",
            }
        if name == "list_plan_role_assignments":
            # the post-attest verification readback — surface the Active grant
            return {"value": [{
                "AssignmentId": "assign-1",
                "Role": arguments.get("role", "WorkdayAdmin"),
                "SubjectId": arguments.get("subjectId", SUBJECT),
                "Status": "Active",
            }]}
        if name == "list_project_plan_tasks":
            return {"value": [dict(t) for t in self.tasks.values()]}
        if name == "get_project_plan_task":
            return dict(self.tasks[arguments["taskId"]])
        if name == "update_project_plan_task":
            tid = arguments["taskId"]
            task = self.tasks[tid]
            if arguments.get("etag") != task.get("ETag"):
                raise McpError(f"PreconditionFailed: stale ETag for {tid}")
            task.update(arguments.get("patch") or {})
            task["ETag"] = task["ETag"] + "'"  # a fresh ETag after the write
            return dict(task)
        raise McpError(f"unexpected tool {name}")


OTHER = "99999999-8888-7777-6666-555555555555"


def _pooled_task(task_id, title, role):
    return {
        "TaskId": task_id,
        "Title": title,
        "AssignedToRoleId": role,
        "AssignedToId": role,  # a pooled task's AssignedToId equals its role
        "AssignedTo": {"Type": "Role", "Id": role, "Role": {"RoleId": role}},
        "ETag": "W/\"1\"",
    }


def _owned_task(task_id, title, role, oid):
    return {
        "TaskId": task_id,
        "Title": title,
        "AssignedToRoleId": role,
        "AssignedToId": oid,
        "AssignedTo": {"Type": "User", "Id": oid, "Role": {"RoleId": role}},
        "ETag": "W/\"1\"",
    }


def test_parser_wires_role_commands():
    parser = roles_cli.build_parser()
    for cmd, func in [
        ("roles", roles_cli.cmd_roles),
        ("attest", roles_cli.cmd_attest),
        ("assignments", roles_cli.cmd_assignments),
        ("revoke", roles_cli.cmd_revoke),
        ("caller-tasks", roles_cli.cmd_caller_tasks),
    ]:
        # every subcommand parses and binds its handler
        if cmd == "attest":
            args = parser.parse_args([cmd, "--person", SUBJECT, "--role", "WorkdayAdmin"])
        elif cmd == "revoke":
            args = parser.parse_args([cmd, "--assignment", "assign-1"])
        elif cmd == "caller-tasks":
            args = parser.parse_args([cmd, "--caller", SUBJECT])
        else:
            args = parser.parse_args([cmd])
        assert args.func is func


def test_roles_listing_offline(capsys):
    rc = roles_cli.main(["roles"])
    out = capsys.readouterr().out
    assert rc == 0
    # verbatim ids, with the External display rendered alongside the compact id
    assert "WorkdayAdmin  (Workday Administrator)" in out
    assert "Power Platform Administrator" in out
    assert "[attestable]" in out


def test_attest_threads_person_and_role(monkeypatch, capsys):
    fake = _FakeToolClient()
    client = AttestationClient(fake, plan_id=PLAN, tenant_id=TENANT, project_id=PROJECT)
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(["attest", "--person", SUBJECT, "--role", "Workday Administrator"])
    out = capsys.readouterr().out
    assert rc == 0
    attest_calls = [(n, a) for (n, a) in fake.calls if n == "attest_plan_role"]
    assert len(attest_calls) == 1                      # a single POST, plus a readback
    _, args = attest_calls[0]
    # display name resolved to the compact wire id; provider derived
    assert args["role"] == "WorkdayAdmin"
    assert args["provider"] == "External"
    assert args["subjectId"] == SUBJECT
    assert "Attested" in out


def test_attest_assigns_only_the_roles_open_pool(monkeypatch, capsys):
    """A verified attest also hands the person the role's still-open pooled tasks
    (patched to User, role retained) — never a different role's pool, and never a
    task already owned by someone else."""
    fake = _FakeToolClient([
        _pooled_task("t-wd", "Configure the Workday tenant", "WorkdayAdmin"),
        _pooled_task("t-env", "Install the ESS agent", "Environment Maker"),
        _owned_task("t-wd2", "Set up Workday SSO", "WorkdayAdmin", OTHER),
    ])
    client = AttestationClient(fake, plan_id=PLAN, tenant_id=TENANT, project_id=PROJECT)
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(["attest", "--person", SUBJECT, "--role", "WorkdayAdmin"])
    out = capsys.readouterr().out
    assert rc == 0

    patched = [(a["taskId"], a["patch"]) for (n, a) in fake.calls if n == "update_project_plan_task"]
    assert len(patched) == 1                            # only the WorkdayAdmin *pool*
    tid, patch = patched[0]
    assert tid == "t-wd"                                # not t-env (other role), not t-wd2 (owned)
    # Claim carries ONLY AssignedToId (schema is additionalProperties:false);
    # AssignedToRoleId stays unchanged server-side.
    assert patch == {"AssignedToId": SUBJECT}
    assert "Configure the Workday tenant" in out


def test_attest_reports_when_pool_is_empty(monkeypatch, capsys):
    """Attesting a role with nothing waiting in its pool says so and writes nothing."""
    fake = _FakeToolClient([
        _owned_task("t-wd2", "Set up Workday SSO", "WorkdayAdmin", OTHER),
    ])
    client = AttestationClient(fake, plan_id=PLAN, tenant_id=TENANT, project_id=PROJECT)
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(["attest", "--person", SUBJECT, "--role", "WorkdayAdmin"])
    out = capsys.readouterr().out
    assert rc == 0
    assert not [c for c in fake.calls if c[0] == "update_project_plan_task"]
    assert "No open WorkdayAdmin tasks" in out


def test_attest_no_assign_tasks_flag_skips_the_pool(monkeypatch, capsys):
    """``--no-assign-tasks`` attests only — the role's pool is left untouched."""
    fake = _FakeToolClient([
        _pooled_task("t-wd", "Configure the Workday tenant", "WorkdayAdmin"),
    ])
    client = AttestationClient(fake, plan_id=PLAN, tenant_id=TENANT, project_id=PROJECT)
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(
        ["attest", "--person", SUBJECT, "--role", "WorkdayAdmin", "--no-assign-tasks"]
    )
    assert rc == 0
    # the task path is never entered at all
    assert not [c for c in fake.calls if c[0] in
                ("list_project_plan_tasks", "update_project_plan_task")]


def test_attest_rejects_non_attestable_role(monkeypatch, capsys):
    fake = _FakeToolClient()
    client = AttestationClient(fake, plan_id=PLAN, tenant_id=TENANT, project_id=PROJECT)
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(["attest", "--person", SUBJECT, "--role", "AgentOwner"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "must be one of" in err
    # no server call was made on a local-validation failure
    assert fake.calls == []


# --- find-users: resolve a display name -> aadId via WeveNova ---------------- #

class _FakePeopleClient:
    """MCP client emulating the WeveNova ``find_users_by_name`` people search."""

    def __init__(self, payload) -> None:
        self._payload = payload
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if name == "find_users_by_name":
            return self._payload
        raise McpError(f"unexpected tool {name}")


def test_find_users_wired_on_parser():
    parser = roles_cli.build_parser()
    args = parser.parse_args(["find-users", "--name", "primary"])
    assert args.func is roles_cli.cmd_find_users
    assert args.name == "primary"


def test_find_users_resolves_aad_id(monkeypatch, capsys):
    payload = {
        "query": "primary",
        "source": "demo-cache",
        "users": [
            {"aadId": "8fde91b6-45cd-4dbf-9908-439cfdd0311e", "displayName": "primary",
             "source": "user-provided TDS identity"},
        ],
    }
    fake = _FakePeopleClient(payload)
    monkeypatch.setattr(roles_cli, "_weve_client", lambda args: fake)

    rc = roles_cli.main(["find-users", "--name", "primary"])
    out = capsys.readouterr().out
    assert rc == 0
    assert fake.calls[-1] == ("find_users_by_name", {"name": "primary"})
    # the resolved aadId (== Entra object id for attest --person) is surfaced
    assert "8fde91b6-45cd-4dbf-9908-439cfdd0311e" in out
    assert "primary" in out


def test_find_users_reports_no_match(monkeypatch, capsys):
    monkeypatch.setattr(roles_cli, "_weve_client", lambda args: _FakePeopleClient({"users": []}))
    rc = roles_cli.main(["find-users", "--name", "nobody"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No one in the WeveNova directory matched" in out


def test_find_users_json_dumps_raw_payload(monkeypatch, capsys):
    payload = {"users": [{"aadId": "abc", "displayName": "primary"}], "source": "demo-cache"}
    monkeypatch.setattr(roles_cli, "_weve_client", lambda args: _FakePeopleClient(payload))
    rc = roles_cli.main(["find-users", "--name", "primary", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"aadId": "abc"' in out
    assert '"source": "demo-cache"' in out


# --- caller-tasks: self-only "what are my tasks" ---------------------------- #

CALLER = "3541af92-2c5d-4b4a-aad8-5f257de3244d"  # the authenticated tunnel user


class _FakeCallerClient:
    """MCP client emulating ``list_project_plan_tasks_for_caller`` — records the
    args so tests can assert the caller scope (and any OData query) sent."""

    def __init__(self, tasks=None) -> None:
        self._tasks = list(tasks) if tasks is not None else []
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if name == "list_project_plan_tasks_for_caller":
            return {"value": list(self._tasks)}
        raise McpError(f"unexpected tool {name}")


def _caller_client(tasks=None) -> AttestationClient:
    return AttestationClient(
        _FakeCallerClient(tasks), plan_id=PLAN, tenant_id=TENANT, project_id=PROJECT
    )


def test_tasks_for_caller_sends_caller_scope_without_query():
    """Passing only the caller id sends ``callerId`` (WeveNova's self-scope
    sentinel) and NO ``query`` — role expansion is the server's job, not a
    client-built ``assignedToId`` filter."""
    client = _caller_client([{"TaskId": "t1", "Title": "Configure Workday", "State": "NotStarted"}])
    tasks = client.tasks_for_caller(CALLER)
    assert [t["TaskId"] for t in tasks] == ["t1"]
    name, args = client.client.calls[-1]
    assert name == "list_project_plan_tasks_for_caller"
    assert args["callerId"] == CALLER
    assert args["projectId"] == PROJECT and args["planId"] == PLAN
    assert "query" not in args  # no invented / duplicated caller predicate


def test_tasks_for_caller_builds_odata_query_object():
    """An extra ``$filter`` is sent as an OData options **object** (``query.filter``),
    never a bare string — matching the ``list_project_plan_tasks_for_caller`` schema."""
    client = _caller_client([])
    client.tasks_for_caller(CALLER, odata_filter="state eq 'NotStarted'")
    _, args = client.client.calls[-1]
    assert args["query"] == {"filter": "state eq 'NotStarted'"}
    assert args["callerId"] == CALLER  # caller scope still carried separately


def test_caller_tasks_defaults_caller_from_env(monkeypatch, capsys):
    """`caller-tasks` with no ``--caller`` falls back to ``PLANNER_MCP_CALLER_ID``
    (the authenticated caller), mirroring how project/plan/tenant resolve."""
    monkeypatch.setenv("PLANNER_MCP_CALLER_ID", CALLER)
    client = _caller_client([{"TaskId": "t1", "Title": "Configure Workday", "State": "NotStarted"}])
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(["caller-tasks"])
    out = capsys.readouterr().out
    assert rc == 0
    _, args = client.client.calls[-1]
    assert args["callerId"] == CALLER  # the env caller flowed through as self-scope
    assert "Configure Workday" in out


def test_caller_tasks_explicit_arg_beats_env(monkeypatch, capsys):
    monkeypatch.setenv("PLANNER_MCP_CALLER_ID", "00000000-0000-0000-0000-000000000000")
    client = _caller_client([])
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(["caller-tasks", "--caller", CALLER])
    assert rc == 0
    _, args = client.client.calls[-1]
    assert args["callerId"] == CALLER


def _must_not_build(args):  # pragma: no cover - only invoked on a guardrail bug
    raise AssertionError("_attest_client must not be reached before a valid caller")


def test_caller_tasks_auto_resolves_caller_from_env_file(monkeypatch, capsys):
    """With no ``--caller`` and no ``PLANNER_MCP_CALLER_ID``, caller-tasks resolves
    the caller from the kit ``.env`` (``aadId``) and uses that own OID as the
    self-scope — so the person is never asked for their AAD id."""
    monkeypatch.delenv("PLANNER_MCP_CALLER_ID", raising=False)
    monkeypatch.setattr(mcp_client, "load_adk_identity", lambda config_path: ("default", CALLER))
    client = _caller_client([{"TaskId": "t1", "Title": "Configure Workday", "State": "NotStarted"}])
    monkeypatch.setattr(roles_cli, "_attest_client", lambda args: client)

    rc = roles_cli.main(["caller-tasks"])
    out = capsys.readouterr().out
    assert rc == 0
    _, args = client.client.calls[-1]
    assert args["callerId"] == CALLER  # the .env-resolved caller flowed through
    assert "Configure Workday" in out


def test_caller_tasks_requires_a_caller(monkeypatch, capsys):
    """No ``--caller``, no env, and no ``.env`` identity → a clear self-only usage
    error, and NO task path is taken (the guardrail returns before the task client
    is built)."""
    monkeypatch.delenv("PLANNER_MCP_CALLER_ID", raising=False)
    monkeypatch.setattr(mcp_client, "load_adk_identity", lambda config_path: (None, None))
    monkeypatch.setattr(roles_cli, "_attest_client", _must_not_build)

    rc = roles_cli.main(["caller-tasks"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "PLANNER_MCP_CALLER_ID" in err
    assert "self-only" in err


def test_caller_tasks_rejects_name_as_caller(monkeypatch, capsys):
    """A display name (e.g. 'primary') is not a GUID — rejected before any call,
    so it can't silently return zero role-pooled tasks."""
    monkeypatch.delenv("PLANNER_MCP_CALLER_ID", raising=False)
    monkeypatch.setattr(roles_cli, "_attest_client", _must_not_build)

    rc = roles_cli.main(["caller-tasks", "--caller", "primary"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "GUID" in err
