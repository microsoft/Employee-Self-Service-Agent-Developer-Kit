# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural contracts for the Dataverse flow-authorization tooling."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALM_DIR = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
    / "alm"
)
_SCRIPT = _ALM_DIR / "Enable-CosmosDAFlowAuthorization.ps1"


def _script_text() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def test_preview_uses_should_process_for_every_mutation() -> None:
    script = _script_text()

    assert "[CmdletBinding(SupportsShouldProcess = $true)]" in script
    assert script.count("$PSCmdlet.ShouldProcess(") == 3
    assert "$PSCmdlet.ShouldProcess(\"delegatedauthorization" in script
    assert "$PSCmdlet.ShouldProcess(\"access team" in script
    assert "$PSCmdlet.ShouldProcess(\"workflow" in script


def test_create_requests_capture_returned_record_ids() -> None:
    script = _script_text()

    assert "Prefer             = 'return=representation'" in script
    assert "$daId = $r.delegatedauthorizationid" in script
    assert "$teamId = $r.teamid" in script


def test_ambiguous_authorization_records_fail_closed() -> None:
    script = _script_text()

    assert "if ($daExisting.Count -gt 1)" in script
    assert "if ($teamExisting.Count -gt 1)" in script
    assert "expected exactly one" in script
    assert "$verifiedTeamId = $null" in script
    assert "$ok = $false" in script


def test_token_fallback_uses_the_kit_authentication_helper() -> None:
    script = _script_text()
    helper = (_ALM_DIR / "get_dataverse_token.py").read_text(encoding="utf-8")

    assert "Test-DataverseToken" in script
    assert "get_dataverse_token.py" in script
    assert script.count("Test-DataverseToken -Resource $Resource -Token $tok") == 2
    assert "returned a token that was rejected" in script
    assert "auth.authenticate(args.environment.rstrip(\"/\"))" in helper
