"""Tests for reply-signal classification (drive-outcome signalling).

When you drive a turn against an agent, you need a structured signal that
distinguishes a real reply from a connector consent gate, a connection-manager
prompt, or an empty/timeout non-reply. Without it, a consent card vacuously
passes an absence/notContains check because the backend call never ran.

``classify_reply_signal`` is the pure, browser-free core of that: given the
captured reply text (and whether the drive timed out), return a ReplySignal the
caller can branch on. A live driver layers a DOM-level consent check on top;
these tests pin the text-level contract.
"""
from __future__ import annotations

from reply_signal import ReplySignal, classify_reply_signal


def test_normal_reply_is_ok():
    sig = classify_reply_signal("You can view the HR case details below.")
    assert sig is ReplySignal.OK


def test_error_reply_is_ok_not_a_gate():
    # A genuine backend error reply is a real turn (the error path fired),
    # NOT a gate — it must classify OK so assertions run against it.
    sig = classify_reply_signal("Error code: 400 Error Message: Something went wrong.")
    assert sig is ReplySignal.OK


def test_connect_to_continue_is_consent_gate():
    reply = ("Connect to continue\nI'll use your credentials to connect and to get "
             "the information you're looking for.\nServiceNow")
    assert classify_reply_signal(reply) is ReplySignal.CONSENT_GATE


def test_connection_manager_prompt_is_consent_gate():
    reply = ("Let's get you connected first, and then I can find that info for you. "
             "Open connection manager to verify your credentials.")
    assert classify_reply_signal(reply) is ReplySignal.CONSENT_GATE


def test_empty_reply_is_empty():
    assert classify_reply_signal("") is ReplySignal.EMPTY
    assert classify_reply_signal(None) is ReplySignal.EMPTY
    assert classify_reply_signal("   \n  ") is ReplySignal.EMPTY


def test_timeout_flag_forces_timeout_signal_even_with_partial_text():
    # If the drive reported a timeout, that wins over whatever partial text was
    # scraped — the caller must know the turn did not complete.
    sig = classify_reply_signal("partial...", timed_out=True)
    assert sig is ReplySignal.TIMEOUT


def test_timeout_with_no_text_is_timeout_not_empty():
    assert classify_reply_signal("", timed_out=True) is ReplySignal.TIMEOUT


def test_timeout_beats_consent_text():
    # Precedence guard: a timed-out turn whose partial scrape happens to contain
    # a consent marker must still report TIMEOUT — the turn did not complete, so
    # the caller must not be routed down the consent-recovery path on stale text.
    reply = "Connect to continue\nServiceNow"
    assert classify_reply_signal(reply, timed_out=True) is ReplySignal.TIMEOUT


def test_signal_actionable_flags():
    # The caller uses these to decide: is this a real reply to assert against?
    assert ReplySignal.OK.is_reply is True
    assert ReplySignal.CONSENT_GATE.is_reply is False
    assert ReplySignal.TIMEOUT.is_reply is False
    assert ReplySignal.EMPTY.is_reply is False
    # Consent gate is specifically recoverable by a manual/inline consent click.
    assert ReplySignal.CONSENT_GATE.needs_consent is True
    assert ReplySignal.OK.needs_consent is False


def test_cli_prints_signal_and_remediation(capsys):
    from reply_signal import main
    rc = main(["Connect to continue\nServiceNow"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert out[0] == "consent_gate"
    assert "Authorize the connection" in out[1]


def test_cli_timeout_flag(capsys):
    from reply_signal import main
    rc = main(["partial...", "--timed-out"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert out[0] == "timeout"


def test_cli_ok_reply(capsys):
    from reply_signal import main
    rc = main(["You have 3 open HR cases."])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert out[0] == "ok"


# --------------------------------------------------------------------------- #
# error-reply advisory: a real turn (OK) can still be an error reply. This is a
# separate axis from ReplySignal — it never downgrades OK, it flags that the
# reply is error-shaped so the caller/agent notices a 400/runtime failure that
# would otherwise read as a normal turn.
# --------------------------------------------------------------------------- #

def test_looks_like_error_detects_connector_error_code():
    from reply_signal import looks_like_error
    assert looks_like_error("Error code: 400 Error Message: Bad Request") is True


def test_looks_like_error_detects_generic_runtime_failure():
    from reply_signal import looks_like_error
    assert looks_like_error("Sorry, something went wrong. Please try again.") is True
    assert looks_like_error("An unexpected error occurred while processing.") is True


def test_looks_like_error_false_for_normal_reply():
    from reply_signal import looks_like_error
    assert looks_like_error("You have 3 open HR cases.") is False
    assert looks_like_error("") is False
    assert looks_like_error(None) is False


# --------------------------------------------------------------------------- #
# expected/rejected-text assertions: the deterministic grade on top of the OK
# signal. This is the axis that separates a 400 from a real success when both
# are "OK" turns — you assert on what the reply must (not) contain.
# --------------------------------------------------------------------------- #

def test_check_expectations_all_met_passes():
    from reply_signal import check_expectations
    res = check_expectations("You have 2 open HR cases.",
                             expect=["open HR cases"], reject=["Error code"])
    assert res.passed is True


def test_check_expectations_missing_expected_fails():
    from reply_signal import check_expectations
    res = check_expectations("Error code: 400", expect=["open HR cases"])
    assert res.passed is False
    assert "open HR cases" in res.reason


def test_check_expectations_present_rejected_fails():
    from reply_signal import check_expectations
    res = check_expectations("Error code: 400 Bad Request", reject=["Error code"])
    assert res.passed is False
    assert "Error code" in res.reason


def test_check_expectations_case_insensitive():
    from reply_signal import check_expectations
    res = check_expectations("You have TWO OPEN cases", expect=["two open"])
    assert res.passed is True


def test_check_expectations_no_criteria_passes_vacuously():
    from reply_signal import check_expectations
    res = check_expectations("anything", expect=None, reject=None)
    assert res.passed is True


def test_cli_expect_pass(capsys):
    from reply_signal import main
    rc = main(["You have 3 open HR cases.", "--expect", "open HR cases"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "assert: pass" in out


def test_cli_expect_fail_returns_1(capsys):
    from reply_signal import main
    rc = main(["Error code: 400", "--expect", "open HR cases"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "assert: fail" in out


def test_cli_reject_fail_returns_1(capsys):
    from reply_signal import main
    rc = main(["Error code: 400 Bad Request", "--reject", "Error code"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "assert: fail" in out


def test_cli_surfaces_error_advisory(capsys):
    from reply_signal import main
    rc = main(["Error code: 400 Error Message: Bad Request"])
    out = capsys.readouterr().out
    assert rc == 0  # no assertions -> drive still "succeeded" as a real turn
    assert "error-shaped" in out.lower()
