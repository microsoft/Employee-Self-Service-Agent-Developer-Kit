<#
.SYNOPSIS
    Opens a GitHub Codespace for the ESS Maker Kit.

.DESCRIPTION
    Launches the Codespace creation page in the user's default browser.
    No local installation is required -- the dev environment runs entirely
    in the cloud with Python, pip dependencies, and Copilot extensions
    pre-configured.

    Designed to be invoked from a single command:

        iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-codespaces.ps1)

.PARAMETER Branch
    Branch to open the Codespace on. Defaults to "main".
#>

[CmdletBinding()]
param(
    [string] $Branch = 'main'
)

$ErrorActionPreference = 'Stop'

$repo = 'microsoft/Employee-Self-Service-Agent-Developer-Kit'
$url = "https://github.com/codespaces/new?repo=$repo&ref=$Branch&devcontainer_path=.devcontainer%2Fdevcontainer.json"

Write-Host ''
Write-Host '==> Opening GitHub Codespaces' -ForegroundColor Cyan
Write-Host ''
Write-Host '    No local install needed -- your dev environment runs in the cloud.' -ForegroundColor White
Write-Host '    A browser window will open to create your Codespace.' -ForegroundColor Gray
Write-Host ''
Write-Host "    URL: $url" -ForegroundColor Gray
Write-Host ''

Start-Process $url

Write-Host '    [ok] Browser launched. Follow the prompts to create your Codespace.' -ForegroundColor Green
Write-Host '    Once it opens, run /setup in Copilot Chat to connect Dataverse.' -ForegroundColor Green
Write-Host ''
