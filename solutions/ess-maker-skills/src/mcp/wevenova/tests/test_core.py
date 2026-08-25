# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the WeveNova MCP core logic.

These exercise :mod:`core` directly with a fake upstream sender and a temp token
directory, so they run without the ``mcp`` package installed and without any
network access. Run from this directory or the package root:

    python -m unittest discover -s tests
    python -m unittest tests.test_core
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402  # pylint: disable=wrong-import-position


class Recorder:
    """Fake upstream sender that records calls and returns a canned response."""

    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response or {
            "ok": True,
            "status": 200,
            "statusText": "OK",
            "text": '{"value": []}',
        }

    def __call__(self, url, method, headers, body):
        self.calls.append({"url": url, "method": method, "headers": headers, "body": body})
        return self.response

    @property
    def last(self) -> dict:
        return self.calls[-1]

    def json_body(self) -> dict:
        return json.loads(self.last["body"])


class WeveNovaCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="weve-test-")
        self.token_dir = os.path.join(self.tmp, "tokens")
        os.makedirs(self.token_dir, exist_ok=True)
        with open(os.path.join(self.token_dir, "default.txt"), "w", encoding="utf-8") as handle:
            handle.write("test-token\n")
        self.config = core.WeveNovaConfig(
            projects_url="https://weve.example/api/beta/agentConfigurationProjects",
            tenants_url="https://weve.example/api/beta/tenants",
            token_directory=self.token_dir,
            default_user_name="default",
            user_cache_file=":memory:",
            log_file=":memory:",
            tasks_resource="agentPlanTasks",
            upstream_timeout=5.0,
        )

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, name, args, rec=None, **kwargs):
        rec = rec or Recorder()
        result = core.call_wevenova(self.config, name, args, send=rec, **kwargs)
        return rec, result

    # --- discovery / static -------------------------------------------------

    def test_lifecycle_rules_keys(self):
        _, result = self.call("get_wevenova_lifecycle_rules", {})
        self.assertEqual(set(result).issuperset({"project", "plan", "task"}), True)
        self.assertFalse(result["project"]["canDelete"])
        self.assertFalse(result["plan"]["canDelete"])
        self.assertTrue(result["task"]["canDelete"])

    def test_list_task_roles_has_twelve(self):
        _, result = self.call("list_task_roles", {})
        roles = result["roles"]
        self.assertEqual(len(roles), 12)
        self.assertTrue(any(r["role"] == "AgentOwner" and r["attestable"] is False for r in roles))
        self.assertTrue(any(r["role"] == "WorkdayAdmin" and r["attestable"] is True for r in roles))

    def test_find_users_by_name(self):
        cache = {
            "aad-1": {
                "aadId": "AAD-1",
                "displayName": "Ada Lovelace",
                "alias": "ada",
                "emailAddress": "ada@contoso.com",
                "tenantId": "t-1",
            }
        }
        _, result = self.call("find_users_by_name", {"name": "ada"}, user_cache=cache)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["users"][0]["aadId"], "AAD-1")
        self.assertEqual(result["users"][0]["tenantId"], "t-1")

    # --- auth ---------------------------------------------------------------

    def test_authorization_bearer_header(self):
        rec, _ = self.call("get_project_plan", {"projectId": "p1", "planId": "pl1"})
        auth = rec.last["headers"]["Authorization"]
        self.assertTrue(auth.startswith("Bearer "))
        self.assertTrue(auth.endswith("test-token"))

    def test_missing_token_file_errors(self):
        with self.assertRaises(core.WeveNovaError):
            self.call("get_project_plan", {"projectId": "p1", "planId": "pl1", "userName": "ghost"})

    # --- projects / plans URL shapes ---------------------------------------

    def test_get_project_plan_url_and_no_body_headers(self):
        rec, _ = self.call("get_project_plan", {"projectId": "p1", "planId": "pl1"})
        self.assertEqual(rec.last["method"], "GET")
        self.assertIn("agentConfigurationProjects('p1')/agentPlans('pl1')", rec.last["url"])
        self.assertNotIn("If-Match", rec.last["headers"])
        self.assertNotIn("Content-Type", rec.last["headers"])

    def test_get_project_plan_select_query_encoding(self):
        rec, _ = self.call("get_project_plan", {"projectId": "p1", "planId": "pl1", "query": {"select": "Id,Status"}})
        self.assertIn("%24select=Id%2CStatus", rec.last["url"])

    def test_list_project_plan_tasks_path(self):
        rec, _ = self.call("list_project_plan_tasks", {"projectId": "p1", "planId": "pl1"})
        self.assertEqual(rec.last["method"], "GET")
        self.assertTrue(rec.last["url"].endswith("agentPlans('pl1')/agentPlanTasks"))

    def test_update_project_plan_patch_if_match(self):
        rec, _ = self.call(
            "update_project_plan",
            {"projectId": "p1", "planId": "pl1", "patch": {"Status": "Active"}, "etag": 'W/"3"'},
        )
        self.assertEqual(rec.last["method"], "PATCH")
        self.assertEqual(rec.last["headers"]["If-Match"], 'W/"3"')
        self.assertEqual(rec.last["headers"]["Content-Type"], "application/json")
        self.assertEqual(rec.json_body(), {"Status": "Active"})

    def test_archive_project_uses_state_archived(self):
        rec, _ = self.call("archive_agent_configuration_project", {"projectId": "p1", "etag": '"9"'})
        self.assertEqual(rec.last["method"], "PATCH")
        self.assertEqual(rec.last["headers"]["If-Match"], '"9"')
        self.assertEqual(rec.json_body(), {"state": "Archived"})

    # --- tasks --------------------------------------------------------------

    def test_create_project_plan_task_post_body_and_idempotency(self):
        rec, _ = self.call(
            "create_project_plan_task",
            {
                "projectId": "p1",
                "planId": "pl1",
                "task": {"title": "Do it", "assignedToId": "u-1"},
                "idempotencyKey": "k-123",
            },
        )
        self.assertEqual(rec.last["method"], "POST")
        self.assertTrue(rec.last["url"].endswith("agentPlans('pl1')/agentPlanTasks"))
        self.assertEqual(rec.last["headers"]["Idempotency-Key"], "k-123")
        self.assertEqual(rec.json_body()["title"], "Do it")

    def test_create_role_assigned_task_validates_and_shapes_body(self):
        with self.assertRaises(core.WeveNovaError):
            self.call(
                "create_role_assigned_project_plan_task",
                {"projectId": "p1", "planId": "pl1", "role": "NotARole", "title": "x"},
            )
        rec, _ = self.call(
            "create_role_assigned_project_plan_task",
            {"projectId": "p1", "planId": "pl1", "role": "AgentOwner", "title": "Own it"},
        )
        body = rec.json_body()
        self.assertEqual(body["assignedToType"], "Role")
        self.assertEqual(body["assignedToId"], "AgentOwner")
        self.assertEqual(body["assignedToRoleId"], "AgentOwner")

    def test_update_task_rejects_unknown_patch_key(self):
        with self.assertRaises(core.WeveNovaError):
            self.call(
                "update_project_plan_task",
                {"projectId": "p1", "planId": "pl1", "taskId": "t1", "patch": {"State": "InProgress"}, "etag": '"1"'},
            )

    def test_update_task_claim_only_assigned_to_id(self):
        rec, _ = self.call(
            "update_project_plan_task",
            {"projectId": "p1", "planId": "pl1", "taskId": "t1", "patch": {"AssignedToId": "u-9"}, "etag": '"1"'},
        )
        self.assertEqual(rec.last["method"], "PATCH")
        self.assertTrue(rec.last["url"].endswith("agentPlanTasks('t1')"))
        self.assertEqual(rec.json_body(), {"AssignedToId": "u-9"})

    def test_set_task_state_validates(self):
        with self.assertRaises(core.WeveNovaError):
            self.call(
                "set_project_plan_task_state",
                {"projectId": "p1", "planId": "pl1", "taskId": "t1", "state": "Bogus", "etag": '"1"'},
            )
        rec, _ = self.call(
            "set_project_plan_task_state",
            {"projectId": "p1", "planId": "pl1", "taskId": "t1", "state": "InProgress", "etag": '"1"'},
        )
        self.assertEqual(rec.json_body(), {"State": "InProgress"})

    def test_complete_task_maps_outputs(self):
        rec, _ = self.call(
            "complete_project_plan_task",
            {
                "projectId": "p1",
                "planId": "pl1",
                "taskId": "t1",
                "etag": '"1"',
                "outputs": [
                    {
                        "key": "env",
                        "kind": "Environment",
                        "attributes": [{"key": "environmentId", "value": "e-1", "description": "the env"}],
                    }
                ],
            },
        )
        body = rec.json_body()
        self.assertEqual(body["State"], "Completed")
        self.assertEqual(
            body["Outputs"],
            [
                {
                    "Key": "env",
                    "Kind": "Environment",
                    "Attributes": [{"Key": "environmentId", "Value": "e-1", "Description": "the env"}],
                }
            ],
        )

    def test_complete_task_environment_requires_environment_id(self):
        with self.assertRaises(core.WeveNovaError):
            self.call(
                "complete_project_plan_task",
                {
                    "projectId": "p1",
                    "planId": "pl1",
                    "taskId": "t1",
                    "etag": '"1"',
                    "outputs": [{"key": "env", "kind": "Environment", "attributes": [{"key": "foo", "value": "bar"}]}],
                },
            )

    # --- role assignments (tenant-sharded) ---------------------------------

    def test_attest_plan_role_post_no_if_match(self):
        rec, _ = self.call(
            "attest_plan_role",
            {"tenantId": "tn1", "planId": "pl1", "subjectId": "s1", "role": "WorkdayAdmin", "provider": "External"},
        )
        self.assertEqual(rec.last["method"], "POST")
        self.assertTrue(rec.last["url"].endswith("tenants('tn1')/agentRoleAssignments/attest"))
        self.assertNotIn("If-Match", rec.last["headers"])
        body = rec.json_body()
        self.assertEqual(body["target"], {"type": "Plan", "id": "pl1"})
        self.assertEqual(body["provider"], "External")

    def test_attest_plan_role_invalid_provider(self):
        with self.assertRaises(core.WeveNovaError):
            self.call(
                "attest_plan_role",
                {"tenantId": "tn1", "planId": "pl1", "subjectId": "s1", "role": "WorkdayAdmin", "provider": "Nope"},
            )

    def test_revoke_role_assignment_delete_if_match(self):
        rec, _ = self.call("revoke_role_assignment", {"tenantId": "tn1", "assignmentId": "a1", "etag": '"7"'})
        self.assertEqual(rec.last["method"], "DELETE")
        self.assertTrue(rec.last["url"].endswith("tenants('tn1')/agentRoleAssignments('a1')"))
        self.assertEqual(rec.last["headers"]["If-Match"], '"7"')

    def test_list_plan_role_assignments_filter(self):
        rec, _ = self.call("list_plan_role_assignments", {"tenantId": "tn1", "planId": "pl1", "subjectId": "s1"})
        self.assertIn("%24filter=", rec.last["url"])
        self.assertIn("targetPlanId", rec.last["url"])
        self.assertIn("subjectObjectId", rec.last["url"])

    # --- transport error surfacing -----------------------------------------

    def test_upstream_non_2xx_raises(self):
        rec = Recorder({"ok": False, "status": 409, "statusText": "Conflict", "text": '{"error":"etag"}'})
        with self.assertRaises(core.WeveNovaError) as ctx:
            self.call("get_project_plan", {"projectId": "p1", "planId": "pl1"}, rec=rec)
        self.assertIn("409", str(ctx.exception))

    def test_removed_delete_plan_tool_errors(self):
        with self.assertRaises(core.WeveNovaError):
            self.call("delete_project_plan", {"projectId": "p1", "planId": "pl1"})

    def test_unknown_tool_errors(self):
        with self.assertRaises(core.WeveNovaError):
            self.call("not_a_tool", {})


if __name__ == "__main__":
    unittest.main()
