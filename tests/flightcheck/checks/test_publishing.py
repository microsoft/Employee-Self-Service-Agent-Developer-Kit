# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the Publishing & QA checklist (PUB-*, QA-*).

The user surfaced that the publishing rows were emitted as
``NotConfigured`` with a generic "Verify: <desc>" remediation and a
single homepage link — operators had no way to act on them. The
module was rewritten so:

  * every row is ``Status.MANUAL`` (nothing is genuinely "not
    configured" — the kit just can't witness the action remotely);
  * every ``result`` describes WHAT the kit can't see, not the
    boilerplate "Manual verification required";
  * every ``remediation`` carries concrete steps and the best
    available deep link (Copilot Studio agent for QA-*; Power Apps
    Solutions for PUB-001/002; the Microsoft 365 admin center
    Integrated apps page for PUB-006/011).

These tests pin those contracts so the rows can't drift back to
"vague + NotConfigured" without breaking CI.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab

require_validated_mock(ab)


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make `flightcheck.*` importable from the kit's scripts dir."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


class _FakeAgentBuilder:
    def __init__(
        self,
        *,
        export_bytes: bytes | None = None,
        export_error: Exception | None = None,
        import_result: dict | None = None,
        import_error: Exception | None = None,
    ) -> None:
        self.export_bytes = (
            ab.export_package_bytes() if export_bytes is None else export_bytes
        )
        self.export_error = export_error
        self.import_result = import_result or ab.import_package_result()
        self.import_error = import_error
        self.export_calls: list[tuple[str, Path]] = []
        self.import_calls: list[Path] = []

    def export_package(self, agent_id: str, destination: Path) -> None:
        self.export_calls.append((agent_id, destination))
        if self.export_error is not None:
            raise self.export_error
        destination.write_bytes(self.export_bytes)

    def import_package(self, package_path: Path) -> dict:
        self.import_calls.append(package_path)
        if self.import_error is not None:
            raise self.import_error
        return self.import_result


def _agentbuilder_http_error(
    *,
    status_code: int,
    error_code: str,
    body: dict | None = None,
):
    from agentbuilder import AgentBuilderHTTPError

    response = requests.Response()
    response.status_code = status_code
    response._content = b"{}" if body is None else str(body).encode()
    response.headers["x-ms-request-id"] = "request-1"
    return AgentBuilderHTTPError(
        "Native ALM test",
        status_code,
        error_code=error_code,
        request_id="request-1",
        response=response,
    )


def _runner(
    env_id: str | None = "env-abc",
    bot_id: str | None = "bot-xyz",
    agentbuilder=None,
    alm_import_probe: bool = False,
):
    """Minimal runner stub exposing the two attributes publishing.py reads."""
    config: dict = {}
    if bot_id:
        config["agents"] = [{"slug": "esshr", "botId": bot_id}]
    return SimpleNamespace(
        env_id=env_id,
        config=config,
        agentbuilder=agentbuilder,
        alm_import_probe=alm_import_probe,
    )


def _results_by_id(runner) -> dict:
    from flightcheck.checks.publishing import run_publishing_checks
    return {r.checkpoint_id: r for r in run_publishing_checks(runner)}


def _zip_bytes(entry_name: str) -> bytes:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr(entry_name, "content")
    return archive_bytes.getvalue()


# --------------------------------------------------------------- shape


def test_all_eight_checks_emitted():
    """Regression guard: the published checklist must keep its 8 IDs."""
    by_id = _results_by_id(_runner())
    assert set(by_id) == {
        "QA-001", "QA-002", "QA-012",
        "PUB-001", "PUB-002", "PUB-003", "PUB-006", "PUB-011",
    }


def test_non_api_checks_are_manual_not_notconfigured():
    """Rows the kit still cannot verify remain manual, not NotConfigured."""
    from flightcheck.runner import Status
    by_id = _results_by_id(_runner())
    for check_id, r in by_id.items():
        if check_id in {"PUB-001", "PUB-002"}:
            continue
        assert r.status == Status.MANUAL.value, (
            f"{r.checkpoint_id} regressed to status={r.status!r}; "
            "publishing/QA gates are manual, not NotConfigured."
        )


def test_pub_api_checks_skip_without_agentbuilder_client():
    from flightcheck.runner import Status

    by_id = _results_by_id(_runner(agentbuilder=None))

    assert by_id["PUB-001"].status == Status.SKIPPED.value
    assert "AgentBuilder ALM client is unavailable" in by_id["PUB-001"].result
    assert "authenticates the Copilot Studio AgentBuilder" in by_id[
        "PUB-001"
    ].remediation
    assert by_id["PUB-002"].status == Status.SKIPPED.value
    assert "import probe was not explicitly enabled" in by_id["PUB-002"].result
    assert "throwaway environment" in by_id["PUB-002"].remediation


def test_every_check_has_concrete_result_text():
    """No row may carry the old "Manual verification required" stub."""
    for r in _results_by_id(_runner()).values():
        assert r.result.strip(), f"{r.checkpoint_id} has empty result"
        assert r.result != "Manual verification required", (
            f"{r.checkpoint_id} regressed to the generic result stub."
        )


def test_every_check_has_remediation_and_doc_link():
    for r in _results_by_id(_runner()).values():
        assert r.remediation.strip(), f"{r.checkpoint_id} has empty remediation"
        # Remediation must say more than "Verify: <desc>".
        assert not r.remediation.startswith("Verify:"), (
            f"{r.checkpoint_id} regressed to the boilerplate remediation."
        )
        assert r.doc_link.startswith("https://"), (
            f"{r.checkpoint_id} has missing/invalid doc_link {r.doc_link!r}"
        )


def test_category_is_publishing():
    for r in _results_by_id(_runner()).values():
        assert r.category == "Publishing"


# ----------------------------------------------------------- QA deep links


def test_qa_checks_link_to_studio_when_env_and_bot_resolved():
    by_id = _results_by_id(_runner(env_id="env-abc", bot_id="bot-xyz"))
    expected = (
        "https://copilotstudio.microsoft.com/environments/env-abc/"
        "bots/bot-xyz/overview"
    )
    for qa_id in ("QA-001", "QA-002", "QA-012"):
        assert expected in by_id[qa_id].remediation, (
            f"{qa_id} remediation missing the Studio deep link {expected!r}; "
            f"got: {by_id[qa_id].remediation!r}"
        )


def test_qa_checks_remain_actionable_without_studio_link():
    """If env_id or botId is missing, the remediation must still tell
    the operator where to go — just without a clickable shortcut."""
    by_id = _results_by_id(_runner(env_id=None, bot_id=None))
    for qa_id in ("QA-001", "QA-002", "QA-012"):
        text = by_id[qa_id].remediation
        # No copilotstudio.microsoft.com link when we can't build one.
        assert "copilotstudio.microsoft.com/environments/" not in text
        # But the operator is still told where to perform the action.
        assert "Analytics" in text and "Evaluations" in text


def test_qa_checks_point_at_evaluations_doc():
    by_id = _results_by_id(_runner())
    for qa_id in ("QA-001", "QA-002", "QA-012"):
        assert by_id[qa_id].doc_link.endswith("/evaluations"), (
            f"{qa_id} doc_link should land on the evaluations guide; "
            f"got {by_id[qa_id].doc_link!r}"
        )


# ----------------------------------------------------------- PUB deep links


def test_pub_001_links_to_studio_alm_for_export():
    by_id = _results_by_id(_runner(env_id="env-abc", agentbuilder=None))
    text = by_id["PUB-001"].remediation
    assert "https://copilotstudio.microsoft.com/environments/env-abc/" in text, (
        f"PUB-001 must deep-link to Copilot Studio so the operator can "
        f"export the agent ALM package; got: {text!r}"
    )
    # And the operator is told what to actually click.
    assert "Settings" in text and "ALM" in text and "package .zip" in text


def test_pub_002_describes_target_environment_import():
    text = _results_by_id(_runner(agentbuilder=None))["PUB-002"].remediation
    # The action happens in a *different* environment than the kit
    # was pointed at, so we can't deep-link — but we must say where.
    assert "test environment" in text.lower()
    assert "ALM package" in text and "Copilot Studio" in text


def test_pub_003_is_explicitly_organizational():
    """No portal link applies. The remediation must own that fact so
    the operator doesn't search for a non-existent maker page."""
    text = _results_by_id(_runner())["PUB-003"].remediation
    assert "organizational gate" in text.lower()
    assert "sign-off" in text.lower() or "sign off" in text.lower()


def test_pub_006_links_to_m365_admin_integrated_apps():
    text = _results_by_id(_runner())["PUB-006"].remediation
    expected = (
        "https://admin.microsoft.com/Adminportal/Home#/Settings/IntegratedApps"
    )
    assert expected in text, (
        f"PUB-006 must deep-link to M365 admin → Integrated apps so a "
        f"tenant admin can approve the publish request; got: {text!r}"
    )


def test_pub_011_is_informational_with_no_action_at_publish_time():
    text = _results_by_id(_runner())["PUB-011"].remediation
    # Operators should see explicitly that this row needs no action.
    assert "no action" in text.lower(), (
        f"PUB-011 is a heads-up; the remediation must say no action is "
        f"required at publish time; got: {text!r}"
    )
    # And still link to where to check status if rollout drags.
    assert "Integrated apps" in text


# ----------------------------------------------------------- PUB API checks


def test_pub_001_passes_when_export_returns_valid_archive():
    from flightcheck.runner import Status

    client = _FakeAgentBuilder()
    by_id = _results_by_id(_runner(agentbuilder=client))

    row = by_id["PUB-001"]
    assert row.status == Status.PASSED.value
    assert "valid zip package" in row.result
    assert "bot-xyz" in row.result
    assert row.remediation == ""
    assert client.export_calls[0][0] == "bot-xyz"


def test_pub_001_fails_when_export_archive_is_corrupt():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(agentbuilder=_FakeAgentBuilder(export_bytes=b"PK\x03\x04junk"))
    )

    row = by_id["PUB-001"]
    assert row.status == Status.FAILED.value
    assert "not a valid zip archive" in row.result
    assert "central directory and CRC checks pass" in row.remediation


