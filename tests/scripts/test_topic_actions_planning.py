# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure M4 fixtures, not tenant evidence or authoritative protection decisions."""

from dataclasses import replace

import pytest

from topic_actions_discovery import (
    DiscoveryTarget,
    SourceBinding,
    TopicEvidence,
    TopicSet,
    build_provisional_snapshot,
)
from topic_actions_flat_discovery import (
    FlatCatalog,
    FlatMember,
    FlatSet,
    InventoryTopic,
    NativeInventory,
    compare_flat_catalog,
)
from topic_actions_planning import (
    PlanningError,
    TopicChange,
    TopicSkip,
    build_provisional_plan,
    plan_topic_actions,
)


TARGET = DiscoveryTarget(
    "00000000-0000-0000-0000-000000001111",
    "00000000-0000-0000-0000-000000002222",
    "00000000-0000-0000-0000-000000003333",
)


class SyntheticPlannerAdapter:
    """Supply explicit synthetic classifications; never infer a live plan."""

    def __init__(self):
        source = SourceBinding("synthetic-package", "1", "r1", True)
        self.sets = (
            TopicSet("alpha", ("alpha-only", "shared", "required"), True, source),
            TopicSet("beta", ("beta-only", "shared"), True, source),
        )
        self.topics = (
            TopicEvidence("alpha-only", False, "Off"),
            TopicEvidence("shared", False, "On"),
            TopicEvidence("required", True, "On"),
            TopicEvidence("beta-only", False, "On"),
        )

    def snapshot(self, keys=("alpha",), coverage=True):
        return build_provisional_snapshot(
            TARGET, keys, self.sets, self.topics, coverage_complete=coverage,
        )

    def enable(self, **overrides):
        arguments = {
            "delta": (TopicChange("alpha-only", "Off", "On"),),
            "satisfied_member_ids": ("shared", "required"),
        }
        arguments.update(overrides)
        return build_provisional_plan(self.snapshot(), "enable", **arguments)

    def protected_skips(self):
        return (
            TopicSkip("shared", "shared", ("beta",)),
            TopicSkip("required", "required"),
        )


@pytest.fixture
def adapter():
    return SyntheticPlannerAdapter()


def test_enable_preserves_exact_delta_target_selection_and_satisfied_members(adapter):
    plan = adapter.enable()
    assert plan.target == TARGET
    assert plan.action == "enable"
    assert plan.selected_keys == ("alpha",)
    assert plan.delta == (TopicChange("alpha-only", "Off", "On"),)
    assert plan.satisfied_member_ids == ("shared", "required")
    assert plan.skips == plan.blockers == ()
    assert plan.outcome == "changes_proposed"
    assert plan.evidence_kind == "synthetic"
    assert plan.live_actions_available is False


def test_supplied_disable_delta_preserves_distinct_required_and_shared_reasons(adapter):
    adapter.topics = (replace(adapter.topics[0], state="On"), *adapter.topics[1:])
    snapshot = adapter.snapshot()
    plan = build_provisional_plan(
        snapshot, "disable", delta=(TopicChange("alpha-only", "On", "Off"),),
        skips=adapter.protected_skips(),
    )
    assert plan.delta == (TopicChange("alpha-only", "On", "Off"),)
    assert plan.skips == adapter.protected_skips()
    assert plan.skips[0].protecting_sets == ("beta",)
    assert "beta-only" not in snapshot.selected_member_ids
    assert plan.outcome == "changes_proposed"
    assert plan.blockers == ()
    assert plan.live_actions_available is False


def test_nonempty_already_correct_can_include_protected_skips(adapter):
    plan = build_provisional_plan(
        adapter.snapshot(), "disable", satisfied_member_ids=("alpha-only",),
        skips=adapter.protected_skips(),
    )
    assert plan.outcome == "already_correct"
    assert plan.satisfied_member_ids == ("alpha-only",)
    assert plan.skips == adapter.protected_skips()
    assert plan.delta == ()
    assert plan.live_actions_available is False


