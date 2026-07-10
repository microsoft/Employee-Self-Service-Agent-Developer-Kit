# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the WD-SEC-003 personal-data write-permission check.

WD-SEC-003 probes whether the ISU/employee resolved by Workday for
ESS personal-contact write topics (Update Email, Update Phone) has
Modify on the Personal Data domain. It has two operating modes:

* Mode A (runtime probe): when the full / legacy Workday install is
  detected and ISU credentials are available, the check issues
  ``Get_Change_Work_Contact_Information_Event_Request`` via the
  existing ``_soap_call`` helper and classifies the response into
  PASS / FAILED / WARNING by faultstring matching.

* Mode B (MANUAL): on the simplified install — or when ISU creds /
  test employee ID are missing — the check emits a MANUAL row with
  exact Workday UI navigation, mirroring the WD-CONN-010 /
  WD-CONN-102 pattern.

What these tests cover:

* The pure-logic classifier (``_classify_personal_data_write_response``).
  No network, no I/O.
* Mode A success / denial / auth-fault / unknown-fault branches, by
  monkeypatching ``_soap_call`` to return canned ``{success,
  response|error}`` dicts. The faultstring strings are derived from
  the WD-SEC-003 source incident and from the existing redaction
  helpers in ``checks/workday.py``.
* Mode B simplified-install branch (gate fires) and missing-creds /
  missing-employee branches (fall back to MANUAL).
* ``TestSimplifiedInstallGate`` pinning the AGENTS.md principle #11
  contract: only ``flavor == "simplified"`` skips the runtime probe;
  every other verdict (``"full"``, ``"partial"``, ``"unknown"``,
  ``"none"``, ``"skipped"``, or attribute-absent) falls through.

What these tests deliberately do NOT cover:

* The underlying SOAP envelope construction (already exercised by
  the live ``/flightcheck`` integration path and pinned by the
  existing 17 WD-WF-* workflow tests).
