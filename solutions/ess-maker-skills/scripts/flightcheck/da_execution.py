# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Plan DA selections from the shared registry and reconcile every planned ID."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import requests

from .runner import BLOCK_REASON_CHECKPOINT_CONTRACT, CheckResult, Status

if TYPE_CHECKING:
    from .registry import CheckpointSpec


class DAConfigurationError(ValueError):
    """A supported read demonstrated missing required configuration."""


def plan_da_checks(*, checkpoint=None, profile=None, local=False, scope=None):
    from .da_checks import validate_da_definitions
    from .registry import REGISTRY, resolve_profile

    validate_da_definitions(REGISTRY)
    if checkpoint:
        requested = (checkpoint,)
    elif profile:
        definition = resolve_profile(profile)
        if definition is None:
            raise ValueError(f"Unknown FlightCheck profile: {profile}.")
        requested = definition.checkpoint_ids
    else:
        features = {
            "workday": {"workday", "workday_oob", "workday_custom"},
            "servicenow": {"servicenow"},
        }.get(scope)
        integration_key = {"workday": "WD-INTEGRATION-001", "servicenow": "SN-INTEGRATION-001"}.get(scope)
        requested = tuple(
            key for key, spec in REGISTRY.items()
            if spec.da and spec.da.executable and (not local or spec.da.local)
            and (features is None or spec.da.feature in features or key == integration_key)
        )
    planned: dict[str, CheckpointSpec] = {}
    visiting: set[str] = set()
    aliases: dict[str, tuple[str, ...]] = {}

    def visit(key):
        spec = REGISTRY.get(key)
        if spec is None or spec.da is None:
            raise ValueError(f"{key} has no registered DA validation definition.")
        if key in visiting:
            raise ValueError(f"Cyclic DA prerequisite/replacement at {key}.")
        if key in planned:
            return
        visiting.add(key)
        if spec.da.disposition == "replaced":
            if not spec.da.replacements:
                raise ValueError(f"{key} declares a replacement without a target.")
            aliases[key] = spec.da.replacements
            for replacement in spec.da.replacements:
                visit(replacement)
        else:
            if spec.da.executable:
                for prerequisite in spec.da.prerequisites:
                    if not local:
                        visit(prerequisite)
            planned[key] = spec
        visiting.remove(key)

    for key in requested:
        visit(key)
    return requested, tuple(planned.values()), aliases


def result_for(spec, status, finding, *, evidence=None):
    return CheckResult(
        checkpoint_id=spec.key, category=spec.category_label,
        priority=spec.priority, status=status, description=spec.da.purpose,
        result=finding, roles=list(spec.roles),
        remediation="", evidence=evidence or {},
        block_reason=BLOCK_REASON_CHECKPOINT_CONTRACT if status == "Blocked" else "",
    )


def manual_result(runner, spec, reason, *, evidence=None):
    row = result_for(spec, "Manual", reason, evidence=evidence)
    return decorate(runner, spec, row)


def decorate(runner, spec, row):
    definition = spec.da
    row.custom_tags = list(dict.fromkeys((*spec.custom_tags, *row.custom_tags)))
    if definition.documentation:
        row.doc_link = definition.documentation
    row.evidence = {
        **row.evidence,
        "agentSlug": runner.agent_slug,
        "verificationScope": {
            "agentSlug": runner.agent_slug,
            "agentId": (getattr(runner, "connection_agent_ids", ()) or ("",))[0],
            "environmentId": runner.env_id or "",
            "targetVerified": getattr(runner, "_da_native_snapshot", None) is not None,
        },
        "apiContract": definition.api_contract,
        "assertionScope": definition.target_scope,
    }
    if definition.local:
        row.evidence.setdefault("deploymentFreshnessVerified", False)
    if row.status == "Manual":
        row.automation_type = "manual"
        row.evidence.setdefault("manualVerificationSteps", list(definition.manual_steps))
        row.evidence.setdefault("ifMissingOrIncorrect", definition.if_incorrect)
        row.evidence.setdefault("verificationReason", row.result)
        row.evidence.setdefault("expectedSetting", definition.purpose)
        if not row.remediation:
            row.remediation = "\n".join(
                f"{index}. {step}" for index, step in enumerate(definition.manual_steps, 1)
            ) + "\nIf missing or incorrect: " + definition.if_incorrect
    elif row.status == "Error":
        row.evidence["executionError"] = True
        row.remediation = (
            "Review the reported service/response error, verify the selected target, and retry "
            "this same check. Do not change configuration or mark it manually complete to hide an execution error."
        )
    elif row.status == "Passed":
        row.remediation = ""
    elif not row.remediation and row.status not in {"NotConfigured", "Skipped"}:
        row.remediation = definition.if_incorrect
    return row


