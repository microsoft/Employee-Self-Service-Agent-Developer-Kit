# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Selected-agent DA dispatch; unresolved coverage is never a successful full run."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import SimpleNamespace

from . import registry
from .agent_scope import active_agent, is_declarative_agent, validate_agent_slug
from .checks.environment import run_connection_checks
from .checks.native_agent import run_native_agent_checks
from .checks.publishing import run_publishing_checks
from .checks.solution import run_solution_checks
from .da_contract import (
    DA_COVERAGE_SCHEMA,
    DAApplicability,
    DACoverageEntry,
    DADisposition,
    DAFeature,
    DAFeatureEvidence,
    build_da_coverage_plan,
)
from .runner import (
    BLOCK_REASON_CHECKPOINT_CONTRACT,
    CheckResult,
    Priority,
    Role,
    Status,
)


# Extend only after the producer's selected-target and read-only paths are reviewed.
_APPROVED_PRODUCERS = frozenset({
    run_native_agent_checks, run_connection_checks,
    run_solution_checks, run_publishing_checks,
})


def da_full_requested(config: dict, selected_slug: str | None = None) -> bool:
    """Route on explicit DA metadata, not on Dataverse or package presence."""
    context = SimpleNamespace(config=config, agent_slug=selected_slug)
    if is_declarative_agent(context):
        return True
    slug = selected_slug or config.get("activeAgent") or (
        config.get("agent") or {}
    ).get("slug")
    selected = active_agent(config, slug) if slug else {}
    if selected:
        return False
    # A broken selection in a DA workspace must fail, not fall through to legacy.
    return is_declarative_agent(SimpleNamespace(config=config)) or (
        str(config.get("releaseLine") or "").strip().casefold() == "da"
    ) or any(
        isinstance(agent, dict)
        and str(agent.get("releaseLine") or "").strip().casefold() == "da"
        for agent in config.get("agents", []) or []
    )


@dataclass(frozen=True)
class DAExecutionPlan:
    config: dict
    profile: registry.ProfileSpec
    requirements: registry.ResolvedPlan
    coverage: tuple[DACoverageEntry, ...]
    pending: tuple[tuple[str, str], ...]

    def matches(self, checkpoint_id: str) -> bool:
        return (
            registry.profile_matches(self.profile, checkpoint_id)
            or checkpoint_id == "DA-PLAN-COVERAGE"
            or (
                "ENV-004" in self.profile.checkpoint_ids
                and (
                    checkpoint_id == "ENV-004-COVERAGE"
                    or checkpoint_id.startswith("ENV-004-UR-")
                )
            )
        )

    def guard_producer(self, fn: Callable) -> Callable:
        """Do not read dependent native surfaces after exact-target validation fails."""
        native_ids = tuple(
            checkpoint_id
            for checkpoint_id in self.profile.checkpoint_ids
            if (spec := registry.resolve(checkpoint_id)) is not None
            and spec.category_fn is fn
            and spec.clients & {registry.AGENTBUILDER, registry.CONNECTIVITY}
        )
        if fn is run_native_agent_checks or not native_ids:
            return fn

        def check(runner) -> list[CheckResult]:
            if any(
                row.checkpoint_id == "DA-AGENT-001"
                and row.status == Status.PASSED.value
                for row in runner.results
            ):
                return fn(runner)
            return [
                CheckResult(
                    checkpoint_id=checkpoint_id,
                    category="DA FlightCheck",
                    priority=Priority.HIGH.value,
                    status=Status.BLOCKED.value,
                    description="Exact native agent prerequisite",
                    result="Exact selected-agent validation did not pass; this producer was not executed.",
                    remediation="Restore access to the exact configured DA and rerun the same full assessment.",
                    roles=[Role.ESS_MAKER.value],
                    block_reason=BLOCK_REASON_CHECKPOINT_CONTRACT,
                )
                for checkpoint_id in native_ids
            ]

        return check

    def coverage_check(self, _runner) -> list[CheckResult]:
        """Persist the complete manifest using the existing result evidence contract."""
        return [CheckResult(
            checkpoint_id="DA-PLAN-COVERAGE",
            category="DA FlightCheck Coverage",
            priority=Priority.CRITICAL.value,
            status=Status.BLOCKED.value if self.pending else Status.PASSED.value,
            description="Full DA dispatch coverage",
            result=(
                f"Full DA dispatch remains incomplete: {len(self.pending)} required "
                "definition(s) have unknown applicability, require DA review, or "
                "lack approved dispatch. "
                + "; ".join(f"{key}: {reason}" for key, reason in self.pending)
                if self.pending else
                "Every applicable requirement has an approved dispatch path; "
                "execution results and manual evidence must still be assessed."
            ),
            remediation=(
                "Resolve applicability and implementation gaps before using this "
                "assessment for deployment sign-off. Inventory is not deployment proof."
                if self.pending else ""
            ),
            evidence={
                "schemaVersion": DA_COVERAGE_SCHEMA,
                "plannedCheckpoints": list(self.profile.checkpoint_ids),
                "coverage": [entry.to_dict() for entry in self.coverage],
                "pending": [
                    {"checkpointId": key, "reason": reason}
                    for key, reason in self.pending
                ],
            },
            roles=[Role.ESS_MAKER.value],
            block_reason=BLOCK_REASON_CHECKPOINT_CONTRACT if self.pending else "",
        )]