* The actual httpx transport in ``_soap_call`` (same reason).
* End-to-end response-shape validation against the Workday SOAP API
  contract — that lives in the ``flightcheck_workday.yaml``
  validated-tier cassette already covering ``POST
  /ccx/service/{tenant}/Human_Resources/v40.0`` (same path + method
  as the write probe, per the AGENTS.md "same endpoint" rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


# ───────────────────────────────────────────────────────────────────────
# Minimal runner — same stand-in shape used by other workday tests
# (test_workday_workflows_gate.py / test_workday_env_vars.py). The
# check only consults runner._workday_package_flavor and runner.config
# (the latter via _resolve_workday_metadata).
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    config: dict[str, Any] = field(default_factory=dict)


@pytest.fixture(autouse=True)
def _isolate_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Isolate every test from the developer's ambient environment.

    Without this fixture, ``_resolve_workday_metadata`` would happily
    read ``WORKDAY_BASE_URL`` / ``WORKDAY_TENANT`` /
    ``WORKDAY_TEST_EMPLOYEE_ID`` from a developer's shell and a
    ``.vscode/mcp.json`` from CWD, producing different verdicts
    depending on the local machine. Same pattern
    ``test_workday_workflows_gate.py::TestSimplifiedInstallGate``
    uses, applied autouse so future tests inherit it automatically.
    """
    for var in (
        "WORKDAY_BASE_URL",
        "WORKDAY_TENANT",
        "WORKDAY_TEST_EMPLOYEE_ID",
        "WORKDAY_USERNAME",
        "WORKDAY_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


# ───────────────────────────────────────────────────────────────────────
# Pure-logic tests — the faultstring classifier
# ───────────────────────────────────────────────────────────────────────


class TestClassifyPersonalDataWriteResponse:
    """``_classify_personal_data_write_response`` is the load-bearing
    pure-logic helper: it maps a ``_soap_call`` return dict into one
    of ``pass``/``denied``/``auth``/``unknown``. The downstream
    CheckResult branches all flow from this verdict, so we pin every
    branch explicitly."""

    def test_success_dict_classifies_as_pass(self) -> None:
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        assert _classify_personal_data_write_response(
            {"success": True, "response": "<irrelevant/>"}
        ) == "pass"

    def test_personal_data_denial_classifies_as_denied(self) -> None:
        """The WD-SEC-003 source incident: HTTP 400 with the precise
        Workday faultstring ``"Processing error occurred. The task
        submitted is not authorized"``."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": (
                "HTTP 400: Processing error occurred. The task "
                "submitted is not authorized"
            ),
        }
        assert _classify_personal_data_write_response(result) == "denied"

    def test_worker_not_found_classifies_as_pass(self) -> None:
        """A clean ``Worker not found`` fault proves the write API
        accepted the request and the security check passed — the
        only problem is the test employee has no open contact-change
        event. This is a PASS for the permission probe."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": "HTTP 400: Worker not found for given reference",
        }
        assert _classify_personal_data_write_response(result) == "pass"

    def test_invalid_id_classifies_as_pass(self) -> None:
        """Some Workday versions return ``Invalid_ID`` instead of
        ``Worker not found`` for the same condition."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": "HTTP 400: Invalid_ID for Worker_Reference",
        }
        assert _classify_personal_data_write_response(result) == "pass"

    def test_invalid_credentials_classifies_as_auth(self) -> None:
        """Auth-class faults route to WD-CONN-101 rather than getting
        treated as a permission denial."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": "HTTP 401: Invalid username or password",
        }
        assert _classify_personal_data_write_response(result) == "auth"

    def test_auth_pattern_wins_over_denied_pattern(self) -> None:
        """If a fault contains both auth and denial signatures, the
        auth classification wins — when the connection itself isn't
        authenticating we can't trust a downstream permission verdict.
        Pins the priority ordering inside the classifier."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": (
                "Invalid username -- secondary symptom: task "
                "submitted is not authorized"
            ),
        }
        assert _classify_personal_data_write_response(result) == "auth"

    def test_unknown_fault_classifies_as_unknown(self) -> None:
        """A fault we don't have a signature for falls through to
        WARNING with MANUAL guidance, NOT to PASS or FAIL — we never
        guess permission state from an ambiguous Workday response."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": "HTTP 500: Internal server error (no faultstring)",
        }
        assert _classify_personal_data_write_response(result) == "unknown"

    def test_empty_error_classifies_as_unknown(self) -> None:
        """Defensive: an error dict with no ``error`` key (or empty
        string) must not be silently treated as PASS."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        assert _classify_personal_data_write_response(
            {"success": False}
        ) == "unknown"
        assert _classify_personal_data_write_response(
            {"success": False, "error": ""}
        ) == "unknown"

    def test_none_soap_result_classifies_as_unknown(self) -> None:
        """Defensive: if an unexpected upstream exception path causes
        ``_soap_call`` to return ``None`` (or any falsy non-dict
        value), the classifier must NOT raise ``AttributeError`` from
        ``soap_result.get(...)``. The safe verdict in the absence of
        any signal is ``unknown``, which routes to the WARNING +
        MANUAL-fallback branch — never PASSED or FAILED on no data.

        Pins the guard added in response to PR review: ``_soap_call``
        always returns a dict on its normal paths, but the classifier
        is load-bearing and must not crash on edge inputs."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        assert _classify_personal_data_write_response(None) == "unknown"
        # An empty dict is also valid input — falsy, but a dict.
        assert _classify_personal_data_write_response({}) == "unknown"

    def test_case_insensitive_match(self) -> None:
        """Workday version differences sometimes capitalize the
        faultstring differently; the classifier must be resilient."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": (
                "HTTP 400: PROCESSING ERROR OCCURRED. THE TASK "
                "SUBMITTED IS NOT AUTHORIZED"
            ),
        }
        assert _classify_personal_data_write_response(result) == "denied"

    def test_generic_not_authorized_does_not_classify_as_denied(self) -> None:
        """Regression for the over-broad pattern catch.

        An earlier iteration of ``_PERSONAL_DATA_DENIED_PATTERNS``
        included the bare substring ``"not authorized"``, which would
        incorrectly classify *any* Workday auth-class failure on an
        unrelated domain as a Personal Data permission denial — and
        emit the wrong remediation (telling the operator to grant
        Personal Data Modify when the real problem is, say, a
        Compensation domain read). The pattern set is now narrowed
        to the verbatim ``"task submitted is not authorized"``
        signature only; generic ``"not authorized"`` faults must
        fall through to ``unknown`` so the MANUAL fallback (not the
        FAILED branch) fires."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": (
                "HTTP 403: User is not authorized to view this resource"
            ),
        }
        assert _classify_personal_data_write_response(result) == "unknown"

    def test_generic_processing_error_does_not_classify_as_denied(self) -> None:
        """Regression for the over-broad pattern catch.

        ``"Processing error occurred"`` is the Workday prefix for many
        SOAP-level failures (validation errors, BP configuration
        errors, reference errors) that have nothing to do with
        permissions. It must NOT alone trigger the FAILED branch."""
        from flightcheck.checks.workday import (
            _classify_personal_data_write_response,
        )

        result = {
            "success": False,
            "error": (
                "HTTP 400: Processing error occurred. Invalid element "
                "reference in request body"
            ),
        }
        assert _classify_personal_data_write_response(result) == "unknown"


# ───────────────────────────────────────────────────────────────────────
# Mode A — runtime probe branches (denied / pass / auth / unknown)
#
# These tests monkeypatch _soap_call to return canned dicts so we can
# exercise every CheckResult branch without touching the network. The
# SOAP envelope construction is owned by _build_write_test_body and is
# independently covered by the live /flightcheck integration path.
# ───────────────────────────────────────────────────────────────────────


def _full_install_runner_with_workday() -> _MinimalRunner:
    """Build a runner that the check sees as a fully-configured
    full / legacy Workday install. ``_resolve_workday_metadata`` will
    pick the URL / tenant / employee from ``runner.config``; the
    credential resolver will pick the username from env vars set by
    the test, and the password from the same source."""
    runner = _MinimalRunner(
        config={
            "connections": {
                "Workday": {
                    "baseUrl": "https://wd2-impl-services1.workday.com",
                    "tenant": "mocktenant_xx",
                }
            },
            "workdayTestEmployeeId": "21508",
        }
    )
    runner._workday_package_flavor = "full"
    return runner


@pytest.fixture
def supply_isu_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set fake ISU creds in env so ``_resolve_workday_credentials``
    returns them non-interactively. Using env vars (not direct
    monkeypatch of the resolver) so we exercise the same code path
    the production check uses."""
    monkeypatch.setenv("WORKDAY_USERNAME", "isu_flightcheck@mocktenant_xx")
    monkeypatch.setenv("WORKDAY_PASSWORD", "not-a-real-secret")  # noqa: S105


