# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure DA coverage reconciliation and explicit deployment evidence policy."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING
from uuid import UUID

from .da_contract import (
    DAApplicability, DACheckpoint, DADisposition, DAFeature, DAFeatureEvidence,
    DA_REVIEWABLE_FEATURES, build_da_coverage_plan, resolve_da_feature_evidence,
)
from .runner import CheckResult, RunResult, Status

if TYPE_CHECKING:
    from .da_execution import DAExecutionPlan


DA_ASSESSMENT_SCHEMA = "flightcheck.da.assessment.v1"
DA_EVIDENCE_SCHEMA = "flightcheck.da.evidence.v1"
_TARGET_FIELDS = (
    "tenantId", "environmentId", "agentId", "agentSchemaName", "agentSlug", "realm", "serviceRing",
)
_BASE_FIELDS = frozenset({"observedAt", "source", "reviewerRole", "configurationRevision"})
_RUNTIME_RUN_FIELDS = {
    "DA-RUNTIME-001": "employeeTestRunIds",
    "DA-SN-RUNTIME-001": "employeeTestRuns",
}


def load_da_evidence(path: str | None) -> list[dict]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != DA_EVIDENCE_SCHEMA:
        raise ValueError(f"--da-evidence requires schemaVersion {DA_EVIDENCE_SCHEMA}.")
    records = payload.get("records")
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError("--da-evidence records must be an array of objects.")
    keys = [record.get("checkpointId") for record in records]
    if any(not isinstance(key, str) or not key.strip() for key in keys):
        raise ValueError("Every evidence record requires a checkpointId.")
    if len(keys) != len(set(keys)):
        raise ValueError("Evidence must contain at most one record per checkpointId.")
    return records


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _present(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value) and all(_present(item) for item in (
            value.values() if isinstance(value, dict) else value
        ))
    return value is not None and type(value) in {bool, int, float}


def _target(runner, result: RunResult) -> dict:
    context = result.validation_context
    ring = getattr(runner, "ring", "")
    return {key: context.get(key) if isinstance(context.get(key), str) else ""
            for key in _TARGET_FIELDS} | {
        "serviceRing": ring if isinstance(ring, str) else "",
    }


def _revision(runner, result: RunResult, target: dict) -> str | None:
    if any(not isinstance(value, str) or not value.strip() for value in target.values()):
        return None
    try:
        for key in ("tenantId", "environmentId", "agentId"):
            UUID(target[key])
    except ValueError:
        return None
    if target["realm"] not in {"dev", "test", "prod"} or target["serviceRing"] not in {"prod", "preprod", "test"}:
        return None
    access = [row for row in result.results if row.checkpoint_id == "DA-AGENT-001"]
    if len(access) != 1 or access[0].status != Status.PASSED.value:
        return None
    snapshot = getattr(runner, "_da_native_snapshot", None)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("changeset"), dict):
        return None
    if any(str(snapshot.get(key, "")).casefold() != target[key].casefold()
           for key in ("agentId", "environmentId")):
        return None
    audit = getattr(runner, "_da_connection_audit", None)
    references = sorted(
        ((ref.agent_id, ref.logical_name, ref.connector_id, ref.connection_id, sorted(ref.flow_ids))
         for ref in audit.references),
        key=lambda item: json.dumps(item),
    ) if audit is not None else []
    payload = {
        "target": target,
        "nativeSnapshot": {key: value for key, value in snapshot["changeset"].items() if key != "changeToken"},
        "bindings": references,
        "alm": [
            {"status": row.status, "evidence": row.evidence}
            for row in result.results if row.checkpoint_id == "ESS-SOLN-001"
        ],
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
    ).hexdigest()


def _family_matches(key: str, checkpoint_id: str) -> bool:
    if key.endswith("*"):
        return checkpoint_id.startswith(key[:-1])
    if key.endswith("-NNN"):
        return re.fullmatch(re.escape(key[:-3]) + r"\d{3,}", checkpoint_id) is not None
    if key.endswith("+"):
        prefix, first = key[:-1].rsplit("-", 1)
        suffix = checkpoint_id.removeprefix(prefix + "-")
        return checkpoint_id.startswith(prefix + "-") and suffix.isascii() and suffix.isdigit() and int(suffix) >= int(first)
    return False


