# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Single-checkpoint registry.

The runner registers checks per *category function* (e.g.
``run_workday_checks``), and a single category function emits many
``CheckResult`` rows — several of which share runner state populated by
earlier rows in the same (or a different) category. You therefore cannot
"run only the check that produces ``WD-CONN-012``" in isolation; you have
to run its in-category prerequisites first to hydrate shared state.

This module is the **static source of truth** that makes single-checkpoint
invocation possible. For each setup-relevant checkpoint ID (or dynamic
family) it records:

* the **owning category function** (the same callable ``cli.py`` registers
  for ``--scope`` runs),
* the **clients** that function needs to evaluate this checkpoint
  (``graph`` / ``dataverse`` / ``pp_admin`` / ``pva``),
* whether it needs ``.local/config.json`` and a ``dataverseEndpoint``,
* the **prerequisite checkpoint IDs** whose category functions must run
  first to hydrate shared state.

``cli.py`` reads this registry to (a) implement ``--list-checkpoints``
without any broad run, and (b) for ``--checkpoint <ID>``, initialise only
the clients the target's transitive prerequisite closure declares, run the
owning functions in canonical order, then filter results down to the
target.

**Scope:** the ESS + Workday *setup* checkpoints only — not the entire
FlightCheck surface. Other integrations (ServiceNow ``SN-*``, graph
connector ``EXT-*``, ``SAP-*``) and the pre-existing ``ENV-003`` /
``ENV-004`` (+ detail) rows stay validated by the existing ``--scope``
runs and are deliberately out of registry scope. See
``plans/workday-setup/flightcheck-single-checkpoint.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from flightcheck.runner import Priority, Role
from flightcheck.checks.entra_app import run_entra_app_checks
from flightcheck.checks.environment import run_environment_checks
from flightcheck.checks.external_systems import run_external_systems_checks
from flightcheck.checks.solution import run_solution_checks
from flightcheck.checks.workday import run_workday_checks
from flightcheck.checks.workday_tenant import run_workday_tenant_checks
from flightcheck.checks.workday_extension import run_workday_extension_checks
from flightcheck.checks.topics import run_topic_checks


# ---------------------------------------------------------------------------
# Client identifiers — the subset of runner clients a checkpoint can declare.
# These are the logical names used in CheckpointSpec.clients and resolved by
# cli.py into the concrete client objects it authenticates.
# ---------------------------------------------------------------------------
GRAPH = "graph"
DATAVERSE = "dataverse"
PP_ADMIN = "pp_admin"
PVA = "pva"
# Power Platform Licensing API client (PowerPlatformClient) — distinct from the
# BAP admin client (PP_ADMIN). Used to read per-environment Copilot Studio
# message-capacity allocation (ENV-CAPACITY-001).
POWERPLATFORM = "powerplatform"
ALL_CLIENTS = frozenset({GRAPH, DATAVERSE, PP_ADMIN, PVA, POWERPLATFORM})


# Canonical category execution order, mirroring cli.py's FULL_SCOPE. When a
# target's transitive closure spans multiple category functions, they MUST run
# in this order so cross-category shared state hydrates correctly — most
# importantly, "External Systems" (run_external_systems_checks, which sets
# runner._workday_flows) must run before "Workday" (run_workday_checks, which
# early-returns when no Workday flows or package flavor are present).
CATEGORY_ORDER = [
    "Prerequisites",
    "Infrastructure",
    "Environment",
    "Solution",
    "Authentication",
    "Entra App",
    "Workday Tenant",
    "External Systems",
    "Workday",
    "Workday Extension",
    "Workday Topics",
    "Graph Connector KB",
    "ServiceNow",
    "Local Files",
    "Licensing",
    "Publishing",
    "Cloud Policies",
]


