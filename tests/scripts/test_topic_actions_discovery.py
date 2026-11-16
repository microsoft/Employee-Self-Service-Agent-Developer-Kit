# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Synthetic M3 contracts only; no API responses or real ISV memberships."""

from dataclasses import replace

import pytest

from topic_actions_discovery import (
    DiscoveryError,
    DiscoveryTarget,
    SourceBinding,
    TopicEvidence,
    TopicSet,
    build_provisional_snapshot,
    discover_topic_sets,
)


TARGET = DiscoveryTarget(
    "00000000-0000-0000-0000-000000001111",
    "00000000-0000-0000-0000-000000002222",
    "00000000-0000-0000-0000-000000003333",
)


class SyntheticDiscoveryAdapter:
    """Test-only exact fixtures, not owner-approved inventories or a live source."""

    def __init__(self):
        workday_source = SourceBinding("synthetic-workday-package", "1", "wd-r1", True)
        servicenow_source = SourceBinding("synthetic-sn-package", "1", "sn-r1", True)
        self.sets = (
            TopicSet("workday", ("wd-exact", "shared-exact"), True, workday_source),
            TopicSet("servicenow-hr", ("sn-hr-exact", "shared-exact"), True, servicenow_source),
            TopicSet("servicenow-it", ("sn-it-exact",), True, servicenow_source),
        )
        self.topics = (
            TopicEvidence("wd-exact", False, "On"),
            TopicEvidence("shared-exact", False, "On"),
            TopicEvidence("sn-hr-exact", False, "Off"),
            TopicEvidence("sn-it-exact", False, "On"),
        )

    def discover(self, keys=("workday",), coverage=True):
        return build_provisional_snapshot(
            TARGET, keys, self.sets, self.topics, coverage_complete=coverage,
        )


@pytest.fixture
def adapter():
    return SyntheticDiscoveryAdapter()


def test_full_isv_sets_exact_union_overlap_and_package_binding(adapter):
    result = adapter.discover(("workday", "servicenow-hr", "servicenow-it"))
    assert result.selected_member_ids == ("wd-exact", "shared-exact", "sn-hr-exact", "sn-it-exact")
    assert result.memberships("shared-exact") == ("workday", "servicenow-hr")
    assert result.memberships("workday-looking-name") == ()
    assert result.sets[0].source.revision == "wd-r1"
    assert result.sets[1].source.package_id == "synthetic-sn-package"
    assert result.blockers == ()
    assert result.evidence_kind == "synthetic"
    assert result.live_actions_available is False


def test_partly_enabled_outside_set_retains_enabled_member_outside_selected_union(adapter):
    adapter.topics = tuple(
        replace(item, state="On") if item.component_id == "sn-hr-exact"
        else replace(item, state="Off") if item.component_id == "shared-exact"
        else item for item in adapter.topics
    )
    result = adapter.discover()
    assert "sn-hr-exact" not in result.selected_member_ids
    assert result.memberships("shared-exact") == ("workday", "servicenow-hr")
    outside = next(item for item in result.topics if item.component_id == "sn-hr-exact")
    shared = next(item for item in result.topics if item.component_id == "shared-exact")
    assert outside.state == "On"
    assert shared.state == "Off"
    assert result.blockers == ()
    assert result.live_actions_available is False


def test_descriptions_and_unrelated_missing_set_do_not_block_explicit_selection(adapter):
    adapter.sets = adapter.sets[:2]
    result = adapter.discover()
    assert result.sets[0].description is None
    assert result.blockers == ()
    adapter.sets = (replace(
        adapter.sets[0], description="Synthetic purpose",
        description_provenance="synthetic-description-source",
    ), adapter.sets[1])
    updated = adapter.discover()
    assert updated.selected_member_ids == result.selected_member_ids
    assert updated.sets[0].description_provenance == "synthetic-description-source"
    assert updated.live_actions_available is False


@pytest.mark.parametrize(("change", "blocker"), [
    ({"membership_complete": None}, "incomplete_membership:workday"),
    ({"membership_complete": False}, "incomplete_membership:workday"),
    ({"source": None}, "missing_source:workday"),
    ({"source": SourceBinding("pkg", "1", None, True)}, "missing_source:workday"),
    ({"source": SourceBinding("pkg", "1", "r1", False)}, "stale_or_unverified_source:workday"),
    ({"source": SourceBinding("pkg", "1", "r1", None)}, "stale_or_unverified_source:workday"),
    ({"member_ids": ()}, "empty_membership:workday"),
])
def test_incomplete_selected_evidence_is_blocked_not_success(adapter, change, blocker):
    adapter.sets = (replace(adapter.sets[0], **change), *adapter.sets[1:])
    result = adapter.discover()
    assert blocker in result.blockers
    assert result.live_actions_available is False


def test_invalid_combined_scope_stays_selected_and_is_not_silently_narrowed(adapter):
    adapter.sets = (adapter.sets[0], adapter.sets[2])
    keys = ("workday", "servicenow-hr")
    result = adapter.discover(keys)
    assert result.selected_keys == keys
    assert "missing_set:servicenow-hr" in result.blockers
    assert result.live_actions_available is False


