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
    submodule_root.mkdir(parents=True, exist_ok=True)
    (submodule_root / ".git").write_text(
        "gitdir: mocked-submodule-metadata\n",
        encoding="utf-8",
    )
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


@pytest.fixture(autouse=True)
def _mock_valid_submodule_integrity(monkeypatch, request):
    if request.node.name.startswith("test_integrity_"):
        return
    monkeypatch.setattr(
        eval_curator_submodule,
        "validate_submodule_integrity",
        lambda repo_root, submodule_root: {
            "parentGitlink": "a" * 40,
            "headGitlink": "a" * 40,
            "gitlinkSource": "HEAD",
            "parentGitlinkStaged": False,
            "submoduleHead": "a" * 40,
            "submoduleClean": True,
        },
    )


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
        "parentGitlink": "a" * 40,
        "headGitlink": "a" * 40,
        "gitlinkSource": "HEAD",
        "parentGitlinkStaged": False,
        "submoduleHead": "a" * 40,
        "submoduleClean": True,
    }


def test_integrity_accepts_clean_configured_submodule(tmp_path, monkeypatch):
    submodule_root = _write_contract(tmp_path)
    responses = {
        ("rev-parse", "--show-toplevel"): str(tmp_path.resolve()),
        (
            "config",
            "-f",
            str(tmp_path / ".gitmodules"),
            "--get-regexp",
            r"^submodule\..*\.path$",
        ): (
            "submodule.solutions/ess-maker-skills/vendor/evals-curator.path "
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-files",
            "--stage",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 " + "a" * 40 + " 0\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-tree",
            "HEAD",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 commit " + "a" * 40 + "\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "--show-superproject-working-tree"): str(
            tmp_path.resolve()
        ),
        ("rev-parse", "HEAD"): "a" * 40,
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
    }

    def fake_run_git(cwd, *args):
        return responses[args]

    monkeypatch.setattr(eval_curator_submodule, "_run_git", fake_run_git)

    result = eval_curator_submodule.validate_submodule_integrity(
        tmp_path,
        submodule_root,
    )

    assert result["parentGitlink"] == "a" * 40
    assert result["headGitlink"] == "a" * 40
    assert result["gitlinkSource"] == "HEAD"
    assert result["parentGitlinkStaged"] is False
    assert result["submoduleHead"] == "a" * 40
    assert result["submoduleClean"] is True


def test_integrity_rejects_non_submodule_directory(tmp_path, monkeypatch):
    submodule_root = _write_contract(tmp_path)
    (submodule_root / ".git").unlink()
    monkeypatch.setattr(
        eval_curator_submodule,
        "_run_git",
        lambda cwd, *args: {
            ("rev-parse", "--show-toplevel"): str(tmp_path.resolve()),
            (
                "config",
                "-f",
                str(tmp_path / ".gitmodules"),
                "--get-regexp",
                r"^submodule\..*\.path$",
            ): "",
        }[args],
    )

    with pytest.raises(eval_curator_submodule.CuratorSubmoduleError) as exc:
        eval_curator_submodule.validate_submodule_integrity(
            tmp_path,
            submodule_root,
        )

    assert exc.value.error_code == "not_configured_submodule"


def test_integrity_rejects_gitlink_head_mismatch(tmp_path, monkeypatch):
    submodule_root = _write_contract(tmp_path)
    responses = {
        ("rev-parse", "--show-toplevel"): str(tmp_path.resolve()),
        (
            "config",
            "-f",
            str(tmp_path / ".gitmodules"),
            "--get-regexp",
            r"^submodule\..*\.path$",
        ): (
            "submodule.evals.path "
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-files",
            "--stage",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 " + "a" * 40 + " 0\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-tree",
            "HEAD",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 commit " + "a" * 40 + "\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "--show-superproject-working-tree"): str(
            tmp_path.resolve()
        ),
        ("rev-parse", "HEAD"): "b" * 40,
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
    }
    monkeypatch.setattr(
        eval_curator_submodule,
        "_run_git",
        lambda cwd, *args: responses[args],
    )

    with pytest.raises(eval_curator_submodule.CuratorSubmoduleError) as exc:
        eval_curator_submodule.validate_submodule_integrity(
            tmp_path,
            submodule_root,
        )

    assert exc.value.error_code == "submodule_commit_mismatch"


