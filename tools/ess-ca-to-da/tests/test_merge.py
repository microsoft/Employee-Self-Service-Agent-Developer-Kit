from __future__ import annotations

from typing import Any

from conftest import DA_PREFIX, ca_component, dialog_component, reference_set
from essmig.discovery import AgentMetadata
from essmig.llm import LlmUnavailable
from essmig.merge import (
    _AGENT_SUFFIX,
    Conflict,
    Decision,
    Outcome,
    Overlays,
    Policy,
    Resolution,
    merge,
    merge_node,
)

SIMPLE = """kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  greeting: hello
  actions:
    - kind: SendActivity
      id: a1
      activity: one
    - kind: SendActivity
      id: a2
      activity: two
"""


# --- merge_node -------------------------------------------------------------


def test_a_value_we_did_not_touch_takes_the_new_template_value() -> None:
    merged, conflicts = merge_node("old", "old", "new", path="x")
    assert (merged, conflicts) == ("new", [])


def test_a_value_ess_did_not_touch_keeps_our_change() -> None:
    merged, conflicts = merge_node("old", "mine", "old", path="x")
    assert (merged, conflicts) == ("mine", [])


def test_the_same_change_on_both_sides_is_not_a_conflict() -> None:
    merged, conflicts = merge_node("old", "same", "same", path="x")
    assert (merged, conflicts) == ("same", [])


def test_different_changes_to_the_same_scalar_conflict() -> None:
    merged, conflicts = merge_node("old", "mine", "theirs", path="x")
    assert merged == "theirs"
    assert [(c.path, c.ours, c.theirs) for c in conflicts] == [("x", "mine", "theirs")]


def test_changes_to_different_keys_both_survive() -> None:
    merged, conflicts = merge_node(
        {"a": 1, "b": 1}, {"a": 2, "b": 1}, {"a": 1, "b": 3}, path="x"
    )
    assert (merged, conflicts) == ({"a": 2, "b": 3}, [])


def test_a_key_only_we_added_is_kept() -> None:
    merged, conflicts = merge_node({}, {"mine": 1}, {}, path="x")
    assert (merged, conflicts) == ({"mine": 1}, [])


def test_our_deletion_is_honoured_when_ess_left_the_key_alone() -> None:
    merged, conflicts = merge_node({"a": 1}, {}, {"a": 1}, path="x")
    assert (merged, conflicts) == ({}, [])


def test_our_deletion_of_something_ess_changed_is_a_conflict() -> None:
    merged, conflicts = merge_node({"a": 1}, {}, {"a": 2}, path="x")
    assert merged == {"a": 2}
    assert conflicts[0].reason == "you removed this; ESS changed it"


def test_ess_deleting_something_we_changed_is_a_conflict() -> None:
    merged, conflicts = merge_node({"a": 1}, {"a": 9}, {}, path="x")
    assert merged == {"a": 9}
    assert conflicts[0].reason == "ESS removed this; you changed it"


def test_ess_deleting_something_we_never_touched_is_honoured() -> None:
    merged, conflicts = merge_node({"a": 1}, {"a": 1}, {}, path="x")
    assert (merged, conflicts) == ({}, [])


def test_a_key_only_ess_added_is_taken_without_a_false_removal_conflict() -> None:
    # base and customer both lack the key; ESS added it. A new template default is
    # not a customer deletion — take it cleanly, do not claim "you removed this".
    merged, conflicts = merge_node({"a": 1}, {"a": 2}, {"a": 1, "new": 7}, path="x")
    assert merged["new"] == 7
    assert conflicts == []


def test_a_key_only_the_customer_added_is_kept_without_a_false_removal_conflict() -> None:
    # base and ESS both lack the key; the customer added it. ESS never had it, so it
    # did not "remove" it — keep the customer's value with no conflict.
    merged, conflicts = merge_node({"a": 1}, {"a": 1, "mine": 5}, {"a": 2}, path="x")
    assert merged["mine"] == 5
    assert conflicts == []


def test_action_lists_merge_by_id_so_both_sides_edits_survive() -> None:
    base = [{"id": "a", "v": 1}, {"id": "b", "v": 1}]
    ours = [{"id": "a", "v": 2}, {"id": "b", "v": 1}, {"id": "mine", "v": 1}]
    theirs = [{"id": "a", "v": 1}, {"id": "b", "v": 3}]
    merged, conflicts = merge_node(base, ours, theirs, path="actions")
    assert conflicts == []
    assert merged == [{"id": "a", "v": 2}, {"id": "b", "v": 3}, {"id": "mine", "v": 1}]