def _applicability(runner, spec):
    feature = spec.da.feature
    if not feature:
        return None
    if feature in {"workday", "workday_oob", "workday_custom", "servicenow"}:
        if feature != "servicenow" and getattr(runner, "da_explicit_selection", False):
            return None
        from .maker_diagnostics import _check_integrations

        runner.da_executor.group("integrations", _check_integrations)
        name = "ServiceNow" if feature == "servicenow" else "Workday"
        state = getattr(runner, "maker_integrations", {}).get(name, {})
        value = state.get("applicability", "unknown")
        if value == "unknown":
            audit = getattr(runner, "_da_connection_audit", None)
            limitations = [
                *(audit.read_limitations if audit else []),
                *state.get("inventoryReadLimitations", []),
            ]
            if any(item["kind"] == "error" for item in limitations):
                return result_for(
                    spec, "Error", f"{name} applicability discovery encountered a service/response error.",
                    evidence={"readLimitations": limitations},
                )
            return manual_result(
                runner, spec, f"{name} applicability could not be established for this agent.",
                evidence={"applicability": "unknown", "discoveryLimitations": state.get("discoveryLimitations", [])},
            )
        if value != "enabled" or (
            feature == "workday_oob" and not getattr(runner, "maker_workday_extension", False)
        ):
            return result_for(
                spec, "NotConfigured", f"{name} is {value}; this check is not applicable to the selected active configuration.",
                evidence={"applicability": "not_applicable", "featureState": value},
            )
        if feature == "workday_custom":
            from .checks.workday_da import reviewed_workday_topic_schemas

            schema = runner._da_native_snapshot["changeset"]["bot"]["schemaName"]
            reviewed = {value.casefold() for value in reviewed_workday_topic_schemas(schema)}
            if not any(
                topic["activation"] == "Active" and topic["topic"].casefold() not in reviewed
                for topic in state.get("topics", [])
            ):
                return result_for(
                    spec, "NotConfigured", "No enabled custom Workday conversation was found in the complete selected-agent integration inventory.",
                    evidence={"applicability": "not_applicable"},
                )
    elif feature == "flows":
        audit = getattr(runner, "_da_connection_audit", None)
        if audit is None or audit.warnings or audit.blocked:
            return manual_result(runner, spec, "Invoked-flow applicability could not be completely established.")
        if audit.flow_count == 0:
            return result_for(
                spec, "NotConfigured", "This agent has no active invoked-flow dependencies.",
                evidence={"applicability": "not_applicable"},
            )
    # Knowledge and Dataverse applicability are decided from their exact
    # inventories, not from an absent local configuration key.
    return None


