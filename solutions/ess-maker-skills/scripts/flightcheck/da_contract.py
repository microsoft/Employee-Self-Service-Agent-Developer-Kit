# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA coverage inventory and fail-closed applicability, without API dispatch.

An existing evaluator is not automatically deployment evidence. Review gaps,
observations, manual requirements and execution diagnostics remain distinct.
This contract does not change legacy scopes or Workday lifecycle membership.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from .runner import Role


DA_COVERAGE_SCHEMA = "flightcheck.da.coverage.v1"


class DAFeature(str, Enum):
    TEAMS = "teams"
    CONNECTORS = "connectors"
    NATIVE_CONNECTIONS = "native_connections"
    POWER_AUTOMATE = "power_automate"
    DATAVERSE_CUSTOMIZATION = "dataverse_customization"
    WORKDAY = "workday"
    WORKDAY_CUSTOMIZATIONS = "workday_customizations"
    WORKDAY_WRITES = "workday_writes"
    SERVICENOW = "servicenow"
    SAP_SUCCESSFACTORS = "sap_successfactors"
    KNOWLEDGE = "knowledge"
    GRAPH_CONNECTOR = "graph_connector"
    HANDOFF = "handoff"
    CUSTOM_TOPICS = "custom_topics"
    EXTERNAL_ENDPOINTS = "external_endpoints"
    REVISION_PIN = "revision_pin"
    ALM_PROMOTION = "alm_promotion"


class DADisposition(str, Enum):
    EVALUATOR = "evaluator"
    REVIEW = "requires_da_review"
    MANUAL = "manual"
    OBSERVATION = "observation"
    DIAGNOSTIC = "diagnostic"
    SUPERSEDED = "superseded"
    LEGACY = "legacy_only"
    ENGINE = "execution_guard"


