# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Tests for tools.validate_samples.

Each test builds a minimal repo tree in tmp_path and a corresponding
ChangedFile list, runs all checks, and asserts on the status of named checks.
"""

from __future__ import annotations

import sys
import textwrap
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
    rel = "samples/WorkdayCustomEngineAgent/Employee/EmployeeGetX/topic.yaml"
    _write(tmp_path, rel, VALID_TOPIC_YAML)
    results = run_all_checks(tmp_path, [ChangedFile(rel, "M")], whitelist={})
    assert _by_name(results)["Diff scope (samples/ only)"].status is Status.PASS


def test_workday_subgroup_readme_not_treated_as_topic(tmp_path: Path) -> None:
    # A subgroup-level README plus a real topic edit must not be flagged as
    # touching multiple topic folders.
    sub_readme = "samples/WorkdayDeclarativeAgent/Employee/README.md"
    topic_yaml = "samples/WorkdayDeclarativeAgent/Employee/EmployeeGetX/topic.yaml"
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
    topic = "samples/WorkdayDeclarativeAgent/Employee/WorkdayEmployeesviewtheirjobtaxonomy"
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
