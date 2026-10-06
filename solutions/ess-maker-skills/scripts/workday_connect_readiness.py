# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Readiness coordination for the Workday Connect lifecycle."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from workday_connect_flightcheck import (
    WorkdayConnectFlightCheckError,
    run_profile,
)
from workday_connect_readiness_policy import PROFILE_POLICIES
from workday_connect_store import WorkdayConnectStore, WorkdayConnectStoreError


ProfileRunner = Callable[..., dict[str, Any]]


def run_profile_gate(
    store: WorkdayConnectStore,
    profile_name: str,
    *,
    profile_runner: ProfileRunner = run_profile,
) -> dict[str, Any]:
    policy = PROFILE_POLICIES[profile_name]
    try:
        summary = profile_runner(
            store.workspace_root,
            store.load(),
            profile_name,
        )
    except WorkdayConnectFlightCheckError as exc:
        try:
            store.block_validation_profile(
                exc.phase_id or policy.phase_id,
                profile_name,
                error_type=exc.error_type,
                message=str(exc),
                customer_remediation=exc.customer_remediation,
                input_fingerprint=exc.input_fingerprint,
                source_profile=profile_name,
            )
        except WorkdayConnectStoreError as stale:
            stale.profile_blocker_persisted = True
            raise
        wrapped = WorkdayConnectStoreError(
            exc.customer_remediation
            or "Readiness checks need attention before setup can continue."
        )
        wrapped.profile_blocker_persisted = True
        wrapped.customer_remediation = exc.customer_remediation
        raise wrapped from exc
    try:
        updated_state = store.record_validation_profile(
            policy.phase_id,
            summary,
        )
    except WorkdayConnectStoreError as stale:
        stale.profile_blocker_persisted = True
        raise
    return updated_state["phases"][policy.phase_id]["validationProfiles"][
        profile_name
    ]


def derived_profile_summary(
    source: Mapping[str, Any],
    profile_name: str,
    *,
    migration_baseline: bool,
) -> dict[str, Any]:
    policy = PROFILE_POLICIES[profile_name]

    def belongs(checkpoint_id: str) -> bool:
        return checkpoint_id in policy.checkpoints or any(
            checkpoint_id.startswith(family + "-")
            for family in policy.families
        )

    return {
        **dict(source),
        "profile": profile_name,
        "sourceProfile": source["profile"],
        "checkpointStatuses": {
            checkpoint_id: status
            for checkpoint_id, status in source[
                "checkpointStatuses"
            ].items()
            if belongs(checkpoint_id)
        },
        "acceptedSuppressions": [
            suppression
            for suppression in source["acceptedSuppressions"]
            if belongs(suppression["checkpointId"])
        ],
        "migrationBaseline": migration_baseline,
    }


def run_final_readiness(
    store: WorkdayConnectStore,
    *,
    profile_runner: ProfileRunner = run_profile,
) -> dict[str, Any]:
    final_summary = run_profile_gate(
        store,
        "workday-da:final",
        profile_runner=profile_runner,
    )
    for profile_name, policy in PROFILE_POLICIES.items():
        if profile_name == "workday-da:final":
            continue
        store.record_validation_profile(
            policy.phase_id,
            derived_profile_summary(
                final_summary,
                profile_name,
                migration_baseline=False,
            ),
        )
    migration = store.load().get("migration") or {}
    if (
        migration.get("source") == "workday-connect-state-v7"
        and migration.get("flightcheckBaselineOutcome")
        == "remediation-required"
    ):
        store.complete_flightcheck_migration()
    return final_summary


def ensure_migration_baseline(
    store: WorkdayConnectStore,
    *,
    profile_runner: ProfileRunner = run_profile,
) -> None:
    try:
        with store.migration_guard():
            state = store.load()
            migration = state.get("migration") or {}
            if not migration.get("flightcheckBaselineRequired"):
                return
            ready = migration.get("legacyReady") is True
            if ready:
                store.complete_flightcheck_migration()
                return
            state = store.load()
            profile_names = tuple(
                profile_name
                for profile_name, phase_id in (
                    ("workday-da:setup-readiness", "preflight"),
                    (
                        "workday-da:external-prerequisites",
                        "workday-admin",
                    ),
                    ("workday-da:package-ready", "connections"),
                    ("workday-da:dataverse-ready", "runtime"),
                    ("workday-da:post-connection", "runtime"),
                    ("workday-da:post-agent-wiring", "runtime"),
                )
                if state["phases"][phase_id]["status"] == "complete"
            )
            if not profile_names:
                store.complete_flightcheck_migration()
                return
            active_profile = profile_names[0]
            try:
                for active_profile in profile_names:
                    summary = profile_runner(
                        store.workspace_root,
                        state,
                        active_profile,
                        source_profile=active_profile,
                        migration_baseline=True,
                    )
                    store.record_validation_profile(
                        PROFILE_POLICIES[active_profile].phase_id,
                        summary,
                    )
            except WorkdayConnectFlightCheckError as exc:
                store.block_flightcheck_migration(
                    exc.phase_id
                    or PROFILE_POLICIES[active_profile].phase_id,
                    error_type=exc.error_type,
                    message=str(exc),
                    customer_remediation=exc.customer_remediation,
                    input_fingerprint=exc.input_fingerprint,
                    source_profile=active_profile,
                )
                wrapped = WorkdayConnectStoreError(
                    exc.customer_remediation
                    or (
                        "Readiness checks need attention before setup can "
                        "continue."
                    )
                )
                wrapped.profile_blocker_persisted = True
                wrapped.customer_remediation = exc.customer_remediation
                raise wrapped from exc
            store.complete_flightcheck_migration()
    except WorkdayConnectStoreError as exc:
        exc.profile_blocker_persisted = True
        raise