class DAApplicability(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class DAFeatureEvidence:
    """Resolved feature state and its non-secret provenance, supplied by a caller."""

    enabled: bool | None
    source: str = ""

    def __post_init__(self) -> None:
        if self.enabled is not None and type(self.enabled) is not bool:
            raise ValueError("DA feature enabled must be a boolean or None.")
        if not isinstance(self.source, str):
            raise ValueError("DA feature evidence source must be text.")
        if self.enabled is not None and not self.source.strip():
            raise ValueError("Resolved DA feature state requires an evidence source.")


@dataclass(frozen=True)
class DACheckpoint:
    key: str
    area: str
    disposition: DADisposition
    reason: str
    owners: tuple[str, ...]
    required: bool = True
    feature: DAFeature | None = None
    kind: str = "fixed"
    replacements: tuple[str, ...] = ()


@dataclass(frozen=True)
class DACoverageEntry:
    checkpoint: DACheckpoint
    applicability: DAApplicability
    applicability_reason: str
    evidence_source: str = ""

    def to_dict(self) -> dict[str, object]:
        spec = self.checkpoint
        return {
            "checkpointId": spec.key,
            "area": spec.area,
            "kind": spec.kind,
            "disposition": spec.disposition.value,
            "required": spec.required,
            "feature": spec.feature.value if spec.feature else None,
            "applicability": self.applicability.value,
            "applicabilityReason": self.applicability_reason,
            "evidenceSource": self.evidence_source,
            "reason": spec.reason,
            "roles": list(spec.owners),
            "replacements": list(spec.replacements),
        }


_MAKER = (Role.ESS_MAKER.value,)
_PP = (Role.POWER_PLATFORM_ADMIN.value,)
_ENTRA = (Role.ENTRA_ADMIN.value,)
_M365 = (Role.M365_ADMIN.value,)
_WORKDAY = (Role.WORKDAY_ADMIN.value,)
_SN = (Role.SERVICENOW_ADMIN.value,)


def _group(
    keys: str,
    area: str,
    disposition: DADisposition,
    reason: str,
    owners: tuple[str, ...],
    *,
    required: bool = True,
    feature: DAFeature | None = None,
    kind: str = "fixed",
    replacements: tuple[str, ...] = (),
) -> tuple[DACheckpoint, ...]:
    return tuple(
        DACheckpoint(
            key, area, disposition, reason, owners,
            required, feature, kind, replacements,
        )
        for key in keys.split()
    )


DA_CATALOG: tuple[DACheckpoint, ...] = (
    *_group(
        "PRE-001 PRE-002 PRE-004 PRE-005 PRE-006", "Prerequisites",
        DADisposition.REVIEW,
        "Tenant inventory and legacy audience sizing do not establish the "
        "selected DA population's licensing and environment billing coverage.",
        _M365 + _PP,
    ),
    *_group(
        "PRE-003", "Prerequisites", DADisposition.REVIEW,
        "Validate licensing against the intended Teams deployment audience.",
        _M365, feature=DAFeature.TEAMS,
    ),
    *_group(
        "PRE-008 PRE-009 AUTH-001 AUTH-002 AUTH-004", "Identity",
        DADisposition.OBSERVATION,
        "Role, organization, policy and user inventory are observations, not "
        "operator authorization, effective policy or synchronization proof.",
        _ENTRA, required=False,
    ),
    *_group(
        "AUTH-005 AUTH-006", "Workday identity", DADisposition.REVIEW,
        "Reconcile selected-app assignment and cross-system identity evidence "
        "with the Workday-specific checks; do not count aliases as independent proof.",
        _ENTRA + _WORKDAY, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "POL-FB-001 POL-FB-002", "Feedback policies", DADisposition.MANUAL,
        "Feedback and attachment policy require administrator verification and "
        "the organization's privacy decision; they are not universal launch gates.",
        _M365, required=False,
    ),
    *_group(
        "ENV-001 ENV-002", "Environment", DADisposition.REVIEW,
        "Environment identity and backend provisioning must be evaluated for "
        "the selected native target, not inferred from a legacy bot lookup.",
        _PP,
    ),
    *_group(
        "ENV-003 ENV-008", "Environment", DADisposition.OBSERVATION,
        "Environment type and policy presence do not prove effective connector policy.",
        _PP, required=False,
    ),
    *_group(
        "ENV-004", "Connections", DADisposition.EVALUATOR,
        "Evaluate active-topic and invoked-flow dependencies; partial discovery "
        "must remain unresolved even when every discovered reference is bound.",
        _PP,
    ),
    *_group(
        "ENV-004-GRS", "Release identity", DADisposition.EVALUATOR,
        "Compare the selected agent with an explicitly required release pin.",
        _MAKER, feature=DAFeature.REVISION_PIN,
    ),
    *_group(
        "ENV-004-COVERAGE", "Connections", DADisposition.DIAGNOSTIC,
        "Conditional detail of incomplete ENV-004 evidence, not another "
        "independent requirement and not a row required in healthy runs.",
        _PP, required=False,
    ),
    *_group(
        "ENV-004-WD", "Connections", DADisposition.SUPERSEDED,
        "Current dependency gaps are reported by the target-scoped connection audit.",
        _PP, required=False, replacements=("ENV-004", "ENV-004-COVERAGE"),
    ),
    *_group(
        "ENV-009", "Dataverse customization", DADisposition.REVIEW,
        "Preferred unmanaged solutions concern explicit Dataverse customization, "
        "not native DA authoring or mere runtime-package presence.",
        _PP, feature=DAFeature.DATAVERSE_CUSTOMIZATION,
    ),
    *_group(
        "ENV-CAPACITY-001", "Capacity", DADisposition.REVIEW,
        "An allocation observation must be reconciled with applicable billing "
        "and deployment population; zero allocation alone does not establish failure.",
        _PP,
    ),
    *_group(
        "EXT-001", "Integration discovery", DADisposition.DIAGNOSTIC,
        "An inventory error is execution evidence, not an integration requirement.",
        _PP, required=False,
    ),
    *_group(
        "WD-001", "Workday discovery", DADisposition.OBSERVATION,
        "Flow-name discovery is not selected-agent Workday readiness.",
        _PP, required=False, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "SN-001", "ServiceNow discovery", DADisposition.OBSERVATION,
        "Flow-name discovery is not native ServiceNow integration readiness.",
        _PP, required=False, feature=DAFeature.SERVICENOW,
    ),
    *_group(
        "SAP-001", "SAP SuccessFactors discovery", DADisposition.OBSERVATION,
        "SAP-named flow discovery does not validate native SAP OData or "
        "SuccessFactors execution.",
        (Role.SAP_ADMIN.value,), required=False,
        feature=DAFeature.SAP_SUCCESSFACTORS,
    ),
    *_group(
        "EXT-002 EXT-002-ACL", "Graph connector knowledge", DADisposition.REVIEW,
        "Legacy PVA discovery and schema operations do not establish native "
        "DA indexing, crawl or item-access readiness.",
        _M365, feature=DAFeature.GRAPH_CONNECTOR,
    ),
    *_group(
        "INFRA-001", "Network", DADisposition.OBSERVATION,
        "Maker-machine reachability is not employee-network or managed-runtime egress proof.",
        _PP, required=False,
    ),
    *_group(
        "INFRA-003", "Network", DADisposition.MANUAL,
        "Normal DA validation stays read-only; managed-runtime reachability "
        "requires accepted runtime evidence or a separately authorized probe.",
        _PP, feature=DAFeature.EXTERNAL_ENDPOINTS,
    ),
    *_group(
        "INFRA-006", "DLP", DADisposition.REVIEW,
        "Resolve the selected DA's direct and flow connectors before evaluating "
        "effective policies; legacy Dataverse discovery is insufficient.",
        _PP, feature=DAFeature.CONNECTORS,
    ),
    *_group(
        "LIC-FLOW-001 LIC-FLOW-002", "Flow licensing", DADisposition.REVIEW,
        "Use exact invoked flows and native deployment audience rather than "
        "all local agents or Dataverse bot-sharing identity.",
        _M365 + _PP, feature=DAFeature.POWER_AUTOMATE,
    ),
    *_group(
        "LOCAL-001", "Local files", DADisposition.DIAGNOSTIC,
        "Missing-workspace guard; healthy extracted workspaces do not emit this row.",
        _MAKER, required=False,
    ),
    *_group(
        "CONFIG-007", "Local files", DADisposition.EVALUATOR,
        "Validate the selected agent's authored identity and instructions; "
        "presence and word count do not establish response quality.",
        _MAKER,
    ),
    *_group(
        "CONFIG-005 TOPIC-011 CONFIG-012 CONFIG-014", "Local files",
        DADisposition.OBSERVATION,
        "Starter, topic and variable inventory and description heuristics are "
        "authoring observations, not functional validation.",
        _MAKER, required=False,
    ),
    *_group(
        "TOPIC-001 TOPIC-002 TOPIC-004 TOPIC-005 TOPIC-009 TOPIC-010",
        "Local topics", DADisposition.REVIEW,
        "Legacy filename expectations need the selected DA package's reviewed "
        "topic contract; neither a name match nor its absence proves behavior.",
        _MAKER, required=False,
    ),
    *_group(
        "CONFIG-013", "Knowledge", DADisposition.REVIEW,
        "No local knowledge directory is not verified native absence; live "
        "indexing requires a validated native source and runtime contract.",
        _MAKER + _M365, feature=DAFeature.KNOWLEDGE,
    ),
    *_group(
        "DA-AGENT-001 DA-CONTENT-001", "Native agent", DADisposition.EVALUATOR,
        "Observe exact authoring access and authored component availability; "
        "neither establishes publication or signed-in employee execution.",
        _MAKER,
    ),
    *_group(
        "DA-RUNTIME-001", "Employee runtime", DADisposition.REVIEW,
        "Require fresh target-bound signed-in employee evidence for the intended "
        "published channel; authored content and evaluation checklists are not substitutes.",
        _MAKER + _M365,
    ),
    *_group(
        "DA-CONN-001", "Native connections", DADisposition.REVIEW,
        "Require exact bindings for deployment evidence; Connected candidates "
        "without an exposed mapping must not satisfy exact-binding readiness.",
        _PP + _MAKER, feature=DAFeature.NATIVE_CONNECTIONS,
    ),
    *_group(
        "QA-001 QA-002 QA-012 PUB-003 PUB-006", "Publishing",
        DADisposition.MANUAL,
        "Evaluation, UAT and approval require structured target-bound evidence, "
        "not automatic acceptance of a displayed manual checklist.",
        _MAKER + _M365,
    ),
    *_group(
        "PUB-001", "Publishing", DADisposition.EVALUATOR,
        "Verify the selected agent's ALM export artifact; an API error is not "
        "proof that export or deployment is ready.",
        _MAKER,
    ),
    *_group(
        "PUB-002", "ALM promotion", DADisposition.MANUAL,
        "A read-only full run cannot perform import. Promotion evidence comes "
        "from a separately authorized test or attestation.",
        _MAKER + _PP, feature=DAFeature.ALM_PROMOTION,
    ),
    *_group(
        "PUB-011", "Publishing", DADisposition.OBSERVATION,
        "A rollout-duration notice is not successful employee channel availability.",
        _M365, required=False,
    ),
    *_group(
        "SN-CONN-001 SN-FLOW-000 SN-RUN-001 SN-LOCAL-001 SN-LOCAL-002 SN-LOCAL-003",
        "ServiceNow", DADisposition.REVIEW,
        "Flow-name discovery, uncorrelated run history and legacy topic "
        "heuristics need selected native DA topology and runtime evidence.",
        _SN + _PP, feature=DAFeature.SERVICENOW,
    ),
    *_group(
        "DA-SN-RUNTIME-001", "ServiceNow runtime", DADisposition.REVIEW,
        "Native connection metadata does not establish selected-agent ServiceNow "
        "employee execution; a DA runtime evidence contract is required.",
        _SN + _MAKER, feature=DAFeature.SERVICENOW,
    ),
    *_group(
        "DA-SAP-RUNTIME-001", "SAP SuccessFactors runtime", DADisposition.REVIEW,
        "SAP-named flow discovery and Connected SAP OData bindings do not "
        "establish selected-agent SuccessFactors employee execution.",
        (Role.SAP_ADMIN.value, Role.ESS_MAKER.value),
        feature=DAFeature.SAP_SUCCESSFACTORS,
    ),
    *_group(
        "ESS-SOLN-001", "ESS package", DADisposition.EVALUATOR,
        "Validate the selected native agent's package identity independently of "
        "environment-wide Dataverse solution inventory.",
        _MAKER,
    ),
    *_group(
        "WD-ENTRA-SCOPE-001 WD-ENTRA-CONSENT-001 WD-ASSIGN-001 WD-ENTRA-NAMEID-001",
        "Workday Entra", DADisposition.EVALUATOR,
        "Existing selected-app configuration checks remain independent of "
        "Workday profile membership and are not employee-runtime proof.",
        _ENTRA, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-ENTRA-SIGNOPT-001 WD-CONN-010 WD-CONN-102",
        "Workday federation", DADisposition.MANUAL,
        "Portal-only settings and cross-system federation/certificate "
        "comparisons need administrator evidence in addition to observable metadata.",
        _ENTRA + _WORKDAY, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-CONN-001 WD-CONN-013 WD-CONN-101 WD-RUN-001", "Workday",
        DADisposition.REVIEW,
        "Environment-wide connections, legacy topic identity and shared run "
        "history must be adapted to exact DA bindings and correlated employee evidence.",
        _PP + _WORKDAY, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-PKG-001", "Workday package", DADisposition.SUPERSEDED,
        "The DA package and binding contracts own deployment evidence; the "
        "shared install fingerprint may still hydrate evaluator state.",
        _PP, required=False,
        replacements=("WD-DA-PKG-001", "WD-CONN-012"),
    ),
    *_group(
        "WD-CONN-012", "Workday bindings", DADisposition.EVALUATOR,
        "Validate required Workday package references and active bindings.",
        _PP, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-REF-001 WD-WF-CAT-001", "Workday customization", DADisposition.REVIEW,
        "Adapt legacy template/scenario inventory to the selected DA's "
        "explicitly enabled custom scenarios.",
        _MAKER + _WORKDAY, feature=DAFeature.WORKDAY_CUSTOMIZATIONS,
    ),
    *_group(
        "WD-WF-CAT-LINK", "Workday customization", DADisposition.SUPERSEDED,
        "The cross-link trailer is not a second scenario requirement.",
        _MAKER, required=False, replacements=("WD-WF-CAT-001",),
    ),
    *_group(
        "WD-SEC-003", "Workday writes", DADisposition.MANUAL,
        "Employee-authenticated write scenarios require appropriate permission "
        "evidence without invoking legacy ISU probes or updating employee data.",
        _WORKDAY, feature=DAFeature.WORKDAY_WRITES,
    ),
    *_group(
        "WD-DA-PKG-001 WD-DA-FLOW-001 WD-DA-AUTH-001 WD-DA-TOPIC-001 WD-DA-WIRING-001",
        "Workday DA", DADisposition.EVALUATOR,
        "Use reviewed HR DA package, flow, authorization, activation and "
        "initialization contracts; static correctness is not employee execution.",
        _MAKER + _PP, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-DA-ATTACH-001 WD-CONN-AUTH-001", "Workday DA",
        DADisposition.MANUAL,
        "Maker UI attachment, parameter sharing and connection authentication "
        "need evidence where no validated read-only API proves the setting.",
        _MAKER + _PP, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "DV-CONN-001 WD-REST-002", "Workday runtime", DADisposition.EVALUATOR,
        "Observe runtime Dataverse binding and the selected agent's REST "
        "redirect; retain owner/access and extraction-freshness limitations.",
        _PP + _MAKER, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-REST-001", "Workday runtime", DADisposition.REVIEW,
        "A trimmed /api suffix alone does not validate the host, tenant or "
        "signed-in employee REST execution.",
        _MAKER + _WORKDAY, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-NET-001", "Workday network", DADisposition.MANUAL,
        "An allowlist attestation is separate from actual managed-runtime reachability.",
        _PP + _WORKDAY, required=False, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "WD-API-CLIENT-001 WD-TENANT-001", "Workday administrator",
        DADisposition.MANUAL,
        "Workday client registration and employee authentication policy "
        "require structured administrator evidence.",
        _WORKDAY, feature=DAFeature.WORKDAY,
    ),
    *_group(
        "LOCAL-TC-001 SN-CFG-001 SN-CFG-010 SN-CFG-020 "
        "WD-ENV-001 WD-ENV-002 WD-ENV-003 WD-ENV-101 WD-WF-000 "
        "WD-WF-001 WD-WF-002 WD-WF-003 WD-WF-004 WD-WF-005 WD-WF-006 "
        "WD-WF-007 WD-WF-008 WD-WF-009 WD-WF-010 WD-WF-011 WD-WF-012 "
        "WD-WF-013 WD-WF-014 WD-WF-015 WD-WF-016 WD-WF-017",
        "Legacy artifacts and ISU", DADisposition.LEGACY,
        "Legacy templates, ISU variables and SOAP probes are not native "
        "employee-authenticated DA requirements.",
        _MAKER, required=False,
    ),
    *_group(
        "DA-CONN-002+", "Native connections", DADisposition.REVIEW,
        "Dynamic connection details must retain exact resource identity and "
        "must not treat an unverified Connected candidate as a proven binding.",
        _PP, feature=DAFeature.NATIVE_CONNECTIONS, kind="family",
    ),
    *_group(
        "ENV-004-UR-*", "Connections", DADisposition.DIAGNOSTIC,
        "Unbound-reference details appear only when dependencies are unbound.",
        _PP, required=False, kind="family",
    ),
    *_group(
        "EXT-002-NNN", "Graph connector knowledge", DADisposition.REVIEW,
        "Per-source observations require validated native knowledge discovery.",
        _M365, feature=DAFeature.GRAPH_CONNECTOR, kind="family",
    ),
    *_group(
        "TOPIC-020-NNN", "Handoff", DADisposition.REVIEW,
        "Validate native active handoff targets rather than legacy PVA-only discovery.",
        _MAKER, feature=DAFeature.HANDOFF, kind="family",
    ),
    *_group(
        "TOPIC-TRIGGER-NNN TOPIC-INTEGRATION-NNN", "Custom topics",
        DADisposition.REVIEW,
        "Custom-topic baseline and placeholder checks need selected-agent "
        "DA applicability; they do not validate all shipped topics.",
        _MAKER, feature=DAFeature.CUSTOM_TOPICS, kind="family",
    ),
    *_group(
        "WD-CONN-002+ WD-FLOW-NNN", "Workday", DADisposition.REVIEW,
        "Replace environment-wide numeric details with exact DA dependencies "
        "without collisions with dedicated checkpoint IDs.",
        _PP, feature=DAFeature.WORKDAY, kind="family",
    ),
    *_group(
        "SN-CONN-002+ SN-FLOW-NNN", "ServiceNow", DADisposition.REVIEW,
        "Resolve only the selected DA's required connections and flows.",
        _PP + _SN, feature=DAFeature.SERVICENOW, kind="family",
    ),
    *_group(
        "CHECKPOINT-CONTRACT-MISSING CHECKPOINT-CONTRACT-UNRESOLVED "
        "CHECKPOINT-CONTRACT-GUIDED PROFILE-CHECKPOINT-MISSING "
        "PROFILE-CHECKPOINT-UNRESOLVED PROFILE-CHECKPOINT-GUIDED "
        "CHECKPOINT-CLIENT-* PROFILE-CLIENT-* PROFILE-FAMILY-* EXEC-NNN-CATEGORY-ERR",
        "Execution contract", DADisposition.ENGINE,
        "Execution guards describe missing, unresolved or guided evidence; "
        "they are not additional deployment requirements.",
        _MAKER, required=False, kind="guard",
    ),
)


def validate_da_catalog(catalog: Sequence[DACheckpoint] = DA_CATALOG) -> None:
    by_key: dict[str, DACheckpoint] = {}
    excluded = {
        DADisposition.DIAGNOSTIC, DADisposition.SUPERSEDED,
        DADisposition.LEGACY, DADisposition.ENGINE,
    }
    for spec in catalog:
        if not spec.key or spec.key in by_key:
            raise ValueError(f"Empty or duplicate DA checkpoint key: {spec.key!r}.")
        if (
            not isinstance(spec.disposition, DADisposition)
            or (spec.feature is not None and not isinstance(spec.feature, DAFeature))
            or spec.kind not in {"fixed", "family", "guard"}
            or type(spec.required) is not bool
            or not spec.area.strip()
            or not spec.reason.strip()
            or not spec.owners
            or any(owner not in {role.value for role in Role} for owner in spec.owners)
        ):
            raise ValueError(f"Invalid DA checkpoint declaration: {spec.key}.")
        if spec.required and spec.disposition in excluded:
            raise ValueError(f"Excluded DA checkpoint cannot be required: {spec.key}.")
        if (spec.disposition == DADisposition.ENGINE) != (spec.kind == "guard"):
            raise ValueError(f"DA execution guard kind mismatch: {spec.key}.")
        if bool(spec.replacements) != (spec.disposition == DADisposition.SUPERSEDED):
            raise ValueError(f"DA checkpoint replacement mismatch: {spec.key}.")
        by_key[spec.key] = spec

    def visit(key: str, visiting: frozenset[str]) -> None:
        if key in visiting:
            raise ValueError(f"Cyclic DA checkpoint replacement: {key}.")
        spec = by_key.get(key)
        if spec is None:
            raise ValueError(f"Unknown DA checkpoint replacement: {key}.")
        for replacement in spec.replacements:
            visit(replacement, visiting | {key})

    for key in by_key:
        visit(key, frozenset())


def build_da_coverage_plan(
    features: Mapping[DAFeature, DAFeatureEvidence],
    *,
    catalog: Sequence[DACheckpoint] = DA_CATALOG,
) -> tuple[DACoverageEntry, ...]:
    """Account for every definition; unknown applicability never becomes disabled."""
    validate_da_catalog(catalog)
    for feature, evidence in features.items():
        if not isinstance(feature, DAFeature):
            raise ValueError(f"Unknown DA feature: {feature!r}.")
        if not isinstance(evidence, DAFeatureEvidence):
            raise ValueError(f"Invalid evidence for DA feature: {feature.value}.")

    for child, parent in (
        (DAFeature.WORKDAY_CUSTOMIZATIONS, DAFeature.WORKDAY),
        (DAFeature.WORKDAY_WRITES, DAFeature.WORKDAY),
        (DAFeature.GRAPH_CONNECTOR, DAFeature.KNOWLEDGE),
        (DAFeature.NATIVE_CONNECTIONS, DAFeature.CONNECTORS),
    ):
        child_evidence = features.get(child)
        parent_evidence = features.get(parent)
        if (
            child_evidence is not None and child_evidence.enabled is True
            and parent_evidence is not None and parent_evidence.enabled is False
        ):
            raise ValueError(
                f"Conflicting DA feature evidence: {child.value} is enabled "
                f"while {parent.value} is disabled."
            )

    entries = []
    excluded = {
        DADisposition.DIAGNOSTIC, DADisposition.SUPERSEDED,
        DADisposition.LEGACY, DADisposition.ENGINE,
    }
    for spec in catalog:
        source = ""
        if spec.disposition in excluded:
            applicability = DAApplicability.EXCLUDED
            reason = spec.reason
        elif spec.feature is None:
            applicability = DAApplicability.APPLICABLE
            reason = "DA baseline requirement or advisory observation."
        else:
            evidence = features.get(spec.feature)
            if evidence is None or evidence.enabled is None:
                applicability = DAApplicability.UNKNOWN
                source = evidence.source if evidence else ""
                reason = f"Applicability of {spec.feature.value} is not established."
            else:
                source = evidence.source
                applicability = (
                    DAApplicability.APPLICABLE if evidence.enabled
                    else DAApplicability.NOT_APPLICABLE
                )
                reason = (
                    f"Feature {spec.feature.value} is "
                    f"{'enabled' if evidence.enabled else 'disabled'} "
                    "according to the supplied applicability evidence."
                )
        entries.append(DACoverageEntry(spec, applicability, reason, source))
    return tuple(entries)