def test_integrity_rejects_dirty_submodule(tmp_path, monkeypatch):
    submodule_root = _write_contract(tmp_path)
    responses = {
        ("rev-parse", "--show-toplevel"): str(tmp_path.resolve()),
        (
            "config",
            "-f",
            str(tmp_path / ".gitmodules"),
            "--get-regexp",
            r"^submodule\..*\.path$",
        ): (
            "submodule.evals.path "
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-files",
            "--stage",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 " + "a" * 40 + " 0\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-tree",
            "HEAD",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 commit " + "a" * 40 + "\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "--show-superproject-working-tree"): str(
            tmp_path.resolve()
        ),
        ("rev-parse", "HEAD"): "a" * 40,
        ("status", "--porcelain=v1", "--untracked-files=all"): (
            " M skills/curate-evals/SKILL.md"
        ),
    }
    monkeypatch.setattr(
        eval_curator_submodule,
        "_run_git",
        lambda cwd, *args: responses[args],
    )

    with pytest.raises(eval_curator_submodule.CuratorSubmoduleError) as exc:
        eval_curator_submodule.validate_submodule_integrity(
            tmp_path,
            submodule_root,
        )

    assert exc.value.error_code == "submodule_dirty"


def test_integrity_uses_staged_index_gitlink(tmp_path, monkeypatch):
    submodule_root = _write_contract(tmp_path)
    responses = {
        ("rev-parse", "--show-toplevel"): str(tmp_path.resolve()),
        (
            "config",
            "-f",
            str(tmp_path / ".gitmodules"),
            "--get-regexp",
            r"^submodule\..*\.path$",
        ): (
            "submodule.evals.path "
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-files",
            "--stage",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 " + "b" * 40 + " 0\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        (
            "ls-tree",
            "HEAD",
            "--",
            "solutions/ess-maker-skills/vendor/evals-curator",
        ): (
            "160000 commit " + "a" * 40 + "\t"
            "solutions/ess-maker-skills/vendor/evals-curator"
        ),
        ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "--show-superproject-working-tree"): str(
            tmp_path.resolve()
        ),
        ("rev-parse", "HEAD"): "b" * 40,
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
    }
    monkeypatch.setattr(
        eval_curator_submodule,
        "_run_git",
        lambda cwd, *args: responses[args],
    )

    result = eval_curator_submodule.validate_submodule_integrity(
        tmp_path,
        submodule_root,
    )

    assert result["parentGitlink"] == "b" * 40
    assert result["headGitlink"] == "a" * 40
    assert result["gitlinkSource"] == "index"
    assert result["parentGitlinkStaged"] is True


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


def test_status_rejects_minimal_unsupported_contract_version(tmp_path, capsys):
    contract_path = (
        _submodule_root(tmp_path) / "integration" / "host-contract.json"
    )
    contract_path.parent.mkdir(parents=True)
    contract_path.write_text(
        json.dumps({"schemaVersion": 2}),
        encoding="utf-8",
    )

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


def test_status_rejects_malformed_contract_path(tmp_path, capsys):
    _write_contract(tmp_path, skillPath="skills/\0/SKILL.md")

    exit_code, payload = _run_status(tmp_path, capsys)

    assert exit_code == 2
    assert payload["errorCode"] == "invalid_contract_path"


def test_status_rejects_contract_path_with_symlink_loop(
    tmp_path,
    capsys,
    monkeypatch,
):
    submodule_root = _write_contract(tmp_path, skillPath="skills/loop")
    loop_path = submodule_root / "skills" / "loop"

    try:
        loop_path.symlink_to(loop_path.name)
    except (NotImplementedError, OSError):
        original_resolve = Path.resolve

        def resolve_with_loop_error(self, *args, **kwargs):
            if self == loop_path:
                raise RuntimeError("Symlink loop from test")
            return original_resolve(self, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve_with_loop_error)

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
