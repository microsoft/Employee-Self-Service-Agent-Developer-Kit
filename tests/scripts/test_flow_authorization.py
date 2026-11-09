# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural contracts for the Dataverse flow-authorization tooling."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

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
    assert "token = auth.authenticate(" in helper
    assert 'args.environment.rstrip("/")' in helper
    assert "preferred_username=args.preferred_username" in helper


def test_token_helper_rejects_mismatched_identity_without_emitting_token(
    monkeypatch,
    capsys,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "get_dataverse_token_test",
        _ALM_DIR / "get_dataverse_token.py",
    )
    assert spec and spec.loader
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    monkeypatch.setattr(
        helper.auth,
        "authenticate",
        lambda *_args, **_kwargs: "secret-token",
    )
    monkeypatch.setattr(
        helper,
        "require_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            helper.WorkdayConnectIdentityError("different account")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "get_dataverse_token.py",
            "--environment",
            "https://example.crm.dynamics.com",
            "--preferred-username",
            "maker@example.com",
        ],
    )

    assert helper.main() == 1
    captured = capsys.readouterr()
    assert "different account" in captured.err
    assert "secret-token" not in captured.out
    assert "secret-token" not in captured.err


def test_authorization_uses_first_python_when_multiple_applications_are_found(tmp_path):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is not installed.")
    helper = tmp_path / "fake-python.ps1"
    helper.write_text(
        "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)\n"
        "$global:LASTEXITCODE=0\n'ESS_DATAVERSE_TOKEN=fixture-token'\n",
        encoding="utf-8",
    )
    (tmp_path / "get_dataverse_token.py").write_text("", encoding="utf-8")
    script_path = str(_SCRIPT).replace("'", "''")
    helper_path = str(helper).replace("'", "''")
    probe = tmp_path / "probe.ps1"
    probe.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$tokens=$null; $errors=$null\n"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{script_path}',"
        "[ref]$tokens,[ref]$errors)\n"
        "$definition=$ast.Find({param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] "
        "-and $node.Name -eq 'Get-DataverseToken'},$true)\n"
        "$functionFile=Join-Path $PSScriptRoot 'token-function.ps1'\n"
        "Set-Content -Path $functionFile -Value $definition.Extent.Text -Encoding UTF8\n"
        ". $functionFile\n"
        "function Test-DataverseToken { param($Resource,$Token) return $true }\n"
        "function Get-Command { param($Name,$CommandType,$ErrorAction)\n"
        f"@([pscustomobject]@{{Source='{helper_path}'}},"
        "[pscustomobject]@{Source='nonexistent-python.exe'}) }\n"
        "$token=Get-DataverseToken -Resource 'https://example.invalid' "
        "-PreferredUsername 'maker@example.com'\n"
        "if ($token -ne 'fixture-token') { throw 'Unexpected helper result.' }\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(probe)],
        capture_output=True, text=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stderr


def test_candidate_tokens_are_attached_to_dataverse_requests() -> None:
    script = _script_text()

    assert 'Authorization = "Bearer $Token"' in script
    assert 'Authorization      = "Bearer $script:Token"' in script


def test_all_requested_workflows_are_validated_before_mutation() -> None:
    script = _script_text()

    preflight = script.index("$workflowRows = @{}")
    mutation = script.index('Write-Step "Step 2/4')
    assert preflight < mutation
    assert "$missingWorkflow = $true" in script
    assert "No authorization records were changed." in script
    assert "workflow $wf not found in this organization - skipping" not in script


