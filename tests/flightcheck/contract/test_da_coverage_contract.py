# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure coverage-planning contracts; no tenant API or simulated API response."""

from dataclasses import replace
import json

import pytest

from flightcheck.da_contract import (
    DAApplicability,
    DA_CATALOG,
    DACheckpoint,
    DADisposition,
    DAFeature,
    DAFeatureEvidence,
    build_da_coverage_plan,
    validate_da_catalog,
)
from flightcheck.runner import Role


def _by_key(features=None):
    return {
        entry.checkpoint.key: entry
        for entry in build_da_coverage_plan(features or {})
    }


def test_unknown_features_remain_visible_without_hiding_baseline():
    entries = _by_key()

    assert entries["DA-AGENT-001"].applicability == DAApplicability.APPLICABLE
    workday = entries["WD-DA-PKG-001"]
    assert workday.applicability == DAApplicability.UNKNOWN
    assert workday.checkpoint.required is True
    assert "not established" in workday.applicability_reason
    assert workday.evidence_source == ""
    assert entries["DA-CONN-002+"].applicability == DAApplicability.EXCLUDED
    assert entries["DA-RUNTIME-001"].applicability == DAApplicability.APPLICABLE
    assert entries["DA-RUNTIME-001"].checkpoint.disposition == DADisposition.MANUAL
    assert entries["DA-SAP-RUNTIME-001"].applicability == DAApplicability.EXCLUDED


def test_explicitly_disabled_feature_retains_its_exclusion_evidence():
    entry = _by_key({
        DAFeature.WORKDAY: DAFeatureEvidence(False, "selected-agent manifest"),
    })["WD-DA-PKG-001"]

    assert entry.applicability == DAApplicability.NOT_APPLICABLE
    assert entry.evidence_source == "selected-agent manifest"
    assert "disabled" in entry.applicability_reason
    assert entry.checkpoint.key in json.dumps(entry.to_dict())


def test_enabling_workday_does_not_enable_legacy_or_infer_other_integrations():
    entries = _by_key({
        DAFeature.WORKDAY: DAFeatureEvidence(True, "verified selected runtime"),
    })

    assert entries["WD-DA-PKG-001"].applicability == DAApplicability.APPLICABLE
    assert entries["WD-WF-001"].applicability == DAApplicability.EXCLUDED
    assert entries["WD-ENV-001"].applicability == DAApplicability.EXCLUDED
    assert entries["SN-CONN-001"].applicability == DAApplicability.UNKNOWN
    assert entries["WD-SEC-003"].applicability == DAApplicability.UNKNOWN
    assert entries["WD-WF-CAT-001"].applicability == DAApplicability.UNKNOWN


def test_da_review_and_manual_evidence_are_not_promoted_to_executable_passes():
    entries = _by_key({
        DAFeature.WORKDAY: DAFeatureEvidence(True, "selected-agent runtime"),
        DAFeature.NATIVE_CONNECTIONS: DAFeatureEvidence(True, "native references"),
    })

    assert entries["DA-CONN-001"].checkpoint.disposition == DADisposition.EVALUATOR
    assert entries["WD-RUN-001"].checkpoint.disposition == DADisposition.SUPERSEDED
    assert entries["WD-DA-ATTACH-001"].checkpoint.disposition == DADisposition.MANUAL
    assert entries["WD-DA-ATTACH-001"].checkpoint.required is True
    assert entries["QA-001"].checkpoint.required is True
    assert entries["POL-FB-001"].checkpoint.required is False


def test_diagnostics_and_replacements_do_not_require_healthy_runs_to_emit_errors():
    entries = _by_key()

    for key in ("LOCAL-001", "ENV-004-UR-*", "ENV-004-COVERAGE",
                "PROFILE-CHECKPOINT-MISSING"):
        assert entries[key].applicability == DAApplicability.EXCLUDED
        assert entries[key].checkpoint.required is False
    assert entries["ENV-004-WD"].checkpoint.replacements == (
        "ENV-004", "ENV-004-COVERAGE",
    )
    assert entries["WD-WF-CAT-LINK"].checkpoint.replacements == ("WD-WF-CAT-001",)


