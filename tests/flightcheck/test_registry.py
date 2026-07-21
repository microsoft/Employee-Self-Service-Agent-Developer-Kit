# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the FlightCheck single-checkpoint registry.

Pure-logic tests (no network, no clients) — the cardinal cassette rule in
``tests/AGENTS.md`` explicitly excludes "tests of the kit's pure-logic
helpers (no network)". These pin the registry's resolution, transitive
requirement union, and graph-validity invariants the single-checkpoint
feature relies on.
"""

from __future__ import annotations

import pytest

from flightcheck import registry
from flightcheck.registry import CheckpointSpec, RegistryError
from flightcheck.runner import Priority, Role
from flightcheck.checks.workday import run_workday_checks
from flightcheck.checks.external_systems import run_external_systems_checks
from flightcheck.checks.solution import run_solution_checks
from flightcheck.checks.workday_tenant import run_workday_tenant_checks
from flightcheck.checks.workday_extension import run_workday_extension_checks
from flightcheck.checks.topics import run_topic_checks


class TestValidateRegistry:
    """The shipped registry must be internally consistent."""

    def test_shipped_registry_is_valid(self):
        # Imports already ran validate_registry() once; calling it again must
        # not raise for the real registry.
        registry.validate_registry()

    def test_every_declared_prereq_resolves(self):
        for spec in registry.REGISTRY.values():
            for prereq in spec.prereqs:
                resolved = registry.resolve(prereq)
                assert resolved is not None, (
                    f"{spec.key} declares unresolvable prereq {prereq!r}"
                )

    def test_cycle_is_rejected(self, monkeypatch):
        # Build a 2-node cycle A -> B -> A and assert validate_registry raises
        # with a message naming the cycle. Patch a copy of REGISTRY in place.
        a = CheckpointSpec(
            key="CYC-A", category_fn=run_workday_checks,
            category_label="Workday", prereqs=("CYC-B",),
        )
        b = CheckpointSpec(
            key="CYC-B", category_fn=run_workday_checks,
            category_label="Workday", prereqs=("CYC-A",),
        )
        monkeypatch.setattr(registry, "REGISTRY", {"CYC-A": a, "CYC-B": b})
        with pytest.raises(RegistryError, match="Cyclic prerequisite chain"):
            registry.validate_registry()

    def test_unresolvable_prereq_is_rejected(self, monkeypatch):
        bad = CheckpointSpec(
            key="BAD-1", category_fn=run_workday_checks,
            category_label="Workday", prereqs=("DOES-NOT-EXIST",),
        )
        monkeypatch.setattr(registry, "REGISTRY", {"BAD-1": bad})
        with pytest.raises(RegistryError, match="does not resolve"):
            registry.validate_registry()


class TestResolve:
    """Exact-before-family + longest-prefix resolution."""

    def test_exact_fixed_id(self):
        assert registry.resolve("WD-PKG-001").key == "WD-PKG-001"

    def test_exact_beats_family(self):
        # WD-CONN-010 / -012 / -102 are fixed entries that must NOT collapse
        # into the WD-CONN family even though that family exists.
        for fixed in ("WD-CONN-010", "WD-CONN-012", "WD-CONN-102"):
            assert registry.resolve(fixed).key == fixed
            assert registry.resolve(fixed).is_family is False

    def test_dynamic_id_resolves_to_family(self):
        assert registry.resolve("WD-CONN-003").key == "WD-CONN"
        assert registry.resolve("WD-FLOW-002").key == "WD-FLOW"
        assert registry.resolve("WD-WF-007").key == "WD-WF"
        assert registry.resolve("WD-ENV-001").key == "WD-ENV"

    def test_wildcard_family_request_resolves(self):
        assert registry.resolve("WD-FLOW-*").key == "WD-FLOW"
        assert registry.resolve("WD-CONN-*").key == "WD-CONN"

    def test_unknown_returns_none(self):
        assert registry.resolve("SN-CONN-003") is None
        assert registry.resolve("BOGUS-1") is None
        assert registry.resolve("") is None

    def test_no_blanket_numeric_strip(self):
        # A fixed ID that is NOT registered and whose prefix is NOT a family
        # must return None, not be coerced into a fabricated family by
        # stripping a trailing -\d+.
        assert registry.resolve("ZZZ-001") is None
        assert registry.resolve("ENV-004-OR-001") is None


class TestMatches:
    """The runner's result filter for hydrate-then-filter."""

    def test_exact_target_matches_only_itself(self):
        assert registry.matches("WD-CONN-012", "WD-CONN-012") is True
        assert registry.matches("WD-CONN-012", "WD-CONN-003") is False
        assert registry.matches("WD-PKG-001", "WD-PKG-001") is True
        assert registry.matches("WD-PKG-001", "WD-CONN-001") is False

    def test_family_target_matches_all_members(self):
        assert registry.matches("WD-FLOW", "WD-FLOW-001") is True
        assert registry.matches("WD-FLOW", "WD-FLOW-099") is True
        assert registry.matches("WD-FLOW-*", "WD-FLOW-002") is True
        assert registry.matches("WD-FLOW", "WD-CONN-001") is False

    def test_exact_dynamic_target_matches_one(self):
        # An operator can ask for a single dynamic row by its exact ID.
        assert registry.matches("WD-FLOW-002", "WD-FLOW-002") is True
        assert registry.matches("WD-FLOW-002", "WD-FLOW-001") is False