@pytest.mark.parametrize("scenario", [
    "new", "old-agent", "legacy", "partial", "authorization-race", "team-race",
    "foreign-name", "foreign-team-race", "duplicate-authorization", "duplicate-team",
    "wrong-provider", "wrong-team-type", "foreign-link", "read-failed", "whatif",
    "expected-team-drift",
])
def test_authorization_script_reuses_only_exact_agent_records(tmp_path, scenario):
    """Execute the real script, replacing only its token and HTTP transports."""
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is not installed.")
    probe = tmp_path / "authorization-probe.ps1"
    state_file = tmp_path / "state.json"
    probe.write_text(
        r"""
$ErrorActionPreference = 'Stop'
$scenario = '__SCENARIO__'
$bot = '11111111-1111-1111-1111-111111111111'
$authorization = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
$team = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
$unit = '44444444-4444-4444-4444-444444444444'
$foreign = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
$name = "ESS DA HR Workday - Development - $bot"
$global:Fixture = @{
    Scenario = $scenario; Bot = $bot; Authorization = $authorization
    Team = $team; Unit = $unit; Name = $name
    Authorizations = @(); Teams = @(); Shares = @()
    Writes = [System.Collections.Generic.List[string]]::new()
}
$row = @{ delegatedauthorizationid = $authorization; botid = $bot; providertype = 3 }
if ($scenario -in @(
    'legacy', 'partial', 'duplicate-authorization', 'duplicate-team', 'wrong-provider',
    'wrong-team-type', 'foreign-link', 'expected-team-drift'
)) {
    $global:Fixture.Authorizations = @($row)
}
if ($scenario -eq 'wrong-provider') { $row.providertype = 2 }
if ($scenario -eq 'duplicate-authorization') { $global:Fixture.Authorizations += $row.Clone() }
if ($scenario -in @('legacy', 'duplicate-team', 'wrong-team-type', 'foreign-link', 'expected-team-drift')) {
    $global:Fixture.Teams = @(@{
        teamid = $team; name = $name; teamtype = 1
        _delegatedauthorizationid_value = $authorization; _businessunitid_value = $unit
    })
}
if ($scenario -eq 'legacy') {
    $name = 'ESS DA HR Workday - Development'
    $global:Fixture.Teams[0].name = $name
}
if ($scenario -eq 'duplicate-team') { $global:Fixture.Teams += $global:Fixture.Teams[0].Clone() }
if ($scenario -eq 'wrong-team-type') { $global:Fixture.Teams[0].teamtype = 0 }
if ($scenario -eq 'foreign-link') { $global:Fixture.Teams[0]._delegatedauthorizationid_value = $foreign }
if ($scenario -in @('old-agent', 'foreign-name')) {
    $global:Fixture.Authorizations += @{
        delegatedauthorizationid = $foreign; botid = $foreign; providertype = 3
    }
    $global:Fixture.Teams += @{
        teamid = $foreign; name = $(if ($scenario -eq 'old-agent') {
            'ESS DA HR Workday - Development'
        } else { $name }); teamtype = 1
        _delegatedauthorizationid_value = $foreign; _businessunitid_value = $unit
    }
}
$tokenMock = @'
function Get-DataverseToken { param($Resource, $PreferredUsername) return 'fixture-token' }
'@
$httpMock = @'
function Invoke-Dv {
    param([string]$Method = 'GET', [string]$Path, $Body)
    $f = $global:Fixture
    if ($Method -ne 'GET') { $f.Writes.Add("${Method}:$Path") }
    if ($Path -eq 'WhoAmI') { return @{ UserId = $f.Team; OrganizationId = $f.Unit } }
    if ($Path.StartsWith('workflows?')) {
        return @{ value = @(@{ workflowid = $f.Unit; name = 'Read Workday'; statecode = 1 }) }
    }
    if ($Method -eq 'POST' -and $Path.StartsWith('delegatedauthorizations?')) {
        $row = @{
            delegatedauthorizationid = $f.Authorization; botid = $Body.botid
            providertype = $Body.providertype
        }
        $f.Authorizations += $row
        if ($f.Scenario -eq 'authorization-race') { throw 'Concurrent creation' }
        return $row
    }
    if ($Path.StartsWith('delegatedauthorizations?')) {
        if ($f.Scenario -eq 'read-failed') { throw '403 Forbidden' }
        if (-not $Path.Contains("botid eq '$($f.Bot)'")) { throw 'Unscoped authorization read' }
        return @{ value = @($f.Authorizations | Where-Object { $_.botid -eq $f.Bot }) }
    }
    if ($Method -eq 'POST' -and $Path.StartsWith('teams?')) {
        $row = @{
            teamid = $f.Team; name = $Body.name; teamtype = $Body.teamtype
            _delegatedauthorizationid_value = $f.Authorization; _businessunitid_value = $f.Unit
        }
        if ($f.Scenario -eq 'foreign-team-race') {
            $row._delegatedauthorizationid_value = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
        }
        $f.Teams += $row
        if ($f.Scenario -in @('team-race', 'foreign-team-race')) {
            throw 'ndx_TeamName_BusinessUnitId'
        }
        return $row
    }
    if ($Path.StartsWith('teams?')) {
        if ($Path.Contains('delegatedauthorizationid/botid')) {
            if (-not $Path.Contains("botid eq '$($f.Bot)'")) { throw 'Unscoped team read' }
            if ($f.Scenario -eq 'foreign-link') { return @{ value = $f.Teams } }
            $owners = @($f.Authorizations | Where-Object { $_.botid -eq $f.Bot })
            return @{ value = @($f.Teams | Where-Object {
                $owners.delegatedauthorizationid -contains $_._delegatedauthorizationid_value
            }) }
        }
        if ($Path -match "and name eq '([^']+)'$") {
            $proposedName = $Matches[1]
            if (-not $Path.Contains("_businessunitid_value eq $($f.Unit)")) { throw 'Unscoped name read' }
            return @{ value = @($f.Teams | Where-Object {
                $_.name -eq $proposedName -and $_._businessunitid_value -eq $f.Unit
            }) }
        }
    }
    if ($Path.StartsWith('roles?')) { return @{ value = @(@{ roleid = $f.Unit }) } }
    if ($Path.StartsWith('systemusers?')) { return @{ value = @(@{ systemuserid = $f.Unit }) } }
    if ($Path.Contains('RetrieveSharedPrincipalsAndAccess')) { return @{ PrincipalAccesses = $f.Shares } }
    if ($Path -eq 'GrantAccess') {
        $f.Shares += @{
            Principal = @{ '@odata.type' = 'Microsoft.Dynamics.CRM.team'; ownerid = $Body.PrincipalAccess.Principal.teamid }
            AccessMask = $Body.PrincipalAccess.AccessMask
        }
        return @{}
    }
    throw "Unexpected transport call: $Method $Path"
}
'@
$tokens = $null; $errors = $null
$source = Get-Content -Raw '__SCRIPT__'
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$functions = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Get-DataverseToken', 'Invoke-Dv')
}, $true)
foreach ($function in ($functions | Sort-Object { $_.Extent.StartOffset } -Descending)) {
    $replacement = if ($function.Name -eq 'Get-DataverseToken') { $tokenMock } else { $httpMock }
    $source = $source.Remove($function.Extent.StartOffset, $function.Extent.Text.Length).Insert(
        $function.Extent.StartOffset, $replacement
    )
}
$copy = Join-Path $PSScriptRoot 'authorization.ps1'
Set-Content -Path $copy -Value $source -Encoding UTF8
$arguments = @{
    OrgUrl = 'https://example.invalid'; BotId = $bot; WorkflowId = @($unit)
    TeamName = $name; BusinessUnitId = $unit
}
if ($scenario -eq 'whatif') { $arguments.WhatIf = $true }
if ($scenario -eq 'expected-team-drift') { $arguments.ExpectedTeamId = $foreign }
try {
    & $copy @arguments
    $scriptExitCode = $LASTEXITCODE
} finally {
    $global:Fixture | ConvertTo-Json -Depth 10 | Set-Content -Path '__STATE__' -Encoding UTF8
}
exit $scriptExitCode
""".replace("__SCENARIO__", scenario)
        .replace("__SCRIPT__", str(_SCRIPT).replace("'", "''"))
        .replace("__STATE__", str(state_file).replace("'", "''")),
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(probe)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    state = json.loads(state_file.read_text(encoding="utf-8-sig"))
    writes = state["Writes"]
    output = result.stdout + result.stderr
    if scenario in {
        "new", "old-agent", "legacy", "partial", "authorization-race", "team-race",
    }:
        assert result.returncode == 0, output
        assert "Dataverse authorization is in place." in output
        assert len(state["Shares"]) == 1
        if scenario == "legacy":
            assert not any("teams?" in write for write in writes)
            assert state["Teams"][0]["name"] == "ESS DA HR Workday - Development"
        elif scenario == "partial":
            assert not any("delegatedauthorizations?" in write for write in writes)
        elif scenario == "old-agent":
            assert len(state["Teams"]) == 2
            assert state["Teams"][0]["name"] == "ESS DA HR Workday - Development"
            assert state["Teams"][1]["name"].endswith(state["Bot"])
        if scenario in {"authorization-race", "team-race"}:
            assert sum("teams?" in write for write in writes) == 1
            assert sum("delegatedauthorizations?" in write for write in writes) == 1
    else:
        assert result.returncode != 0, output
        assert "Dataverse authorization is in place." not in output
        assert state["Shares"] == []
        if scenario == "foreign-team-race":
            assert sum("teams?" in write for write in writes) == 1
            assert "ndx_TeamName_BusinessUnitId" in output
        else:
            assert writes == [], output
        if scenario == "foreign-name":
            assert "[WD-AUTH-TEAM-NAME-CONFLICT]" in output
        if scenario == "whatif":
            assert "would create delegatedauthorization" in output
            assert "would create access team" in output