def test_editing_an_action_ess_removed_is_a_conflict() -> None:
    base = [{"id": "a", "v": 1}]
    merged, conflicts = merge_node(base, [{"id": "a", "v": 2}], [], path="actions")
    assert merged == [{"id": "a", "v": 2}]
    assert conflicts[0].reason == "ESS removed this action; you changed it"


def test_lists_without_ids_are_merged_whole_and_conflict_when_both_changed() -> None:
    merged, conflicts = merge_node(["a"], ["a", "mine"], ["a", "theirs"], path="phrases")
    assert merged == ["a", "theirs"]
    assert "carry no ids" in conflicts[0].reason


# --- overlays ---------------------------------------------------------------


def test_the_default_policy_is_a_three_way_merge() -> None:
    assert Overlays.from_document(None).policy_for("anything") is Policy.MERGE


def test_read_only_overlays_lock_the_template_value() -> None:
    overlays = Overlays.from_document(
        {"overlays": [{"path": "components[*]", "isManaged": True, "readOnly": True}]}
    )
    assert overlays.policy_for("components[DialogComponent:topic.X]") is Policy.LOCKED


def test_unmanaged_overlays_give_the_customer_ownership() -> None:
    overlays = Overlays.from_document(
        {"overlays": [{"path": "components[*]", "isManaged": False, "isCustomizable": True}]}
    )
    assert overlays.policy_for("components[DialogComponent:topic.X]") is Policy.CUSTOMER_OWNED


def test_the_most_specific_selector_wins() -> None:
    overlays = Overlays.from_document(
        {
            "overlays": [
                {"path": "components[*]", "isManaged": True, "readOnly": True},
                {
                    "path": "components[DialogComponent:topic.X]",
                    "isManaged": False,
                },
            ]
        }
    )
    assert overlays.policy_for("components[DialogComponent:topic.X]") is Policy.CUSTOMER_OWNED
    assert overlays.policy_for("components[DialogComponent:topic.Y]") is Policy.LOCKED


# --- merge ------------------------------------------------------------------


def _da_dialog() -> dict[str, object]:
    return {
        "beginDialog": {
            "kind": "OnRedirect",
            "id": "main",
            "greeting": "hello",
            "actions": [
                {"kind": "SendActivity", "id": "a1", "activity": "one"},
                {"kind": "SendActivity", "id": "a2", "activity": "two"},
            ],
        }
    }


def test_an_untouched_component_is_reported_as_unchanged() -> None:
    reference = reference_set(
        [dialog_component("topic.Foo", _da_dialog())], {"topic.Foo": SIMPLE}
    )
    component = ca_component("topic.Foo", SIMPLE)
    result = merge(reference, {component.component_id: component}, "hr")
    assert result.results[0].outcome is Outcome.UNCHANGED


def test_our_edit_lands_on_top_of_the_ess_version() -> None:
    theirs = _da_dialog()
    theirs["beginDialog"]["actions"][1]["activity"] = "two (improved by ESS)"  # type: ignore[index]
    reference = reference_set([dialog_component("topic.Foo", theirs)], {"topic.Foo": SIMPLE})
    component = ca_component("topic.Foo", SIMPLE.replace("activity: one", "activity: mine"))

    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.MERGED
    actions = reference.da_components["topic.Foo"]["dialog"]["beginDialog"]["actions"]
    assert actions[0]["activity"] == "mine"
    assert actions[1]["activity"] == "two (improved by ESS)"


def test_both_sides_editing_the_same_action_conflicts_and_keeps_the_ess_version() -> None:
    theirs = _da_dialog()
    theirs["beginDialog"]["actions"][0]["activity"] = "ess version"  # type: ignore[index]
    reference = reference_set([dialog_component("topic.Foo", theirs)], {"topic.Foo": SIMPLE})
    component = ca_component("topic.Foo", SIMPLE.replace("activity: one", "activity: my version"))

    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.CONFLICTED
    conflict = result.results[0].conflicts[0]
    assert (conflict.ours, conflict.theirs) == ("my version", "ess version")
    # Nothing was written: the template is untouched until a human decides.
    actions = reference.da_components["topic.Foo"]["dialog"]["beginDialog"]["actions"]
    assert actions[0]["activity"] == "ess version"