class DAExecutor:
    def __init__(self, runner, args, requested, specs, aliases):
        self.runner, self.args = runner, args
        self.requested, self.specs, self.aliases = requested, specs, aliases
        self.rows: dict[str, CheckResult] = {}
        self.groups: dict[str, list[CheckResult] | BaseException] = {}
        self._graph_error: Exception | None = None

    def graph(self):
        from agentbuilder import tenant_id_from_access_token
        from .graph_client import GraphClient

        if self._graph_error is not None:
            raise self._graph_error
        if self.runner.graph is None:
            client = GraphClient(self.runner.tenant_id, strict_reads=True)
            try:
                token = client.authenticate(preferred_username=self.runner.authenticated_account)
                account = client.signed_in_username
                if not account or account.casefold() != self.runner.authenticated_account.casefold():
                    raise ValueError("Graph authentication selected a different or unverifiable account.")
                if tenant_id_from_access_token(token).casefold() != self.runner.tenant_id.casefold():
                    raise ValueError("Graph authentication selected a different tenant.")
            except (RuntimeError, ValueError, requests.RequestException) as exc:
                self._graph_error = exc
                raise
            self.runner.graph = client
        return self.runner.graph

    def powerplatform(self):
        from .powerplatform_client import PowerPlatformClient

        if self.runner.powerplatform is None:
            client = PowerPlatformClient(self.runner.tenant_id, ring=self.runner.ring, strict_reads=True)
            client._token = self.runner.connection_dependency_token(client.scope)
            client.signed_in_username = self.runner.authenticated_account
            self.runner.powerplatform = client
        return self.runner.powerplatform

    def azure_arm(self):
        from .azure_arm_client import AzureArmClient

        if self.runner.azure_arm is None:
            client = AzureArmClient(self.runner.tenant_id, strict_reads=True)
            client._token = self.runner.connection_dependency_token("https://management.azure.com/.default")
            self.runner.azure_arm = client
        return self.runner.azure_arm

    def group(self, name, producer):
        if name not in self.groups:
            try:
                rows = producer(self.runner)
                if not isinstance(rows, list) or any(not isinstance(row, CheckResult) for row in rows):
                    raise ValueError(f"Producer {name} did not return list[CheckResult].")
                self.groups[name] = rows
            except (Exception, SystemExit) as exc:
                self.groups[name] = exc
        value = self.groups[name]
        if isinstance(value, BaseException):
            raise value
        return value

    def run(self, _runner):
        results = []
        for spec in self.specs:
            row = self._execute(spec)
            row = decorate(self.runner, spec, row)
            self.rows[spec.key] = row
            results.append(row)
        return results

    def _execute(self, spec):
        definition = spec.da
        if not definition.executable:
            return result_for(
                spec, "NotConfigured", definition.reason,
                evidence={"applicability": "not_applicable", "disposition": definition.disposition},
            )
        unsafe = [
            key for key in definition.prerequisites
            if key in self.rows and (
                self.rows[key].status in {"Blocked", "Error", "Manual"}
                or (key in {"DA-AGENT-001", "DA-CONTENT-001"} and self.rows[key].status == "Failed")
            )
        ]
        if unsafe:
            denied = all(self.rows[key].status == "Manual" for key in unsafe)
            row = result_for(
                spec, "Manual" if denied else "Blocked",
                "Dependent reads were not attempted because prerequisite verification was unavailable: "
                + ", ".join(unsafe) + ".",
                evidence={"unverifiedPrerequisites": unsafe},
            )
            return row
        try:
            applicability = _applicability(self.runner, spec)
            if applicability is not None:
                return applicability
            self.runner.da_current_spec = spec
            rows = spec.category_fn(self.runner) if definition.strategy == "custom" else self._registered(spec)
            matches = [row for row in rows if row.checkpoint_id == spec.key]
            if len(matches) != 1:
                raise ValueError(
                    f"Producer for {spec.key} returned {len(matches)} matching rows; exactly one is required."
                )
            row = replace(matches[0], evidence=dict(matches[0].evidence), roles=list(matches[0].roles))
            if row.status not in {status.value for status in Status}:
                raise ValueError(f"Producer for {spec.key} returned invalid status {row.status!r}.")
            return row
        except DAConfigurationError as exc:
            return result_for(spec, "Failed", str(exc))
        except PermissionError as exc:
            return manual_result(
                self.runner, spec, f"The delegated read was denied: {exc}",
                evidence={"readLimitation": "permission_denied", "httpStatus": 403},
            )
        except NotImplementedError as exc:
            return manual_result(
                self.runner, spec, str(exc), evidence={"readLimitation": "unsupported_contract"},
            )
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code == 403:
                return manual_result(
                    self.runner, spec, f"The delegated read returned HTTP 403: {exc}",
                    evidence={"readLimitation": "permission_denied", "httpStatus": code},
                )
            return result_for(spec, "Error", f"{type(exc).__name__}: {exc}", evidence={"httpStatus": code})
        except (Exception, SystemExit) as exc:
            return result_for(spec, "Error", f"{type(exc).__name__}: {exc}")

    def _registered(self, spec):
        from .checks.da_validation import run_registered_da_check

        return run_registered_da_check(self.runner)

    def coverage(self):
        from .registry import REGISTRY

        definitions = [spec for spec in REGISTRY.values() if spec.da is not None]
        rows = list(self.rows.values())
        not_applicable = {
            row.checkpoint_id for row in rows
            if row.status == "NotConfigured" and row.evidence.get("applicability") in {
                "not_applicable", "not_configured", "disabled", "configured",
            }
        }
        return {
            "definitionsConsidered": len(definitions),
            "requested": list(self.requested),
            "planned": [spec.key for spec in self.specs],
            "emitted": [row.checkpoint_id for row in rows],
            "aliases": {key: list(value) for key, value in self.aliases.items()},
            "automaticCompleted": sum(row.status in {"Passed", "Failed", "Warning"} for row in rows),
            "manual": sum(row.status == "Manual" for row in rows),
            "notApplicable": len(not_applicable),
            "limitations": sum(
                row.status in {"Blocked", "Error", "Skipped"}
                or (row.status == "NotConfigured" and row.checkpoint_id not in not_applicable)
                for row in rows
            ),
            "dispositions": [
                {"checkpointId": spec.key, "disposition": spec.da.disposition,
                 "reason": spec.da.reason, "replacements": list(spec.da.replacements)}
                for spec in definitions if not spec.da.executable
            ],
        }