def build_da_execution_plan(
    config: dict,
    selected_slug: str | None = None,
    *,
    features: Mapping[DAFeature, DAFeatureEvidence] | None = None,
    environment_url: str = "",
) -> DAExecutionPlan:
    """Compile approved producers without mutating global profiles or caller config."""
    slug = selected_slug or config.get("activeAgent") or (
        config.get("agent") or {}
    ).get("slug")
    slug = validate_agent_slug(slug)
    selected = active_agent(config, slug)
    if not selected:
        raise ValueError("The selected DA does not resolve to one configured agent.")
    if not is_declarative_agent(SimpleNamespace(config=config, agent_slug=slug)):
        raise ValueError("The selected agent does not have explicit DA release-line metadata.")
    try:
        bot_id = str(uuid.UUID(str(selected.get("botId") or "")))
        environment_id = str(uuid.UUID(str(
            config.get("environmentId") or selected.get("environmentId") or ""
        )))
        if selected.get("environmentId") is not None and (
            uuid.UUID(str(selected["environmentId"])) != uuid.UUID(environment_id)
        ):
            raise ValueError("Selected agent and workspace environment IDs differ.")
    except ValueError as exc:
        raise ValueError(
            "Full DA validation requires exact, consistent agent and environment GUIDs."
        ) from exc
    if not isinstance(selected.get("schemaName"), str) or not selected["schemaName"].strip():
        raise ValueError("Full DA validation requires the selected agent's schemaName.")

    subject = dict(selected, botId=bot_id)
    scoped_config = dict(
        config, activeAgent=slug, agents=[subject], agent=subject,
        environmentId=environment_id,
    )
    for key in ("realm", "ring", "powerPlatformApiEndpoint", "agentBuilderApiVersion"):
        if subject.get(key) is not None:
            scoped_config[key] = subject[key]
    coverage = build_da_coverage_plan(features or {})
    targets: list[str] = []
    pending: list[tuple[str, str]] = []
    for entry in coverage:
        spec = entry.checkpoint
        if entry.applicability in {DAApplicability.EXCLUDED, DAApplicability.NOT_APPLICABLE}:
            continue
        reason = ""
        if entry.applicability == DAApplicability.UNKNOWN:
            reason = entry.applicability_reason
        elif spec.disposition == DADisposition.REVIEW:
            reason = spec.reason
        elif spec.disposition in {DADisposition.EVALUATOR, DADisposition.MANUAL}:
            registered = registry.resolve(spec.key)
            if registered is None or registered.key != spec.key or registered.is_family:
                reason = "No exact registered DA selector."
            else:
                requirements = registry.transitive_requirements(spec.key)
                if any(fn not in _APPROVED_PRODUCERS for _, fn in requirements.ordered_fns):
                    reason = "Producer requires selected-agent DA dispatch review."
                else:
                    targets.append(spec.key)
        if reason and spec.required:
            pending.append((spec.key, reason))

    profile = registry.ProfileSpec(
        name="da:full",
        checkpoint_ids=tuple(sorted(targets)),
        description="Read-only full DA assessment for exactly one selected agent.",
    )
    requirements = registry.profile_requirements(profile)
    ordered = requirements.ordered_fns
    requirements = replace(
        requirements,
        ordered_fns=(
            [pair for pair in ordered if pair[1] is run_native_agent_checks]
            + [pair for pair in ordered if pair[1] is not run_native_agent_checks]
        ),
    )
    if environment_url or config.get("dataverseEndpoint"):
        requirements = replace(
            requirements, clients=requirements.clients | {registry.PP_ADMIN},
        )
    return DAExecutionPlan(
        scoped_config, profile, requirements, coverage, tuple(pending),
    )
