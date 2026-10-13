from __future__ import annotations

from io import BytesIO
import json
import sys
import urllib.error
from pathlib import Path

import pytest


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import evaluate_evals  # noqa: E402


@pytest.fixture(autouse=True)
def clear_github_token_overrides(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def test_resolve_evaluation_folder_accepts_exact_absolute_path(tmp_path):
    set_folder = tmp_path / "workspace" / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)

    resolved = evaluate_evals.resolve_evaluation_folder(
        str(set_folder),
        tmp_path,
    )

    assert resolved == set_folder.resolve()


def test_resolve_evaluation_folder_accepts_solution_relative_path(
    tmp_path,
    monkeypatch,
):
    set_folder = tmp_path / "workspace" / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    resolved = evaluate_evals.resolve_evaluation_folder(
        "workspace/evaluations/compensation",
        tmp_path,
    )

    assert resolved == set_folder.resolve()


def test_resolve_evaluation_folder_rejects_missing_path(tmp_path):
    try:
        evaluate_evals.resolve_evaluation_folder(
            "workspace/evaluations/missing",
            tmp_path,
        )
    except FileNotFoundError as exc:
        assert str(exc) == "workspace/evaluations/missing"
    else:
        raise AssertionError("Expected missing evaluation folder to fail")


def test_report_disclaimer_keeps_quality_errors_visible(capsys):
    evaluate_evals.render_report([{
        "category": "Selected", "total_cases": 1, "sampled": 1,
        "error": "Quality judge unavailable",
    }], "Agent", 1)
    report = capsys.readouterr().out
    assert "not whether your agent passes the tests in your tenant" in report
    assert "Run the evaluation in Copilot Studio" in report
    assert "ERROR: Quality judge unavailable" in report


def _process(returncode=0, stdout="", stderr=""):
    return evaluate_evals.subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_credential_defers_account_lookup_on_happy_path(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "do-not-print-this-token")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return _process(stdout="secret-token\n")

    monkeypatch.setattr(evaluate_evals.subprocess, "run", run)

    credential = evaluate_evals.get_gh_credential()

    assert credential.account is None
    assert credential.environment_override == "GH_TOKEN"
    assert credential.token == "secret-token"
    assert commands == [
        ["gh", "auth", "token", "--hostname", "github.com"],
    ]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (FileNotFoundError(), "gh_cli_missing"),
        (
            evaluate_evals.subprocess.TimeoutExpired("gh auth token", 10),
            "github_auth_timeout",
        ),
        (_process(returncode=1, stderr="not logged in"), "gh_not_authenticated"),
        (_process(stdout=""), "gh_not_authenticated"),
    ],
)
def test_credential_classifies_missing_github_auth(monkeypatch, failure, reason):
    if isinstance(failure, BaseException):
        def fail(*args, **kwargs):
            raise failure
        monkeypatch.setattr(evaluate_evals.subprocess, "run", fail)
    else:
        monkeypatch.setattr(
            evaluate_evals.subprocess, "run", lambda *args, **kwargs: failure,
        )

    with pytest.raises(evaluate_evals.EvaluationAuthenticationError) as caught:
        evaluate_evals.get_gh_credential()

    assert caught.value.reason == reason


def test_identity_lookup_failure_does_not_block_copilot_credential(monkeypatch):
    monkeypatch.setattr(
        evaluate_evals.subprocess, "run",
        lambda *args, **kwargs: _process(stdout="secret-token\n"),
    )

    credential = evaluate_evals.get_gh_credential()

    assert credential.account is None
    assert credential.environment_override is None
    assert "secret-token" not in repr(credential)