def test_pub_001_fails_when_export_archive_has_posix_absolute_entry():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(agentbuilder=_FakeAgentBuilder(export_bytes=_zip_bytes("/evil")))
    )

    row = by_id["PUB-001"]
    assert row.status == Status.FAILED.value
    assert "unsafe entry '/evil'" in row.result
    assert "readable .zip package" in row.remediation


def test_pub_001_fails_when_export_returns_4003_not_opted_in():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(
            agentbuilder=_FakeAgentBuilder(
                export_error=_agentbuilder_http_error(
                    status_code=400,
                    error_code="4003",
                )
            )
        )
    )

    row = by_id["PUB-001"]
    assert row.status == Status.FAILED.value
    assert "not enrolled in ALM" in row.result
    assert "Settings > ALM" in row.remediation


def test_pub_001_warns_on_export_http_error():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(
            agentbuilder=_FakeAgentBuilder(
                export_error=_agentbuilder_http_error(
                    status_code=500,
                    error_code="ExportFailed",
                )
            )
        )
    )

    row = by_id["PUB-001"]
    assert row.status == Status.WARNING.value
    assert "ALM export failed" in row.result
    assert "re-run PUB-001" in row.remediation


def test_pub_001_skips_without_bot_id():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(bot_id=None, agentbuilder=_FakeAgentBuilder())
    )

    row = by_id["PUB-001"]
    assert row.status == Status.SKIPPED.value
    assert "No configured agent botId" in row.result
    assert ".local/config.json" in row.remediation


