# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic persisted-state operations for Workday DA setup."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

import portalocker

from workday_da_contract import (
    DEFINITION_ROOT,
    WorkdayDAContractError,
    load_definition,
    validate_state,
)


_VALID_RESULTS = {
    value.casefold(): value
    for value in (
        "Passed",
        "Failed",
        "Error",
        "Warning",
        "Manual",
        "NotConfigured",
        "Skipped",
    )
}
_STATUS_RE = re.compile(
    r"status: (pending|in-progress|done|blocked)(?= -->)"
)
_ID_RE = re.compile(r"\bid: (?P<id>DA[1-5]\.[1-9][0-9]*)\b")


class WorkdayDAStateError(RuntimeError):
    """Raised when Workday DA state cannot be read, migrated, or written."""


class WorkdayDAStateConflictError(WorkdayDAStateError):
    """Raised when multiple state copies require explicit reconciliation."""


class WorkdayDAStateLockError(WorkdayDAStateError):
    """Raised when another Workday DA state writer holds the lock."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write one file through a durable same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkdayDAStateError(
            f"Workday DA state is not valid JSON: {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise WorkdayDAStateError(
            f"Workday DA state could not be read: {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayDAStateError(
            f"Workday DA state must contain a JSON object: {path}"
        )
    return document


def _parse_json_argument(value: str | None, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkdayDAStateError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise WorkdayDAStateError(f"{label} must be a JSON object")
    return document


class WorkdayDAStateStore:
    """Serialize and validate all Workday DA persisted-state mutations."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        definition: dict[str, Any] | None = None,
        lock_timeout: float = 5.0,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.definition = definition or load_definition()
        self.lock_timeout = lock_timeout
        state = self.definition["state"]
        self.config_path = self.workspace_root / Path(state["configPath"])
        self.checklist_path = self.workspace_root / Path(state["checklistPath"])
        self.legacy_checklist_paths = [
            self.workspace_root / Path(path)
            for path in state["legacyChecklistPaths"]
        ]
        self.lock_path = self.config_path.with_name("state.lock")
        self.foundation_config_path = self.workspace_root / ".local" / "config.json"
        self.template_path = DEFINITION_ROOT / "tasks.md"
        self.step_by_id = {
            step["id"]: step for step in self.definition["steps"]
        }

    @contextmanager
    def _locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with portalocker.Lock(
                str(self.lock_path),
                mode="a+",
                timeout=self.lock_timeout,
                encoding="utf-8",
            ):
                yield
        except portalocker.exceptions.LockException as exc:
            raise WorkdayDAStateLockError(
                "Another /connect workday session is updating this workspace. "
                "Wait for it to finish, then retry."
            ) from exc

    def _migrate_legacy_checklist(self) -> bool:
        existing_legacy = [
            path for path in self.legacy_checklist_paths if path.exists()
        ]
        if self.checklist_path.exists() and existing_legacy:
            raise WorkdayDAStateConflictError(
                "Both canonical and legacy Workday DA checklists exist. "
                "Reconcile them manually; the state helper will not overwrite "
                "or delete either copy."
            )
        if len(existing_legacy) > 1:
            raise WorkdayDAStateConflictError(
                "Multiple legacy Workday DA checklists exist. Reconcile them "
                "before continuing."
            )
        if not existing_legacy:
            return False
        self.checklist_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing_legacy[0].replace(self.checklist_path)
        except OSError as exc:
            raise WorkdayDAStateError(
                "The legacy Workday DA checklist could not be moved to its "
                f"canonical location: {exc}"
            ) from exc
        return True

    def _task_states(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        states: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            identifier = _ID_RE.search(line)
            status = _STATUS_RE.search(line)
            if identifier and status:
                states[identifier.group("id")] = status.group(1)
        return states

    def _default_step_state(
        self,
        step: dict[str, Any],
        *,
        state: str = "pending",
    ) -> dict[str, Any]:
        checkpoints = step["checkpoints"]
        return {
            "state": state,
            "checkpoint": checkpoints[0] if checkpoints else None,
            "gate": step["gate"],
            "verifiedBy": None,
        }

    def _migrate_config(
        self,
        document: dict[str, Any],
        *,
        checklist_states: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        migrated = dict(document)
        definition_version = self.definition["definitionVersion"]
        state_schema_version = self.definition["stateSchemaVersion"]
        for field, current in (
            ("definitionVersion", definition_version),
            ("stateSchemaVersion", state_schema_version),
        ):
            existing = migrated.get(field)
            if existing in (None, 0):
                migrated[field] = current
            elif existing != current:
                raise WorkdayDAStateError(
                    f"Unsupported Workday DA {field} {existing}; this kit "
                    f"supports version {current}."
                )

        migrated.setdefault("status", "in-progress")
        setup_status = migrated.setdefault("setupStatus", {})
        if not isinstance(setup_status, dict):
            raise WorkdayDAStateError("Workday DA setupStatus must be an object")
        checklist_states = checklist_states or {}
        for step in self.definition["steps"]:
            step_id = step["id"]
            row = setup_status.get(step_id)
            if row is None:
                setup_status[step_id] = self._default_step_state(
                    step,
                    state=checklist_states.get(step_id, "pending"),
                )
                continue
            if not isinstance(row, dict):
                raise WorkdayDAStateError(
                    f"Workday DA setupStatus.{step_id} must be an object"
                )
            row = dict(row)
            row.setdefault("state", checklist_states.get(step_id, "pending"))
            row["checkpoint"] = (
                step["checkpoints"][0] if step["checkpoints"] else None
            )
            row["gate"] = step["gate"]
            row.setdefault("verifiedBy", None)
            setup_status[step_id] = row
        self._validate_canonical_config(migrated)
        return migrated

    def _validate_canonical_config(self, config: dict[str, Any]) -> None:
        try:
            validate_state(config)
        except WorkdayDAContractError as exc:
            raise WorkdayDAStateError(str(exc)) from exc
        for field in ("definitionVersion", "stateSchemaVersion"):
            expected = self.definition[field]
            if config.get(field) != expected:
                raise WorkdayDAStateError(
                    f"Workday DA {field} must be {expected}, got "
                    f"{config.get(field)!r}."
                )
        actual_steps = set(config["setupStatus"])
        expected_steps = set(self.step_by_id)
        if actual_steps != expected_steps:
            missing = expected_steps - actual_steps
            unknown = actual_steps - expected_steps
            details = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if unknown:
                details.append("unknown " + ", ".join(sorted(unknown)))
            raise WorkdayDAStateError(
                "Workday DA setupStatus does not match the active definition: "
                + "; ".join(details)
            )
        for step_id, step in self.step_by_id.items():
            row = config["setupStatus"][step_id]
            expected_checkpoint = (
                step["checkpoints"][0] if step["checkpoints"] else None
            )
            if row["checkpoint"] != expected_checkpoint:
                raise WorkdayDAStateError(
                    f"Workday DA step {step_id} has checkpoint "
                    f"{row['checkpoint']!r}; expected {expected_checkpoint!r}."
                )
            if row["gate"] != step["gate"]:
                raise WorkdayDAStateError(
                    f"Workday DA step {step_id} has gate {row['gate']!r}; "
                    f"expected {step['gate']!r}."
                )

    def _render_checklist(self, config: dict[str, Any]) -> str:
        lines = self.template_path.read_text(encoding="utf-8").splitlines()
        rendered: list[str] = []
        seen: set[str] = set()
        for line in lines:
            identifier = _ID_RE.search(line)
            if not identifier:
                rendered.append(line)
                continue
            step_id = identifier.group("id")
            if step_id not in self.step_by_id:
                raise WorkdayDAStateError(
                    f"Checklist template contains unknown step {step_id}"
                )
            state = config["setupStatus"][step_id]["state"]
            updated = _STATUS_RE.sub(f"status: {state}", line)
            if updated == line and not _STATUS_RE.search(line):
                raise WorkdayDAStateError(
                    f"Checklist template row {step_id} has no status marker"
                )
            if rendered:
                marker = "x" if state == "done" else " "
                rendered[-1] = re.sub(
                    r"^- \[[ x]\]",
                    f"- [{marker}]",
                    rendered[-1],
                    count=1,
                )
            rendered.append(updated)
            seen.add(step_id)
        missing = self.step_by_id.keys() - seen
        if missing:
            raise WorkdayDAStateError(
                "Checklist template is missing steps: "
                + ", ".join(sorted(missing))
            )
        return "\n".join(rendered) + "\n"

    def _write_config(self, config: dict[str, Any]) -> None:
        self._validate_canonical_config(config)
        serialized = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
        _atomic_write_text(self.config_path, serialized)

    def _write_checklist(self, config: dict[str, Any]) -> None:
        _atomic_write_text(self.checklist_path, self._render_checklist(config))

    def _load_for_mutation(self) -> tuple[dict[str, Any], bool]:
        migrated_checklist = self._migrate_legacy_checklist()
        checklist_states = self._task_states(self.checklist_path)
        config = self._migrate_config(
            _read_json_object(self.config_path),
            checklist_states=checklist_states,
        )
        return config, migrated_checklist

    def initialize(self) -> dict[str, Any]:
        """Migrate legacy state and create validated canonical config/state."""
        with self._locked():
            config, migrated_checklist = self._load_for_mutation()
            self._write_config(config)
            if not migrated_checklist:
                self._write_checklist(config)
            return config

    def reconcile(self) -> dict[str, Any]:
        """Repair the derived checklist from authoritative validated config."""
        with self._locked():
            config, _ = self._load_for_mutation()
            self._write_config(config)
            self._write_checklist(config)
            return config

    def validate(self) -> dict[str, Any]:
        """Validate canonical config without changing any file."""
        config = _read_json_object(self.config_path)
        if not config:
            raise WorkdayDAStateError(
                "Workday DA state does not exist; initialize it first."
            )
        self._validate_canonical_config(config)
        return config

    def _normalize_result(self, result: str | None) -> str | None:
        if result is None:
            return None
        normalized = _VALID_RESULTS.get(result.casefold())
        if normalized is None:
            raise WorkdayDAStateError(
                f"Unsupported checkpoint result: {result}"
            )
        return normalized

    def _automatic_evidence(
        self,
        *,
        step: dict[str, Any],
        result: str | None,
        result_source: str,
    ) -> dict[str, Any] | None:
        if result in {"Failed", "Error"}:
            return {
                "outcome": result.upper(),
                "provenance": result_source,
                "note": "The current verification did not pass.",
                "capturedAt": _utc_now(),
                "failureCategory": "verification-failed",
                "retryable": False,
                "attemptCount": 1,
            }
        if (
            step["gate"] == "prog"
            and result == "Passed"
            and result_source != "external"
        ):
            checkpoint = (
                step["checkpoints"][0]
                if step["checkpoints"]
                else "external verification"
            )
            return {
                "outcome": "PASSED",
                "provenance": result_source,
                "note": f"{checkpoint} passed.",
                "capturedAt": _utc_now(),
            }
        if step["gate"] == "advisory":
            return {
                "outcome": (result or "REVIEWED").upper(),
                "provenance": "advisory",
                "note": "The advisory result was shown to the operator.",
                "capturedAt": _utc_now(),
            }
        return None

    def _resulting_state(
        self,
        *,
        step: dict[str, Any],
        result: str | None,
        result_source: str,
        ack: bool,
        evidence: dict[str, Any] | None,
    ) -> str:
        if result in {"Failed", "Error"} and step["gate"] != "advisory":
            return "blocked"
        gate = step["gate"]
        if gate == "advisory":
            return "done"
        if gate == "prog":
            if result != "Passed":
                return "in-progress"
            if result_source == "external" and evidence is None:
                return "in-progress"
            return "done"
        if gate in {"manual", "attest"}:
            return "done" if ack and evidence is not None else "in-progress"
        raise WorkdayDAStateError(f"Unsupported gate for {step['id']}: {gate}")

    def _validate_readiness_evidence(
        self,
        step_id: str,
        *,
        ack: bool,
        evidence: dict[str, Any] | None,
    ) -> None:
        final_step_id = self.definition["completion"]["finalStepId"]
        if step_id != final_step_id or not ack or evidence is None:
            return
        scenario = evidence.get("scenario")
        if not isinstance(scenario, dict):
            raise WorkdayDAStateError(
                "Final Workday readiness evidence must include a structured "
                "scenario record."
            )
        required_truth = (
            scenario.get("signedInUserConfirmed") is True
            and scenario.get("realWorkdayDataConfirmed") is True
            and scenario.get("unexpectedSignIn") is False
        )
        if not required_truth:
            raise WorkdayDAStateError(
                "Final Workday readiness requires a signed-in employee, real "
                "Workday data, and no unexpected additional sign-in."
            )

    def _dependent_ids(self, step_id: str) -> set[str]:
        dependents: set[str] = set()
        changed = True
        while changed:
            changed = False
            for candidate in self.definition["steps"]:
                candidate_id = candidate["id"]
                if candidate_id == step_id or candidate_id in dependents:
                    continue
                dependencies = set(candidate["dependsOn"])
                if step_id in dependencies or dependencies & dependents:
                    dependents.add(candidate_id)
                    changed = True
        return dependents

    def _regress_rows(
        self,
        config: dict[str, Any],
        step_ids: set[str],
        *,
        root_step_id: str,
        root_state: str,
    ) -> None:
        for step_id in step_ids:
            row = config["setupStatus"][step_id]
            row["state"] = root_state if step_id == root_step_id else "in-progress"
            row["verifiedBy"] = None
            row.pop("evidence", None)

    def _recompute_provider_status(self, config: dict[str, Any]) -> None:
        required = self.definition["completion"]["requiredStepIds"]
        final_step = self.definition["completion"]["finalStepId"]
        setup_status = config["setupStatus"]
        revalidation = config.get("revalidation")
        revalidation_pending = bool(
            isinstance(revalidation, dict)
            and revalidation.get("requiredStepIds")
        )
        if (
            not revalidation_pending
            and all(
                setup_status[step_id]["state"] == "done"
                for step_id in required
            )
        ):
            config["status"] = self.definition["completion"]["providerStatus"]
        elif all(
            setup_status[step_id]["state"] == "done"
            for step_id in required
            if step_id != final_step
        ):
            config["status"] = "configured"
        else:
            config["status"] = "in-progress"

    def _scope_fingerprint(
        self,
        step: dict[str, Any],
        config: dict[str, Any],
    ) -> str:
        foundation = _read_json_object(self.foundation_config_path)
        scope = {}
        for field in step["scopeFields"]:
            if field in config:
                value = config.get(field)
            else:
                value = foundation.get(field)
            scope[field] = value
        serialized = json.dumps(
            scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def revalidation_plan(self) -> dict[str, Any]:
        """Create a durable resume plan and regress scope-stale manual rows."""
        with self._locked():
            config, _ = self._load_for_mutation()
            actions = []
            required_programmatic = []
            stale_manual: set[str] = set()
            for step in self.definition["steps"]:
                step_id = step["id"]
                row = config["setupStatus"][step_id]
                if row["state"] != "done":
                    continue
                evidence = row.get("evidence")
                saved_fingerprint = (
                    evidence.get("scopeFingerprint")
                    if isinstance(evidence, dict)
                    else None
                )
                current_fingerprint = self._scope_fingerprint(step, config)
                if step["gate"] == "prog":
                    required_programmatic.append(step_id)
                    actions.append(
                        {
                            "stepId": step_id,
                            "owner": step["owner"],
                            "mode": (
                                "checkpoint"
                                if step["checkpoints"]
                                else "external-verification"
                            ),
                            "checkpoints": step["checkpoints"],
                            "reason": (
                                "scope-changed"
                                if saved_fingerprint != current_fingerprint
                                else "live-recheck"
                            ),
                        }
                    )
                elif saved_fingerprint != current_fingerprint:
                    stale_manual.add(step_id)
                    actions.append(
                        {
                            "stepId": step_id,
                            "owner": step["owner"],
                            "mode": "manual-evidence-stale",
                            "checkpoints": step["checkpoints"],
                            "reason": "scope-changed",
                        }
                    )

            if stale_manual:
                affected = set(stale_manual)
                for step_id in stale_manual:
                    affected.update(self._dependent_ids(step_id))
                for step_id in affected:
                    row = config["setupStatus"][step_id]
                    row["state"] = "in-progress"
                    row["verifiedBy"] = None
                    row.pop("evidence", None)

            if required_programmatic:
                config["revalidation"] = {
                    "requiredStepIds": required_programmatic,
                    "createdAt": _utc_now(),
                }
            else:
                config.pop("revalidation", None)
            self._recompute_provider_status(config)
            self._write_config(config)
            self._write_checklist(config)
            return {"actions": actions, "config": config}

    def update_row(
        self,
        step_id: str,
        *,
        checkpoint_result: str | None,
        result_source: str = "flightcheck",
        ack: bool = False,
        evidence: dict[str, Any] | None = None,
        gate_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply one gate transition and persist config before its derived view."""
        if step_id not in self.step_by_id:
            raise WorkdayDAStateError(f"Unknown Workday DA step: {step_id}")
        if result_source not in {
            "flightcheck",
            "external",
            "user-acknowledgement",
            "advisory",
        }:
            raise WorkdayDAStateError(
                f"Unsupported Workday DA result source: {result_source}"
            )
        result = self._normalize_result(checkpoint_result)
        step = self.step_by_id[step_id]
        evidence = evidence or self._automatic_evidence(
            step=step,
            result=result,
            result_source=result_source,
        )
        self._validate_readiness_evidence(
            step_id,
            ack=ack,
            evidence=evidence,
        )
        resulting_state = self._resulting_state(
            step=step,
            result=result,
            result_source=result_source,
            ack=ack,
            evidence=evidence,
        )

        with self._locked():
            config, _ = self._load_for_mutation()
            if resulting_state == "done":
                incomplete_dependencies = [
                    dependency
                    for dependency in step["dependsOn"]
                    if config["setupStatus"][dependency]["state"] != "done"
                ]
                if incomplete_dependencies:
                    raise WorkdayDAStateError(
                        f"Cannot complete {step_id}; prerequisites are not "
                        "done: " + ", ".join(incomplete_dependencies)
                    )
            existing_state = config["setupStatus"][step_id]["state"]
            row = config["setupStatus"][step_id]
            row["state"] = resulting_state
            row["checkpoint"] = (
                step["checkpoints"][0] if step["checkpoints"] else None
            )
            row["gate"] = step["gate"]
            if resulting_state == "done":
                row["verifiedBy"] = {
                    "prog": "programmatic",
                    "manual": "attested",
                    "attest": "attested",
                    "advisory": "reviewed",
                }[step["gate"]]
                if evidence is not None:
                    evidence = dict(evidence)
                    evidence["scopeFingerprint"] = self._scope_fingerprint(
                        step, config
                    )
                    row["evidence"] = evidence
            else:
                row["verifiedBy"] = None
                row.pop("evidence", None)
                if evidence is not None and resulting_state == "blocked":
                    row["evidence"] = evidence
            if gate_evidence is not None:
                row["gateEvidence"] = gate_evidence

            revalidation = config.get("revalidation")
            if isinstance(revalidation, dict):
                required = revalidation.get("requiredStepIds")
                if isinstance(required, list) and step_id in required:
                    revalidation["requiredStepIds"] = [
                        candidate
                        for candidate in required
                        if candidate != step_id
                    ]
                    if not revalidation["requiredStepIds"]:
                        config.pop("revalidation", None)

            if resulting_state != "done" and existing_state == "done":
                self._regress_rows(
                    config,
                    self._dependent_ids(step_id),
                    root_step_id=step_id,
                    root_state=resulting_state,
                )
            self._recompute_provider_status(config)
            self._write_config(config)
            try:
                self._write_checklist(config)
            except Exception as exc:
                raise WorkdayDAStateError(
                    "Workday DA config was saved, but its checklist view could "
                    "not be refreshed. Run the reconcile command before "
                    "continuing."
                ) from exc
            return config

    def regress_row(
        self,
        step_id: str,
        *,
        blocked: bool = False,
    ) -> dict[str, Any]:
        """Regress one row and all transitive dependents."""
        if step_id not in self.step_by_id:
            raise WorkdayDAStateError(f"Unknown Workday DA step: {step_id}")
        with self._locked():
            config, _ = self._load_for_mutation()
            affected = self._dependent_ids(step_id) | {step_id}
            self._regress_rows(
                config,
                affected,
                root_step_id=step_id,
                root_state="blocked" if blocked else "in-progress",
            )
            self._recompute_provider_status(config)
            self._write_config(config)
            self._write_checklist(config)
            return config


def _summary(config: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for row in config["setupStatus"].values():
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return json.dumps(
        {"status": config["status"], "steps": counts},
        sort_keys=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage canonical Workday DA setup state."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Workspace root containing .local (default: current directory).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initialize")
    subparsers.add_parser("reconcile")
    subparsers.add_parser("validate")
    subparsers.add_parser("revalidation-plan")

    update = subparsers.add_parser("update-row")
    update.add_argument("--step-id", required=True)
    update.add_argument("--checkpoint-result")
    update.add_argument(
        "--result-source",
        choices=[
            "flightcheck",
            "external",
            "user-acknowledgement",
            "advisory",
        ],
        default="flightcheck",
    )
    update.add_argument("--ack", action="store_true")
    update.add_argument("--evidence-json")
    update.add_argument("--gate-evidence-json")

    regress = subparsers.add_parser("regress-row")
    regress.add_argument("--step-id", required=True)
    regress.add_argument("--blocked", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    store = WorkdayDAStateStore(args.root)
    try:
        if args.command == "initialize":
            config = store.initialize()
        elif args.command == "reconcile":
            config = store.reconcile()
        elif args.command == "validate":
            config = store.validate()
        elif args.command == "revalidation-plan":
            plan = store.revalidation_plan()
            print(json.dumps(plan["actions"], sort_keys=True))
            return 0
        elif args.command == "update-row":
            config = store.update_row(
                args.step_id,
                checkpoint_result=args.checkpoint_result,
                result_source=args.result_source,
                ack=args.ack,
                evidence=_parse_json_argument(
                    args.evidence_json, "evidence-json"
                ),
                gate_evidence=_parse_json_argument(
                    args.gate_evidence_json, "gate-evidence-json"
                ),
            )
        else:
            config = store.regress_row(
                args.step_id,
                blocked=args.blocked,
            )
    except (WorkdayDAStateError, WorkdayDAContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(_summary(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
