# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.attest — the role-attestation client seam (pure logic /
in-memory fake, no network).

The MCP tool surface is emulated by a small fake so the local validation,
argument shaping, and provider derivation are exercised without a server.
"""

from __future__ import annotations

import pytest

from planner.attest import (
    AttestationClient,
    AttestationError,
    is_oid,
    validate_attestation,
)
from planner.mcp_client import McpError

TENANT = "af8c5344-6ea5-443d-8d17-11df9512ae7c"
PROJECT = "003ab3c7-544f-435d-89c2-7970b7c2e6bf"
PLAN = "17aeb22e-02bb-4729-8097-4adeae4313a1"
SUBJECT = "11111111-2222-3333-4444-555555555555"


class FakeAttestClient:
    """Emulates the role-assignment + caller-task MCP tools in memory."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.assignments: dict[str, dict] = {}
        self.caller_tasks: list[dict] = []
        self._next = 0

    def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if name == "attest_plan_role":
            self._next += 1
            aid = f"assign-{self._next}"
            rec = {
                "AssignmentId": aid,
                "SubjectId": arguments["subjectId"],
                "Role": arguments["role"],
                "Provider": arguments["provider"],
                "PlanId": arguments["planId"],
                "Status": "Active",
                "ETag": f'W/"{self._next}"',
            }
            self.assignments[aid] = rec
            return rec
        if name == "list_plan_role_assignments":
            return {"value": list(self.assignments.values())}
        if name == "get_role_assignment":
            return self.assignments[arguments["assignmentId"]]
        if name == "revoke_role_assignment":
            rec = self.assignments.get(arguments["assignmentId"], {})
            rec["Status"] = "Revoked"
            return rec
        if name == "list_project_plan_tasks_for_caller":
            return {"value": list(self.caller_tasks)}
        raise McpError(f"unknown tool {name}")


def _client(**kw) -> AttestationClient:
    kw.setdefault("plan_id", PLAN)
    kw.setdefault("tenant_id", TENANT)
    kw.setdefault("project_id", PROJECT)
    return AttestationClient(FakeAttestClient(), **kw)


# --- pure validation --------------------------------------------------------- #

def test_is_oid():
    assert is_oid(SUBJECT)
    assert not is_oid("not-a-guid")
    assert not is_oid("")
    assert not is_oid(None)


def test_validate_attestation_derives_provider():
    role, provider = validate_attestation(SUBJECT, "WorkdayAdmin")
    assert (role, provider) == ("WorkdayAdmin", "External")
    role, provider = validate_attestation(SUBJECT, "Environment Maker")
    assert (role, provider) == ("Environment Maker", "PowerPlatform")


def test_validate_attestation_resolves_display_name():
    # Free-typed display name resolves to the compact wire id.
    role, provider = validate_attestation(SUBJECT, "Workday Administrator")
    assert (role, provider) == ("WorkdayAdmin", "External")


def test_validate_attestation_rejects_bad_oid():
    with pytest.raises(AttestationError) as e:
        validate_attestation("someone@contoso.com", "WorkdayAdmin")
    assert "subjectId" in str(e.value)


def test_validate_attestation_rejects_non_attestable_role():
    with pytest.raises(AttestationError) as e:
        validate_attestation(SUBJECT, "AgentOwner")     # internal authority role
    assert "must be one of" in str(e.value)


def test_validate_attestation_rejects_unknown_role():
    with pytest.raises(AttestationError):
        validate_attestation(SUBJECT, "workday-admin")  # slug is not a role


def test_validate_attestation_rejects_wrong_provider():
    with pytest.raises(AttestationError) as e:
        validate_attestation(SUBJECT, "WorkdayAdmin", "Entra")
    assert "not owned by the supplied provider" in str(e.value)


# --- client argument shaping ------------------------------------------------- #

def test_attest_shapes_args_and_derives_provider():
    c = _client()
    rec = c.attest(SUBJECT, "Workday Administrator", idempotency_key="k1")
    attest_calls = [(n, a) for (n, a) in c.client.calls if n == "attest_plan_role"]
    assert len(attest_calls) == 1                       # one POST, plus a verify readback
    _, args = attest_calls[0]
    assert args == {
        "tenantId": TENANT, "planId": PLAN, "subjectId": SUBJECT,
        "role": "WorkdayAdmin", "provider": "External", "idempotencyKey": "k1",
    }
    assert rec["Role"] == "WorkdayAdmin"


def test_attest_requires_tenant():
    c = _client(tenant_id=None)
    with pytest.raises(AttestationError) as e:
        c.attest(SUBJECT, "WorkdayAdmin")
    assert "tenant_id is required" in str(e.value)


def test_list_and_get_and_revoke_round_trip():
    c = _client()
    c.attest(SUBJECT, "WorkdayAdmin")
    listed = c.list_assignments(subject_id=SUBJECT)
    assert len(listed) == 1
    aid = listed[0]["AssignmentId"]
    got = c.get_assignment(aid)
    assert got["SubjectId"] == SUBJECT
    revoked = c.revoke(aid)
    assert revoked["Status"] == "Revoked"


def test_list_assignments_resolves_role_filter():
    c = _client()
    c.list_assignments(role="Workday Administrator")
    name, args = c.client.calls[-1]
    assert name == "list_plan_role_assignments"
    assert args["role"] == "WorkdayAdmin"       # resolved to the wire id


def test_tasks_for_caller_shapes_project_scoped_args():
    c = _client()
    c.client.caller_tasks = [{"TaskId": "t1", "Title": "Do Workday thing"}]
    tasks = c.tasks_for_caller(SUBJECT)
    name, args = c.client.calls[-1]
    assert name == "list_project_plan_tasks_for_caller"
    assert args == {"projectId": PROJECT, "planId": PLAN, "callerId": SUBJECT}
    assert tasks[0]["TaskId"] == "t1"


def test_tasks_for_caller_requires_project():
    c = _client(project_id=None)
    with pytest.raises(AttestationError) as e:
        c.tasks_for_caller(SUBJECT)
    assert "project_id is required" in str(e.value)