def test_supplied_shared_skip_retains_partly_enabled_outside_set_evidence(adapter):
    adapter.sets = (
        adapter.sets[0],
        replace(adapter.sets[1], member_ids=(*adapter.sets[1].member_ids, "beta-off")),
    )
    adapter.topics = (*adapter.topics, TopicEvidence("beta-off", False, "Off"))
    snapshot = adapter.snapshot()
    plan = build_provisional_plan(
        snapshot, "disable", satisfied_member_ids=("alpha-only",),
        skips=adapter.protected_skips(),
    )
    outside_states = {
        item.component_id: item.state for item in snapshot.topics
        if item.component_id not in snapshot.selected_member_ids
    }
    assert outside_states == {"beta-only": "On", "beta-off": "Off"}
    assert plan.skips[0] == TopicSkip("shared", "shared", ("beta",))
    assert plan.live_actions_available is False


def test_all_protected_is_not_already_correct_or_successful_disable(adapter):
    adapter.topics = (replace(adapter.topics[0], required=True), *adapter.topics[1:])
    plan = build_provisional_plan(
        adapter.snapshot(), "disable",
        skips=(TopicSkip("alpha-only", "required"), *adapter.protected_skips()),
    )
    assert plan.outcome == "all_protected"
    assert plan.satisfied_member_ids == plan.delta == ()
    assert len(plan.skips) == 3
    assert plan.live_actions_available is False


def test_empty_membership_is_distinct_from_already_correct(adapter):
    adapter.sets = (replace(adapter.sets[0], member_ids=()), adapter.sets[1])
    plan = build_provisional_plan(adapter.snapshot(), "enable")
    assert plan.outcome == "empty"
    assert plan.blockers == ("empty_membership:alpha",)
    assert plan.delta == plan.satisfied_member_ids == ()


@pytest.mark.parametrize(("change", "reason"), [
    ({"state": "Unknown"}, "unknown_state:alpha-only"),
    ({"required": None}, "unknown_protection:alpha-only"),
])
def test_unknown_evidence_is_not_an_already_correct_plan(adapter, change, reason):
    adapter.topics = (replace(adapter.topics[0], **change), *adapter.topics[1:])
    plan = build_provisional_plan(adapter.snapshot(), "enable")
    assert plan.outcome == "unknown"
    assert reason in plan.blockers
    assert plan.delta == plan.satisfied_member_ids == ()
    assert plan.live_actions_available is False


def test_invalid_combined_scope_is_preserved_and_never_silently_narrowed(adapter):
    plan = build_provisional_plan(adapter.snapshot(("alpha", "missing")), "enable")
    assert plan.selected_keys == ("alpha", "missing")
    assert plan.outcome == "blocked"
    assert plan.blockers == ("missing_set:missing",)
    assert plan.live_actions_available is False


@pytest.mark.parametrize(("change", "reason"), [
    ({"membership_complete": False}, "incomplete_membership:alpha"),
    ({"source": SourceBinding("synthetic-package", "1", "r1", False)}, "stale_or_unverified_source:alpha"),
    ({"source": None}, "missing_source:alpha"),
])
def test_discovery_blockers_survive_planning(adapter, change, reason):
    adapter.sets = (replace(adapter.sets[0], **change), adapter.sets[1])
    plan = build_provisional_plan(adapter.snapshot(), "enable")
    assert plan.outcome == "blocked"
    assert reason in plan.blockers
    assert plan.live_actions_available is False


def test_stale_plan_blocker_is_preserved_without_claiming_live_freshness(adapter):
    initial = adapter.enable()
    stale = adapter.enable(blockers=("stale_plan", "stale_plan"))
    assert stale.outcome == "blocked"
    assert stale.blockers == ("stale_plan",)
    assert stale.delta == initial.delta
    assert stale.approval_basis != initial.approval_basis
    assert stale.live_actions_available is False


def test_incomplete_outside_coverage_stays_blocked(adapter):
    plan = build_provisional_plan(adapter.snapshot(coverage=None), "disable")
    assert plan.outcome == "blocked"
    assert plan.blockers == ("incomplete_coverage",)


