# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the deploy-target resolution + environment-SKU caching in
``push.py`` (ADO 7609605).

``_resolve_deploy_target`` classifies an agent.deploy telemetry event into
``sandbox`` vs ``production`` from the target environment's Power Platform SKU.
The resolution priority is:
  1. explicit ``ESS_ADK_DEPLOY_TARGET`` override (returned verbatim),
  2. ``environmentSku`` cached in config,
  3. best-effort silent BAP lookup (cached back to config),
  4. ``production`` default.

The silent BAP lookup itself (network + MSAL) is intentionally NOT unit-tested
here — it is best-effort and swallows all errors — so these tests monkeypatch
``_lookup_environment_sku_silent``/``_cache_environment_sku`` to pin only the
orchestration logic.
"""

from __future__ import annotations

import json
import os

import push


class TestResolveDeployTarget:
    def test_valid_override_wins_and_skips_lookup(self, monkeypatch):
        # A current-bucket override (case-insensitive) is honored and short-
        # circuits both the cached SKU and any BAP lookup.
        monkeypatch.setattr(
            push, "_lookup_environment_sku_silent",
            lambda url: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        for raw, expected in (("production", "production"), ("SANDBOX", "sandbox")):
            monkeypatch.setenv("ESS_ADK_DEPLOY_TARGET", raw)
            assert push._resolve_deploy_target(
                {"environmentSku": "Sandbox"}, "https://x.crm.dynamics.com"
            ) == expected

    def test_retired_override_is_ignored(self, monkeypatch):
        # Stale test/staging values must NOT resurface retired buckets — fall
        # through to SKU classification instead.
        for raw in ("test", "staging", "some-custom-label"):
            monkeypatch.setenv("ESS_ADK_DEPLOY_TARGET", raw)
            assert push._resolve_deploy_target({"environmentSku": "Sandbox"}, "url") == "sandbox"
            assert push._resolve_deploy_target({"environmentSku": "Production"}, "url") == "production"

    def test_blank_override_is_ignored(self, monkeypatch):
        monkeypatch.setenv("ESS_ADK_DEPLOY_TARGET", "   ")
        assert push._resolve_deploy_target({"environmentSku": "Sandbox"}, "") == "sandbox"

    def test_cached_sku_classified_without_lookup(self, monkeypatch):
        monkeypatch.delenv("ESS_ADK_DEPLOY_TARGET", raising=False)
        monkeypatch.setattr(
            push, "_lookup_environment_sku_silent",
            lambda url: (_ for _ in ()).throw(AssertionError("cached SKU should win")),
        )
        assert push._resolve_deploy_target({"environmentSku": "Sandbox"}, "url") == "sandbox"
        assert push._resolve_deploy_target({"environmentSku": "Production"}, "url") == "production"

    def test_silent_lookup_used_and_cached_when_no_cached_sku(self, monkeypatch):
        monkeypatch.delenv("ESS_ADK_DEPLOY_TARGET", raising=False)
        monkeypatch.setattr(push, "_lookup_environment_sku_silent", lambda url: "Sandbox")
        cached = {}
        monkeypatch.setattr(
            push, "_cache_environment_sku", lambda sku: cached.__setitem__("sku", sku)
        )
        assert push._resolve_deploy_target({}, "https://x.crm.dynamics.com") == "sandbox"
        assert cached["sku"] == "Sandbox"  # discovered SKU is persisted

    def test_defaults_to_production_when_lookup_returns_none(self, monkeypatch):
        monkeypatch.delenv("ESS_ADK_DEPLOY_TARGET", raising=False)
        monkeypatch.setattr(push, "_lookup_environment_sku_silent", lambda url: None)
        monkeypatch.setattr(push, "_cache_environment_sku", lambda sku: None)
        assert push._resolve_deploy_target({}, "") == "production"


class TestCacheEnvironmentSku:
    def test_writes_sku_into_config(self, chdir_kit_root):
        push._cache_environment_sku("Sandbox")
        with open(os.path.join(".local", "config.json"), encoding="utf-8") as f:
            data = json.load(f)
        assert data["environmentSku"] == "Sandbox"

    def test_empty_sku_is_noop(self, chdir_kit_root):
        push._cache_environment_sku("")
        with open(os.path.join(".local", "config.json"), encoding="utf-8") as f:
            data = json.load(f)
        assert "environmentSku" not in data


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


class TestWorkflowCreatePayload:
    """The Dataverse ``workflows`` create payload for an agent flow.

    A Copilot Studio agent flow must be created as ``modernflowtype=1``
    (CopilotStudioFlow); the historical default of 0 (PowerAutomateFlow) is
    the root cause of the runtime ``flowNotFound`` — the agent cannot resolve
    a modernflowtype=0 workflow as one of its flows (adk-fix-2-modernflowtype).
    The other attributes carry the modern-flow defaults, each overridable from
    the flow's companion ``metadata.yml``.
    """

    def test_defaults_mark_it_a_copilot_studio_modern_flow(self):
        payload = push._workflow_create_payload(
            {}, name="Options flow", clientdata="{}", description="",
        )
        assert payload["modernflowtype"] == 1
        assert payload["category"] == 5   # Modern Flow
        assert payload["type"] == 1       # Definition
        assert payload["primaryentity"] == "none"
        assert payload["mode"] == 0
        assert payload["scope"] == 4

    def test_passes_through_name_clientdata_description(self):
        payload = push._workflow_create_payload(
            {}, name="My Flow", clientdata='{"x":1}', description="does a thing",
        )
        assert payload["name"] == "My Flow"
        assert payload["clientdata"] == '{"x":1}'
        assert payload["description"] == "does a thing"

    def test_metadata_overrides_every_default(self):
        meta = {
            "modernflowtype": 0,
            "category": 6,
            "type": 2,
            "primaryentity": "incident",
            "mode": 1,
            "scope": 1,
        }
        payload = push._workflow_create_payload(
            meta, name="f", clientdata="{}", description="",
        )
        assert payload["modernflowtype"] == 0
        assert payload["category"] == 6
        assert payload["type"] == 2
        assert payload["primaryentity"] == "incident"
        assert payload["mode"] == 1
        assert payload["scope"] == 1

    def test_none_metadata_is_treated_as_empty(self):
        payload = push._workflow_create_payload(
            None, name="f", clientdata="{}", description="",
        )
        assert payload["modernflowtype"] == 1
        assert payload["category"] == 5

    def test_preserves_client_workflow_id_from_metadata(self):
        # The maker authors one client GUID and uses it as BOTH the workflow's
        # metadata.yml workflowId AND the topic's InvokeFlowAction flowId.
        # Sending it as the created record's `workflowid` keeps the two in
        # sync so the agent can resolve the flow (no flowNotFound) and the
        # botcomponent_workflow link is derivable.
        meta = {"workflowId": "d4e5f6a7-b8c9-4d0e-8f1a-2b3c4d5e6f7a"}
        payload = push._workflow_create_payload(
            meta, name="f", clientdata="{}", description="",
        )
        assert payload["workflowid"] == "d4e5f6a7-b8c9-4d0e-8f1a-2b3c4d5e6f7a"

    def test_omits_workflowid_when_metadata_lacks_it(self):
        # No client GUID → let Dataverse assign one (create_record reads it
        # back from the OData-EntityId header).
        payload = push._workflow_create_payload(
            {}, name="f", clientdata="{}", description="",
        )
        assert "workflowid" not in payload


class TestExtractFlowIds:
    """push._extract_flow_ids parses a topic's clientdata (YAML) for the
    flowId of every InvokeFlowAction. With the client GUID preserved on
    workflow create (workflowid == flowId), these are exactly the workflow
    records a system topic must be botcomponent_workflow-linked to.
    """

    def test_finds_single_invoke_flow_action_flow_id(self):
        content = (
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: OnRedirect\n"
            "  actions:\n"
            "    - kind: InvokeFlowAction\n"
            "      id: invokeFlowAction_x\n"
            "      flowId: 521ce2a6-daaa-f011-bbd2-0022480b25f5\n"
        )
        assert push._extract_flow_ids(content) == [
            "521ce2a6-daaa-f011-bbd2-0022480b25f5"
        ]

    def test_finds_multiple_flow_ids(self):
        content = (
            "actions:\n"
            "  - kind: InvokeFlowAction\n"
            "    flowId: 11111111-1111-1111-1111-111111111111\n"
            "  - kind: SendActivity\n"
            "    activity: hi\n"
            "  - kind: InvokeFlowAction\n"
            "    flowId: 22222222-2222-2222-2222-222222222222\n"
        )
        assert push._extract_flow_ids(content) == [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]

    def test_returns_empty_for_topic_without_a_flow(self):
        content = (
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  actions:\n"
            "    - kind: SendActivity\n"
            "      activity: hello\n"
        )
        assert push._extract_flow_ids(content) == []

    def test_ignores_a_flow_id_key_not_under_invoke_flow_action(self):
        # A stray flowId not attached to an InvokeFlowAction kind must not be
        # treated as an invoked flow.
        content = (
            "someOtherBlock:\n"
            "  kind: SendActivity\n"
            "  flowId: 33333333-3333-3333-3333-333333333333\n"
        )
        assert push._extract_flow_ids(content) == []

    def test_returns_empty_on_unparseable_yaml(self):
        assert push._extract_flow_ids("{ this: is: not: valid") == []

    def test_deduplicates_repeated_flow_ids(self):
        content = (
            "actions:\n"
            "  - kind: InvokeFlowAction\n"
            "    flowId: 44444444-4444-4444-4444-444444444444\n"
            "elseActions:\n"
            "  - kind: InvokeFlowAction\n"
            "    flowId: 44444444-4444-4444-4444-444444444444\n"
        )
        assert push._extract_flow_ids(content) == [
            "44444444-4444-4444-4444-444444444444"
        ]


class TestPlanTopicWorkflowLinks:
    """push._plan_topic_workflow_links pairs each pushed system topic with the
    workflow(s) it invokes, scoped to flows CREATED in this push. Scoping to
    newly-created flows targets the new-flow-registration gap precisely: a
    fresh flow has no pre-existing botcomponent_workflow link (so no
    duplicate-link risk) and a link failure is a genuine error, while an
    unchanged flow on a re-push is not re-linked.
    """

    @staticmethod
    def _resolver(mapping):
        return lambda fp: mapping.get(fp)

    def test_pairs_topic_with_its_created_flow(self):
        wf = "d4e5f6a7-b8c9-4d0e-8f1a-2b3c4d5e6f7a"
        topic_items = [(
            "topic.mcs.yml",
            "actions:\n  - kind: InvokeFlowAction\n    flowId: " + wf + "\n",
        )]
        links = push._plan_topic_workflow_links(
            topic_items, {wf}, self._resolver({"topic.mcs.yml": "bc-1"}),
        )
        assert links == [("bc-1", wf)]

    def test_skips_flows_not_created_this_push(self):
        wf_new = "11111111-1111-1111-1111-111111111111"
        wf_existing = "22222222-2222-2222-2222-222222222222"
        topic_items = [(
            "topic.mcs.yml",
            "actions:\n"
            "  - kind: InvokeFlowAction\n    flowId: " + wf_new + "\n"
            "  - kind: InvokeFlowAction\n    flowId: " + wf_existing + "\n",
        )]
        links = push._plan_topic_workflow_links(
            topic_items, {wf_new}, self._resolver({"topic.mcs.yml": "bc-1"}),
        )
        assert links == [("bc-1", wf_new)]

    def test_skips_topics_with_no_flow(self):
        topic_items = [(
            "plain.mcs.yml",
            "actions:\n  - kind: SendActivity\n    activity: hi\n",
        )]
        links = push._plan_topic_workflow_links(
            topic_items, {"any"}, self._resolver({"plain.mcs.yml": "bc-1"}),
        )
        assert links == []

    def test_skips_when_botcomponentid_unresolvable(self):
        wf = "d4e5f6a7-b8c9-4d0e-8f1a-2b3c4d5e6f7a"
        topic_items = [(
            "topic.mcs.yml",
            "actions:\n  - kind: InvokeFlowAction\n    flowId: " + wf + "\n",
        )]
        links = push._plan_topic_workflow_links(
            topic_items, {wf}, self._resolver({}),  # no botcomponentid
        )
        assert links == []

    def test_deduplicates_pairs_across_topics(self):
        wf = "d4e5f6a7-b8c9-4d0e-8f1a-2b3c4d5e6f7a"
        block = "actions:\n  - kind: InvokeFlowAction\n    flowId: " + wf + "\n"
        topic_items = [("t.mcs.yml", block), ("t.mcs.yml", block)]
        links = push._plan_topic_workflow_links(
            topic_items, {wf}, self._resolver({"t.mcs.yml": "bc-1"}),
        )
        assert links == [("bc-1", wf)]

    def test_empty_created_set_yields_no_links(self):
        wf = "d4e5f6a7-b8c9-4d0e-8f1a-2b3c4d5e6f7a"
        topic_items = [(
            "topic.mcs.yml",
            "actions:\n  - kind: InvokeFlowAction\n    flowId: " + wf + "\n",
        )]
        links = push._plan_topic_workflow_links(
            topic_items, set(), self._resolver({"topic.mcs.yml": "bc-1"}),
        )
        assert links == []

    def test_matches_created_flow_case_insensitively(self):
        # The topic authors flowId in one case; the created-workflow id can come
        # back in another (Dataverse returns the OData-EntityId GUID canonical /
        # lowercase). A case-sensitive membership test would skip the link with
        # no error, leaving the flow non-invocable but reported as success.
        authored = "D4E5F6A7-B8C9-4D0E-8F1A-2B3C4D5E6F7A"  # topic, upper
        canonical = "d4e5f6a7-b8c9-4d0e-8f1a-2b3c4d5e6f7a"  # created, lower
        topic_items = [(
            "topic.mcs.yml",
            "actions:\n  - kind: InvokeFlowAction\n    flowId: " + authored + "\n",
        )]
        links = push._plan_topic_workflow_links(
            topic_items, {canonical}, self._resolver({"topic.mcs.yml": "bc-1"}),
        )
        # Link is planned despite the case delta, and targets the canonical id
        # (the actual Dataverse record) rather than the authored-case value.
        assert links == [("bc-1", canonical)]


class TestPlanFlowConnrefs:
    """push._plan_flow_connrefs reads a flow's authored connectionReferences and
    plans one flow-scoped connection reference per connector. Copilot Studio
    resolves an agent flow's connection through a connref named
    ``{agentSchema}.{workflowid}.{connector}``; the flow's workflow.json only
    names the shared design connref, so push must mint the flow-scoped one.
    """

    AGENT = "msdyn_copilotforemployeeselfserviceit"
    WF = "8e518921-4c1b-4c57-beb1-05c850e1f4c9"

    def test_plans_one_connref_per_connector(self):
        wf_json = {
            "properties": {
                "connectionReferences": {
                    "shared_service-now": {
                        "api": {"name": "shared_service-now"},
                        "connection": {
                            "connectionReferenceLogicalName":
                                "msdyn_copilotforemployeeselfserviceit.cr.EXAMPLE1"
                        },
                        "runtimeSource": "invoker",
                    }
                }
            }
        }
        plan = push._plan_flow_connrefs(wf_json, self.AGENT, self.WF)
        assert plan == [{
            "connector_api_name": "shared_service-now",
            "design_logical_name":
                "msdyn_copilotforemployeeselfserviceit.cr.EXAMPLE1",
            "new_logical_name":
                f"{self.AGENT}.{self.WF}.shared_service-now",
        }]

    def test_no_connection_references_yields_empty(self):
        assert push._plan_flow_connrefs(
            {"properties": {}}, self.AGENT, self.WF) == []
        assert push._plan_flow_connrefs({}, self.AGENT, self.WF) == []

    def test_skips_connector_without_a_design_connref(self):
        wf_json = {
            "properties": {
                "connectionReferences": {
                    "shared_service-now": {
                        "api": {"name": "shared_service-now"},
                        "runtimeSource": "invoker",
                    }
                }
            }
        }
        assert push._plan_flow_connrefs(wf_json, self.AGENT, self.WF) == []


class TestFlowConnrefPayload:
    """push._flow_connref_payload mirrors an existing (design) connection
    reference into the create body for a new flow-scoped connref: same
    connector, connection, and parameter-set config, new logical name.
    """

    def test_mirrors_connection_fields(self):
        mirror = {
            "connectionid": "00000000000000000000000000000001",
            "connectorid": "/providers/Microsoft.PowerApps/apis/shared_service-now",
            "connectionparametersetconfig":
                '{"name":"entraIDUserLogin","values":{}}',
        }
        payload = push._flow_connref_payload("agent.wf.shared_service-now", mirror)
        assert payload == {
            "connectionreferencelogicalname": "agent.wf.shared_service-now",
            "connectionreferencedisplayname": "agent.wf.shared_service-now",
            "connectorid":
                "/providers/Microsoft.PowerApps/apis/shared_service-now",
            "connectionid": "00000000000000000000000000000001",
            "connectionparametersetconfig":
                '{"name":"entraIDUserLogin","values":{}}',
        }

    def test_omits_parametersetconfig_when_mirror_lacks_it(self):
        mirror = {
            "connectionid": "conn-1",
            "connectorid": "/providers/.../shared_service-now",
            "connectionparametersetconfig": None,
        }
        payload = push._flow_connref_payload("agent.wf.shared_service-now", mirror)
        assert "connectionparametersetconfig" not in payload
        assert payload["connectionid"] == "conn-1"


class TestBuildConnrefMirror:
    """push._build_connref_mirror derives the connection fields for a new
    flow-scoped connref. The design connref a flow names can lack the
    parameter-set config (the shared `cr.*` connref does), while sibling
    connrefs on the SAME connection carry it — so the mirror pulls the config
    from a sibling when the design connref is missing it.
    """

    def _design(self, param):
        return {
            "connectionid": "conn-1",
            "connectorid": "/providers/.../shared_service-now",
            "connectionparametersetconfig": param,
        }

    def test_uses_design_parametersetconfig_when_present(self):
        mirror = push._build_connref_mirror(
            self._design('{"name":"entraIDUserLogin"}'), [])
        assert mirror["connectionparametersetconfig"] == '{"name":"entraIDUserLogin"}'
        assert mirror["connectionid"] == "conn-1"

    def test_pulls_config_from_same_connection_sibling(self):
        siblings = [
            {"connectionid": "conn-OTHER",
             "connectionparametersetconfig": '{"wrong":1}'},
            {"connectionid": "conn-1",
             "connectionparametersetconfig": '{"name":"entraIDUserLogin"}'},
        ]
        mirror = push._build_connref_mirror(self._design(None), siblings)
        assert mirror["connectionparametersetconfig"] == '{"name":"entraIDUserLogin"}'

    def test_ignores_sibling_config_on_a_different_connection(self):
        siblings = [
            {"connectionid": "conn-OTHER",
             "connectionparametersetconfig": '{"wrong":1}'},
        ]
        mirror = push._build_connref_mirror(self._design(None), siblings)
        assert mirror["connectionparametersetconfig"] is None

    def test_returns_none_for_missing_design(self):
        assert push._build_connref_mirror(None, []) is None


class TestFlowConnrefDeleteFilter:
    """push._flow_connref_delete_filter builds the OData filter that selects a
    flow's flow-scoped connection references for cleanup on flow-delete. push
    mints connrefs named `{schema}.{workflowid}.{connector}` on create; without
    symmetric deletion they orphan when the flow is removed.
    """

    def test_matches_all_connrefs_for_the_workflow(self):
        f = push._flow_connref_delete_filter(
            "msdyn_copilotforemployeeselfserviceit",
            "8e518921-4c1b-4c57-beb1-05c850e1f4c9",
        )
        assert f == (
            "startswith(connectionreferencelogicalname,"
            "'msdyn_copilotforemployeeselfserviceit."
            "8e518921-4c1b-4c57-beb1-05c850e1f4c9.')"
        )

    def test_escapes_single_quotes(self):
        f = push._flow_connref_delete_filter("a'b", "wf")
        assert "a''b" in f


class TestBotcomponentRecreatePayload:
    """push._botcomponent_recreate_payload rebuilds a create body from the
    component-map entry (stable identity) + current content, for the stale-id
    self-heal recreate fallback.
    """

    BOT = "00000000-0000-0000-0000-0000000b0771"

    def test_rebuilds_from_entry_and_content(self):
        entry = {
            "botcomponentid": "old-stale",
            "schemaname": "msdyn_x.topic.SystemGetCreateTicketOptions",
            "componenttype": 0,
            "name": "System Get Create Ticket Options",
        }
        payload = push._botcomponent_recreate_payload(
            entry, "kind: AdaptiveDialog\n", self.BOT)
        assert payload == {
            "data": "kind: AdaptiveDialog\n",
            "name": "System Get Create Ticket Options",
            "schemaname": "msdyn_x.topic.SystemGetCreateTicketOptions",
            "componenttype": 0,
            "parentbotid@odata.bind": f"/bots({self.BOT})",
        }

    def test_includes_parent_botcomponent_when_present(self):
        entry = {
            "schemaname": "mspva_child",
            "componenttype": 19,
            "name": "Case 1",
            "parentbotcomponentid": "parent-id",
        }
        payload = push._botcomponent_recreate_payload(entry, "data", self.BOT)
        assert payload["ParentBotComponentId@odata.bind"] == \
            "/botcomponents(parent-id)"

    def test_returns_none_without_schemaname(self):
        assert push._botcomponent_recreate_payload(
            {"name": "x"}, "data", self.BOT) is None

    def test_falls_back_to_schemaname_for_name(self):
        entry = {"schemaname": "mspva_abc"}
        payload = push._botcomponent_recreate_payload(entry, "data", self.BOT)
        assert payload["name"] == "mspva_abc"
        assert "componenttype" not in payload


class TestSchemanameLooksKebab:
    """push._schemaname_looks_kebab flags a derived botcomponent schemaname
    that came from a kebab filename. A system topic must have a PascalCase
    schemaname to match the caller's BeginDialog reference; a hyphenated
    (kebab) segment means the topic file was misnamed (e.g. a fetched file
    pushed as new) and the reference will dangle. Can't auto-fix (itsm→ITSM
    is unguessable), so push warns.
    """

    def test_flags_kebab_segment(self):
        assert push._schemaname_looks_kebab(
            "msdyn_x.topic.ess-it-servicenow-itsm-system-get-options") is True

    def test_passes_pascalcase_segment(self):
        assert push._schemaname_looks_kebab(
            "msdyn_x.topic.ServiceNowITSMSystemGetCreateTicketOptions") is False

    def test_passes_single_lowercase_word(self):
        # A one-word lowercase segment (e.g. a simple topic) is a valid
        # schemaname and must not warn — only hyphenation is the kebab tell.
        assert push._schemaname_looks_kebab("msdyn_x.topic.conversation") is False

    def test_handles_no_dot(self):
        assert push._schemaname_looks_kebab("a-b") is True
        assert push._schemaname_looks_kebab("Ab") is False


class TestEnsureSkillsResponse:
    """push._ensure_skills_response coerces every Response action in an agent
    flow's clientdata to kind:Skills ("Respond to Copilot"). A Copilot Studio
    agent flow with a kind:PowerApp Response yields an empty output picker and
    InvalidBindingInvokeAction at publish; push creates only agent flows
    (modernflowtype=1), so coercing is safe.
    """

    def _wf(self, *response_kinds):
        actions = {}
        for i, kind in enumerate(response_kinds):
            a = {"type": "Response"}
            if kind is not None:
                a["kind"] = kind
            actions[f"Respond_{i}"] = a
        return {"properties": {"definition": {"actions": actions}}}

    def test_coerces_powerapp_response_to_skills(self):
        import json
        content = json.dumps(self._wf("PowerApp"))
        fixed, n = push._ensure_skills_response(content)
        assert n == 1
        assert json.loads(fixed)["properties"]["definition"]["actions"][
            "Respond_0"]["kind"] == "Skills"

    def test_coerces_missing_kind(self):
        import json
        fixed, n = push._ensure_skills_response(json.dumps(self._wf(None)))
        assert n == 1
        assert json.loads(fixed)["properties"]["definition"]["actions"][
            "Respond_0"]["kind"] == "Skills"

    def test_noop_when_already_skills(self):
        import json
        content = json.dumps(self._wf("Skills", "Skills"))
        fixed, n = push._ensure_skills_response(content)
        assert n == 0
        assert fixed == content

    def test_handles_nested_response_actions(self):
        import json
        wf = {"properties": {"definition": {"actions": {
            "If1": {"type": "If",
                    "actions": {"R1": {"type": "Response", "kind": "PowerApp"}},
                    "else": {"actions": {
                        "R2": {"type": "Response", "kind": "Skills"}}}},
            "R3": {"type": "Response"},
        }}}}
        fixed, n = push._ensure_skills_response(json.dumps(wf))
        assert n == 2  # R1 (PowerApp) + R3 (missing)
        d = json.loads(fixed)
        acts = d["properties"]["definition"]["actions"]
        assert acts["If1"]["actions"]["R1"]["kind"] == "Skills"
        assert acts["R3"]["kind"] == "Skills"

    def test_returns_unchanged_on_invalid_json(self):
        fixed, n = push._ensure_skills_response("{not valid")
        assert n == 0
        assert fixed == "{not valid"


class TestEvaluateFlowRegistration:
    """push._evaluate_flow_registration composes the agent-invocability checks
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
        r = push._evaluate_flow_registration(**self._ready_facts())
        assert r["ready"] is True
        assert all(r["checks"].values())

    def test_not_activated_fails(self):
        f = self._ready_facts()
        f["statecode"], f["statuscode"] = 0, 1  # Draft
        r = push._evaluate_flow_registration(**f)
        assert r["ready"] is False
        assert r["checks"]["activated"] is False

    def test_wrong_modernflowtype_fails(self):
        f = self._ready_facts()
        f["modernflowtype"] = 0
        r = push._evaluate_flow_registration(**f)
        assert r["checks"]["modern_flow"] is False
        assert r["ready"] is False

    def test_non_skills_response_fails(self):
        f = self._ready_facts()
        f["response_kinds"] = ["Skills", "PowerApp"]
        r = push._evaluate_flow_registration(**f)
        assert r["checks"]["response_skills"] is False

    def test_no_response_actions_fails(self):
        f = self._ready_facts()
        f["response_kinds"] = []
        r = push._evaluate_flow_registration(**f)
        assert r["checks"]["response_skills"] is False

    def test_missing_connref_fails(self):
        f = self._ready_facts()
        f["connref_bound_count"] = 0
        r = push._evaluate_flow_registration(**f)
        assert r["checks"]["flow_scoped_connref"] is False

    def test_missing_link_fails(self):
        f = self._ready_facts()
        f["link_count"] = 0
        r = push._evaluate_flow_registration(**f)
        assert r["checks"]["botcomponent_workflow_link"] is False


