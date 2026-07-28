# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the flow-selection scoping in ``validate.py``.

``_select_validate_flows`` decides which mapped flows a no-arg ``validate.py``
run judges pass/fail on. The default scopes to maker-authored flows (those with
a local ``workflow.json`` on disk) so solution/pack-installed orchestrators —
which register their connection differently and would spuriously show NOT READY
— never fail the run. An explicit name filter or ``--all`` widens to every
mapped flow.
"""

import validate


class TestSelectValidateFlows:
    MAP = {
        "workflows/authored-a/workflow.json": {
            "workflowid": "aaa", "name": "Authored A"},
        "workflows/authored-b/workflow.json": {
            "workflowid": "bbb", "name": "Authored B"},
        "workflows/pack-orch/workflow.json": {
            "workflowid": "ccc", "name": "Pack Orchestrator"},
        "botcomponents/Foo/data": {"botcomponentid": "ddd"},
    }
    ON_DISK = {
        "workflows/authored-a/workflow.json",
        "workflows/authored-b/workflow.json",
    }

    def test_default_scopes_to_on_disk_authored_flows(self):
        flows, skipped = validate._select_validate_flows(self.MAP, self.ON_DISK)
        paths = {f[0] for f in flows}
        assert paths == self.ON_DISK
        # The pack orchestrator (has workflowid, not on disk) is scoped out.
        assert skipped == 1

    def test_default_excludes_entries_without_workflowid(self):
        flows, _ = validate._select_validate_flows(self.MAP, self.ON_DISK)
        assert all(f[1] for f in flows)
        assert "ddd" not in {f[1] for f in flows}

    def test_include_all_returns_every_mapped_flow(self):
        flows, skipped = validate._select_validate_flows(
            self.MAP, self.ON_DISK, include_all=True)
        assert {f[1] for f in flows} == {"aaa", "bbb", "ccc"}
        assert skipped == 0

    def test_name_filter_widens_to_all_and_matches_name_ci(self):
        flows, skipped = validate._select_validate_flows(
            self.MAP, self.ON_DISK, name_filter="pack")
        assert {f[1] for f in flows} == {"ccc"}
        assert skipped == 0

    def test_name_filter_matches_workflowid(self):
        flows, _ = validate._select_validate_flows(
            self.MAP, self.ON_DISK, name_filter="aaa")
        assert {f[1] for f in flows} == {"aaa"}

    def test_flow_tuple_carries_name_falling_back_to_path(self):
        cmap = {"workflows/x/workflow.json": {"workflowid": "xxx"}}
        on_disk = {"workflows/x/workflow.json"}
        flows, _ = validate._select_validate_flows(cmap, on_disk)
        assert flows == [("workflows/x/workflow.json", "xxx",
                          "workflows/x/workflow.json")]


class TestValidateIsGating:
    """A no-arg / --all overview is informational (exit 0) because validate
    cannot reliably tell a maker-pushed flow from a solution-installed one.
    Gating (non-zero exit on NOT READY) requires an explicit scope: a named
    flow or --strict.
    """

    def test_named_flow_gates(self):
        assert validate._validate_is_gating("create-ticket", False) is True

    def test_strict_gates(self):
        assert validate._validate_is_gating(None, True) is True

    def test_default_is_informational(self):
        assert validate._validate_is_gating(None, False) is False