def test_identical_inputs_have_identical_evidence_and_review_fingerprints(adapter):
    assert adapter.enable() == adapter.enable()
    plan = adapter.enable()
    assert plan.approval_basis.startswith("synthetic:")
    assert len(plan.evidence_revision) == 64
    assert plan.approval_basis != plan.evidence_revision
    assert plan.live_actions_available is False


def test_revision_state_target_and_selection_are_bound_to_review(adapter):
    initial = adapter.enable()
    revised_source = replace(adapter.sets[0].source, revision="r2")
    adapter.sets = (replace(adapter.sets[0], source=revised_source), adapter.sets[1])
    revised = adapter.enable()
    assert revised.evidence_revision != initial.evidence_revision
    assert revised.approval_basis != initial.approval_basis
    adapter.topics = (*adapter.topics[:3], replace(adapter.topics[3], state="Off"))
    outside_changed = adapter.enable()
    assert outside_changed.evidence_revision != revised.evidence_revision
    assert outside_changed.approval_basis != revised.approval_basis
    snapshot = adapter.snapshot()
    other_target = replace(TARGET, agent_id="00000000-0000-0000-0000-000000004444")
    other = build_provisional_snapshot(
        other_target, snapshot.selected_keys, snapshot.sets, snapshot.topics,
        coverage_complete=True,
    )
    other_plan = build_provisional_plan(
        other, "enable", delta=initial.delta,
        satisfied_member_ids=initial.satisfied_member_ids,
    )
    assert other_plan.approval_basis != outside_changed.approval_basis
    renamed = replace(adapter.sets[0], key="owner-defined:future")
    renamed_snapshot = build_provisional_snapshot(
        TARGET, (renamed.key,), (renamed, adapter.sets[1]), adapter.topics,
        coverage_complete=True,
    )
    renamed_plan = build_provisional_plan(
        renamed_snapshot, "enable", delta=initial.delta,
        satisfied_member_ids=initial.satisfied_member_ids,
    )
    assert renamed_plan.selected_keys == ("owner-defined:future",)
    assert renamed_plan.approval_basis != outside_changed.approval_basis


def test_overlapping_selected_sets_account_for_shared_id_only_once(adapter):
    snapshot = adapter.snapshot(("alpha", "beta"))
    plan = build_provisional_plan(
        snapshot, "enable", delta=(TopicChange("alpha-only", "Off", "On"),),
        satisfied_member_ids=("shared", "required", "beta-only"),
    )
    assert plan.selected_keys == ("alpha", "beta")
    assert len(plan.delta) + len(plan.satisfied_member_ids) == 4
    assert plan.satisfied_member_ids.count("shared") == 1


@pytest.mark.parametrize("delta", [
    (TopicChange("beta-only", "On", "Off"),),
    (TopicChange("lookalike-alpha-only", "Off", "On"),),
])
def test_delta_never_expands_scope_or_matches_display_names(adapter, delta):
    with pytest.raises(PlanningError) as error:
        adapter.enable(delta=delta)
    assert error.value.reason == "out_of_scope"


@pytest.mark.parametrize("change", [
    TopicChange("alpha-only", "On", "On"),
    TopicChange("alpha-only", "Off", "Off"),
    TopicChange("alpha-only", "Unknown", "On"),
    TopicChange("shared", "On", "On"),
])
def test_delta_requires_exact_observed_before_state_and_real_change(adapter, change):
    with pytest.raises(PlanningError) as error:
        adapter.enable(delta=(change,), satisfied_member_ids=())
    assert error.value.reason == "invalid_change"


@pytest.mark.parametrize(("state", "arguments", "reason"), [
    ("On", {"delta": (TopicChange("required", "On", "Off"),)}, "invalid_change"),
    ("Off", {"satisfied_member_ids": ("required",)}, "invalid_satisfied_member"),
])
def test_required_topic_cannot_be_changed_or_counted_as_eligible_during_disable(
    adapter, state, arguments, reason,
):
    adapter.topics = (
        *adapter.topics[:2], replace(adapter.topics[2], state=state), adapter.topics[3],
    )
    with pytest.raises(PlanningError) as error:
        build_provisional_plan(adapter.snapshot(), "disable", **arguments)
    assert error.value.reason == reason