def test_a_topic_with_no_template_counterpart_is_carried_wholesale() -> None:
    reference = reference_set([])
    component = ca_component("topic.Mine", SIMPLE, solutions=("MyDevSolution",))

    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.CARRIED_NEW
    assert reference.da_components["topic.Mine"]["managedProperties"]["isManaged"] is False


def test_a_customization_from_a_non_ported_extension_pack_is_blocked() -> None:
    # SuccessFactors has no Declarative Agent equivalent in this release, so a
    # customization that belongs to it cannot be migrated and must be reported as
    # blocked rather than carried into HR where its pack does not exist.
    reference = reference_set([])
    component = ca_component(
        "topic.SuccessFactorsThing",
        SIMPLE,
        solutions=("msdyn_EssHRSuccessFactors", "Active"),
    )

    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.BLOCKED
    assert "HR Success Factors" in result.results[0].detail
    # Nothing was carried into the package.
    assert "topic.SuccessFactorsThing" not in reference.da_components
    # The customer's configuration is reproduced so nothing is silently lost.
    assert result.results[0].configuration


def test_a_customization_from_a_ported_extension_pack_is_carried() -> None:
    # ServiceNow ITSM (IT) shipped a DA equivalent, so its net-new content is still
    # carried rather than blocked.
    reference = reference_set([])
    component = ca_component(
        "topic.ItsmThing",
        SIMPLE,
        solutions=("msdyn_EssITServiceNowITSM", "Active"),
    )

    result = merge(reference, {component.component_id: component}, "it")

    assert result.results[0].outcome is Outcome.CARRIED_NEW


def test_one_unparseable_component_fails_alone_without_aborting_the_run() -> None:
    # A component whose 'data' cannot be read (here: malformed YAML) must be reported
    # as a single FAILED row, not raise and take the whole migration down with it.
    reference = reference_set([])
    good = ca_component("topic.Good", SIMPLE)
    bad = ca_component("topic.Bad", "kind: AdaptiveDialog\nfoo: [unterminated\n")

    result = merge(
        reference,
        {good.component_id: good, bad.component_id: bad},
        "hr",
    )

    by_suffix = {r.suffix: r for r in result.results}
    assert by_suffix["topic.Bad"].outcome is Outcome.FAILED
    assert "could not parse" in by_suffix["topic.Bad"].detail
    assert by_suffix["topic.Good"].outcome is Outcome.CARRIED_NEW


def test_a_locked_component_refuses_our_edit_and_says_so() -> None:
    reference = reference_set(
        [dialog_component("topic.Foo", _da_dialog())],
        {"topic.Foo": SIMPLE},
        overlays={"overlays": [{"path": "components[*]", "isManaged": True, "readOnly": True}]},
    )
    component = ca_component("topic.Foo", SIMPLE.replace("activity: one", "activity: mine"))

    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.LOCKED
    assert "read-only" in result.results[0].detail


def test_without_a_baseline_we_cannot_tell_whose_change_it_is_so_it_conflicts() -> None:
    reference = reference_set([dialog_component("topic.Foo", _da_dialog())], {})
    component = ca_component("topic.Foo", SIMPLE.replace("activity: one", "activity: mine"))

    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.CONFLICTED
    assert "no shipped baseline" in result.results[0].conflicts[0].reason


def test_a_carried_topic_using_an_unsupported_trigger_is_disabled_but_preserved() -> None:
    reference = reference_set([])
    data = SIMPLE.replace("kind: OnRedirect", "kind: OnUnknownIntent")
    component = ca_component("topic.Mine", data, solutions=("MyDevSolution",))

    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].deprecated is True
    entry = reference.da_components["topic.Mine"]
    assert entry["state"] == "Inactive"
    assert entry["displayName"].startswith("[DEPRECATED]")
    # The logic survives intact — nothing was deleted.
    assert len(entry["dialog"]["beginDialog"]["actions"]) == 2