class TestModeA_DeniedBranch:
    """When ``_soap_call`` returns the WD-SEC-003 denial signature,
    the check FAILs with the specific Personal Data + Employee as
    Self remediation."""

    def test_denial_returns_failed_with_personal_data_remediation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        supply_isu_creds: None,
    ) -> None:
        from flightcheck.checks import workday as wd_mod
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        def fake_soap_call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "success": False,
                "error": (
                    "HTTP 400: Processing error occurred. The task "
                    "submitted is not authorized"
                ),
            }

        monkeypatch.setattr(wd_mod, "_soap_call", fake_soap_call)

        runner = _full_install_runner_with_workday()
        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.category == "Workday"
        assert r.priority == "High"
        assert r.status == "Failed"

        # ── result pins: name the observed Workday state precisely
        assert "task submitted is not authorized" in r.result.lower()
        assert "Personal Data" in r.result
        assert "Update Email" in r.result and "Update Phone" in r.result

        # ── remediation pins: WHY + HOW per AGENTS.md principle #8
        assert "Workday admin action required" in r.remediation
        assert "Personal Data" in r.remediation
        assert "Employee as Self" in r.remediation
        assert "Maintain Contact Information" in r.remediation
        assert "Edit Worker Additional Data" in r.remediation
        assert "Activate Pending Security Policy Changes" in r.remediation
        # Runtime-impact framing (principle 9 — functional risk WARNING
        # text equivalent, applied to FAIL here): the operator must
        # know what breaks if they ignore this.
        assert "fail at runtime" in r.result.lower() or (
            "fail for every employee" in r.remediation.lower()
        )

        assert "workday" in r.doc_link.lower()