@pytest.mark.parametrize("skips", [
    (TopicSkip("required", "required", ("beta",)),),
    (TopicSkip("alpha-only", "required"),),
    (TopicSkip("shared", "shared"),),
    (TopicSkip("shared", "shared", ("alpha",)),),
    (TopicSkip("shared", "shared", ("missing",)),),
    (TopicSkip("alpha-only", "shared", ("beta",)),),
    (TopicSkip("shared", "shared", ("beta", "beta")),),
    (TopicSkip("shared", "unverified", ("beta",)),),
])
def test_skip_reasons_and_protecting_set_references_are_validated(adapter, skips):
    with pytest.raises(PlanningError) as error:
        build_provisional_plan(adapter.snapshot(), "disable", skips=skips)
    assert error.value.reason == "invalid_skip"


def test_enable_does_not_accept_disable_protection_skips(adapter):
    with pytest.raises(PlanningError) as error:
        adapter.enable(skips=(TopicSkip("required", "required"),))
    assert error.value.reason == "ambiguous_plan"
    with pytest.raises(PlanningError) as error:
        adapter.enable(satisfied_member_ids=("shared",), skips=(TopicSkip("required", "required"),))
    assert error.value.reason == "invalid_skip"


def test_each_selected_member_requires_one_classification_when_evidence_is_complete(adapter):
    with pytest.raises(PlanningError) as error:
        adapter.enable(satisfied_member_ids=("shared",))
    assert error.value.reason == "incomplete_plan"
    with pytest.raises(PlanningError) as error:
        adapter.enable(satisfied_member_ids=("shared", "required", "alpha-only"))
    assert error.value.reason == "ambiguous_plan"


@pytest.mark.parametrize("action", ["", "Enable", "publish", None, []])
def test_invalid_action_fails_without_fixture_disclosure(adapter, action):
    with pytest.raises(PlanningError) as error:
        build_provisional_plan(adapter.snapshot(), action)
    assert error.value.reason == "invalid_action"
    assert "alpha-only" not in str(error.value)


@pytest.mark.parametrize("arguments", [
    {"delta": []},
    {"delta": ("not-a-change",)},
    {"satisfied_member_ids": []},
    {"skips": ("not-a-skip",)},
    {"blockers": ["stale_plan"]},
    {"blockers": ("unsafe\n",)},
    {"blockers": ("",)},
])
def test_malformed_plan_fields_fail_closed(adapter, arguments):
    with pytest.raises(PlanningError):
        build_provisional_plan(adapter.snapshot(), "disable", **arguments)


@pytest.mark.parametrize("field", [
    {"selected_member_ids": ("beta-only",)},
    {"blockers": ()},
])
def test_forged_discovery_derived_fields_are_rejected(adapter, field):
    snapshot = adapter.snapshot(("alpha", "missing"))
    with pytest.raises(PlanningError) as error:
        build_provisional_plan(replace(snapshot, **field), "enable")
    assert error.value.reason == "invalid_snapshot"


def test_live_or_untyped_evidence_cannot_enter_the_synthetic_builder():
    with pytest.raises(PlanningError) as error:
        build_provisional_plan({"evidence_kind": "native_read"}, "disable")
    assert error.value.reason == "invalid_snapshot"


