from __future__ import annotations

import json
from pathlib import Path

import pytest

import eval_curator_submodule


CONTRACT = {
    "schemaVersion": 1,
    "skillPath": "skills/curate-evals/SKILL.md",
    "structuralValidatorPath": "scripts/check_eval_artifacts.py",
    "defaultOutputRoot": "workspace/evaluations",
    "supportsHostOutputOverride": True,
    "supportsHostLifecycleHandoff": True,
}


def _submodule_root(repo_root: Path) -> Path:
    return (
        repo_root
        / "solutions"
        / "ess-maker-skills"
        / "vendor"
        / "evals-curator"
    )


def _write_contract(repo_root: Path, **overrides: object) -> Path:
    submodule_root = _submodule_root(repo_root)
    contract = CONTRACT | overrides
    contract_path = submodule_root / "integration" / "host-contract.json"
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    (submodule_root / CONTRACT["skillPath"]).parent.mkdir(parents=True)
    (submodule_root / CONTRACT["skillPath"]).write_text(
        "# Curate evaluations\n",
        encoding="utf-8",
    )
    (submodule_root / CONTRACT["structuralValidatorPath"]).parent.mkdir(
        parents=True
    )
    (submodule_root / CONTRACT["structuralValidatorPath"]).write_text(
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    return submodule_root


def _run_status(repo_root: Path, capsys) -> tuple[int, dict[str, object]]:
    exit_code = eval_curator_submodule.main(
        ["status", "--repo-root", str(repo_root)]
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return exit_code, json.loads(captured.out)


def test_resolve_submodule_returns_expected_path(tmp_path):
    assert eval_curator_submodule.resolve_submodule(tmp_path) == _submodule_root(
        tmp_path
    )


def test_status_returns_resolved_contract_paths(tmp_path, capsys):
    submodule_root = _write_contract(tmp_path)

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 0
    assert payload == {
        "available": True,
        "schemaVersion": 1,
        "submoduleRoot": str(submodule_root.resolve()),
        "skillPath": str((submodule_root / CONTRACT["skillPath"]).resolve()),
        "structuralValidatorPath": str(
            (
                submodule_root / CONTRACT["structuralValidatorPath"]
            ).resolve()
        ),
        "defaultOutputRoot": "workspace/evaluations",
        "supportsHostOutputOverride": True,
        "supportsHostLifecycleHandoff": True,
    }


@pytest.mark.parametrize("create_directory", [False, True])
def test_status_fails_when_submodule_is_uninitialized(
    tmp_path,
    capsys,
    create_directory,
):
    if create_directory:
        _submodule_root(tmp_path).mkdir(parents=True)

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["available"] is False
    assert payload["errorCode"] == "submodule_not_initialized"


def test_status_rejects_unsupported_contract_version(tmp_path, capsys):
    _write_contract(tmp_path, schemaVersion=2)

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "unsupported_contract_version"


def test_status_rejects_paths_outside_submodule(tmp_path, capsys):
    _write_contract(tmp_path, skillPath="../../../../../../outside.md")

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "invalid_contract_path"


def test_status_rejects_absolute_contract_paths(tmp_path, capsys):
    submodule_root = _write_contract(tmp_path)
    absolute_skill_path = submodule_root / CONTRACT["skillPath"]
    contract_path = submodule_root / "integration" / "host-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["skillPath"] = str(absolute_skill_path)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "invalid_contract_path"


def test_status_rejects_missing_referenced_path(tmp_path, capsys):
    _write_contract(tmp_path, structuralValidatorPath="scripts/missing.py")

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "invalid_contract_path"


def test_status_rejects_malformed_json(tmp_path, capsys):
    submodule_root = _submodule_root(tmp_path)
    contract_path = submodule_root / "integration" / "host-contract.json"
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text("{not-json", encoding="utf-8")

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "invalid_contract"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", True),
        ("skillPath", 42),
        ("structuralValidatorPath", None),
        ("defaultOutputRoot", ""),
        ("supportsHostOutputOverride", 1),
        ("supportsHostLifecycleHandoff", "true"),
    ],
)
def test_status_rejects_invalid_contract_types(
    tmp_path,
    capsys,
    field,
    value,
):
    _write_contract(tmp_path, **{field: value})

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "invalid_contract"


def test_status_rejects_missing_required_contract_field(tmp_path, capsys):
    _write_contract(tmp_path)
    contract_path = (
        _submodule_root(tmp_path) / "integration" / "host-contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    del contract["defaultOutputRoot"]
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "invalid_contract"