def _feature_evidence(
    record: dict, observed: dict[DAFeature, DAFeatureEvidence],
) -> dict[DAFeature, DAFeatureEvidence]:
    details = record.get("details")
    flags = details.get("features") if isinstance(details, dict) else None
    if not isinstance(flags, dict) or not flags:
        raise ValueError("The feature review requires explicit feature choices.")
    declared = {}
    for name, enabled in flags.items():
        try:
            feature = DAFeature(name)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unknown feature in the applicability review: {name!r}.") from exc
        if feature not in DA_REVIEWABLE_FEATURES or (
            enabled is not None and type(enabled) is not bool
        ):
            raise ValueError(f"Feature {name} is not reviewable or lacks an explicit boolean choice.")
        if enabled is None:
            continue
        existing = observed.get(feature)
        if existing is not None and existing.enabled is not None:
            if existing.enabled != enabled:
                raise ValueError(f"Feature {name} contradicts the observed feature evidence.")
            continue
        declared[feature] = DAFeatureEvidence(
            enabled, f"Reviewed feature applicability: {record.get('source', '')}",
        )
    return resolve_da_feature_evidence({**observed, **declared})


def _review_record(
    record: dict, spec: DACheckpoint, rows: list[CheckResult],
    target: dict[str, str], revision: str | None, now: datetime,
    *, features: dict[DAFeature, DAFeatureEvidence] | None = None,
) -> list[str]:
    errors: list[str] = []
    supplied_target = record.get("target")
    if not isinstance(supplied_target, dict) or any(
        not isinstance(supplied_target.get(key), str)
        or supplied_target[key].casefold() != target[key].casefold()
        for key in _TARGET_FIELDS
    ):
        errors.append("evidence_target_mismatch")
    if revision is None or record.get("configurationRevision") != revision:
        errors.append("evidence_revision_mismatch")
    if record.get("reviewed") is not True or record.get("reviewerRole") not in spec.owners:
        errors.append("evidence_review_missing_or_wrong_role")
    if not isinstance(record.get("source"), str) or not record["source"].strip():
        errors.append("evidence_source_missing")
    observed, reviewed, valid_until = (
        _timestamp(record.get(key)) for key in ("observedAt", "reviewedAt", "validUntil")
    )
    if observed is None or reviewed is None or valid_until is None:
        errors.append("evidence_validity_window_invalid")
    elif not observed <= reviewed <= now < valid_until:
        errors.append("evidence_expired_or_future")
    if not isinstance(record.get("outcome"), str) or record["outcome"] not in {"satisfied", "defect"}:
        errors.append("evidence_outcome_invalid")
    required_fields: set[str] = set()
    for row in rows:
        fields = row.evidence.get("requiredFields")
        if (
            row.evidence.get("evidenceType") != "manual_requirement"
            or not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) for field in fields)
            or row.status not in {Status.MANUAL.value, Status.SKIPPED.value, Status.NOT_CONFIGURED.value}
        ):
            errors.append("evidence_cannot_replace_automated_verification")
            break
        required_fields.update(fields)
    details = record.get("details")
    detail_fields = required_fields - _BASE_FIELDS
    if spec.key == "DA-INTEGRATIONS-001":
        detail_fields -= {"features"}  # Validated separately; null choices remain unknown.
    if not rows or not isinstance(details, dict) or any(
        not _present(details.get(field)) for field in detail_fields
    ):
        errors.append("evidence_required_details_missing")
    kind = (
        "feature_applicability" if spec.key == "DA-INTEGRATIONS-001" else
        "published_employee_runtime" if spec.key in _RUNTIME_RUN_FIELDS else
        "maker_test_pane" if spec.key == "WD-DA-MAKER-001" else "manual_attestation"
    )
    if record.get("evidenceKind") != kind:
        errors.append("evidence_kind_mismatch")
    if spec.key == "DA-INTEGRATIONS-001":
        try:
            _feature_evidence(record, features or {})
        except ValueError:
            errors.append("evidence_features_invalid_or_conflicting")
    if isinstance(details, dict) and spec.key in _RUNTIME_RUN_FIELDS:
        runs = details.get(_RUNTIME_RUN_FIELDS[spec.key])
        outcomes = details.get("outcomes")
        if (
            not isinstance(runs, list) or not runs
            or any(not isinstance(run, str) or not run.strip() for run in runs)
            or len(runs) != len(set(runs))
            or not isinstance(outcomes, dict)
            or set(runs) != set(outcomes)
            or any(not isinstance(value, str) or value not in {"passed", "failed"} for value in outcomes.values())
        ):
            errors.append("employee_runtime_correlation_missing")
        elif (record.get("outcome") == "satisfied") != all(value == "passed" for value in outcomes.values()):
            errors.append("employee_runtime_outcome_conflict")
        if spec.key == "DA-RUNTIME-001" and str(details.get("publishedChannel", "")).casefold() in {
            "test", "test_pane", "copilot_studio_test_pane",
        }:
            errors.append("test_pane_is_not_published_employee_runtime")
    if isinstance(details, dict) and spec.key == "WD-DA-MAKER-001":
        test_time = _timestamp(details.get("testTimestamp"))
        if (
            details.get("makerTestCategory") != "copilot_studio_test_pane"
            or test_time is None or reviewed is None or test_time > reviewed
            or details.get("outcome") != ("passed" if record.get("outcome") == "satisfied" else "failed")
        ):
            errors.append("maker_test_evidence_invalid")
    return list(dict.fromkeys(errors))