class TestModeA_PassBranches:
    """``Worker not found`` / ``Invalid_ID`` / success all map to
    PASSED — these prove the API accepted the request and Personal
    Data resolution succeeded. The check NEVER returns PASSED with a
    remediation set."""

    @pytest.mark.parametrize(
        "fake_result",
        [
            {"success": True, "response": "<x/>"},
            {"success": False, "error": "Worker not found for given reference"},
            {"success": False, "error": "Invalid_ID for Worker_Reference"},
        ],
    )
    def test_benign_response_returns_passed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        supply_isu_creds: None,
        fake_result: dict[str, Any],
    ) -> None:
        from flightcheck.checks import workday as wd_mod
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        monkeypatch.setattr(
            wd_mod, "_soap_call",
            lambda *_a, **_k: fake_result,
        )

        runner = _full_install_runner_with_workday()
        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.status == "Passed"
        # PASSED remediation now describes what was validated.
        assert r.remediation.startswith("Validated:")
        assert "Personal Data" in r.remediation
        # Result must report the observed state — specifically that
        # the runtime permission is in place.
        assert "Personal Data" in r.result
        assert "Modify" in r.result


class TestModeA_AuthBranch:
    """A 401 fault routes to WD-CONN-101 rather than getting treated
    as a Personal Data denial."""

    def test_auth_fault_returns_warning_routing_to_wd_conn_101(
        self,
        monkeypatch: pytest.MonkeyPatch,
        supply_isu_creds: None,
    ) -> None:
        from flightcheck.checks import workday as wd_mod
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        monkeypatch.setattr(
            wd_mod, "_soap_call",
            lambda *_a, **_k: {
                "success": False,
                "error": "HTTP 401: Invalid username or password",
            },
        )

        runner = _full_install_runner_with_workday()
        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.status == "Warning"
        # Result names the observed auth-class fault.
        assert "auth-class fault" in r.result.lower() or (
            "auth-class" in r.result.lower()
        )
        # Remediation routes to WD-CONN-101, NOT to Personal Data fix
        # steps (those would be misleading guidance when auth itself
        # is broken).
        assert "WD-CONN-101" in r.remediation
        assert "Personal Data" not in r.remediation


class TestModeA_UnknownFaultBranch:
    """An unrecognized fault signature returns WARNING + MANUAL
    guidance — we never guess permission state from an ambiguous
    response."""

    def test_unknown_fault_returns_warning_with_manual_remediation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        supply_isu_creds: None,
    ) -> None:
        from flightcheck.checks import workday as wd_mod
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        monkeypatch.setattr(
            wd_mod, "_soap_call",
            lambda *_a, **_k: {
                "success": False,
                "error": "HTTP 500: Internal server error",
            },
        )

        runner = _full_install_runner_with_workday()
        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.status == "Warning"
        # Result surfaces the redacted faultstring (truncated at 200).
        assert "unrecognized response" in r.result.lower()
        assert "500" in r.result or "Internal server error" in r.result
        # Falls back to the same MANUAL navigation block the
        # simplified-install / no-creds branches use.
        assert "Manual verification required" in r.remediation
        assert "Personal Data" in r.remediation
        assert "Employee as Self" in r.remediation

    def test_unknown_fault_redacts_pii_from_surfaced_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        supply_isu_creds: None,
    ) -> None:
        """Regression for the WD-SEC-003 PR review concern: Workday
        faultstrings can include worker IDs, employee names, or user
        emails. The ``unknown`` branch is the only place the check
        surfaces raw faultstring text into ``result``, and ``result``
        flows into the HTML report. Confirm
        ``_redact_faultstring_pii`` is applied before that text lands
        in the CheckResult."""
        from flightcheck.checks import workday as wd_mod
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        monkeypatch.setattr(
            wd_mod, "_soap_call",
            lambda *_a, **_k: {
                "success": False,
                "error": (
                    "HTTP 500: Worker_Reference: 21508 for jane.doe@"
                    "contoso.com (WID f47ac10b-58cc-4372-a567-"
                    "0e02b2c3d479) is in an inconsistent state"
                ),
            },
        )

        runner = _full_install_runner_with_workday()
        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        # PII must NOT appear verbatim in the surfaced result.
        assert "21508" not in r.result
        assert "jane.doe" not in r.result
        assert "contoso.com" not in r.result
        assert "f47ac10b-58cc-4372-a567-0e02b2c3d479" not in r.result
        # Redaction markers SHOULD be present in place of each PII
        # category so an operator reading the report still has enough
        # context to recognize what was scrubbed.
        assert "[REDACTED-ID]" in r.result
        assert "[REDACTED-EMAIL]" in r.result
        # Benign error context (HTTP status, "inconsistent state") must
        # still pass through — redaction does not destroy debug value.
        assert "500" in r.result
        assert "inconsistent state" in r.result