def test_a_conflicted_topic_is_not_also_deprecated_since_it_was_never_written() -> None:
    reference = reference_set([dialog_component("topic.Foo", _da_dialog())], {})
    component = ca_component("topic.Foo", SIMPLE.replace("kind: OnRedirect", "kind: OnActivity"))
    result = merge(reference, {component.component_id: component}, "hr")
    assert result.results[0].deprecated is False


def test_a_knowledge_source_is_carried_into_the_agent_as_a_component() -> None:
    # Knowledge sources were once reported as "no Declarative Agent equivalent" and
    # later as manual agent-settings work. Both were wrong: a real published ESS DA
    # carries them as KnowledgeSourceComponent entries, so the tool must too.
    reference = reference_set(
        [
            {
                "kind": "GptComponent",
                "schemaName": f"{DA_PREFIX}.gpt.default",
                "metadata": {"instructions": "be helpful"},
            }
        ]
    )
    component = ca_component(
        "knowledge.X",
        "kind: KnowledgeSourceConfiguration\n"
        "source:\n"
        "  kind: SharePointSearchSource\n"
        "  site: https://contoso.sharepoint.com/sites/HR\n",
        component_type=16,
        name="ContosoHR",
    )
    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.CARRIED_NEW
    carried = [
        entry
        for entry in result.agent["components"]
        if isinstance(entry, dict) and entry.get("kind") == "KnowledgeSourceComponent"
    ]
    assert len(carried) == 1
    assert carried[0]["configuration"]["source"]["kind"] == "SharePointSearchSource"
    # The GPT must be told to search the carried source, or it is inert.
    gpt = next(
        entry
        for entry in result.agent["components"]
        if isinstance(entry, dict) and entry.get("kind") == "GptComponent"
    )
    assert gpt["metadata"]["knowledgeSources"] == {"kind": "SearchAllKnowledgeSources"}


def test_an_unrecognised_component_type_admits_the_tool_might_be_wrong() -> None:
    reference = reference_set([])
    component = ca_component("mystery.X", "kind: X\n", component_type=17)
    result = merge(reference, {component.component_id: component}, "hr")

    assert result.results[0].outcome is Outcome.NO_TARGET
    assert "gap in the tool" in result.results[0].detail


# --- instruction reconciliation ---------------------------------------------


def _gpt_reference(da_instructions: str) -> Any:
    return reference_set(
        [
            {
                "kind": "GptComponent",
                "schemaName": f"{DA_PREFIX}.gpt.default",
                "metadata": {"instructions": da_instructions},
            }
        ],
        baseline={
            "gpt.default": "kind: GptComponentMetadata\ninstructions: shipped CA text\n"
        },
    )


def _gpt_component(instructions: str) -> Any:
    return ca_component(
        "gpt.default",
        f"kind: GptComponentMetadata\ninstructions: {instructions}\n",
        component_type=15,
        name="gpt.default",
    )


def test_edited_instructions_are_reconciled_onto_the_da_wording_by_the_model() -> None:
    # The CA and DA word the same instructions differently, so a structural merge can
    # only conflict. An edited-instructions migration must re-express the customer's
    # delta onto the DA text via the model.
    reference = _gpt_reference("shipped DA text")
    component = _gpt_component("shipped CA text plus my rule")

    calls: list[tuple[str, str, str]] = []

    def fake_merge(base: str, ours: str, theirs: str) -> str:
        calls.append((base, ours, theirs))
        return "DA text plus my rule"

    result = merge(
        reference,
        {component.component_id: component},
        "hr",
        merge_instructions=fake_merge,
    )

    assert calls == [("shipped CA text", "shipped CA text plus my rule", "shipped DA text")]
    gpt = next(
        entry
        for entry in result.agent["components"]
        if isinstance(entry, dict) and entry.get("kind") == "GptComponent"
    )
    assert gpt["metadata"]["instructions"] == "DA text plus my rule"
    assert result.results[0].outcome is Outcome.MERGED
    assert "re-applied to the DA's wording" in result.results[0].detail


def test_unedited_instructions_do_not_call_the_model() -> None:
    # If the customer never touched the instructions, keep the DA's wording and make
    # no model call.
    reference = _gpt_reference("shipped DA text")
    component = _gpt_component("shipped CA text")

    def fail_merge(base: str, ours: str, theirs: str) -> str:  # pragma: no cover
        raise AssertionError("the model must not be called when instructions are unchanged")

    result = merge(
        reference,
        {component.component_id: component},
        "hr",
        merge_instructions=fail_merge,
    )

    gpt = next(
        entry
        for entry in result.agent["components"]
        if isinstance(entry, dict) and entry.get("kind") == "GptComponent"
    )
    assert gpt["metadata"]["instructions"] == "shipped DA text"


