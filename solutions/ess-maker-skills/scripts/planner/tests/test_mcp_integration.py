from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from planner.mcp_client import McpError
from planner.plan_store import McpPlanStore, PlanStoreError


class FakeClient:
    def __init__(self, *, plan_status: str = "Active", conflict_once: bool = False):
        self.plan_status = plan_status
        self.conflict_once = conflict_once
        self.task_reads = 0
        self.calls: list[tuple[str, dict]] = []

    def lifecycle_rules(self):
        return {
            "planActivationRule": "Only the plan resource owner may activate it."
        }

    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == "get_project_plan":
            return {
                "PlanId": "plan-1",
                "Status": self.plan_status,
                "OwnedById": "owner-1",
                "ETag": 'W/"9"',
            }
        if name == "get_project_plan_task":
            self.task_reads += 1
            return {
                "TaskId": "task-1",
                "State": "NotStarted",
                "ETag": f'W/"{self.task_reads}"',
            }
        if name == "set_project_plan_task_state":
            if self.conflict_once:
                self.conflict_once = False
                raise McpError("ETag conflict: If-Match did not match")
            return {"TaskId": "task-1", "State": arguments["state"]}
        raise AssertionError(f"unexpected tool {name}")


class McpPlanStoreIntegrationTests(unittest.TestCase):
    def store(self, client: FakeClient) -> McpPlanStore:
        summary = os.path.join(tempfile.gettempdir(), "mcp-plan-test.md")
        return McpPlanStore(
            client,
            summary,
            project_id="project-1",
            plan_id="plan-1",
        )

    def test_task_mutation_uses_direct_task_etag(self):
        client = FakeClient()
        store = self.store(client)
        store._mutate_task(
            "set_project_plan_task_state", "task-1", {"state": "InProgress"}
        )
        mutation = next(
            args for name, args in client.calls if name == "set_project_plan_task_state"
        )
        self.assertEqual(mutation["etag"], 'W/"1"')

    def test_etag_conflict_retries_once_with_new_direct_read(self):
        client = FakeClient(conflict_once=True)
        store = self.store(client)
        store._mutate_task(
            "set_project_plan_task_state", "task-1", {"state": "InProgress"}
        )
        mutations = [
            args for name, args in client.calls if name == "set_project_plan_task_state"
        ]
        self.assertEqual([m["etag"] for m in mutations], ['W/"1"', 'W/"2"'])

    def test_draft_plan_stops_before_state_mutation(self):
        client = FakeClient(plan_status="Draft")
        store = self.store(client)
        with self.assertRaisesRegex(PlanStoreError, "must be activated"):
            store._require_active_plan()
        self.assertFalse(
            any(name == "set_project_plan_task_state" for name, _ in client.calls)
        )

    def test_draft_plan_stops_before_partial_content_update(self):
        client = FakeClient(plan_status="Draft")
        store = self.store(client)
        current = {"Title": "Before", "State": "NotStarted"}
        desired = {"Title": "After", "State": "InProgress"}
        with self.assertRaisesRegex(PlanStoreError, "must be activated"):
            store._update_task("task-1", desired, current)
        self.assertFalse(
            any(
                name in {"update_project_plan_task", "set_project_plan_task_state"}
                for name, _ in client.calls
            )
        )


if __name__ == "__main__":
    unittest.main()