class TestRedactFaultstringPii:
    """Direct unit tests for the ``_redact_faultstring_pii`` helper.

    PII patterns are best-effort defense-in-depth — the categorical
    defense is the WD-SEC-003 ``unknown`` branch falling back to
    MANUAL guidance. These tests pin the patterns we DO catch so
    a future refactor cannot silently weaken the redaction."""

    def test_email_addresses_redacted(self) -> None:
        from flightcheck.checks.workday import _redact_faultstring_pii

        out = _redact_faultstring_pii(
            "User jane.doe+work@contoso.co.uk not authorized"
        )
        assert "jane.doe" not in out
        assert "contoso" not in out
        assert "[REDACTED-EMAIL]" in out

    def test_long_numeric_ids_redacted(self) -> None:
        from flightcheck.checks.workday import _redact_faultstring_pii

        out = _redact_faultstring_pii(
            "Worker 21508 not found in tenant"
        )
        assert "21508" not in out
        assert "[REDACTED-ID]" in out

    def test_short_numbers_preserved(self) -> None:
        """3-digit HTTP status codes and 4-digit year/version numbers
        must NOT be redacted — they contain no PII and are essential
        debugging context."""
        from flightcheck.checks.workday import _redact_faultstring_pii

        out = _redact_faultstring_pii(
            "HTTP 400 from Workday v42.0 at 2026"
        )
        assert "400" in out
        assert "42" in out
        assert "2026" in out
        assert "[REDACTED" not in out

    def test_uuid_style_ids_redacted(self) -> None:
        from flightcheck.checks.workday import _redact_faultstring_pii

        out = _redact_faultstring_pii(
            "WID f47ac10b-58cc-4372-a567-0e02b2c3d479 not found"
        )
        assert "f47ac10b" not in out
        assert "[REDACTED-ID]" in out

    def test_field_style_reference_redacted(self) -> None:
        """``Worker_Reference: ABC123`` is a Workday-specific shape
        that the bare-id rule would miss (3 letters + 3 digits).
        The field-style pattern catches it as a whole tag-value pair."""
        from flightcheck.checks.workday import _redact_faultstring_pii

        out = _redact_faultstring_pii(
            "Worker_Reference: ABC123 cannot be modified"
        )
        assert "ABC123" not in out
        assert "[REDACTED-ID]" in out
        assert "Worker_Reference" in out  # field name preserved

    def test_empty_and_none_inputs_pass_through(self) -> None:
        """Defensive: empty / None inputs must not raise."""
        from flightcheck.checks.workday import _redact_faultstring_pii

        assert _redact_faultstring_pii("") == ""
        assert _redact_faultstring_pii(None) is None  # type: ignore[arg-type]

    def test_clean_text_unchanged(self) -> None:
        """A faultstring with no PII shapes must pass through verbatim
        — the redactor never falsely flags benign content."""
        from flightcheck.checks.workday import _redact_faultstring_pii

        clean = "Processing error occurred. Invalid element reference."
        assert _redact_faultstring_pii(clean) == clean


# ───────────────────────────────────────────────────────────────────────
# Mode B — MANUAL branches (simplified install, no creds, no employee)
# ───────────────────────────────────────────────────────────────────────


class TestModeB_SimplifiedInstall:
    """The simplified install has no ISU to probe — the runtime
    permission resolves against the signed-in employee's own group.
    The check emits MANUAL with the OBO context spelled out."""

    def test_simplified_install_emits_manual(self) -> None:
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        runner = _MinimalRunner()
        runner._workday_package_flavor = "simplified"

        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.status == "Manual"
        assert r.priority == "High"

        # Result names the OBO context that explains why MANUAL is
        # the right verdict here (not a workaround).
        assert "WD-PKG-001" in r.result
        assert "simplified" in r.result.lower()
        assert "OBO" in r.result or "signed-in employee" in r.result.lower()

        # Remediation is the canonical MANUAL block.
        assert "Manual verification required" in r.remediation
        assert "Personal Data" in r.remediation
        assert "Employee as Self" in r.remediation
        assert "Maintain Contact Information" in r.remediation