def test_missing_outside_member_and_unknown_required_evidence_are_explicit(adapter):
    adapter.topics = tuple(
        replace(item, required=None) if item.component_id == "wd-exact" else item
        for item in adapter.topics if item.component_id != "sn-hr-exact"
    )
    result = adapter.discover()
    assert "unknown_protection:wd-exact" in result.blockers
    assert "missing_topic:sn-hr-exact" in result.blockers


@pytest.mark.parametrize("coverage", [False, None])
def test_unknown_outside_coverage_is_not_no_dependencies(adapter, coverage):
    assert "incomplete_coverage" in adapter.discover(coverage=coverage).blockers


def test_required_topics_and_unknown_states_remain_evidence_not_mutation_decisions(adapter):
    adapter.topics = (replace(adapter.topics[0], required=True, state="Unknown"), *adapter.topics[1:])
    result = adapter.discover()
    assert result.topics[0].required is True
    assert result.topics[0].state == "Unknown"
    assert result.live_actions_available is False


@pytest.mark.parametrize(("mutation", "reason"), [
    (lambda a: setattr(a, "sets", (*a.sets, a.sets[0])), "ambiguous_set"),
    (lambda a: setattr(a, "sets", (replace(a.sets[0], member_ids=("same", "same")),)), "ambiguous_membership"),
    (lambda a: setattr(a, "topics", (*a.topics, a.topics[0])), "ambiguous_topic"),
    (lambda a: setattr(a, "topics", (TopicEvidence("unsafe\n", False),)), "invalid_identity"),
    (lambda a: setattr(a, "topics", (TopicEvidence("wd-exact", 1),)), "invalid_evidence"),
    (lambda a: setattr(a, "topics", (TopicEvidence("wd-exact", False, "Active"),)), "invalid_state"),
    (lambda a: setattr(a, "sets", (TopicSet("invalid\nkey", (), True, None),)), "invalid_identity"),
])
def test_malformed_and_ambiguous_contracts_fail_closed(adapter, mutation, reason):
    mutation(adapter)
    with pytest.raises(DiscoveryError) as error:
        adapter.discover()
    assert error.value.reason == reason


@pytest.mark.parametrize("keys", [(), ("workday", "workday"), (" workday",), ("unsafe\n",)])
def test_invalid_selection_never_expands_all_or_guesses_members(adapter, keys):
    with pytest.raises(DiscoveryError) as error:
        adapter.discover(keys)
    assert error.value.reason == "invalid_selection"


def test_unknown_key_does_not_expand_all_or_fall_back_to_current_sets(adapter):
    result = adapter.discover(("all",))
    assert result.selected_keys == ("all",)
    assert result.selected_member_ids == ()
    assert result.blockers == ("missing_set:all",)
    assert result.live_actions_available is False


def test_future_source_keys_and_revisions_do_not_require_isv_name_changes(adapter):
    source = SourceBinding("future-package", "2", "future-schema-r2", True)
    adapter.sets = (
        TopicSet("owner-defined:absence", ("wd-exact", "shared-exact"), True, source),
        TopicSet("owner-defined:pay", ("shared-exact", "sn-hr-exact"), True, source),
        TopicSet("owner-defined:additional-isv", ("sn-it-exact",), True, source),
    )
    result = adapter.discover(("owner-defined:absence", "owner-defined:additional-isv"))
    assert result.selected_member_ids == ("wd-exact", "shared-exact", "sn-it-exact")
    assert result.memberships("shared-exact") == ("owner-defined:absence", "owner-defined:pay")
    assert result.sets[0].source.revision == "future-schema-r2"
    assert result.sets[0].source.package_version == "2"
    assert result.blockers == ()
    assert result.evidence_kind == "synthetic"
    assert result.live_actions_available is False


def test_uuid_member_identity_is_canonicalized_before_deduplication(adapter):
    identity = "00000000-0000-0000-0000-00000000aaaa"
    adapter.sets = (replace(adapter.sets[0], member_ids=(identity.upper(),)),)
    adapter.topics = (TopicEvidence(identity, False),)
    result = adapter.discover()
    assert result.selected_member_ids == (identity,)
    assert result.memberships(identity.upper()) == ("workday",)
    adapter.sets = (replace(adapter.sets[0], member_ids=(identity, identity.upper())),)
    with pytest.raises(DiscoveryError) as error:
        adapter.discover()
    assert error.value.reason == "ambiguous_membership"


def test_bad_target_is_rejected_without_source_or_identity_disclosure(adapter):
    with pytest.raises(DiscoveryError) as error:
        build_provisional_snapshot(
            replace(TARGET, agent_id="private-invalid-target"), ("workday",),
            adapter.sets, adapter.topics, coverage_complete=True,
        )
    assert error.value.reason == "invalid_target"
    assert "private-invalid-target" not in str(error.value)


def test_live_entry_never_uses_synthetic_adapter_or_mutates(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Production entry must not invoke the synthetic boundary.")

    monkeypatch.setattr("topic_actions_discovery.build_provisional_snapshot", forbidden)
    with pytest.raises(DiscoveryError) as error:
        discover_topic_sets(TARGET, ("workday",))
    assert error.value.reason == "implementation_pending"
    assert list(tmp_path.iterdir()) == []
