"""Reading an exported CA solution package into a DiscoveryResult.

These tests build a *synthetic* exported solution on disk — the same layout
make.powerapps.com produces (``solution.xml`` + ``botcomponents/<name>/{botcomponent.xml,data}``)
— and assert that :mod:`essmig.package_source` reconstructs the identical
classification the live Dataverse path would: edited-OOB vs net-new, owning-pack
provenance, agent metadata, and the ownership drop of publisher-prefixed
(test-harness) components. No Dataverse connection is involved.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from conftest import HR_PREFIX, reference_set
from essmig import package_source
from essmig.ess import CA_AGENT_SCHEMANAMES

HR_OOB = "msdyn_CopilotForEmployeeSelfServiceHR"
SERVICENOW_PACK = "msdyn_EssHRServiceNowHRSD"


def _write_component(
    root: Path,
    folder: str,
    *,
    schemaname: str,
    name: str,
    componenttype: int,
    data: str,
    statecode: int = 0,
    statuscode: int = 1,
) -> None:
    component_dir = root / "botcomponents" / folder
    component_dir.mkdir(parents=True)
    (component_dir / "botcomponent.xml").write_text(
        "<botcomponent "
        f'schemaname="{schemaname}">'
        f"<name>{name}</name>"
        f"<componenttype>{componenttype}</componenttype>"
        f"<statecode>{statecode}</statecode>"
        f"<statuscode>{statuscode}</statuscode>"
        "</botcomponent>",
        encoding="utf-8",
    )
    (component_dir / "data").write_text(data, encoding="utf-8")


def _write_solution(root: Path, *, unique_name: str, in_place_edits: dict[str, str]) -> None:
    deps = "".join(
        "<MissingDependency>"
        f'<Required id.schemaname="{schema}" solution="{pack} (1.2.0.1)" />'
        f'<Dependent id.schemaname="{schema}" />'
        "</MissingDependency>"
        for schema, pack in in_place_edits.items()
    )
    (root / "solution.xml").write_text(
        "<ImportExportXml>"
        "<SolutionManifest>"
        f"<UniqueName>{unique_name}</UniqueName>"
        "</SolutionManifest>"
        f"<MissingDependencies>{deps}</MissingDependencies>"
        "</ImportExportXml>",
        encoding="utf-8",
    )


def _sample_package(root: Path) -> None:
    """An HR export: one edited OOB topic, one net-new topic, a renamed agent, and
    a publisher-prefixed test component that ownership filtering must drop."""
    edited = f"{HR_PREFIX}.topic.ServiceNowHRSDCreateCase"
    _write_solution(
        root,
        unique_name="EmployeeSelfServiceCustomization",
        in_place_edits={edited: SERVICENOW_PACK},
    )
    _write_component(
        root,
        "create-case",
        schemaname=edited,
        name="Create Case",
        componenttype=9,
        data="kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRecognizedIntent\n  edited: true\n",
    )
    _write_component(
        root,
        "request-support",
        schemaname=f"{HR_PREFIX}.topic.RequestSupport",
        name="Request Support",
        componenttype=9,
        data="kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRecognizedIntent\n",
    )
    _write_component(
        root,
        "gpt-default",
        schemaname=f"{HR_PREFIX}.gpt.default",
        name="ESS CR Agent",
        componenttype=15,
        data="kind: GptComponentMetadata\ndisplayName: ESS CR Agent\n",
    )
    # Publisher-GUID-prefixed test harness component: owned by no ESS agent.
    _write_component(
        root,
        "test-case",
        schemaname="mspva_0123456789abcdef.testcase.Smoke",
        name="Smoke test",
        componenttype=19,
        data="kind: TestCase\n",
    )


def _hr_reference():
    baseline_data = (
        "kind: GptComponentMetadata\n"
        "displayName: Employee Self-Service HR (Preview)\n"
    )
    return reference_set(components=[], baseline={"gpt.default": baseline_data})


def test_package_targets_detects_hr(tmp_path: Path) -> None:
    _sample_package(tmp_path)
    assert package_source.package_targets(tmp_path) == ["hr"]


def test_package_targets_reads_zip(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    _sample_package(pkg)
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in pkg.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(pkg).as_posix())
    assert package_source.package_targets(archive) == ["hr"]


def test_discover_classifies_edit_vs_net_new(tmp_path: Path) -> None:
    _sample_package(tmp_path)
    result = package_source.discover_from_package(tmp_path, "hr", _hr_reference())

    assert result.solution_unique_name == "EmployeeSelfServiceCustomization"
    kept = {comp.suffix: comp for comp in result.components.values()}
    assert "topic.ServiceNowHRSDCreateCase" in kept
    assert "topic.RequestSupport" in kept

    edited = kept["topic.ServiceNowHRSDCreateCase"]
    assert not edited.is_net_new
    assert SERVICENOW_PACK in edited.solutions

    new = kept["topic.RequestSupport"]
    assert new.is_net_new


def test_publisher_prefixed_components_are_dropped(tmp_path: Path) -> None:
    _sample_package(tmp_path)
    result = package_source.discover_from_package(tmp_path, "hr", _hr_reference())
    schemas = {comp.schemaname for comp in result.components.values()}
    assert not any(schema.startswith("mspva_") for schema in schemas)
    assert "testcase.Smoke" not in result.components


def test_agent_rename_is_surfaced(tmp_path: Path) -> None:
    _sample_package(tmp_path)
    result = package_source.discover_from_package(tmp_path, "hr", _hr_reference())
    assert result.agent is not None
    assert result.agent.name == "ESS CR Agent"
    assert result.agent.baseline_name == "Employee Self-Service HR (Preview)"
    # The vendored baseline data carries no Overview description column.
    assert result.agent.baseline_description is None


def test_unknown_vertical_rejected(tmp_path: Path) -> None:
    _sample_package(tmp_path)
    with pytest.raises(ValueError):
        package_source.discover_from_package(tmp_path, "nope", _hr_reference())


def test_missing_solution_xml_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "botcomponents").mkdir()
    with pytest.raises(FileNotFoundError):
        package_source.package_targets(tmp_path)


def test_gpt_prefix_present_for_all_known_verticals() -> None:
    # Guards the schema-prefix map package_targets/discover rely on.
    assert set(CA_AGENT_SCHEMANAMES) == {"core", "hr", "it"}