def test_production_entry_never_calls_synthetic_adapter_or_touches_live_input(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("The production entry must not invoke synthetic planning.")

    class LiveInput:
        def __getattribute__(self, name):
            pytest.fail("No live input, client, token, or mutation may be accessed.")

    monkeypatch.setattr("topic_actions_planning.build_provisional_plan", forbidden)
    with pytest.raises(PlanningError) as error:
        plan_topic_actions(LiveInput(), "disable")
    assert error.value.reason == "implementation_pending"
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def flat_catalog():
    return FlatCatalog((
        FlatSet("demo-hr", "exact.hr", (
            FlatMember("exact.hr.topic.One"),
            FlatMember("exact.hr.topic.Shared"),
        ), "source-r1", "synthetic-hr-inventory", "1"),
        FlatSet("demo-extra", "exact.hr", (
            FlatMember("exact.hr.topic.Shared"),
        ), "source-r1", "synthetic-hr-inventory", "1"),
        FlatSet("demo-it", "exact.it", (
            FlatMember("exact.it.topic.Tickets"),
        ), "source-r1", "synthetic-it-inventory", "1"),
    ), "catalog-r1")


@pytest.fixture
def flat_inventory():
    return NativeInventory(TARGET, "exact.hr", (
        InventoryTopic("installed-one", "exact.hr.topic.One", "Off"),
        InventoryTopic("installed-shared", "exact.hr.topic.Shared", "On"),
    ), "read-r1")


@pytest.mark.parametrize(("action", "differences", "matching"), [
    ("enable", (TopicChange("installed-one", "Off", "On"),), ("installed-shared",)),
    ("disable", (TopicChange("installed-shared", "On", "Off"),), ("installed-one",)),
])
def test_whole_flat_set_produces_observations_not_an_eligible_delta(
    flat_catalog, flat_inventory, action, differences, matching,
):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",))
    plan = plan_topic_actions(discovery, action)
    assert plan.target == TARGET
    assert plan.selected_keys == ("demo-hr",)
    assert plan.state_differences == differences
    assert plan.observed_satisfied_member_ids == matching
    assert plan.delta == plan.satisfied_member_ids == plan.skips == ()
    assert plan.blockers == (*discovery.blockers, "authoritative_planning_unavailable")
    assert plan.outcome == "blocked"
    assert plan.evidence_kind == "provided_inventory"
    assert plan.approval_basis.startswith("read_only:")
    assert plan.live_actions_available is False


def test_flat_overlap_is_deduplicated_without_individual_topic_selection(flat_catalog, flat_inventory):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr", "demo-extra"))
    plan = plan_topic_actions(discovery, "disable")
    assert plan.selected_keys == ("demo-hr", "demo-extra")
    assert plan.state_differences == (TopicChange("installed-shared", "On", "Off"),)
    assert plan.observed_satisfied_member_ids == ("installed-one",)
    assert plan.delta == ()


def test_flat_source_variants_and_unrelated_topics_are_not_merged(flat_catalog, flat_inventory):
    other = FlatSet("demo-hr", "package.hr", (
        FlatMember("package.hr.topic.One"),
    ), "source-r1", "synthetic-package-inventory", "2")
    catalog = replace(flat_catalog, sets=(other, *flat_catalog.sets))
    inventory = replace(flat_inventory, topics=(
        *flat_inventory.topics,
        InventoryTopic("foreign-prefix", "package.hr.topic.One", "Off"),
    ))
    discovery = compare_flat_catalog(catalog, inventory, ("demo-hr",))
    plan = plan_topic_actions(discovery, "enable")
    assert plan.state_differences == (TopicChange("installed-one", "Off", "On"),)
    assert plan.observed_satisfied_member_ids == ("installed-shared",)
    assert all(item.component_id != "foreign-prefix" for item in plan.state_differences)


@pytest.mark.parametrize(("keys", "reason"), [
    (("demo-hr", "missing"), "missing_set:missing"),
    (("demo-hr", "demo-it"), "set_not_applicable:demo-it"),
])
def test_invalid_combined_flat_selection_is_not_silently_narrowed(
    flat_catalog, flat_inventory, keys, reason,
):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, keys)
    plan = plan_topic_actions(discovery, "enable")
    assert plan.selected_keys == keys
    assert reason in plan.blockers
    assert plan.state_differences == (TopicChange("installed-one", "Off", "On"),)
    assert plan.outcome == "blocked"
    assert plan.delta == ()


def test_unselected_inapplicable_set_does_not_add_a_selected_scope_blocker(flat_catalog, flat_inventory):
    plan = plan_topic_actions(
        compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",)), "enable",
    )
    assert "set_not_applicable:demo-it" not in plan.blockers
    assert not any(item.component_id.startswith("it-") for item in plan.state_differences)