def reviewed_da_features(
    execution: DAExecutionPlan, result: RunResult, runner, records: list[dict] | None,
    *, now: datetime | None = None,
) -> dict[DAFeature, DAFeatureEvidence]:
    """Admit only reviewed choices bound to the same live configuration evidence."""
    observed = dict(runner._da_observed_features)
    pin = next(
        (entry for entry in execution.coverage if entry.checkpoint.feature == DAFeature.REVISION_PIN),
        None,
    )
    if pin is not None:
        observed[DAFeature.REVISION_PIN] = DAFeatureEvidence(
            pin.applicability == DAApplicability.APPLICABLE, pin.evidence_source,
        )
    record = next(
        (record for record in records or [] if record["checkpointId"] == "DA-INTEGRATIONS-001"),
        None,
    )
    spec = next(
        (entry.checkpoint for entry in execution.coverage if entry.checkpoint.key == "DA-INTEGRATIONS-001"),
        None,
    )
    if record is None or spec is None:
        return observed
    target = _target(runner, result)
    errors = _review_record(
        record, spec,
        [row for row in result.results if row.checkpoint_id == spec.key],
        target, _revision(runner, result, target), now or datetime.now(timezone.utc),
        features=observed,
    )
    if errors or record.get("outcome") != "satisfied":
        return observed
    return _feature_evidence(record, observed)