class TestTransitiveRequirements:
    """Client/config union over the transitive prerequisite closure."""

    def test_entra_only_checkpoint_needs_no_dataverse(self):
        plan = registry.transitive_requirements("WD-CONN-102")
        assert plan.clients == frozenset({registry.GRAPH})
        assert plan.requires_dataverse_endpoint is False
        # Only the Workday owning function runs (no prereqs).
        assert [label for label, _ in plan.ordered_fns] == ["Workday"]

    def test_closure_unions_clients_across_prereqs(self):
        # WD-CONN-012 itself declares only dataverse, but pulls pp_admin in via
        # its WD-001 prerequisite — naive one-level resolution would miss it.
        plan = registry.transitive_requirements("WD-CONN-012")
        assert registry.DATAVERSE in plan.clients
        assert registry.PP_ADMIN in plan.clients
        assert plan.requires_dataverse_endpoint is True

    def test_external_systems_orders_before_workday(self):
        # _workday_flows must be hydrated by run_external_systems_checks before
        # run_workday_checks runs (which early-returns without it).
        plan = registry.transitive_requirements("WD-CONN-012")
        labels = [label for label, _ in plan.ordered_fns]
        fns = [fn for _, fn in plan.ordered_fns]
        assert labels.index("External Systems") < labels.index("Workday")
        assert run_external_systems_checks in fns
        assert run_workday_checks in fns
        # Each category function registered exactly once despite multiple specs
        # sharing run_workday_checks.
        assert fns.count(run_workday_checks) == 1

    def test_env002_pulls_env001_prereq(self):
        plan = registry.transitive_requirements("ENV-002")
        # Single category function (run_environment_checks) covers both.
        assert len(plan.ordered_fns) == 1
        assert plan.requires_config is True

    def test_env_capacity_001_resolves_and_unions_powerplatform(self):
        spec = registry.resolve("ENV-CAPACITY-001")
        assert spec is not None and spec.key == "ENV-CAPACITY-001"
        assert spec.category_label == "Environment"
        # Needs BOTH the BAP admin client (env id) and the licensing client.
        assert spec.clients == frozenset({registry.PP_ADMIN, registry.POWERPLATFORM})
        plan = registry.transitive_requirements("ENV-CAPACITY-001")
        assert registry.PP_ADMIN in plan.clients
        assert registry.POWERPLATFORM in plan.clients
        assert plan.requires_dataverse_endpoint is True
        # Shares run_environment_checks with its ENV-001 prereq -> one fn.
        assert len(plan.ordered_fns) == 1

    def test_ess_soln_001_resolves_and_pulls_env_prereqs(self):
        spec = registry.resolve("ESS-SOLN-001")
        assert spec is not None and spec.key == "ESS-SOLN-001"
        assert spec.category_label == "Solution"
        assert spec.category_fn is run_solution_checks
        # Solution presence is a pure Dataverse read.
        assert spec.clients == frozenset({registry.DATAVERSE})
        assert spec.prereqs == ("ENV-002",)
        plan = registry.transitive_requirements("ESS-SOLN-001")
        assert registry.DATAVERSE in plan.clients
        assert plan.requires_config is True
        assert plan.requires_dataverse_endpoint is True
        # Own fn (run_solution_checks) plus the shared run_environment_checks
        # that ENV-001+ENV-002 pull in -> exactly two, environment first.
        fns = [fn for _label, fn in plan.ordered_fns]
        assert run_solution_checks in fns
        assert len(fns) == 2
        assert fns.index(run_solution_checks) == len(fns) - 1