@pytest.mark.parametrize(("topics", "reason"), [
    ((InventoryTopic("installed-shared", "exact.hr.topic.Shared", "On"),), "set_partial:demo-hr"),
    ((), "set_absent:demo-hr"),
    ((
        InventoryTopic("duplicate-one-a", "exact.hr.topic.One", "Off"),
        InventoryTopic("duplicate-one-b", "exact.hr.topic.One", "Off"),
        InventoryTopic("installed-shared", "exact.hr.topic.Shared", "On"),
    ), "set_ambiguous:demo-hr"),
])
def test_incomplete_flat_membership_cannot_create_an_eligible_delta(flat_catalog, flat_inventory, topics, reason):
    inventory = replace(flat_inventory, topics=topics)
    plan = plan_topic_actions(compare_flat_catalog(flat_catalog, inventory, ("demo-hr",)), "disable")
    assert reason in plan.blockers
    assert plan.outcome == "blocked"
    assert plan.delta == ()
    assert all(item.component_id == "installed-shared" for item in plan.state_differences)


def test_unknown_flat_state_is_not_treated_as_on_off_or_already_correct(flat_catalog, flat_inventory):
    inventory = replace(flat_inventory, topics=(
        replace(flat_inventory.topics[0], state="Unknown"), flat_inventory.topics[1],
    ))
    plan = plan_topic_actions(compare_flat_catalog(flat_catalog, inventory, ("demo-hr",)), "disable")
    assert "unknown_state:installed-one" in plan.blockers
    assert plan.state_differences == (TopicChange("installed-shared", "On", "Off"),)
    assert plan.observed_satisfied_member_ids == ()
    assert plan.satisfied_member_ids == plan.delta == ()


def test_all_observed_states_matching_does_not_prove_eligible_already_correct(flat_catalog, flat_inventory):
    inventory = replace(flat_inventory, topics=tuple(
        replace(topic, state="Off") for topic in flat_inventory.topics
    ))
    plan = plan_topic_actions(compare_flat_catalog(flat_catalog, inventory, ("demo-hr",)), "disable")
    assert plan.state_differences == ()
    assert plan.observed_satisfied_member_ids == ("installed-one", "installed-shared")
    assert plan.outcome == "blocked"
    assert plan.satisfied_member_ids == ()


def test_catalog_required_flags_do_not_become_verified_live_protection(flat_catalog, flat_inventory):
    definition = flat_catalog.sets[0]
    catalog = replace(flat_catalog, sets=(
        replace(definition, members=(replace(definition.members[0], required=True), definition.members[1])),
        *flat_catalog.sets[1:],
    ))
    inventory = replace(flat_inventory, topics=(
        replace(flat_inventory.topics[0], state="On"), flat_inventory.topics[1],
    ))
    plan = plan_topic_actions(compare_flat_catalog(catalog, inventory, ("demo-hr",)), "disable")
    assert "protection_coverage_unverified" in plan.blockers
    assert plan.skips == plan.delta == ()
    assert plan.live_actions_available is False


def test_missing_inventory_revision_stays_unverified(flat_catalog, flat_inventory):
    inventory = replace(flat_inventory, revision=None)
    plan = plan_topic_actions(compare_flat_catalog(flat_catalog, inventory, ("demo-hr",)), "enable")
    assert "inventory_freshness_unverified" in plan.blockers
    assert plan.delta == ()