def build_da_assessment(
    execution: DAExecutionPlan,
    result: RunResult,
    runner,
    records: list[dict] | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """Do not mutate diagnostics or accept a completion/accepted flag as proof."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Assessment time requires an explicit timezone.")
    target = _target(runner, result)
    revision = _revision(runner, result, target)
    coverage_entries = execution.coverage
    if hasattr(runner, "_da_observed_features"):
        features = reviewed_da_features(execution, result, runner, records, now=now)
        coverage_entries = build_da_coverage_plan(
            features, catalog=tuple(entry.checkpoint for entry in execution.coverage),
        )
    by_key = {entry.checkpoint.key: entry for entry in coverage_entries}
    matched: dict[str, list[CheckResult]] = defaultdict(list)
    other_rows = []
    for row in result.results:
        owner = row.checkpoint_id if row.checkpoint_id in by_key else next((
            key for key, entry in by_key.items()
            if entry.checkpoint.kind == "family" and _family_matches(key, row.checkpoint_id)
        ), None)
        if owner is None:
            other_rows.append({"checkpointId": row.checkpoint_id, "status": row.status})
        else:
            matched[owner].append(row)
    evidence = {record["checkpointId"]: record for record in records or []}
    issues = []
    if revision is None:
        issues.append("verified_configuration_snapshot_unavailable")
    if any(row.evidence.get("executionError") is True for row in result.results):
        issues.append("producer_execution_error")
    if any(state.get("required") is True and state.get("available") is not True
           for state in result.client_availability.values()):
        issues.append("required_client_unavailable")
    if any(key not in by_key for key in evidence):
        issues.append("unrecognized_evidence_checkpoint")
    entries = []
    reviews = []
    selected = set(execution.profile.checkpoint_ids)
    for entry in coverage_entries:
        spec = entry.checkpoint
        rows = matched[spec.key]
        statuses = [row.status for row in rows]
        applicable = entry.applicability == DAApplicability.APPLICABLE
        required = spec.required and entry.applicability not in {
            DAApplicability.EXCLUDED, DAApplicability.NOT_APPLICABLE,
        }
        reasons = []
        basis = ""
        if entry.applicability == DAApplicability.EXCLUDED:
            coverage, state = "excluded", "excluded"
        elif entry.applicability == DAApplicability.NOT_APPLICABLE:
            coverage, state = "not_applicable", "not_applicable"
        elif not applicable:
            coverage, state = "unknown", "incomplete"
            reasons.append("unknown_applicability")
        elif spec.key not in selected:
            coverage, state = "unsupported", "incomplete"
            reasons.append("no_approved_dispatch")
        elif not rows:
            coverage, state = "missing", "incomplete"
            reasons.append("expected_result_missing")
        elif len(rows) != len({(row.checkpoint_id, row.status) for row in rows}):
            coverage, state = "ambiguous", "incomplete"
            reasons.append("duplicate_status_bucket")
        else:
            coverage, state = "observed", "incomplete"
            if Status.FAILED.value in statuses and revision is not None:
                state, basis = "defect", "automated_assertion"
            elif spec.disposition != DADisposition.MANUAL and all(
                status == Status.PASSED.value for status in statuses
            ) and not any(row.evidence.get("dependencyCoverageComplete") is False for row in rows):
                state, basis = "satisfied", "automated"
            else:
                reasons.append("required_evidence_unverified")
        record = evidence.get(spec.key)
        if record is not None:
            errors = (
                _review_record(
                    record, spec, rows, target, revision, now,
                    features=getattr(runner, "_da_observed_features", None),
                )
                if required and applicable and coverage == "observed" else
                ["evidence_not_applicable_to_observed_requirement"]
            )
            if not errors and state != "defect":
                state = "satisfied" if record["outcome"] == "satisfied" else "defect"
                basis = "reviewed_attestation"
                reasons = []
            elif required and state != "defect":
                state = "incomplete"
                reasons.extend(errors)
            reviews.append({
                "checkpointId": spec.key, "accepted": not errors,
                "reasonCodes": errors,
                **({
                    key: record[key]
                    for key in ("source", "reviewerRole", "observedAt", "reviewedAt", "validUntil", "evidenceKind")
                } if not errors else {}),
            })
        if not required and state not in {"excluded", "not_applicable"}:
            state = "advisory"
        entries.append({
            **entry.to_dict(),
            "deploymentRequired": required,
            "scheduled": spec.key in selected,
            "coverageState": coverage,
            "observed": [{"checkpointId": row.checkpoint_id, "status": row.status} for row in rows],
            "evidenceState": state,
            "evidenceBasis": basis,
            "reasonCodes": list(dict.fromkeys(reasons)),
            "requiredEvidenceFields": sorted({
                field for row in rows for field in (
                    row.evidence["requiredFields"]
                    if isinstance(row.evidence.get("requiredFields"), list) else []
                )
                if isinstance(field, str)
            }),
        })
    required_entries = [entry for entry in entries if entry["deploymentRequired"]]
    states = Counter(entry["evidenceState"] for entry in required_entries)
    deployment = "NOT_READY" if states["defect"] else (
        "INCOMPLETE" if states["incomplete"] or issues else "READY"
    )
    return {
        "schemaVersion": DA_ASSESSMENT_SCHEMA,
        "assessedAt": now.isoformat(),
        "target": target,
        "scope": "selected_realm_only",
        "configurationRevision": revision,
        "diagnosticOverall": result.overall,
        "deploymentReadiness": deployment,
        "decisionBasis": "automated_results_and_explicitly_reviewed_attestations",
        "issues": issues,
        "counts": {
            "catalogDefinitions": len(entries),
            "scheduledSelectors": len(selected),
            "observedRows": len(result.results),
            "requiredDefinitions": len(required_entries),
            "satisfied": states["satisfied"],
            "defects": states["defect"],
            "incomplete": states["incomplete"],
            "unknownApplicability": sum(entry["coverageState"] == "unknown" for entry in required_entries),
            "missingResults": sum(entry["coverageState"] == "missing" for entry in required_entries),
            "assessmentGaps": len(issues),
            "excluded": sum(entry["evidenceState"] == "excluded" for entry in entries),
            "notApplicable": sum(entry["evidenceState"] == "not_applicable" for entry in entries),
        },
        "coverage": entries,
        "otherObservations": other_rows,
        "evidenceReviews": reviews,
        "unrecognizedEvidenceCheckpoints": sorted(set(evidence) - set(by_key)),
    }