def test_an_unreachable_model_keeps_da_instructions_and_reports_a_conflict() -> None:
    reference = _gpt_reference("shipped DA text")
    component = _gpt_component("shipped CA text plus my rule")

    def unavailable(base: str, ours: str, theirs: str) -> str:
        raise LlmUnavailable("gh auth token failed")

    result = merge(
        reference,
        {component.component_id: component},
        "hr",
        merge_instructions=unavailable,
    )

    gpt = next(
        entry
        for entry in result.agent["components"]
        if isinstance(entry, dict) and entry.get("kind") == "GptComponent"
    )
    assert gpt["metadata"]["instructions"] == "shipped DA text"
    assert result.results[0].outcome is Outcome.CONFLICTED
    assert "could not be auto-migrated" in result.results[0].detail


# --- interactive conflict resolution ----------------------------------------


def _always(choice: Resolution) -> object:
    return lambda conflict: Decision(choice)


def test_resolving_a_scalar_conflict_to_ours_takes_our_value_and_clears_it() -> None:
    merged, conflicts = merge_node(
        "old", "mine", "theirs", path="x", resolve=_always(Resolution.OURS)
    )
    assert (merged, conflicts) == ("mine", [])


def test_resolving_a_scalar_conflict_to_theirs_takes_their_value_and_clears_it() -> None:
    merged, conflicts = merge_node(
        "old", "mine", "theirs", path="x", resolve=_always(Resolution.THEIRS)
    )
    assert (merged, conflicts) == ("theirs", [])


def test_a_hand_merged_value_is_placed_at_the_spot() -> None:
    merged, conflicts = merge_node(
        "old", "mine", "theirs", path="x", resolve=lambda c: Decision.manual("blended")
    )
    assert (merged, conflicts) == ("blended", [])


def test_a_resolver_that_returns_none_leaves_the_conflict_as_before() -> None:
    merged, conflicts = merge_node(
        "old", "mine", "theirs", path="x", resolve=lambda conflict: None
    )
    assert merged == "theirs"
    assert [(c.path, c.ours, c.theirs) for c in conflicts] == [("x", "mine", "theirs")]


def test_resolving_our_deletion_to_ours_drops_the_key() -> None:
    merged, conflicts = merge_node(
        {"a": 1}, {}, {"a": 2}, path="x", resolve=_always(Resolution.OURS)
    )
    assert (merged, conflicts) == ({}, [])


def test_resolving_our_deletion_to_theirs_keeps_the_changed_key() -> None:
    merged, conflicts = merge_node(
        {"a": 1}, {}, {"a": 2}, path="x", resolve=_always(Resolution.THEIRS)
    )
    assert (merged, conflicts) == ({"a": 2}, [])


def test_hand_merging_a_removed_key_places_the_edited_value() -> None:
    merged, conflicts = merge_node(
        {"a": 1}, {}, {"a": 2}, path="x", resolve=lambda c: Decision.manual(7)
    )
    assert (merged, conflicts) == ({"a": 7}, [])


def test_resolving_an_ess_deletion_to_theirs_drops_the_key() -> None:
    merged, conflicts = merge_node(
        {"a": 1}, {"a": 9}, {}, path="x", resolve=_always(Resolution.THEIRS)
    )
    assert (merged, conflicts) == ({}, [])


def test_resolving_an_ess_deletion_to_ours_keeps_our_value() -> None:
    merged, conflicts = merge_node(
        {"a": 1}, {"a": 9}, {}, path="x", resolve=_always(Resolution.OURS)
    )
    assert (merged, conflicts) == ({"a": 9}, [])


def test_resolving_a_removed_action_to_ours_omits_it_from_the_merged_list() -> None:
    base = [{"id": "a", "v": 1}]
    merged, conflicts = merge_node(
        base, [], [{"id": "a", "v": 2}], path="actions", resolve=_always(Resolution.OURS)
    )
    assert (merged, conflicts) == ([], [])