class TestModeB_MissingEmployeeOrCreds:
    """Mode A requires a test employee ID AND ISU credentials. Either
    being absent falls back to MANUAL on a full / legacy install
    (where the kit can't run the probe but can still surface the
    Workday UI verification steps the operator owns)."""

    def test_missing_employee_id_emits_manual(self) -> None:
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        # full install, Workday configured, but no test employee.
        runner = _MinimalRunner(
            config={
                "connections": {
                    "Workday": {
                        "baseUrl": "https://wd2-impl-services1.workday.com",
                        "tenant": "mocktenant_xx",
                    }
                },
                # workdayTestEmployeeId deliberately omitted
            }
        )
        runner._workday_package_flavor = "full"

        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.status == "Manual"
        assert "test employee" in r.result.lower()
        assert "Manual verification required" in r.remediation

    def test_missing_isu_creds_emits_manual(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        # Make the interactive credential prompt unavailable so the
        # resolver returns empty without hanging the test.
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

        runner = _full_install_runner_with_workday()
        # Note: NO WORKDAY_USERNAME / WORKDAY_PASSWORD env vars set
        # (the autouse _isolate_env fixture deletes them).

        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.status == "Manual"
        assert "ISU credentials not provided" in r.result
        assert "Manual verification required" in r.remediation

    def test_missing_workday_url_emits_skipped(self) -> None:
        """When Workday isn't configured at all, the check SKIPs
        (this isn't a Workday-tenant problem, it's a kit-setup
        problem). The skip remediation must route to /connect workday."""
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        # full install per WD-PKG-001 verdict, but no Workday URL —
        # e.g. a tenant with the connection refs deployed but
        # /connect workday never run yet.
        runner = _MinimalRunner()
        runner._workday_package_flavor = "full"

        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        assert r.status == "Skipped"
        assert "not configured" in r.result.lower()
        assert "/connect workday" in r.remediation


# ───────────────────────────────────────────────────────────────────────
# Install-flavor gating contract (AGENTS.md design principle #11)
# ───────────────────────────────────────────────────────────────────────


class TestSimplifiedInstallGate:
    """Pins the install-flavor gating contract for
    ``_check_personal_data_write_permission`` per AGENTS.md design
    principle #11. The simplified-install MANUAL branch fires ONLY
    on a positive ``flavor == "simplified"`` match; every other
    verdict — including ``None`` for backwards-compat with minimal
    test runners — must fall through to the runtime-probe path
    (where it SKIPs cleanly without Workday config, MANUALs without
    creds, etc.).

    Without this pin, a future careless rewrite like
    ``if flavor != "full": skip`` would silently suppress the
    runtime probe on intermediate states — exactly the failure mode
    the safety rule exists to prevent. Mirrors the equivalent test
    in ``test_workday_workflows_gate.py``.
    """

    def test_simplified_takes_the_manual_branch(self) -> None:
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        runner = _MinimalRunner()
        runner._workday_package_flavor = "simplified"

        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        # The simplified branch has the WD-PKG-001 signature in the
        # result; the fall-through branches do NOT.
        assert "WD-PKG-001" in r.result
        assert r.status == "Manual"

    def test_attribute_absent_falls_through(self) -> None:
        """Backwards-compat: when ``_workday_package_flavor`` isn't
        set (e.g. a minimal test runner, or a runner where WD-PKG-001
        couldn't run), the gate must NOT fire. The fall-through then
        emits SKIPPED for our zero-config runner (no Workday URL).
        Pin both that the gate didn't suppress the result AND that
        the result is the fall-through one, not the gate's.
        """
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        runner = _MinimalRunner()
        assert not hasattr(runner, "_workday_package_flavor")

        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        # Fall-through branch — gate text MUST NOT leak in.
        assert "WD-PKG-001" not in r.result
        assert r.status == "Skipped"
        assert "not configured" in r.result.lower()

    @pytest.mark.parametrize(
        "flavor", ["full", "partial", "unknown", "none", "skipped"]
    )
    def test_non_simplified_verdicts_fall_through(self, flavor: str) -> None:
        """Safety rule (AGENTS.md design principle #11.b): only a
        positive ``"simplified"`` match skips the runtime probe. Any
        other verdict — including the ambiguous ``"partial"`` /
        ``"unknown"`` / ``"none"`` / ``"skipped"`` values where the
        fingerprint couldn't reach a confident answer — must fall
        through to the existing logic.
        """
        from flightcheck.checks.workday import (
            _check_personal_data_write_permission,
        )

        runner = _MinimalRunner()
        runner._workday_package_flavor = flavor

        results = _check_personal_data_write_permission(runner)

        assert len(results) == 1
        r = results[0]
        assert r.checkpoint_id == "WD-SEC-003"
        # Gate text must NOT leak into the fall-through branch.
        assert "WD-PKG-001" not in r.result, (
            f"flavor={flavor!r} leaked simplified gate text into result"
        )
        # With no Workday URL configured on the minimal runner, the
        # fall-through emits a clean SKIPPED. The point of this test
        # is that the gate didn't preempt that path with its
        # simplified-only MANUAL.
        assert r.status == "Skipped"


# ───────────────────────────────────────────────────────────────────────
# Wiring smoke test — _check_personal_data_write_permission is invoked
# by run_workday_checks
# ───────────────────────────────────────────────────────────────────────


class TestWiring:
    """Pins that the new check actually runs from the top-level
    ``run_workday_checks`` entry point. Without this, the new function
    could exist in the module but never get invoked from the CLI.

    Uses auto-discovery (``_auto_stub_other_workday_checks`` fixture)
    to stub every ``_check_*`` helper in ``flightcheck.checks.workday``
    except ``_check_personal_data_write_permission`` itself. This is
    deliberately broader than enumerating the call sites of
    ``run_workday_checks`` by hand: if a new ``_check_*`` helper is
    added to the orchestrator without being added to a hand-maintained
    stub list, the older enumeration pattern would either
    (a) silently run the new check for real — potentially making
    network calls, prompting for credentials, or polluting the
    ``sec_003`` filter with cross-check CheckResults — or
    (b) break for the wrong reason. Auto-discovery means any future
    helper is stubbed by default; if a test ever NEEDS a particular
    helper to run for real, it overrides the stub explicitly (as this
    test does for ``_check_package_flavor``). Failing closed.
    """

    @pytest.fixture
    def _auto_stub_other_workday_checks(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Auto-stub every callable in ``flightcheck.checks.workday``
        whose name starts with ``_check_`` EXCEPT
        ``_check_personal_data_write_permission`` (the one this test
        suite is exercising)."""
        from flightcheck.checks import workday as wd_mod

        keep = {"_check_personal_data_write_permission"}
        for name in dir(wd_mod):
            if not name.startswith("_check_") or name in keep:
                continue
            if not callable(getattr(wd_mod, name)):
                continue
            # ``*_a, **_k`` swallows both positional and keyword args
            # since the orchestrator helpers have inconsistent
            # signatures (some take ``wd_flows`` kwarg, some don't).
            monkeypatch.setattr(
                wd_mod, name, lambda *_a, **_k: [],
            )

    def test_run_workday_checks_invokes_personal_data_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _auto_stub_other_workday_checks: None,
    ) -> None:
        """Force ``_workday_package_flavor = "simplified"`` to short
        the runtime-probe path (which would require a fully-built
        runner) and assert the WD-SEC-003 row appears in the
        aggregated output.

        ``_auto_stub_other_workday_checks`` has already replaced every
        sibling ``_check_*`` helper with a no-op returning ``[]``;
        this test overrides ``_check_package_flavor`` on top of that
        so it sets ``runner._workday_package_flavor = "simplified"``
        (causing WD-SEC-003 to route through its MANUAL branch
        instead of the no-Workday-URL SKIPPED branch).
        """
        from flightcheck.checks import workday as wd_mod
        from flightcheck.checks.workday import run_workday_checks

        # Override the auto-stub for _check_package_flavor with a
        # version that populates runner state. monkeypatch stacks
        # last-write-wins, so this overrides the fixture's no-op.
        def fake_pkg(runner: Any, *, wd_flows: list[Any]) -> list[Any]:
            runner._workday_package_flavor = "simplified"
            runner._workday_connection_refs = []
            return []

        monkeypatch.setattr(wd_mod, "_check_package_flavor", fake_pkg)

        runner = _MinimalRunner()
        # Past the no-Workday-integration early-return gate.
        runner._workday_flows = [{"id": "fake-flow"}]

        results = run_workday_checks(runner)

        sec_003 = [r for r in results if r.checkpoint_id == "WD-SEC-003"]
        assert len(sec_003) == 1, (
            "WD-SEC-003 must be emitted by run_workday_checks "
            "(wiring regression check)"
        )
        assert sec_003[0].status == "Manual"
