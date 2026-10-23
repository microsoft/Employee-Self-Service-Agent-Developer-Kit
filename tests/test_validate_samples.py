# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Tests for tools.validate_samples.

Each test builds a minimal repo tree in tmp_path and a corresponding
ChangedFile list, runs all checks, and asserts on the status of named checks.
"""

from __future__ import annotations

import sys
import textwrap
import subprocess
from pathlib import Path

import pytest

# Make repo-root tools/ package importable for tests without altering pyproject.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.validate_samples.checks import (  # noqa: E402
    ChangedFile,
    Status,
    run_all_checks,
)
from tools.validate_samples.cli import (  # noqa: E402
    _git_changed,
    _preserved_workday_migration,
    _retired_workday_areas,
)

VALID_TOPIC_YAML = textwrap.dedent(
    """\
    kind: AdaptiveDialog
    modelDisplayName: Sample
    modelDescription: Sample.
    beginDialog:
      kind: OnRecognizedIntent
      actions:
        - kind: SendActivity
          id: send_hi
          activity: hi
    """
)

VALID_XML = '<?xml version="1.0"?><TemplateConfiguration><Name>X</Name></TemplateConfiguration>'

VALID_README = "# Topic\n\nDescription.\n"


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _new_topic(repo: Path, topic_dir: str) -> list[ChangedFile]:
    _write(repo, f"{topic_dir}/topic.yaml", VALID_TOPIC_YAML)
    _write(repo, f"{topic_dir}/msdyn_Sample.xml", VALID_XML)
    _write(repo, f"{topic_dir}/README.md", VALID_README)
    return [
        ChangedFile(f"{topic_dir}/topic.yaml", "A"),
        ChangedFile(f"{topic_dir}/msdyn_Sample.xml", "A"),
        ChangedFile(f"{topic_dir}/README.md", "A"),
    ]


def _by_name(results) -> dict[str, "object"]:
    return {r.name: r for r in results}


def test_new_topic_valid_all_pass(tmp_path: Path) -> None:
    changed = _new_topic(tmp_path, "samples/Facilities/EmployeeGetThing")
    results = run_all_checks(tmp_path, changed, whitelist={})
    by = _by_name(results)
    assert by["YAML parse"].status is Status.PASS
    assert by["AdaptiveDialog kind"].status is Status.PASS
    assert by["XML parse"].status is Status.PASS
    assert by["Filename convention (new)"].status is Status.PASS
    assert by["Folder convention (new, incl. README.md)"].status is Status.PASS
    assert by["Diff scope (samples/ only)"].status is Status.PASS
    assert by["Secrets / internal URLs"].status is Status.PASS


def test_update_existing_topic_neighbor_checks_na(tmp_path: Path) -> None:
    # Pre-existing topic; only a modification touch.
    rel = "samples/Facilities/EmployeeGetThing/topic.yaml"
    _write(tmp_path, rel, VALID_TOPIC_YAML)
    changed = [ChangedFile(rel, "M")]
    results = run_all_checks(tmp_path, changed, whitelist={})
    by = _by_name(results)
    assert by["YAML parse"].status is Status.PASS
    assert by["AdaptiveDialog kind"].status is Status.PASS
    assert by["XML parse"].status is Status.NA
    assert by["Filename convention (new)"].status is Status.NA
    assert by["Folder convention (new, incl. README.md)"].status is Status.NA
    assert by["Diff scope (samples/ only)"].status is Status.PASS


def test_invalid_yaml_fails(tmp_path: Path) -> None:
    rel = "samples/Facilities/Foo/topic.yaml"
    _write(tmp_path, rel, "kind: AdaptiveDialog\n  bad: : :\n")
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["YAML parse"].status is Status.FAIL


def test_missing_adaptive_dialog_kind_fails(tmp_path: Path) -> None:
    rel = "samples/Facilities/Foo/topic.yaml"
    _write(tmp_path, rel, "kind: SomethingElse\nbeginDialog: {}\n")
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    by = _by_name(results)
    assert by["YAML parse"].status is Status.PASS
    assert by["AdaptiveDialog kind"].status is Status.FAIL


def test_invalid_xml_fails(tmp_path: Path) -> None:
    rel = "samples/Facilities/Foo/msdyn_Foo.xml"
    _write(tmp_path, rel, "<TemplateConfiguration><Unclosed>")
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["XML parse"].status is Status.FAIL


def test_bad_xml_filename_for_new_file_fails(tmp_path: Path) -> None:
    rel = "samples/Facilities/Foo/getThing.xml"
    _write(tmp_path, rel, VALID_XML)
    results = run_all_checks(tmp_path, [ChangedFile(rel, "A")], whitelist={})
    assert _by_name(results)["Filename convention (new)"].status is Status.FAIL


def test_bad_folder_name_for_new_topic_fails(tmp_path: Path) -> None:
    topic = "samples/Facilities/employee_get_thing"
    _write(tmp_path, f"{topic}/topic.yaml", VALID_TOPIC_YAML)
    _write(tmp_path, f"{topic}/msdyn_Sample.xml", VALID_XML)
    _write(tmp_path, f"{topic}/README.md", VALID_README)
    changed = [
        ChangedFile(f"{topic}/topic.yaml", "A"),
        ChangedFile(f"{topic}/msdyn_Sample.xml", "A"),
        ChangedFile(f"{topic}/README.md", "A"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    folder = _by_name(results)["Folder convention (new, incl. README.md)"]
    assert folder.status is Status.FAIL
    assert any("PascalCase" in d for d in folder.details)


def test_new_topic_missing_readme_fails(tmp_path: Path) -> None:
    topic = "samples/Facilities/EmployeeGetThing"
    _write(tmp_path, f"{topic}/topic.yaml", VALID_TOPIC_YAML)
    _write(tmp_path, f"{topic}/msdyn_Sample.xml", VALID_XML)
    changed = [
        ChangedFile(f"{topic}/topic.yaml", "A"),
        ChangedFile(f"{topic}/msdyn_Sample.xml", "A"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    folder = _by_name(results)["Folder convention (new, incl. README.md)"]
    assert folder.status is Status.FAIL
    assert any("README.md" in d for d in folder.details)


def test_out_of_scope_edit_fails(tmp_path: Path) -> None:
    _write(tmp_path, "solutions/foo.txt", "x")
    _write(tmp_path, "samples/Facilities/Foo/topic.yaml", VALID_TOPIC_YAML)
    changed = [
        ChangedFile("samples/Facilities/Foo/topic.yaml", "M"),
        ChangedFile("solutions/foo.txt", "M"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    diff = _by_name(results)["Diff scope (samples/ only)"]
    assert diff.status is Status.FAIL
    assert any("outside samples/" in d for d in diff.details)


def test_diff_touching_multiple_topic_folders_fails(tmp_path: Path) -> None:
    for t in ("samples/Facilities/Foo/topic.yaml", "samples/Facilities/Bar/topic.yaml"):
        _write(tmp_path, t, VALID_TOPIC_YAML)
    changed = [
        ChangedFile("samples/Facilities/Foo/topic.yaml", "M"),
        ChangedFile("samples/Facilities/Bar/topic.yaml", "M"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.FAIL


def test_secret_leak_detected(tmp_path: Path) -> None:
    rel = "samples/Facilities/Foo/msdyn_Foo.xml"
    _write(tmp_path, rel, '<?xml version="1.0"?><Cfg token="AKIA0123456789ABCDEF"/>')
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["Secrets / internal URLs"].status is Status.FAIL


def test_internal_url_detected(tmp_path: Path) -> None:
    rel = "samples/Facilities/Foo/topic.yaml"
    _write(
        tmp_path,
        rel,
        VALID_TOPIC_YAML + '\n# see https://host.corp.microsoft.com/x\n',
    )
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["Secrets / internal URLs"].status is Status.FAIL


def test_workday_subgroup_topic_folder_resolves(tmp_path: Path) -> None:
    rel = "samples/Workday/Employee/EmployeeGetX/topic.yaml"
    _write(tmp_path, rel, VALID_TOPIC_YAML)
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_workday_subgroup_readme_not_treated_as_topic(tmp_path: Path) -> None:
    # A subgroup-level README plus a real topic edit must not be flagged as
    # touching multiple topic folders.
    sub_readme = "samples/Workday/Employee/README.md"
    topic_yaml = "samples/Workday/Employee/EmployeeGetX/topic.yaml"
    _write(tmp_path, sub_readme, VALID_README)
    _write(tmp_path, topic_yaml, VALID_TOPIC_YAML)
    changed = [
        ChangedFile(sub_readme, "M"),
        ChangedFile(topic_yaml, "M"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_area_level_readme_alongside_topic_edit_not_multi_topic(tmp_path: Path) -> None:
    # An area-level README (samples/<Area>/README.md) is explicitly allowed
    # alongside a topic edit and must not be misidentified as its own topic.
    area_readme = "samples/Facilities/README.md"
    topic_yaml = "samples/Facilities/EmployeeGetThing/topic.yaml"
    _write(tmp_path, area_readme, VALID_README)
    _write(tmp_path, topic_yaml, VALID_TOPIC_YAML)
    changed = [
        ChangedFile(area_readme, "M"),
        ChangedFile(topic_yaml, "M"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_whitelisted_filename_inconsistency_not_flagged(tmp_path: Path) -> None:
    # Lowercase msdyn_copilotforemployeeselfservice* prefix is whitelisted.
    rel = "samples/Facilities/Foo/msdyn_copilotforemployeeselfserviceFoo.xml"
    _write(tmp_path, rel, VALID_XML)
    whitelist = {
        "filename_exemption_substrings": ["msdyn_copilotforemployeeselfservice"],
    }
    results = run_all_checks(tmp_path, [ChangedFile(rel, "A")], whitelist=whitelist)
    assert _by_name(results)["Filename convention (new)"].status is Status.PASS


def test_whitelisted_folder_inconsistency_not_flagged(tmp_path: Path) -> None:
    topic = "samples/Facilities/legacy-topic"
    _write(tmp_path, f"{topic}/topic.yaml", VALID_TOPIC_YAML)
    _write(tmp_path, f"{topic}/msdyn_X.xml", VALID_XML)
    _write(tmp_path, f"{topic}/README.md", VALID_README)
    changed = [
        ChangedFile(f"{topic}/topic.yaml", "A"),
        ChangedFile(f"{topic}/msdyn_X.xml", "A"),
        ChangedFile(f"{topic}/README.md", "A"),
    ]
    whitelist = {"folder_exemptions": [topic]}
    results = run_all_checks(tmp_path, changed, whitelist=whitelist)
    assert _by_name(results)["Folder convention (new, incl. README.md)"].status is Status.PASS


def test_area_level_readme_edit_passes_diff_scope(tmp_path: Path) -> None:
    rel = "samples/Facilities/README.md"
    _write(tmp_path, rel, "# Facilities\n")
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_add_readme_to_existing_topic_not_treated_as_new(tmp_path: Path) -> None:
    # Backfilling a missing README.md into an existing (non-PascalCase) topic
    # must not trigger "new topic" folder convention checks.
    topic = "samples/Facilities/legacyfolder"
    _write(tmp_path, f"{topic}/topic.yaml", VALID_TOPIC_YAML)
    _write(tmp_path, f"{topic}/msdyn_X.xml", VALID_XML)
    _write(tmp_path, f"{topic}/README.md", VALID_README)
    changed = [ChangedFile(f"{topic}/README.md", "A")]
    results = run_all_checks(tmp_path, changed, whitelist={})
    assert _by_name(results)["Folder convention (new, incl. README.md)"].status is Status.NA


def test_servicenow_subgroup_topic_folder_resolves(tmp_path: Path) -> None:
    # ServiceNow uses a sub-grouping folder (Employee/) above the topic folder,
    # like Workday. A topic.yaml at samples/ServiceNow/Employee/TopicX/ must map
    # to that 4-part topic folder, not to samples/ServiceNow/Employee/.
    rel = "samples/ServiceNow/Employee/EmployeeGetHRCaseStatus/topic.yaml"
    _write(tmp_path, rel, VALID_TOPIC_YAML)
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_servicenow_subgroup_readme_not_treated_as_topic(tmp_path: Path) -> None:
    # A ServiceNow sub-group README plus a real topic edit must not be flagged
    # as touching multiple topic folders.
    sub_readme = "samples/ServiceNow/Employee/README.md"
    topic_yaml = "samples/ServiceNow/Employee/EmployeeGetHRCaseStatus/topic.yaml"
    _write(tmp_path, sub_readme, VALID_README)
    _write(tmp_path, topic_yaml, VALID_TOPIC_YAML)
    changed = [
        ChangedFile(sub_readme, "M"),
        ChangedFile(topic_yaml, "M"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_new_servicenow_topic_with_json_connector_passes(tmp_path: Path) -> None:
    # ServiceNow connector configs are JSON, not XML. A new topic with a
    # .json connector file must pass the Folder convention check.
    topic = "samples/ServiceNow/Employee/EmployeeGetHRCaseStatus"
    _write(tmp_path, f"{topic}/topic.yaml", VALID_TOPIC_YAML)
    _write(tmp_path, f"{topic}/msdyn_HRServiceNowHRSDGetHRCaseStatus.json", '{"Scenario": "x"}')
    _write(tmp_path, f"{topic}/README.md", VALID_README)
    changed = [
        ChangedFile(f"{topic}/topic.yaml", "A"),
        ChangedFile(f"{topic}/msdyn_HRServiceNowHRSDGetHRCaseStatus.json", "A"),
        ChangedFile(f"{topic}/README.md", "A"),
    ]
    results = run_all_checks(tmp_path, changed, whitelist={})
    by = _by_name(results)
    assert by["Folder convention (new, incl. README.md)"].status is Status.PASS
    assert by["Filename convention (new)"].status is Status.PASS
    assert by["Diff scope (samples/ only)"].status is Status.PASS


def test_new_json_connector_bad_filename_fails(tmp_path: Path) -> None:
    # A new JSON connector config must also start with 'msdyn_'.
    rel = "samples/ServiceNow/Employee/EmployeeGetHRCaseStatus/getCase.json"
    _write(tmp_path, rel, '{"Scenario": "x"}')
    results = run_all_checks(tmp_path, [ChangedFile(rel, "A")], whitelist={})
    assert _by_name(results)["Filename convention (new)"].status is Status.FAIL


GA_ROOT = "samples/Workday"
PREVIEW_ROOT = "samples/WorkdayDeclarativeAgentPreview"
SHARED_CONFIG = f"{GA_ROOT}/WorkdayOSSTemplateConfigurationSetup.yaml"
VALID_SHARED_CONFIG = "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRedirect\n  actions: []\n"


def _new_ga_topic(repo: Path, name: str = "EmployeeGetThing") -> list[ChangedFile]:
    topic = f"{GA_ROOT}/Employee/{name}"
    _write(repo, f"{topic}/topic.yaml", VALID_TOPIC_YAML)
    _write(repo, f"{topic}/README.md", VALID_README)
    _write(repo, SHARED_CONFIG, VALID_SHARED_CONFIG)
    return [
        ChangedFile(f"{topic}/topic.yaml", "A"),
        ChangedFile(f"{topic}/README.md", "A"),
        ChangedFile(SHARED_CONFIG, "A"),
    ]


@pytest.mark.parametrize("area", ["Workday", "WorkdayDeclarativeAgentPreview"])
def test_new_workday_areas_resolve_real_topic_not_subgroup(tmp_path: Path, area: str) -> None:
    subgroup = f"samples/{area}/Employee/README.md"
    topic = f"samples/{area}/Employee/EmployeeGetThing/topic.yaml"
    _write(tmp_path, subgroup, VALID_README)
    _write(tmp_path, topic, VALID_TOPIC_YAML)
    results = run_all_checks(tmp_path, [
        ChangedFile(subgroup, "M"), ChangedFile(topic, "M"),
    ])
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_ga_topic_uses_shared_config_instead_of_per_topic_xml(tmp_path: Path) -> None:
    results = run_all_checks(tmp_path, _new_ga_topic(tmp_path))
    assert all(result.status is not Status.FAIL for result in results)


@pytest.mark.parametrize("config", [None, "kind: Record\n", "kind: AdaptiveDialog\nbeginDialog: {}\n"])
def test_ga_topic_missing_or_invalid_shared_config_fails(tmp_path: Path, config: str | None) -> None:
    changed = _new_ga_topic(tmp_path)
    if config is None:
        (tmp_path / SHARED_CONFIG).unlink()
    else:
        _write(tmp_path, SHARED_CONFIG, config)
    results = run_all_checks(tmp_path, changed)
    assert _by_name(results)["Folder convention (new, incl. README.md)"].status is Status.FAIL


def test_ga_new_topic_still_requires_readme(tmp_path: Path) -> None:
    changed = _new_ga_topic(tmp_path)
    (tmp_path / GA_ROOT / "Employee/EmployeeGetThing/README.md").unlink()
    results = run_all_checks(tmp_path, changed)
    assert _by_name(results)["Folder convention (new, incl. README.md)"].status is Status.FAIL


def test_shared_topic_is_checked_even_without_scenario_changes(tmp_path: Path) -> None:
    _write(tmp_path, SHARED_CONFIG, "kind: Record\n")
    results = run_all_checks(tmp_path, [ChangedFile(SHARED_CONFIG, "M")])
    assert _by_name(results)["AdaptiveDialog kind"].status is Status.FAIL
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_shared_topic_rejects_non_redirect_trigger(tmp_path: Path) -> None:
    _write(tmp_path, SHARED_CONFIG, VALID_TOPIC_YAML)
    results = run_all_checks(tmp_path, [ChangedFile(SHARED_CONFIG, "M")])
    assert _by_name(results)["AdaptiveDialog kind"].status is Status.FAIL


def test_ga_assets_are_not_topics_and_arbitrary_area_yaml_is_rejected(tmp_path: Path) -> None:
    changed = _new_ga_topic(tmp_path)
    asset = f"{GA_ROOT}/assets/01-setup.png"
    _write(tmp_path, asset, "image")
    results = run_all_checks(tmp_path, [*changed, ChangedFile(asset, "A")])
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS
    results = run_all_checks(tmp_path, [*changed, ChangedFile(f"{GA_ROOT}/unexpected.yaml", "A")])
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.FAIL


def test_ga_name_exemption_does_not_exempt_missing_readme(tmp_path: Path) -> None:
    changed = _new_ga_topic(tmp_path, "WorkdayManagersdirect-CostCenter")
    topic = f"{GA_ROOT}/Employee/WorkdayManagersdirect-CostCenter"
    whitelist = {"folder_name_exemptions": [topic]}
    results = run_all_checks(tmp_path, changed, whitelist)
    assert _by_name(results)["Folder convention (new, incl. README.md)"].status is Status.PASS
    (tmp_path / topic / "README.md").unlink()
    results = run_all_checks(tmp_path, changed, whitelist)
    assert _by_name(results)["Folder convention (new, incl. README.md)"].status is Status.FAIL


def test_preview_new_topic_still_requires_local_xml_and_readme(tmp_path: Path) -> None:
    topic = f"{PREVIEW_ROOT}/Employee/EmployeeGetThing"
    _write(tmp_path, f"{topic}/topic.yaml", VALID_TOPIC_YAML)
    results = run_all_checks(tmp_path, [ChangedFile(f"{topic}/topic.yaml", "A")])
    folder = _by_name(results)["Folder convention (new, incl. README.md)"]
    assert folder.status is Status.FAIL
    assert any("connector config" in detail for detail in folder.details)
    assert any("README" in detail for detail in folder.details)


def _migration_repo(repo: Path) -> str:
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    legacy = "samples/WorkdayDeclarativeAgent/Employee/legacy-name/topic.yaml"
    _write(repo, legacy, VALID_TOPIC_YAML)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repo), "-c", "user.name=Validator Test",
        "-c", "user.email=validator@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "--quiet", "-m", "Baseline",
    ], check=True)
    base = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    subprocess.run([
        "git", "-C", str(repo), "mv",
        "samples/WorkdayDeclarativeAgent", PREVIEW_ROOT,
    ], check=True)
    _new_ga_topic(repo)
    _new_ga_topic(repo, "EmployeeGetOther")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repo), "-c", "user.name=Validator Test",
        "-c", "user.email=validator@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "--quiet", "-m", "Split samples",
    ], check=True)
    return base


def test_complete_preserved_split_passes_without_weakening_normal_scope(tmp_path: Path) -> None:
    base = _migration_repo(tmp_path)
    changed = _git_changed(tmp_path, base)
    preserved = _preserved_workday_migration(tmp_path, base)
    assert preserved == frozenset({f"{PREVIEW_ROOT}/Employee/legacy-name/topic.yaml"})
    results = run_all_checks(tmp_path, changed, preserved_workday_paths=preserved)
    assert all(result.status is not Status.FAIL for result in results)
    assert _by_name(run_all_checks(tmp_path, changed))["Diff scope (samples/ only)"].status is Status.FAIL


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra", "legacy-retained"])
def test_split_exception_requires_complete_unchanged_preview(tmp_path: Path, mutation: str) -> None:
    base = _migration_repo(tmp_path)
    preview = f"{PREVIEW_ROOT}/Employee/legacy-name/topic.yaml"
    if mutation == "changed":
        _write(tmp_path, preview, VALID_TOPIC_YAML + "# modified\n")
    elif mutation == "missing":
        (tmp_path / preview).unlink()
    elif mutation == "extra":
        _write(tmp_path, f"{PREVIEW_ROOT}/extra.txt", "extra")
    else:
        _write(tmp_path, "samples/WorkdayDeclarativeAgent/README.md", VALID_README)
    assert not _preserved_workday_migration(tmp_path, base)


def test_preserved_split_does_not_allow_unrelated_sample_topic(tmp_path: Path) -> None:
    base = _migration_repo(tmp_path)
    changed = _git_changed(tmp_path, base)
    preserved = _preserved_workday_migration(tmp_path, base)
    other = "samples/Facilities/EmployeeGetThing/topic.yaml"
    _write(tmp_path, other, VALID_TOPIC_YAML)
    results = run_all_checks(
        tmp_path, [*changed, ChangedFile(other, "M")], preserved_workday_paths=preserved,
    )
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.FAIL


def test_validator_repairs_do_not_bypass_scope_or_secret_checks(tmp_path: Path) -> None:
    changed = _new_ga_topic(tmp_path)
    maintainer = ChangedFile("tools/validate_samples/checks.py", "M")
    results = run_all_checks(tmp_path, [*changed, maintainer])
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS
    results = run_all_checks(tmp_path, [
        *changed, maintainer, ChangedFile("solutions/unrelated.py", "M"),
    ])
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.FAIL
    _write(tmp_path, f"{GA_ROOT}/Employee/EmployeeGetThing/README.md",
           "# Internal\nhttps://host.corp.microsoft.com/private\n")
    results = run_all_checks(tmp_path, [*changed, maintainer])
    assert _by_name(results)["Secrets / internal URLs"].status is Status.FAIL


def test_workflow_runs_validation_for_sample_and_validator_edits() -> None:
    workflow = (
        _REPO_ROOT / ".github" / "workflows" / "validate-samples.yml"
    ).read_text(encoding="utf-8")
    assert "self_edit" not in workflow
    assert '--diff-base "$BASE_SHA"' in workflow


def _retirement_repo(repo: Path, area: str) -> tuple[str, list[ChangedFile]]:
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    original = []
    for name in ("First", "Second"):
        original.extend(_new_topic(repo, f"{area}/Employee/{name}"))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repo), "-c", "user.name=Validator Test",
        "-c", "user.email=validator@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "--quiet", "-m", "Old samples",
    ], check=True)
    base = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True,
    ).strip()
    subprocess.run(["git", "-C", str(repo), "rm", "-r", "--quiet", "--", area], check=True)
    return base, [ChangedFile(file.path, "D") for file in original]


@pytest.mark.parametrize("area", [
    "samples/WorkdayCustomEngineAgent", PREVIEW_ROOT,
    "samples/WorkdayDeclarativeAgent", "samples/WorkdayDeclarativeAgentGA",
])
def test_complete_workday_retirement_allows_only_deleted_old_paths(tmp_path: Path, area: str) -> None:
    base, changed = _retirement_repo(tmp_path, area)
    retired = _retired_workday_areas(tmp_path, base)
    assert retired == frozenset({area})
    results = run_all_checks(tmp_path, changed, retired_workday_areas=retired)
    assert all(result.status is not Status.FAIL for result in results)


def test_retirement_requires_entire_area_removed(tmp_path: Path) -> None:
    base, _ = _retirement_repo(tmp_path, PREVIEW_ROOT)
    _write(tmp_path, f"{PREVIEW_ROOT}/remaining.txt", "remaining")
    assert not _retired_workday_areas(tmp_path, base)


def test_ga_rollout_can_accompany_verified_retirement(tmp_path: Path) -> None:
    base, changed = _retirement_repo(tmp_path, "samples/WorkdayDeclarativeAgent")
    changed.extend(_new_ga_topic(tmp_path))
    changed.extend(_new_ga_topic(tmp_path, "EmployeeGetOther"))
    retired = _retired_workday_areas(tmp_path, base)
    results = run_all_checks(tmp_path, changed, retired_workday_areas=retired)
    assert all(result.status is not Status.FAIL for result in results)
    assert not _preserved_workday_migration(tmp_path, base)


def test_retirement_does_not_allow_multiple_existing_ga_topic_edits(tmp_path: Path) -> None:
    base, changed = _retirement_repo(tmp_path, PREVIEW_ROOT)
    for name in ("EmployeeGetThing", "EmployeeGetOther"):
        topic = f"{GA_ROOT}/Employee/{name}/topic.yaml"
        _write(tmp_path, topic, VALID_TOPIC_YAML)
        changed.append(ChangedFile(topic, "M"))
    results = run_all_checks(
        tmp_path, changed, retired_workday_areas=_retired_workday_areas(tmp_path, base),
    )
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.FAIL


def test_retirement_does_not_allow_unrelated_topics_or_outside_paths(tmp_path: Path) -> None:
    base, changed = _retirement_repo(tmp_path, PREVIEW_ROOT)
    changed.extend(_new_ga_topic(tmp_path))
    changed.extend(_new_topic(tmp_path, "samples/Facilities/EmployeeGetOther"))
    changed.append(ChangedFile("solutions/unrelated.py", "M"))
    results = run_all_checks(
        tmp_path, changed, retired_workday_areas=_retired_workday_areas(tmp_path, base),
    )
    scope = _by_name(results)["Diff scope (samples/ only)"]
    assert scope.status is Status.FAIL
    assert any("multiple topic" in detail for detail in scope.details)
    assert any("outside samples" in detail for detail in scope.details)


def test_sample_authoring_guidance_paths_are_in_scope(tmp_path: Path) -> None:
    changed = _new_ga_topic(tmp_path)
    changed.extend([
        ChangedFile(".github/ISSUE_TEMPLATE/sample-topic-request.yml", "M"),
        ChangedFile(".github/agents/skills/prepare-sample-pr/SKILL.md", "M"),
    ])
    results = run_all_checks(tmp_path, changed)
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS
