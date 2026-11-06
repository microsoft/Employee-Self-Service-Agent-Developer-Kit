from __future__ import annotations

from essmig.ess import (
    CA_AGENT_SCHEMANAMES,
    CA_SOLUTION_BY_VERTICAL,
    DA_SCHEMANAME_BY_VERTICAL,
    NON_PORTED_EXTENSION_SOLUTIONS,
    OOB_CA_SOLUTIONS,
    PORTED_EXTENSION_SOLUTIONS,
    TARGETS,
    non_ported_pack_of,
    schema_prefix,
    schema_suffix,
)


def test_suffix_is_the_shared_join_key_between_ca_and_da() -> None:
    ca = "msdyn_copilotforemployeeselfservicehr.topic.ConversationStart"
    da = "gptagent_copilotforemployeeselfservicehr.topic.ConversationStart"
    assert schema_suffix(ca) == schema_suffix(da) == "topic.ConversationStart"


def test_suffix_keeps_dots_beyond_the_first() -> None:
    assert schema_suffix("msdyn_x.topic.A.B") == "topic.A.B"


def test_unprefixed_names_are_returned_unchanged() -> None:
    assert schema_suffix("new_CustomMetricDefinition_abc") == "new_CustomMetricDefinition_abc"


def test_prefix_is_everything_before_the_first_dot() -> None:
    assert schema_prefix("gptagent_foo.topic.Bar") == "gptagent_foo"


def test_extension_solution_names_match_their_manifests_not_their_folders() -> None:
    # These folders are named *HCM but the solutions are not. Discovery classifies
    # by solution name, so an inferred name would misread OOB content as customized.
    assert "msdyn_EssHRWorkday" in OOB_CA_SOLUTIONS
    assert "msdyn_EssHRWorkdayHCM" not in OOB_CA_SOLUTIONS
    assert "msdyn_EssHRSuccessFactors" in OOB_CA_SOLUTIONS
    assert "msdyn_EssHRADP" in OOB_CA_SOLUTIONS


def test_core_is_a_first_class_target_alongside_the_domain_agents() -> None:
    assert TARGETS == ("core", "hr", "it")


def test_core_maps_to_the_hub_bot_not_the_legacy_monolith() -> None:
    # The router hub is ...core; the suffix-less ...selfservice is a legacy monolith.
    assert CA_AGENT_SCHEMANAMES["core"] == "msdyn_copilotforemployeeselfservicecore"
    assert CA_AGENT_SCHEMANAMES["core"] != "msdyn_copilotforemployeeselfservice"


def test_every_target_has_a_ca_source_and_a_da_destination() -> None:
    for target in TARGETS:
        assert target in CA_SOLUTION_BY_VERTICAL
        assert target in CA_AGENT_SCHEMANAMES
        assert target in DA_SCHEMANAME_BY_VERTICAL


def test_core_destinations_point_at_the_core_da_agent() -> None:
    assert CA_SOLUTION_BY_VERTICAL["core"] == "msdyn_CopilotForEmployeeSelfServiceCore"
    assert DA_SCHEMANAME_BY_VERTICAL["core"] == "gptagent_copilotforemployeeselfservicecore"


def test_ported_and_non_ported_packs_partition_the_extension_solutions() -> None:
    # A pack is either portable into HR/IT or it isn't; nothing may be both or neither.
    assert PORTED_EXTENSION_SOLUTIONS.isdisjoint(NON_PORTED_EXTENSION_SOLUTIONS)
    assert PORTED_EXTENSION_SOLUTIONS <= OOB_CA_SOLUTIONS
    assert NON_PORTED_EXTENSION_SOLUTIONS <= OOB_CA_SOLUTIONS


def test_a_non_ported_pack_is_named_so_the_report_can_flag_it() -> None:
    # SuccessFactors has no DA equivalent in this release -> blocked, and named.
    assert non_ported_pack_of(["msdyn_EssHRSuccessFactors"]) == "msdyn_EssHRSuccessFactors"


def test_a_ported_pack_is_not_flagged_as_non_ported() -> None:
    # Workday HR ships a DA equivalent, so its customizations can be carried.
    assert non_ported_pack_of(["msdyn_EssHRWorkday"]) is None


def test_pack_lookup_ignores_non_extension_solutions_and_bad_input() -> None:
    assert non_ported_pack_of(["msdyn_CopilotForEmployeeSelfServiceHR"]) is None
    assert non_ported_pack_of([]) is None
    assert non_ported_pack_of(None) is None