@dataclass(frozen=True)
class CheckpointSpec:
    """A single registered checkpoint (or dynamic family).

    ``key`` is an exact checkpoint ID (``"WD-PKG-001"``) for fixed
    checkpoints, or a family prefix (``"WD-FLOW"``) for dynamically-numbered
    checkpoints whose exact IDs cannot be enumerated ahead of time
    (``WD-FLOW-001``, ``WD-FLOW-002``, ...). When ``is_family`` is True the
    key matches any emitted ID of the form ``"{key}-..."``.
    """

    key: str
    category_fn: Callable
    category_label: str
    clients: frozenset = frozenset()
    requires_config: bool = True
    requires_dataverse_endpoint: bool = False
    prereqs: tuple = ()
    priority: str = Priority.HIGH.value
    roles: tuple = ()
    is_family: bool = False
    # listable=False registers a checkpoint so it can satisfy another
    # checkpoint's prerequisite resolution, while hiding it from
    # --list-checkpoints (it belongs to another scope's surface — e.g.
    # WD-001 is an External-Systems checkpoint we only register because the
    # below-early-return Workday checks need it to hydrate _workday_flows).
    listable: bool = True


@dataclass
class ResolvedPlan:
    """The fully-resolved execution plan for a single ``--checkpoint`` run."""

    target: str
    spec: CheckpointSpec
    clients: frozenset
    requires_config: bool
    requires_dataverse_endpoint: bool
    # (category_label, category_fn) pairs to register on the runner, ordered
    # by CATEGORY_ORDER (prerequisites' functions first), de-duped by function.
    ordered_fns: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# The registry. Order here is for readability only; lookups go through