class TestListCheckpoints:
    """--list-checkpoints surface."""

    def test_excludes_non_listable_prereq_nodes(self):
        keys = {spec.key for spec in registry.list_checkpoints()}
        # WD-001 is registered only to satisfy prereq resolution; it belongs to
        # the External-Systems scope and must not appear in the setup listing.
        assert "WD-001" not in keys
        assert "WD-PKG-001" in keys
        assert "WD-CONN" in keys  # family is listable

    def test_sorted_by_key(self):
        keys = [spec.key for spec in registry.list_checkpoints()]
        assert keys == sorted(keys)


class TestWorkdayTenantCheckpoints:
    """skill-4 mints two portal-only MANUAL checkpoints (no client), sharing
    checks/workday_tenant.run_workday_tenant_checks."""

    def test_api_client_spec(self):
        spec = registry.resolve("WD-API-CLIENT-001")
        assert spec is not None and spec.key == "WD-API-CLIENT-001"
        assert spec.category_label == "Workday Tenant"
        assert spec.category_fn is run_workday_tenant_checks
        # Pure-logic attestation — needs no client (like WD-ENTRA-SIGNOPT-001).
        assert spec.clients == frozenset()
        assert spec.requires_dataverse_endpoint is False
        assert spec.priority == Priority.CRITICAL.value
        assert Role.WORKDAY_ADMIN.value in spec.roles

    def test_tenant_spec(self):
        spec = registry.resolve("WD-TENANT-001")
        assert spec is not None and spec.key == "WD-TENANT-001"
        assert spec.category_label == "Workday Tenant"
        assert spec.category_fn is run_workday_tenant_checks
        assert spec.clients == frozenset()
        assert spec.priority == Priority.HIGH.value
        assert Role.WORKDAY_ADMIN.value in spec.roles

    def test_plan_is_self_contained_and_clientless(self):
        # Self-contained (prereqs=()) — only the owning function runs, and the
        # target needs neither a client nor a Dataverse endpoint.
        plan = registry.transitive_requirements("WD-API-CLIENT-001")
        assert plan.clients == frozenset()
        assert plan.requires_dataverse_endpoint is False
        assert [label for label, _ in plan.ordered_fns] == ["Workday Tenant"]

    def test_both_are_listable(self):
        keys = {spec.key for spec in registry.list_checkpoints()}
        assert "WD-API-CLIENT-001" in keys
        assert "WD-TENANT-001" in keys