def test_copilot_auth_failure_resolves_account_lazily(monkeypatch):
    credential = evaluate_evals.GitHubCredential(
        token="secret-token", account=None, environment_override="GH_TOKEN",
    )
    error = urllib.error.HTTPError(
        evaluate_evals.MODELS_API_URL, 401, "Unauthorized", {}, BytesIO(b"denied"),
    )
    commands = []

    monkeypatch.setattr(
        evaluate_evals.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    def run(command, **kwargs):
        commands.append(command)
        return _process(stdout="licensed-user\n")

    monkeypatch.setattr(evaluate_evals.subprocess, "run", run)

    with pytest.raises(evaluate_evals.EvaluationAuthenticationError) as caught:
        evaluate_evals.call_judge("score this", credential)

    assert caught.value.account == "licensed-user"
    assert commands == [
        ["gh", "api", "--hostname", "github.com", "user", "--jq", ".login"],
    ]


@pytest.mark.parametrize("status_code", [401, 403])
def test_copilot_auth_failure_returns_authentication_required_without_token(
    monkeypatch, status_code,
):
    credential = evaluate_evals.GitHubCredential(
        token="secret-token",
        account="wrong-user",
        environment_override="GITHUB_TOKEN",
    )
    error = urllib.error.HTTPError(
        evaluate_evals.MODELS_API_URL,
        status_code,
        "Unauthorized",
        {},
        BytesIO(b"denied"),
    )

    def unauthorized(*args, **kwargs):
        raise error

    monkeypatch.setattr(evaluate_evals.urllib.request, "urlopen", unauthorized)

    with pytest.raises(evaluate_evals.EvaluationAuthenticationError) as caught:
        evaluate_evals.call_judge("score this", credential)

    result = caught.value.as_result()
    assert result == {
        "status": "authentication_required",
        "reason": "copilot_unauthorized",
        "message": (
            "The effective GitHub account could not access the GitHub Copilot API. "
            "The credential may be stale, belong to the wrong account, lack a "
            "Copilot entitlement, or be restricted by organization policy."
        ),
        "host": "github.com",
        "account": "wrong-user",
        "environmentOverride": "GITHUB_TOKEN",
    }
    assert "secret-token" not in json.dumps(result)


def test_rate_limited_403_retries_without_authentication_recovery(monkeypatch):
    credential = evaluate_evals.GitHubCredential(
        token="secret-token", account=None, environment_override=None,
    )
    rate_limit = urllib.error.HTTPError(
        evaluate_evals.MODELS_API_URL,
        403,
        "Forbidden",
        {"X-RateLimit-Remaining": "0"},
        BytesIO(b"rate limited"),
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"overall": 5}'},
                }],
            }).encode()

    responses = iter([rate_limit, Response()])

    def urlopen(*args, **kwargs):
        response = next(responses)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(evaluate_evals.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr("time.sleep", lambda *args: None)

    assert evaluate_evals.call_judge("score this", credential) == '{"overall": 5}'


def test_non_auth_http_failure_does_not_request_authentication(monkeypatch):
    credential = evaluate_evals.GitHubCredential(
        token="secret-token", account="licensed-user", environment_override=None,
    )
    error = urllib.error.HTTPError(
        evaluate_evals.MODELS_API_URL, 500, "Server Error", {}, BytesIO(b"failed"),
    )

    def server_error(*args, **kwargs):
        raise error

    monkeypatch.setattr(evaluate_evals.urllib.request, "urlopen", server_error)

    with pytest.raises(SystemExit) as caught:
        evaluate_evals.call_judge("score this", credential)

    assert caught.value.code == 1


def test_rate_limit_retry_preserves_credential(monkeypatch):
    credential = evaluate_evals.GitHubCredential(
        token="secret-token", account="licensed-user", environment_override=None,
    )
    rate_limit = urllib.error.HTTPError(
        evaluate_evals.MODELS_API_URL, 429, "Rate limited", {}, BytesIO(b"wait"),
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"overall": 5}'},
                }],
            }).encode()

    responses = iter([rate_limit, Response()])

    def urlopen(*args, **kwargs):
        result = next(responses)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(evaluate_evals.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr("time.sleep", lambda *args: None)

    assert evaluate_evals.call_judge("score this", credential) == '{"overall": 5}'


def test_cli_emits_only_structured_auth_result_and_distinct_exit_code(
    tmp_path, monkeypatch, capsys,
):
    failure = evaluate_evals.EvaluationAuthenticationError(
        "gh_not_authenticated",
        "GitHub CLI has no usable github.com credential.",
    )

    def fail():
        raise failure

    set_folder = tmp_path / "evaluations" / "selected"
    set_folder.mkdir(parents=True)
    monkeypatch.setattr(evaluate_evals, "get_gh_credential", fail)
    monkeypatch.setattr(
        sys, "argv",
        ["evaluate_evals.py", "--evaluation-folder", str(set_folder)],
    )

    assert evaluate_evals.cli() == evaluate_evals.AUTHENTICATION_REQUIRED_EXIT
    streams = capsys.readouterr()
    output = json.loads(streams.out)
    assert streams.err == ""
    assert output["status"] == "authentication_required"
    assert output["reason"] == "gh_not_authenticated"
    assert "environmentOverride" not in output


def test_cli_discards_progress_before_copilot_auth_failure(
    tmp_path, monkeypatch, capsys,
):
    set_folder = tmp_path / "evaluations" / "selected"
    set_folder.mkdir(parents=True)
    monkeypatch.setattr(
        evaluate_evals,
        "get_gh_credential",
        lambda: evaluate_evals.GitHubCredential(
            token="secret-token", account="wrong-user", environment_override=None,
        ),
    )

    def unauthorized(*args, **kwargs):
        raise evaluate_evals.EvaluationAuthenticationError(
            "copilot_unauthorized",
            "The effective GitHub account could not access the GitHub Copilot API.",
            account="wrong-user",
        )

    monkeypatch.setattr(evaluate_evals, "call_judge", unauthorized)
    (set_folder / "set.mcs.yml").write_text(
        "kind: EvaluationSet\ndisplayName: Selected\n"
        "graders:\n  - kind: CompareMeaningGrader\n    threshold: 0.7\n",
        encoding="utf-8",
    )
    (set_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\nrows:\n"
        "  - input: Question\n    expectedOutput: Answer\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys, "argv",
        ["evaluate_evals.py", "--evaluation-folder", str(set_folder)],
    )

    assert evaluate_evals.cli() == evaluate_evals.AUTHENTICATION_REQUIRED_EXIT
    streams = capsys.readouterr()
    output = json.loads(streams.out)
    assert output["reason"] == "copilot_unauthorized"
    assert output["account"] == "wrong-user"
    assert "Loading eval test cases" not in streams.out
    assert "sending 1 to quality evaluator" not in streams.out
    assert "secret-token" not in streams.out


def test_cli_streams_progress_for_interactive_terminal(monkeypatch):
    calls = []
    monkeypatch.setattr(evaluate_evals.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(evaluate_evals, "main", lambda: calls.append("main"))

    assert evaluate_evals.cli() == 0
    assert calls == ["main"]