# resolve(). Keep this list aligned with the master-checklist registry/mint
# table and the owned-prefix allow-list below.
# ---------------------------------------------------------------------------
_SPECS: list[CheckpointSpec] = [
    # ---- Environment (skill-1 reuse) ----
    CheckpointSpec(
        key="ENV-001",
        category_fn=run_environment_checks,
        category_label="Environment",
        clients=frozenset({PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        priority=Priority.CRITICAL.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
    ),
    CheckpointSpec(
        key="ENV-002",
        category_fn=run_environment_checks,
        category_label="Environment",
        clients=frozenset({PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("ENV-001",),
        priority=Priority.CRITICAL.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
    ),
    # ---- Environment (skill-1 net-new) ----
    # ENV-CAPACITY-001: Copilot Studio message capacity provisioned for the
    # environment. Reads the per-env allocation via the Power Platform Licensing
    # client (POWERPLATFORM), with PP_ADMIN deriving the env id. Not queryable =>
    # MANUAL attestation row (never a silent pass).
    CheckpointSpec(
        key="ENV-CAPACITY-001",
        category_fn=run_environment_checks,
        category_label="Environment",
        clients=frozenset({PP_ADMIN, POWERPLATFORM}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("ENV-001",),
        priority=Priority.CRITICAL.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
    ),
    # ---- Solution: ESS-SOLN-001 (skill-2 install-ess) ----
    # ESS-SOLN-001: the base ESS agent solution (msdyn_copilotforemployeeselfservice*)
    # is installed in the target env. Queries the Dataverse `solutions` table
    # (DATAVERSE client, already wired in cli.py's single-checkpoint path — no
    # new client init). Prereq ENV-002 (Dataverse provisioned) transitively
    # pulls ENV-001 (environment exists). Environment Maker owns the fix; the
    # AppSource install itself is a manual portal action, but this check
    # definitively verifies the outcome, so the S2.1 checklist row auto-completes
    # (`prog` gate) on a PASSED result.
    CheckpointSpec(
        key="ESS-SOLN-001",
        category_fn=run_solution_checks,
        category_label="Solution",
        clients=frozenset({DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("ENV-002",),
        priority=Priority.CRITICAL.value,
        roles=(Role.ESS_MAKER.value,),
    ),
    # ---- External Systems: WD-001 (prereq-only, hidden from listing) ----
    # Sets runner._workday_flows, which the below-early-return Workday checks
    # (WD-CONN-012, WD-FLOW-*, WD-WF-*, WD-ENV-*, WD-CONN-*) depend on.
    CheckpointSpec(
        key="WD-001",
        category_fn=run_external_systems_checks,
        category_label="External Systems",
        clients=frozenset({PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        priority=Priority.HIGH.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
        listable=False,
    ),
    # ---- Workday: package detection (top of the Workday pipeline) ----
    CheckpointSpec(
        key="WD-PKG-001",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        priority=Priority.HIGH.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
    ),
    # ---- Workday: pre-early-return Entra/SAML checks (graph-only) ----
    # These run BEFORE run_workday_checks' no-Workday early-return, and read
    # only Microsoft Graph, so they can run with NO Dataverse endpoint
    # configured — the Entra-only checkpoints the plan calls out explicitly.
    CheckpointSpec(
        key="WD-CONN-010",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ENTRA_ADMIN.value, Role.WORKDAY_ADMIN.value),
    ),
    CheckpointSpec(
        key="WD-CONN-102",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ENTRA_ADMIN.value, Role.WORKDAY_ADMIN.value),
    ),
    # ---- Workday: connection-reference binding completeness ----
    # Reads cached refs from WD-PKG-001 and needs _workday_flows (WD-001).
    CheckpointSpec(
        key="WD-CONN-012",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("WD-PKG-001", "WD-001"),
        priority=Priority.HIGH.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
    ),
    # ---- Workday dynamic families ----
    # WD-CONN-* — the generic connection enumerator (connections.py emits
    # WD-CONN-001 summary + WD-CONN-{i+2:03d} per connection). Exact-first
    # resolution keeps WD-CONN-010/012/102 above as fixed entries; this family
    # absorbs the per-connection detail rows.
    CheckpointSpec(
        key="WD-CONN",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({PP_ADMIN, DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("WD-001",),
        priority=Priority.HIGH.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
        is_family=True,
    ),
    # WD-FLOW-* — one per discovered Workday flow (_check_flow_status).
    CheckpointSpec(
        key="WD-FLOW",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({DATAVERSE, PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("WD-001",),
        priority=Priority.HIGH.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
        is_family=True,
    ),
    # WD-WF-* — per-workflow SOAP runtime checks (skipped on the simplified
    # flavor; registered for completeness). Emitted with category
    # "Workday Workflows" but owned by run_workday_checks.
    CheckpointSpec(
        key="WD-WF",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({DATAVERSE, PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("WD-PKG-001", "WD-001"),
        priority=Priority.HIGH.value,
        roles=(Role.WORKDAY_ADMIN.value,),
        is_family=True,
    ),
    # WD-ENV-* — legacy Workday environment-variable checks (banned on the
    # simplified flavor; registered so the family resolves).
    CheckpointSpec(
        key="WD-ENV",
        category_fn=run_workday_checks,
        category_label="Workday",
        clients=frozenset({DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("WD-001",),
        priority=Priority.CRITICAL.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
        is_family=True,
    ),
    # ---- Entra App (skill-3 provision-workday-entra-app) ----
    # The five setup checkpoints skill-3 mints. All Entra-only (Microsoft
    # Graph, no Dataverse) and self-contained (prereqs=()) — each is
    # independently runnable via --checkpoint. Emitted by
    # checks/entra_app.run_entra_app_checks. WD-ENTRA / WD-ASSIGN are already
    # in OWNED_PREFIXES, so the drift test forces these entries to exist.
    CheckpointSpec(
        key="WD-ENTRA-SCOPE-001",
        category_fn=run_entra_app_checks,
        category_label="Entra App",
        clients=frozenset({GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.CRITICAL.value,
        roles=(Role.ENTRA_ADMIN.value,),
    ),
    CheckpointSpec(
        key="WD-ENTRA-CONSENT-001",
        category_fn=run_entra_app_checks,
        category_label="Entra App",
        clients=frozenset({GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.CRITICAL.value,
        roles=(Role.ENTRA_ADMIN.value,),
    ),
    CheckpointSpec(
        key="WD-ASSIGN-001",
        category_fn=run_entra_app_checks,
        category_label="Entra App",
        clients=frozenset({GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.CRITICAL.value,
        roles=(Role.ENTRA_ADMIN.value,),
    ),
    CheckpointSpec(
        key="WD-ENTRA-NAMEID-001",
        category_fn=run_entra_app_checks,
        category_label="Entra App",
        clients=frozenset({GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ENTRA_ADMIN.value,),
    ),
    # WD-ENTRA-SIGNOPT-001 is a portal-only MANUAL attestation — there is no
    # documented Graph property for the SAML signing option, so it needs no
    # client (clients=frozenset()).
    CheckpointSpec(
        key="WD-ENTRA-SIGNOPT-001",
        category_fn=run_entra_app_checks,
        category_label="Entra App",
        clients=frozenset(),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ENTRA_ADMIN.value,),
    ),
    # ---- Workday Tenant (skill-4 configure-workday-tenant) ----
    # The two setup checkpoints skill-4 mints. Both are portal-only MANUAL
    # attestations — Workday exposes no queryable admin API the kit can
    # reach, and self-verifying via a Workday connection would be circular
    # (it needs the same config the ESS agent needs) — so neither needs a
    # client (clients=frozenset(), like WD-ENTRA-SIGNOPT-001). Self-contained
    # (prereqs=()) — each is independently runnable via --checkpoint. Emitted
    # by checks/workday_tenant.run_workday_tenant_checks. WD-API-CLIENT and
    # WD-TENANT are already in OWNED_PREFIXES, so the drift test forces these
    # entries to exist. S4.4 cert parity reuses WD-CONN-102.
    CheckpointSpec(
        key="WD-API-CLIENT-001",
        category_fn=run_workday_tenant_checks,
        category_label="Workday Tenant",
        clients=frozenset(),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.CRITICAL.value,
        roles=(Role.WORKDAY_ADMIN.value,),
    ),
    CheckpointSpec(
        key="WD-TENANT-001",
        category_fn=run_workday_tenant_checks,
        category_label="Workday Tenant",
        clients=frozenset(),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.WORKDAY_ADMIN.value,),
    ),
    # ---- Workday Extension: skill-5 (install-workday-extension-pack) ----
    # Five checkpoints, all emitted by
    # checks/workday_extension.run_workday_extension_checks, category
    # "Workday Extension" (ordered AFTER "Workday" so WD-PKG-001 hydrates the
    # cached refs / install flavor first). Prefixes WD-CONN / DV-CONN / WD-REST
    # / WD-NET are already in OWNED_PREFIXES, so the drift test forces these
    # entries to exist. Skill-5 also reuses WD-PKG-001 (S5.1), WD-CONN-012
    # (S5.2) and WD-FLOW-* (S5.6) from checks/workday.py.
    #
    # WD-CONN-AUTH-001 registers as a FIXED spec under the WD-CONN owned prefix;
    # exact-first resolution keeps it distinct from the WD-CONN family (like
    # WD-CONN-012 / WD-CONN-102). It reads the cached ff0df ref (WD-PKG-001) and
    # the BAP connection (PP admin), so it declares PP_ADMIN and pulls the
    # Dataverse-backed WD-PKG-001 in as a prerequisite.
    CheckpointSpec(
        key="WD-CONN-AUTH-001",
        category_fn=run_workday_extension_checks,
        category_label="Workday Extension",
        clients=frozenset({PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        prereqs=("WD-PKG-001", "WD-001"),
        priority=Priority.HIGH.value,
        roles=(Role.ESS_MAKER.value,),
    ),
    # DV-CONN-001 — self-contained Dataverse read (its own connectionreferences
    # query) plus a best-effort BAP owner echo.
    CheckpointSpec(
        key="DV-CONN-001",
        category_fn=run_workday_extension_checks,
        category_label="Workday Extension",
        clients=frozenset({DATAVERSE, PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        priority=Priority.HIGH.value,
        roles=(Role.ESS_MAKER.value,),
    ),
    # WD-REST-001 — pure config check (restBaseUrl trimmed to /api), no client.
    CheckpointSpec(
        key="WD-REST-001",
        category_fn=run_workday_extension_checks,
        category_label="Workday Extension",
        clients=frozenset(),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ESS_MAKER.value,),
    ),
    # WD-REST-002 — pure local-file check (user-context-setup.mcs.yml redirect),
    # no client. Gated on config installPath (SKIPPED on legacy).
    CheckpointSpec(
        key="WD-REST-002",
        category_fn=run_workday_extension_checks,
        category_label="Workday Extension",
        clients=frozenset(),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ESS_MAKER.value,),
    ),
    # WD-NET-001 — MANUAL/InfoSec attestation (firewall allowlisting), no
    # client. No InfoSec Role enum value exists; POWER_PLATFORM_ADMIN is the
    # closest infra-owning role (see checks/workday_extension.py note).
    CheckpointSpec(
        key="WD-NET-001",
        category_fn=run_workday_extension_checks,
        category_label="Workday Extension",
        clients=frozenset(),
        requires_config=True,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.POWER_PLATFORM_ADMIN.value,),
    ),
    # ---- Workday Topics: skill-6 (create-new-topic) ----
    # Two FAMILY checkpoints, both emitted by checks/topics.run_topic_checks,
    # category "Workday Topics" (ordered AFTER "Workday Extension"). Each expands
    # to one row per *new* topic — a workspace/agents/*/topics/*.mcs.yml that
    # differs from the OOTB .baseline/ snapshot. Prefixes TOPIC-TRIGGER /
    # TOPIC-INTEGRATION are already in OWNED_PREFIXES, so the drift test forces
    # these entries to exist. Both are pure local-file checks — no client, no
    # config or Dataverse endpoint required, self-contained (prereqs=()).
    #
    # TOPIC-TRIGGER-* (S6.1) — each new topic is a well-formed AdaptiveDialog
    # with a trigger (and trigger phrases when intent-routed).
    CheckpointSpec(
        key="TOPIC-TRIGGER",
        category_fn=run_topic_checks,
        category_label="Workday Topics",
        clients=frozenset(),
        requires_config=False,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ESS_MAKER.value,),
        is_family=True,
    ),
    # TOPIC-INTEGRATION-* (S6.2) — each new topic's integration wiring resolves
    # (no unresolved {{PLACEHOLDER}} / <UPPERCASE> tenant reference-ID tokens).
    # Tenant-ID *value* correctness is an SME attestation carried in the
    # remediation + playbook overlay (the "prog (+ SME for IDs)" gate).
    CheckpointSpec(
        key="TOPIC-INTEGRATION",
        category_fn=run_topic_checks,
        category_label="Workday Topics",
        clients=frozenset(),
        requires_config=False,
        requires_dataverse_endpoint=False,
        priority=Priority.HIGH.value,
        roles=(Role.ESS_MAKER.value,),
        is_family=True,
    ),
]

REGISTRY: dict[str, CheckpointSpec] = {spec.key: spec for spec in _SPECS}


# ---------------------------------------------------------------------------
# Owned-prefix allow-list for the drift test (tests/flightcheck/
# test_registry_drift.py). This is the set of checkpoint-ID prefixes the
# *setup* skills own. The drift test FAILS if a setup-owned checkpoint is
# emitted by a check module but does not resolve in this registry — catching
# an added/renamed setup checkpoint nobody registered. Prefixes outside this
# list belong to other integrations and are ignored by the drift test.
#
# Several prefixes below have NO emitter or registry entry YET — they are
# minted by the per-skill plans (skills 1-6) and master-checklist. They are
# listed here so the drift test forces their registration the moment a skill
# starts emitting them. Do NOT remove a prefix just because nothing emits it
# yet.
# ---------------------------------------------------------------------------
OWNED_PREFIXES: tuple = (
    "ENV-001",
    "ENV-002",
    "ENV-CAPACITY",
    "ESS-SOLN",
    "WD-PKG",
    "WD-CONN",
    "WD-FLOW",
    "WD-WF",
    "WD-ENV",
    "WD-ENTRA",
    "WD-ASSIGN",
    "WD-TENANT",
    "WD-API-CLIENT",
    "WD-REST",
    "WD-NET",
    "DV-CONN",
    "TOPIC-TRIGGER",
    "TOPIC-INTEGRATION",
)


class RegistryError(Exception):
    """Raised when the registry is internally inconsistent (cyclic prereqs or
    a prerequisite that doesn't resolve)."""


def resolve(checkpoint_id: str) -> Optional[CheckpointSpec]:
    """Resolve a checkpoint ID (or family key) to its spec.

    Resolution order, per the plan:
      1. **Exact** key match first — so fixed IDs like ``WD-CONN-010`` /
         ``WD-CONN-012`` / ``WD-CONN-102`` resolve to their own entries even
         though a ``WD-CONN`` family also exists.
      2. **Longest-prefix family** match — an exact dynamic ID
         (``WD-FLOW-002``) or a family key with a wildcard suffix
         (``WD-FLOW-*``) resolves to the most specific registered family.

    Never strips a trailing ``-\\d+`` heuristically — that would fabricate
    bogus families and mis-bucket fixed IDs (``WD-CONN-012``, ``ENV-001``,
    ``WD-REST-001``). Resolution is registry-driven only.

    Returns None if nothing matches.
    """
    if not checkpoint_id:
        return None

    # Normalise a trailing wildcard ("WD-FLOW-*" / "WD-FLOW*") to the bare key.
    probe = checkpoint_id
    if probe.endswith("*"):
        probe = probe.rstrip("*").rstrip("-")

    # 1. Exact match wins.
    spec = REGISTRY.get(probe)
    if spec is not None:
        return spec

    # 2. Longest-prefix family match. Only family specs are eligible, and only
    #    when the probe is strictly within the family namespace ("WD-FLOW-002"
    #    matches family "WD-FLOW"; "WD-FLOWX" does not).
    best: Optional[CheckpointSpec] = None
    for fam in REGISTRY.values():
        if not fam.is_family:
            continue
        if probe.startswith(fam.key + "-"):
            if best is None or len(fam.key) > len(best.key):
                best = fam
    return best


def _resolve_or_raise(checkpoint_id: str) -> CheckpointSpec:
    spec = resolve(checkpoint_id)
    if spec is None:
        raise RegistryError(
            f"Checkpoint {checkpoint_id!r} does not resolve to any registered "
            f"checkpoint or family."
        )
    return spec


def _closure(checkpoint_id: str, _seen: Optional[set] = None) -> list[CheckpointSpec]:
    """Return every spec in the transitive prerequisite closure of a target,
    target included. Raises RegistryError on an unresolved prereq or a cycle.
    """
    if _seen is None:
        _seen = set()

    spec = _resolve_or_raise(checkpoint_id)
    if spec.key in _seen:
        # Already collected on this walk — guard against cycles. validate_registry
        # proves the whole graph is acyclic at load; this is belt-and-braces.
        return []
    _seen.add(spec.key)

    specs: list[CheckpointSpec] = []
    for prereq in spec.prereqs:
        specs.extend(_closure(prereq, _seen))
    specs.append(spec)
    return specs


def transitive_requirements(checkpoint_id: str) -> ResolvedPlan:
    """Resolve a target to its full execution plan.

    Walks the transitive prerequisite closure and returns the **union** of
    every spec's client/config requirements (a checkpoint that declares no
    Dataverse can still inherit a Dataverse-backed prerequisite), plus the
    ordered, de-duped list of ``(category_label, category_fn)`` pairs to
    register on the runner — ordered by CATEGORY_ORDER so cross-category
    shared state hydrates correctly.
    """
    target_spec = _resolve_or_raise(checkpoint_id)
    closure = _closure(checkpoint_id)

    clients: frozenset = frozenset()
    requires_config = False
    requires_dataverse_endpoint = False
    for spec in closure:
        clients = clients | spec.clients
        requires_config = requires_config or spec.requires_config
        requires_dataverse_endpoint = (
            requires_dataverse_endpoint or spec.requires_dataverse_endpoint
        )

    # De-dupe category functions, then order by CATEGORY_ORDER. Multiple specs
    # frequently share a function (the whole Workday block is run_workday_checks),
    # so register each function exactly once.
    seen_fns: set = set()
    unique: list[tuple] = []
    for spec in closure:
        if spec.category_fn in seen_fns:
            continue
        seen_fns.add(spec.category_fn)
        unique.append((spec.category_label, spec.category_fn))

    def _order_index(label: str) -> int:
        try:
            return CATEGORY_ORDER.index(label)
        except ValueError:
            return len(CATEGORY_ORDER)

    unique.sort(key=lambda pair: _order_index(pair[0]))

    return ResolvedPlan(
        target=checkpoint_id,
        spec=target_spec,
        clients=clients,
        requires_config=requires_config,
        requires_dataverse_endpoint=requires_dataverse_endpoint,
        ordered_fns=unique,
    )


def matches(target: str, emitted_id: str) -> bool:
    """True if a runner-emitted checkpoint ID belongs to the requested target.

    Used by the runner to filter a hydrated run down to just the target:
      * exact target (``WD-CONN-012``) -> emitted_id == target
      * exact dynamic ID (``WD-FLOW-002``) -> emitted_id == target
      * family target (``WD-FLOW`` or ``WD-FLOW-*``) -> emitted_id is in the
        family namespace (``WD-FLOW-001``, ``WD-FLOW-002``, ...)
    """
    if not target or not emitted_id:
        return False

    # Family target, expressed either as the bare family key or with a "*".
    fam_key = target
    is_family_request = False
    if fam_key.endswith("*"):
        fam_key = fam_key.rstrip("*").rstrip("-")
        is_family_request = True
    else:
        spec = REGISTRY.get(fam_key)
        if spec is not None and spec.is_family:
            is_family_request = True

    if is_family_request:
        return emitted_id == fam_key or emitted_id.startswith(fam_key + "-")

    # Exact (fixed or exact-dynamic) target.
    return emitted_id == target


def list_checkpoints() -> list[CheckpointSpec]:
    """Return the listable checkpoints/families, sorted by key, for
    ``--list-checkpoints``. Prereq-only nodes (listable=False) are excluded."""
    return sorted(
        (spec for spec in REGISTRY.values() if spec.listable),
        key=lambda s: s.key,
    )


def validate_registry() -> None:
    """Fail fast if the registry is internally inconsistent.

    Asserts (1) every referenced prerequisite ID/family resolves, and (2) the
    prerequisite graph is acyclic (a cycle would be a bootstrap deadlock).
    Called at import time and re-asserted by tests/flightcheck/test_registry.py.
    """
    # (1) Every prerequisite must resolve.
    for spec in REGISTRY.values():
        for prereq in spec.prereqs:
            if resolve(prereq) is None:
                raise RegistryError(
                    f"Checkpoint {spec.key!r} declares prerequisite "
                    f"{prereq!r}, which does not resolve to any registered "
                    f"checkpoint or family."
                )

    # (2) The prereq graph (keyed by resolved spec key) must be acyclic.
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {key: WHITE for key in REGISTRY}

    def _visit(key: str, stack: list[str]) -> None:
        color[key] = GREY
        stack.append(key)
        spec = REGISTRY[key]
        for prereq in spec.prereqs:
            resolved = resolve(prereq)
            # resolve() is guaranteed non-None by step (1) above.
            nxt = resolved.key
            if color[nxt] == GREY:
                cycle = " -> ".join(stack[stack.index(nxt):] + [nxt])
                raise RegistryError(f"Cyclic prerequisite chain: {cycle}")
            if color[nxt] == WHITE:
                _visit(nxt, stack)
        stack.pop()
        color[key] = BLACK

    for key in REGISTRY:
        if color[key] == WHITE:
            _visit(key, [])


# Fail fast at import: a malformed registry is a programming error that should
# surface the moment cli.py (or a test) imports this module, not mid-run.
validate_registry()