class TestFlowResponseKinds:
    """push._flow_response_kinds lists the kind of every Response action in a
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
        kinds = push._flow_response_kinds(json.dumps(wf))
        assert sorted(k or "" for k in kinds) == ["", "PowerApp", "Skills"]

    def test_empty_on_invalid_json(self):
        assert push._flow_response_kinds("{nope") == []

    def test_empty_when_no_responses(self):
        import json
        assert push._flow_response_kinds(
            json.dumps({"properties": {"definition": {"actions": {}}}})) == []


class TestConnrefNeedsCreate:
    """push._connref_needs_create guards connref-create idempotency: when
    re-driving registration (adopt-on-existing / --repair) the flow-scoped
    connref may already exist, and a blind create would 400 on duplicate key.
    """

    def _rows(self, *names):
        return [{"connectionreferencelogicalname": n} for n in names]

    def test_true_when_absent(self):
        assert push._connref_needs_create(
            "schema.wf.shared_service-now", self._rows("other.name")) is True

    def test_false_when_present(self):
        assert push._connref_needs_create(
            "schema.wf.shared_service-now",
            self._rows("schema.wf.shared_service-now")) is False

    def test_match_is_case_insensitive(self):
        assert push._connref_needs_create(
            "Schema.WF.Shared_Service-Now",
            self._rows("schema.wf.shared_service-now")) is False

    def test_true_on_empty_rows(self):
        assert push._connref_needs_create("schema.wf.conn", []) is True


class TestIsBenignDuplicateError:
    """push._is_benign_duplicate_error recognizes a Dataverse
    already-exists/duplicate-key error so a re-driven link or connref can be
    treated as already-registered rather than a failure.
    """

    def test_matches_duplicate_key_text(self):
        assert push._is_benign_duplicate_error(
            Exception("Cannot insert duplicate key")) is True

    def test_matches_already_exists_text(self):
        assert push._is_benign_duplicate_error(
            Exception("A record with matching key values already exists")) is True

    def test_matches_dataverse_duplicate_code(self):
        assert push._is_benign_duplicate_error(
            Exception("error 0x80040237: duplicate record")) is True

    def test_false_on_unrelated_error(self):
        assert push._is_benign_duplicate_error(
            Exception("500 internal server error")) is False

    def test_false_on_none(self):
        assert push._is_benign_duplicate_error(None) is False


class TestRegistrationReport:
    """push._registration_report turns the best-effort registration failures
    into an honest terminal signal: a banner naming each flow + failed step and
    a non-zero exit, so a flow that was created but is NOT agent-invocable is
    never reported as a silent green success.
    """

    def test_empty_is_success(self):
        r = push._registration_report([])
        assert r["lines"] == []
        assert r["exit_code"] == 0
        assert r["telemetry_outcome"] == "success"

    def test_nonempty_is_failure_with_repair_guidance(self):
        r = push._registration_report([
            {"flow": "wf-123", "step": "activate", "detail": "ARM 500"},
        ])
        assert r["exit_code"] != 0
        assert r["telemetry_outcome"] == "failure"
        blob = "\n".join(r["lines"])
        assert "wf-123" in blob
        assert "activate" in blob
        assert "--repair" in blob

    def test_lists_every_incomplete_flow(self):
        r = push._registration_report([
            {"flow": "wf-1", "step": "connref", "detail": "x"},
            {"flow": "wf-2", "step": "link", "detail": "y"},
        ])
        blob = "\n".join(r["lines"])
        assert "wf-1" in blob and "wf-2" in blob


class TestPlanRepairFlows:
    """push._plan_repair_flows selects the flows --repair re-drives from the
    component map: workflow entries only, optional case-insensitive name/id
    filter, deterministic order. Bounded so --repair never fans out over the
    pack orchestrators the way an unfiltered validate would.
    """

    MAP = {
        "workflows/get-options/workflow.json": {
            "entity_set": "workflows", "workflowid": "aaa", "name": "Get Options"},
        "workflows/create-ticket/workflow.json": {
            "entity_set": "workflows", "workflowid": "bbb", "name": "Create Ticket"},
        "botcomponents/Foo/data": {"botcomponentid": "ccc", "schemaname": "Foo"},
    }

    def test_selects_only_workflow_entries(self):
        got = push._plan_repair_flows(self.MAP)
        assert ("workflows/get-options/workflow.json", "aaa") in got
        assert ("workflows/create-ticket/workflow.json", "bbb") in got
        assert all(wid in ("aaa", "bbb") for _, wid in got)
        assert len(got) == 2

    def test_deterministic_order(self):
        assert push._plan_repair_flows(self.MAP) == sorted(
            push._plan_repair_flows(self.MAP))

    def test_name_filter_matches_name_substring_ci(self):
        got = push._plan_repair_flows(self.MAP, name_filter="create")
        assert got == [("workflows/create-ticket/workflow.json", "bbb")]

    def test_filter_matches_workflowid(self):
        got = push._plan_repair_flows(self.MAP, name_filter="aaa")
        assert got == [("workflows/get-options/workflow.json", "aaa")]

    def test_filter_no_match_is_empty(self):
        assert push._plan_repair_flows(self.MAP, name_filter="zzz") == []


class TestRunRepairNoop:
    """push._run_repair returns 0 without authenticating when there are no
    mapped flows to repair — the early-return branch, exercisable without network.
    """

    def test_empty_map_returns_zero_without_auth(self, monkeypatch):
        monkeypatch.setattr(
            push, "_AuthHolder",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("must not authenticate when nothing to repair")),
        )
        assert push._run_repair(
            "https://x.crm.dynamics.com", "schema", "/agent", {}, None) == 0

    def test_no_filter_match_returns_zero_without_auth(self, monkeypatch):
        monkeypatch.setattr(
            push, "_AuthHolder",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("must not authenticate when nothing matches")),
        )
        cmap = {"workflows/a/workflow.json": {
            "entity_set": "workflows", "workflowid": "aaa", "name": "Alpha"}}
        assert push._run_repair(
            "https://x.crm.dynamics.com", "schema", "/agent", cmap, "zzz") == 0

    def test_flow_not_on_disk_is_scoped_out_without_auth(self, monkeypatch):
        # A mapped workflow whose workflow.json is absent on disk (e.g. a
        # solution/pack-installed orchestrator) must not be repaired.
        monkeypatch.setattr(
            push, "_AuthHolder",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("must not authenticate for a pack flow")),
        )
        cmap = {"workflows/pack/workflow.json": {
            "entity_set": "workflows", "workflowid": "aaa", "name": "Pack"}}
        assert push._run_repair(
            "https://x.crm.dynamics.com", "schema",
            "/nonexistent-agent-dir", cmap, None) == 0

    def test_dry_run_lists_plan_without_auth(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            push, "_AuthHolder",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("dry-run must not authenticate")),
        )
        wf_dir = tmp_path / "workflows" / "a"
        wf_dir.mkdir(parents=True)
        (wf_dir / "workflow.json").write_text("{}", encoding="utf-8")
        cmap = {"workflows/a/workflow.json": {
            "entity_set": "workflows", "workflowid": "aaa", "name": "Alpha"}}
        assert push._run_repair(
            "https://x.crm.dynamics.com", "schema", str(tmp_path), cmap,
            None, dry_run=True) == 0
