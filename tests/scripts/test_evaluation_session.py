from pathlib import Path

import pytest
import yaml

import evaluation_authoring
import evaluation_case_categories as categories
import evaluation_session as session


def _set(tmp_path):
    folder = tmp_path / "evaluations" / "pay"
    folder.mkdir(parents=True)
    (folder / "set.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationSet", "displayName": "Pay",
        "graders": [{"kind": "CompareMeaningGrader", "threshold": 0.7}],
    }), encoding="utf-8")
    (folder / "cases.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationData",
        "rows": [
            {"input": "My pay?", "expectedOutput": "The agent should show pay."},
            {"input": "Peer pay?", "expectedOutput": "The agent should refuse."},
            {"input": "Weather?", "expectedOutput": "The agent should redirect."},
        ],
    }), encoding="utf-8")
    return folder


def test_categories_survive_removal_of_other_rows_and_reset_on_edit(tmp_path):
    folder = _set(tmp_path)
    categories.save_case_categories(folder, {
        "cases.mcs.yml:1": "positive",
        "cases.mcs.yml:2": "negative",
        "cases.mcs.yml:3": "out_of_scope",
    })
    evaluation_authoring.remove_evaluation_cases(
        folder, ["cases.mcs.yml:1"], tmp_path / "backups",
    )
    assert categories.load_case_categories(folder) == {
        "cases.mcs.yml:1": "negative",
        "cases.mcs.yml:2": "out_of_scope",
    }

    document = yaml.safe_load((folder / "cases.mcs.yml").read_text(encoding="utf-8"))
    document["rows"][0]["expectedOutput"] = "The agent should explain the policy."
    (folder / "cases.mcs.yml").write_text(yaml.safe_dump(document), encoding="utf-8")
    assert categories.load_case_categories(folder)["cases.mcs.yml:1"] is None


def test_preview_saves_flagged_categories_and_reuses_them(tmp_path, monkeypatch, capsys):
    import sys
    import evaluation_presentation as presentation

    folder = _set(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "evaluation_presentation.py", "--evaluation-folder", str(folder),
        "--boundary", "cases.mcs.yml:1", "--other-negative", "cases.mcs.yml:2",
    ])
    assert presentation.main() == 0
    assert categories.load_case_categories(folder) == {
        "cases.mcs.yml:1": "boundary",
        "cases.mcs.yml:2": "negative",
        "cases.mcs.yml:3": None,
    }
    capsys.readouterr()

    monkeypatch.setattr(sys, "argv", [
        "evaluation_presentation.py", "--evaluation-folder", str(folder),
    ])
    assert presentation.main() == 0
    output = capsys.readouterr().out
    in_scope = output.split("#### Positive cases / In scope")[1].split("####")[0]
    negative = output.split("#### Other negative cases")[1].split("####")[0]
    assert "My pay?" in in_scope
    assert "Peer pay?" in negative
    assert "Weather?" in output.split("#### Additional cases")[1]


def test_categories_reject_unknown_values_and_cases_without_writing(tmp_path):
    folder = _set(tmp_path)
    with pytest.raises(categories.CaseCategoryError, match="Unknown categories"):
        categories.save_case_categories(folder, {"cases.mcs.yml:1": "happy"})
    with pytest.raises(categories.CaseCategoryError, match="Unknown case"):
        categories.save_case_categories(folder, {"cases.mcs.yml:9": "positive"})
    assert not (folder / categories.CATEGORIES_FILENAME).exists()


def test_session_records_only_confirmed_runs_per_agent_and_tracks_stage(tmp_path):
    folder = _set(tmp_path)
    session.set_context("agent-a", {"setFolder": str(folder), "stage": "created"})
    assert session.record_run("agent-a", {"state": "Queued"}) is None
    session.record_run(
        "agent-a", {"runId": "run-1", "testSetName": "Pay", "response": {"state": "Queued"}},
        source_folder=folder,
    )
    assert session.adk_runs("agent-b") == []
    run = session.adk_runs("agent-a")[0]
    assert run["lastObserved"]["state"] == "Queued"
    assert run["sourceFolder"] == str(folder.resolve())
    assert session.get_context("agent-a")["stage"] == "running"

    session.observe_run("agent-a", "run-1", {"state": "Completed"})
    assert session.get_context("agent-a")["stage"] == "complete"
    assert session.observe_run("agent-a", "unknown", {"state": "Completed"}) is False


def test_session_context_clears_only_for_the_selected_set(tmp_path):
    folder = _set(tmp_path)
    session.set_context("agent-a", {"setFolder": str(folder), "pendingAction": "delete"})
    assert session.clear_context("agent-a", set_folder=tmp_path / "other") is False
    assert session.get_context("agent-a")["pendingAction"] == "delete"
    assert session.clear_context("agent-a", set_folder=folder) is True
    assert session.get_context("agent-a") is None
    with pytest.raises(session.EvaluationSessionError, match="Unknown stage"):
        session.set_context("agent-a", {"stage": "approved"})


def test_session_keeps_scenario_per_set_until_that_set_is_deleted(tmp_path):
    first, second = tmp_path / "leave", tmp_path / "comp"
    session.set_context("agent-a", {"setFolder": str(first), "scenario": "Leave and time off"})
    session.set_context("agent-a", {"setFolder": str(second), "scenario": "Compensation"})
    session.set_context("agent-a", {"setFolder": str(first)})

    assert session.get_context("agent-a")["scenario"] == "Leave and time off"
    assert session.set_details("agent-a") == {
        str(first.resolve()): {"scenario": "Leave and time off"},
        str(second.resolve()): {"scenario": "Compensation"},
    }
    assert session.clear_context("agent-a", set_folder=second) is False
    assert str(second.resolve()) not in session.set_details("agent-a")
    with pytest.raises(session.EvaluationSessionError, match="needs --set-folder"):
        session.set_context("agent-b", {"scenario": "Orphan"})


def test_session_agent_key_prefers_active_agent_and_falls_back_to_workspace():
    assert session.agent_key({"activeAgent": "hr", "agent": {"slug": "it"}}) == "hr"
    assert session.agent_key({"agent": {"folder": "workspace/agents/hr"}}) == "hr"
    assert session.agent_key(None) == session.WORKSPACE_KEY