def test_removed_discovery_blockers_do_not_unlock_flat_planning(flat_catalog, flat_inventory):
    discovery = replace(compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",)), blockers=())
    plan = plan_topic_actions(discovery, "enable")
    assert "authoritative_planning_unavailable" in plan.blockers
    assert "unknown_protection:installed-one" in plan.blockers
    assert plan.outcome == "blocked"
    assert plan.delta == ()
    assert plan.live_actions_available is False


def test_flat_preview_retains_declared_native_provenance_without_synthetic_fallback(
    flat_catalog, flat_inventory, monkeypatch,
):
    discovery = replace(
        compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",)),
        evidence_kind="native_read",
    )

    def forbidden(*args, **kwargs):
        pytest.fail("A flat preview must not discover, mutate, or use synthetic planning.")

    monkeypatch.setattr("topic_actions_planning.build_provisional_plan", forbidden)
    monkeypatch.setattr("topic_actions_discovery.discover_topic_sets", forbidden)
    monkeypatch.setattr("topic_actions_flat_discovery.discover_flat_topic_sets", forbidden)
    plan = plan_topic_actions(discovery, "enable")
    assert plan.evidence_kind == "native_read"
    assert not plan.approval_basis.startswith("synthetic:")
    assert plan.live_actions_available is False
    with pytest.raises(PlanningError) as error:
        build_provisional_plan(discovery, "enable")
    assert error.value.reason == "invalid_snapshot"


def test_flat_review_fingerprint_tracks_source_read_state_action_and_selection(flat_catalog, flat_inventory):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",))
    initial = plan_topic_actions(discovery, "enable")
    assert initial == plan_topic_actions(discovery, "enable")
    changes = (
        replace(discovery, catalog_revision="catalog-r2"),
        replace(discovery, inventory_revision="read-r2"),
        compare_flat_catalog(flat_catalog, replace(flat_inventory, topics=(
            replace(flat_inventory.topics[0], state="On"), flat_inventory.topics[1],
        )), ("demo-hr",)),
        compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr", "demo-extra")),
    )
    for changed in changes:
        revised = plan_topic_actions(changed, "enable")
        assert revised.evidence_revision != initial.evidence_revision
        assert revised.approval_basis != initial.approval_basis
    disabled = plan_topic_actions(discovery, "disable")
    assert disabled.evidence_revision == initial.evidence_revision
    assert disabled.approval_basis != initial.approval_basis


@pytest.mark.parametrize("keys", [None, ()])
def test_flat_listing_never_implicitly_plans_all_sets(flat_catalog, flat_inventory, keys):
    if keys == ():
        discovery = replace(compare_flat_catalog(flat_catalog, flat_inventory), selected_keys=())
    else:
        discovery = compare_flat_catalog(flat_catalog, flat_inventory)
    with pytest.raises(PlanningError) as error:
        plan_topic_actions(discovery, "enable")
    assert error.value.reason == "invalid_selection"


@pytest.mark.parametrize("change", [
    {"selected_member_ids": ("foreign-id",)},
    {"selected_member_ids": ("installed-one", "installed-one")},
    {"evidence_kind": "synthetic"},
    {"evidence_kind": "unverified-other-source"},
    {"blockers": ("private\nunsafe",)},
    {"selected_keys": ("demo-hr", "demo-hr")},
])
def test_malformed_flat_contracts_fail_without_disclosure_or_fallback(flat_catalog, flat_inventory, change):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",))
    with pytest.raises(PlanningError) as error:
        plan_topic_actions(replace(discovery, **change), "enable")
    assert "foreign-id" not in str(error.value)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("field", [
    {"status": "absent"},
    {"members": ()},
])
def test_flat_availability_must_agree_with_its_definition_and_matches(flat_catalog, flat_inventory, field):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",))
    forged = replace(discovery, sets=(replace(discovery.sets[0], **field), *discovery.sets[1:]))
    with pytest.raises(PlanningError) as error:
        plan_topic_actions(forged, "enable")
    assert error.value.reason == "invalid_discovery"


def test_conflicting_shared_states_fail_instead_of_choosing_a_favorable_state(flat_catalog, flat_inventory):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr", "demo-extra"))
    other = discovery.sets[1]
    forged = replace(discovery, sets=(
        discovery.sets[0],
        replace(other, members=(replace(other.members[0], state="Off"),)),
        *discovery.sets[2:],
    ))
    with pytest.raises(PlanningError) as error:
        plan_topic_actions(forged, "disable")
    assert error.value.reason == "conflicting_evidence"


@pytest.mark.parametrize("action", ["publish", "", None, []])
def test_invalid_flat_action_does_not_create_a_preview(flat_catalog, flat_inventory, action):
    discovery = compare_flat_catalog(flat_catalog, flat_inventory, ("demo-hr",))
    with pytest.raises(PlanningError) as error:
        plan_topic_actions(discovery, action)
    assert error.value.reason == "invalid_action"
