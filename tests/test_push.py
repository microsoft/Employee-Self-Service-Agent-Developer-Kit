# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared console behavior and surviving read-only registration diagnostics."""

import push
import flow_registration as registration


class _FakeStream:
    """Minimal text-stream stand-in for _ensure_utf8_stdout tests.

    Records a reconfigure(...) call so a test can assert both that it fired
    and with which encoding/errors. Set ``supports_reconfigure=False`` to
    model a stream (e.g. a pytest capture buffer) that has no reconfigure.
    """

    def __init__(self, encoding, *, supports_reconfigure=True):
        self.encoding = encoding
        self._supports_reconfigure = supports_reconfigure
        self.reconfigure_calls = []
        if supports_reconfigure:
            self.reconfigure = self._reconfigure

    def _reconfigure(self, *, encoding=None, errors=None):
        self.reconfigure_calls.append({"encoding": encoding, "errors": errors})
        self.encoding = encoding



class TestEnsureUtf8Stdout:
    """push.py prints emoji status glyphs (✅/❌/➕). On a legacy Windows
    console (cp1252) those raise UnicodeEncodeError and abort the push
    mid-run. Every sibling CLI script guards against this by reconfiguring
    stdout to UTF-8; push.py was missing the guard (adk-gap-push-unicode).
    """

    def test_reconfigures_a_legacy_codepage_stream(self):
        stream = _FakeStream("cp1252")
        assert push._ensure_utf8_stdout(stream) is True
        assert stream.reconfigure_calls == [
            {"encoding": "utf-8", "errors": "replace"}
        ]

    def test_is_a_noop_when_already_utf8(self):
        stream = _FakeStream("utf-8")
        assert push._ensure_utf8_stdout(stream) is False
        assert stream.reconfigure_calls == []

    def test_is_case_insensitive_about_utf8(self):
        stream = _FakeStream("UTF-8")
        assert push._ensure_utf8_stdout(stream) is False
        assert stream.reconfigure_calls == []

    def test_handles_stream_without_encoding(self):
        stream = _FakeStream(None)
        assert push._ensure_utf8_stdout(stream) is False
        assert stream.reconfigure_calls == []

    def test_handles_stream_without_reconfigure(self):
        # A capture buffer with a legacy encoding but no reconfigure() must
        # not raise — the guard degrades to a no-op.
        stream = _FakeStream("cp1252", supports_reconfigure=False)
        assert push._ensure_utf8_stdout(stream) is False



class TestFlowConnrefDeleteFilter:
    """registration._flow_connref_delete_filter builds the OData filter that selects a
    flow's flow-scoped connection references for cleanup on flow-delete. push
    mints connrefs named `{schema}.{workflowid}.{connector}` on create; without
    symmetric deletion they orphan when the flow is removed.
    """

    def test_matches_all_connrefs_for_the_workflow(self):
        f = registration._flow_connref_delete_filter(
            "msdyn_copilotforemployeeselfserviceit",
            "8e518921-4c1b-4c57-beb1-05c850e1f4c9",
        )
        assert f == (
            "startswith(connectionreferencelogicalname,"
            "'msdyn_copilotforemployeeselfserviceit."
            "8e518921-4c1b-4c57-beb1-05c850e1f4c9.')"
        )

    def test_escapes_single_quotes(self):
        f = registration._flow_connref_delete_filter("a'b", "wf")
        assert "a''b" in f



class TestEvaluateFlowRegistration:
    """registration._evaluate_flow_registration composes the agent-invocability checks
    for a created flow into a readiness report (the post-push validation that
    mirrors the manual 5-step check).
    """

    def _ready_facts(self):
        return dict(
            statecode=1, statuscode=2, modernflowtype=1,
            response_kinds=["Skills", "Skills"],
            connref_bound_count=1, link_count=1,
        )

    def test_all_checks_pass_is_ready(self):
        r = registration._evaluate_flow_registration(**self._ready_facts())
        assert r["ready"] is True
        assert all(r["checks"].values())

    def test_not_activated_fails(self):
        f = self._ready_facts()
        f["statecode"], f["statuscode"] = 0, 1  # Draft
        r = registration._evaluate_flow_registration(**f)
        assert r["ready"] is False
        assert r["checks"]["activated"] is False

    def test_wrong_modernflowtype_fails(self):
        f = self._ready_facts()
        f["modernflowtype"] = 0
        r = registration._evaluate_flow_registration(**f)
        assert r["checks"]["modern_flow"] is False
        assert r["ready"] is False

    def test_non_skills_response_fails(self):
        f = self._ready_facts()
        f["response_kinds"] = ["Skills", "PowerApp"]
        r = registration._evaluate_flow_registration(**f)
        assert r["checks"]["response_skills"] is False

    def test_no_response_actions_fails(self):
        f = self._ready_facts()
        f["response_kinds"] = []
        r = registration._evaluate_flow_registration(**f)
        assert r["checks"]["response_skills"] is False

    def test_missing_connref_fails(self):
        f = self._ready_facts()
        f["connref_bound_count"] = 0
        r = registration._evaluate_flow_registration(**f)
        assert r["checks"]["flow_scoped_connref"] is False

    def test_missing_link_fails(self):
        f = self._ready_facts()
        f["link_count"] = 0
        r = registration._evaluate_flow_registration(**f)
        assert r["checks"]["botcomponent_workflow_link"] is False



class TestFlowResponseKinds:
    """registration._flow_response_kinds lists the kind of every Response action in a
    flow's clientdata (for the readiness report). Empty list on invalid JSON."""

    def test_lists_all_response_kinds(self):
        import json
        wf = {"properties": {"definition": {"actions": {
            "If1": {"type": "If",
                    "actions": {"R1": {"type": "Response", "kind": "Skills"}},
                    "else": {"actions": {
                        "R2": {"type": "Response", "kind": "PowerApp"}}}},
            "R3": {"type": "Response"},  # missing kind
            "X": {"type": "Compose"},
        }}}}
        kinds = registration._flow_response_kinds(json.dumps(wf))
        assert sorted(k or "" for k in kinds) == ["", "PowerApp", "Skills"]

    def test_empty_on_invalid_json(self):
        assert registration._flow_response_kinds("{nope") == []

    def test_empty_when_no_responses(self):
        import json
        assert registration._flow_response_kinds(
            json.dumps({"properties": {"definition": {"actions": {}}}})) == []