@pytest.mark.parametrize("enabled", [0, 1, "", "false", [], {}])
def test_invalid_feature_state_is_rejected_instead_of_coerced(enabled):
    with pytest.raises(ValueError, match="boolean or None"):
        DAFeatureEvidence(enabled, "config")


@pytest.mark.parametrize("enabled", [True, False])
def test_known_applicability_requires_provenance(enabled):
    with pytest.raises(ValueError, match="evidence source"):
        DAFeatureEvidence(enabled, "  ")


def test_failed_feature_discovery_keeps_its_reason_and_does_not_hide_requirements():
    entry = _by_key({
        DAFeature.KNOWLEDGE: DAFeatureEvidence(None, "native inventory unreadable"),
    })["CONFIG-013"]

    assert entry.applicability == DAApplicability.UNKNOWN
    assert entry.evidence_source == "native inventory unreadable"
    assert entry.checkpoint.required is True


def test_invalid_feature_names_and_unstructured_evidence_fail_explicitly():
    with pytest.raises(ValueError, match="Unknown DA feature"):
        build_da_coverage_plan({"unknown": DAFeatureEvidence(False, "config")})
    with pytest.raises(ValueError, match="Invalid evidence"):
        build_da_coverage_plan({DAFeature.WORKDAY: False})


@pytest.mark.parametrize("child,parent", [
    (DAFeature.WORKDAY_CUSTOMIZATIONS, DAFeature.WORKDAY),
    (DAFeature.WORKDAY_WRITES, DAFeature.WORKDAY),
    (DAFeature.GRAPH_CONNECTOR, DAFeature.KNOWLEDGE),
    (DAFeature.NATIVE_CONNECTIONS, DAFeature.CONNECTORS),
])
def test_conflicting_feature_evidence_does_not_exclude_an_enabled_dependency(child, parent):
    with pytest.raises(ValueError, match="Conflicting DA feature evidence"):
        build_da_coverage_plan({
            child: DAFeatureEvidence(True, "native inventory"),
            parent: DAFeatureEvidence(False, "configuration"),
        })


def _spec(key="TEST-001", **overrides):
    return DACheckpoint(
        key=key,
        area="Test",
        disposition=DADisposition.EVALUATOR,
        reason="Test configuration concern.",
        owners=(Role.ESS_MAKER.value,),
        **overrides,
    )


def test_duplicate_declarations_and_required_exclusions_are_rejected():
    spec = _spec()
    with pytest.raises(ValueError, match="duplicate"):
        validate_da_catalog((spec, spec))
    with pytest.raises(ValueError, match="cannot be required"):
        validate_da_catalog((replace(spec, disposition=DADisposition.LEGACY),))


def test_replacement_graph_rejects_dangling_and_cyclic_aliases():
    old = replace(
        _spec(),
        disposition=DADisposition.SUPERSEDED,
        required=False,
        replacements=("TEST-002",),
    )
    with pytest.raises(ValueError, match="Unknown DA checkpoint replacement"):
        validate_da_catalog((old,))
    other = replace(old, key="TEST-002", replacements=("TEST-001",))
    with pytest.raises(ValueError, match="Cyclic DA checkpoint replacement"):
        validate_da_catalog((old, other))


def test_serialized_plan_preserves_manual_unknown_and_dynamic_metadata():
    entries = build_da_coverage_plan({})
    payload = json.loads(json.dumps([entry.to_dict() for entry in entries]))
    rows = {row["checkpointId"]: row for row in payload}

    assert rows["WD-DA-ATTACH-001"]["disposition"] == "manual"
    assert rows["WD-DA-ATTACH-001"]["applicability"] == "unknown"
    assert rows["DA-CONN-002+"]["kind"] == "family"
    assert rows["DA-CONN-002+"]["roles"] == [Role.POWER_PLATFORM_ADMIN.value]
    assert len(rows) == len(DA_CATALOG)