def test_pub_002_passes_when_import_returns_valid_identity():
    from flightcheck.runner import Status

    client = _FakeAgentBuilder()
    by_id = _results_by_id(
        _runner(agentbuilder=client, alm_import_probe=True)
    )

    row = by_id["PUB-002"]
    assert row.status == Status.PASSED.value
    assert "ALM import created agent" in row.result
    assert "gptagent_mockemployeeselfservice_imported" in row.result
    assert row.remediation == ""
    assert client.import_calls


def test_pub_002_skips_import_probe_when_not_opted_in_with_client_present():
    from flightcheck.runner import Status

    client = _FakeAgentBuilder()
    by_id = _results_by_id(
        _runner(agentbuilder=client, alm_import_probe=False)
    )

    row = by_id["PUB-002"]
    assert row.status == Status.SKIPPED.value
    assert "import probe was not explicitly enabled" in row.result
    assert "throwaway environment" in row.remediation
    assert not client.import_calls


def test_pub_002_fails_on_same_environment_import_conflict():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(
            agentbuilder=_FakeAgentBuilder(
                import_error=_agentbuilder_http_error(
                    status_code=409,
                    error_code="DuplicateItemError",
                )
            ),
            alm_import_probe=True,
        )
    )

    row = by_id["PUB-002"]
    assert row.status == Status.FAILED.value
    assert "HTTP 409" in row.result
    assert "already contain this exported agent" in row.remediation


def test_pub_002_fails_when_import_returns_4003_not_opted_in():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(
            agentbuilder=_FakeAgentBuilder(
                import_error=_agentbuilder_http_error(
                    status_code=400,
                    error_code="4003",
                )
            ),
            alm_import_probe=True,
        )
    )

    row = by_id["PUB-002"]
    assert row.status == Status.FAILED.value
    assert "not enrolled in ALM" in row.result
    assert "throwaway environment" in row.remediation


def test_pub_002_warns_on_import_http_error():
    from flightcheck.runner import Status

    by_id = _results_by_id(
        _runner(
            agentbuilder=_FakeAgentBuilder(
                import_error=_agentbuilder_http_error(
                    status_code=500,
                    error_code="ImportFailed",
                )
            ),
            alm_import_probe=True,
        )
    )

    row = by_id["PUB-002"]
    assert row.status == Status.WARNING.value
    assert "ALM import failed" in row.result
    assert "import permission" in row.remediation


def test_pub_002_skips_without_client_or_bot_id():
    from flightcheck.runner import Status

    no_client = _results_by_id(_runner(alm_import_probe=True))["PUB-002"]
    no_bot = _results_by_id(
        _runner(
            bot_id=None,
            agentbuilder=_FakeAgentBuilder(),
            alm_import_probe=True,
        )
    )["PUB-002"]

    assert no_client.status == Status.SKIPPED.value
    assert "AgentBuilder ALM client is unavailable" in no_client.result
    assert "authenticates the Copilot Studio AgentBuilder" in no_client.remediation
    assert no_bot.status == Status.SKIPPED.value
    assert "No configured agent botId" in no_bot.result
    assert ".local/config.json" in no_bot.remediation