def test_hand_merging_a_list_action_places_the_edited_item() -> None:
    base = [{"id": "a", "v": 1}]
    merged, conflicts = merge_node(
        base, [], [{"id": "a", "v": 2}], path="actions",
        resolve=lambda c: Decision.manual({"id": "a", "v": 99}),
    )
    assert (merged, conflicts) == ([{"id": "a", "v": 99}], [])


def test_a_resolver_can_answer_each_spot_differently() -> None:
    seen: list[str] = []

    def resolve(conflict: Conflict) -> Decision:
        seen.append(conflict.path)
        return Decision.ours() if conflict.path.endswith("a") else Decision.theirs()

    merged, conflicts = merge_node(
        {"a": 1, "b": 1}, {"a": 2, "b": 2}, {"a": 3, "b": 3}, path="x", resolve=resolve
    )
    assert conflicts == []
    assert merged == {"a": 2, "b": 3}
    assert seen == ["x.a", "x.b"]



# --- agent name & description ------------------------------------------------


def _config_with_name(name: str) -> dict:
    return {
        "formatVersion": "1.0",
        "realm": "dev",
        "values": {"botName": name, "gptDisplayName": name},
    }


def test_a_renamed_agent_is_carried_onto_the_config() -> None:
    reference = reference_set([], config=_config_with_name("ESS HR (Preview)"))
    reference.agent["entity"]["description"] = "The shipped ESS description."
    metadata = AgentMetadata(
        name="Contoso People Helper",
        description="The shipped ESS description.",
        baseline_name="ESS HR (Preview)",
        baseline_description="The shipped ESS description.",
    )
    merged = merge(reference, {}, "hr", agent_metadata=metadata)

    assert reference.config["values"]["botName"] == "Contoso People Helper"
    assert reference.config["values"]["gptDisplayName"] == "Contoso People Helper"
    result = next(r for r in merged.results if r.suffix == _AGENT_SUFFIX)
    assert result.outcome is Outcome.MERGED
    assert "display name" in result.detail


def test_a_re_described_agent_is_carried_onto_the_agent_yml() -> None:
    reference = reference_set([], config=_config_with_name("ESS HR (Preview)"))
    reference.agent["entity"]["description"] = "Shipped description."
    metadata = AgentMetadata(
        name="ESS HR (Preview)",
        description="Our tailored HR helper description.",
        baseline_name="ESS HR (Preview)",
        baseline_description="Shipped description.",
    )
    merged = merge(reference, {}, "hr", agent_metadata=metadata)

    assert reference.agent["entity"]["description"] == "Our tailored HR helper description."
    result = next(r for r in merged.results if r.suffix == _AGENT_SUFFIX)
    assert result.outcome is Outcome.MERGED
    assert "description" in result.detail


def test_an_unchanged_agent_produces_no_result() -> None:
    reference = reference_set([], config=_config_with_name("ESS HR (Preview)"))
    reference.agent["entity"]["description"] = "Shipped description."
    metadata = AgentMetadata(
        name="ESS HR (Preview)",
        description="Shipped description.",
        baseline_name="ESS HR (Preview)",
        baseline_description="Shipped description.",
    )
    merged = merge(reference, {}, "hr", agent_metadata=metadata)

    assert reference.config["values"]["botName"] == "ESS HR (Preview)"
    assert not any(r.suffix == _AGENT_SUFFIX for r in merged.results)


def test_a_missing_baseline_that_differs_from_the_template_needs_review() -> None:
    reference = reference_set([], config=_config_with_name("ESS HR (Preview)"))
    reference.agent["entity"]["description"] = "Shipped description."
    metadata = AgentMetadata(name="Contoso People Helper", description="Shipped description.")
    merged = merge(reference, {}, "hr", agent_metadata=metadata)

    # Baseline unknown -> do not silently overwrite the template's name.
    assert reference.config["values"]["botName"] == "ESS HR (Preview)"
    result = next(r for r in merged.results if r.suffix == _AGENT_SUFFIX)
    assert result.outcome is Outcome.CONFLICTED
    assert "Confirm which name" in result.detail


def test_no_agent_metadata_produces_no_agent_result() -> None:
    reference = reference_set([], config=_config_with_name("ESS HR (Preview)"))
    merged = merge(reference, {}, "hr", agent_metadata=None)
    assert not any(r.suffix == _AGENT_SUFFIX for r in merged.results)