class TestWorkdayExtensionCheckpoints:
    """skill-5 mints five checkpoints, all sharing
    checks/workday_extension.run_workday_extension_checks, category
    "Workday Extension". Two are always-MANUAL echoes/attestations, three are
    programmatic (one Dataverse read + two pure-local)."""

    _ALL = (
        "WD-CONN-AUTH-001",
        "DV-CONN-001",
        "WD-REST-001",
        "WD-REST-002",
        "WD-NET-001",
    )

    def test_all_five_resolve_to_the_extension_category(self):
        for cp in self._ALL:
            spec = registry.resolve(cp)
            assert spec is not None and spec.key == cp
            assert spec.category_label == "Workday Extension"
            assert spec.category_fn is run_workday_extension_checks
            assert spec.priority == Priority.HIGH.value

    def test_conn_auth_spec_declares_pp_admin_and_pkg_prereq(self):
        # WD-CONN-AUTH-001 is a FIXED spec coexisting with the WD-CONN family
        # (exact-first resolution), reads the cached ff0df ref (WD-PKG-001) and
        # the BAP connection (PP admin) for its echo.
        spec = registry.resolve("WD-CONN-AUTH-001")
        assert spec.clients == frozenset({registry.PP_ADMIN})
        assert spec.requires_dataverse_endpoint is True
        assert spec.prereqs == ("WD-PKG-001", "WD-001")
        assert Role.ESS_MAKER.value in spec.roles

    def test_conn_auth_exact_beats_wd_conn_family(self):
        # The WD-CONN family must still resolve dynamic members, and the fixed
        # WD-CONN-AUTH-001 must resolve to itself, not the family.
        assert registry.resolve("WD-CONN-003").key == "WD-CONN"
        assert registry.resolve("WD-CONN-AUTH-001").key == "WD-CONN-AUTH-001"
        assert registry.resolve("WD-CONN-AUTH-001").is_family is False

    def test_dv_conn_spec_declares_dataverse_and_pp_admin(self):
        spec = registry.resolve("DV-CONN-001")
        assert spec.clients == frozenset({registry.DATAVERSE, registry.PP_ADMIN})
        assert spec.requires_dataverse_endpoint is True
        assert spec.prereqs == ()
        assert Role.ESS_MAKER.value in spec.roles

    def test_rest_and_local_checks_are_clientless(self):
        for cp in ("WD-REST-001", "WD-REST-002"):
            spec = registry.resolve(cp)
            assert spec.clients == frozenset()
            assert spec.requires_dataverse_endpoint is False
            assert spec.prereqs == ()
            assert Role.ESS_MAKER.value in spec.roles

    def test_net_check_is_clientless_and_ppadmin_gated(self):
        spec = registry.resolve("WD-NET-001")
        assert spec.clients == frozenset()
        assert spec.requires_dataverse_endpoint is False
        # No InfoSec Role enum exists; POWER_PLATFORM_ADMIN is the closest
        # infra-owning role (see checks/workday_extension.py note).
        assert Role.POWER_PLATFORM_ADMIN.value in spec.roles

    def test_dv_conn_plan_unions_clients(self):
        plan = registry.transitive_requirements("DV-CONN-001")
        assert registry.DATAVERSE in plan.clients
        assert registry.PP_ADMIN in plan.clients

    def test_all_five_are_listable(self):
        keys = {spec.key for spec in registry.list_checkpoints()}
        for cp in self._ALL:
            assert cp in keys


class TestTopicCheckpoints:
    """skill-6 mints two FAMILY checkpoints (one row per new/custom topic),
    both sharing checks/topics.run_topic_checks, category "Workday Topics".
    Both are pure local-file checks — no client, no config, no Dataverse
    endpoint, self-contained (prereqs=())."""

    _FAMILIES = ("TOPIC-TRIGGER", "TOPIC-INTEGRATION")

    def test_both_families_resolve_to_the_topics_category(self):
        for key in self._FAMILIES:
            spec = registry.resolve(key)
            assert spec is not None and spec.key == key
            assert spec.category_label == "Workday Topics"
            assert spec.category_fn is run_topic_checks
            assert spec.priority == Priority.HIGH.value
            assert spec.is_family is True

    def test_dynamic_members_resolve_to_the_family(self):
        # A per-topic member ID (TOPIC-TRIGGER-001) resolves to its family key,
        # and the family remains distinct from the integration family.
        assert registry.resolve("TOPIC-TRIGGER-001").key == "TOPIC-TRIGGER"
        assert registry.resolve("TOPIC-TRIGGER-099").key == "TOPIC-TRIGGER"
        assert registry.resolve("TOPIC-INTEGRATION-002").key == "TOPIC-INTEGRATION"
        assert registry.resolve("TOPIC-TRIGGER-*").key == "TOPIC-TRIGGER"

    def test_both_families_are_clientless_and_self_contained(self):
        for key in self._FAMILIES:
            spec = registry.resolve(key)
            assert spec.clients == frozenset()
            assert spec.requires_config is False
            assert spec.requires_dataverse_endpoint is False
            assert spec.prereqs == ()
            assert Role.ESS_MAKER.value in spec.roles

    def test_topic_family_matching(self):
        assert registry.matches("TOPIC-TRIGGER", "TOPIC-TRIGGER-001") is True
        assert registry.matches("TOPIC-INTEGRATION", "TOPIC-INTEGRATION-042") is True
        assert registry.matches("TOPIC-TRIGGER", "TOPIC-INTEGRATION-001") is False

    def test_both_families_are_listable(self):
        keys = {spec.key for spec in registry.list_checkpoints()}
        for key in self._FAMILIES:
            assert key in keys
