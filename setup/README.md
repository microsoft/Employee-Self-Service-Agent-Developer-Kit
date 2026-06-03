# ESS ADK — One-Shot Installer

A single PowerShell command that takes a customer from a clean Windows machine to a ready-to-use ESS Maker Kit workspace in VS Code.

## What this delivers

The customer experience goes from:

> Install VS Code → Install Python → Install PowerShell 7 → Install Git → Install GitHub & Copilot extensions → Sign in → Clone repo → Open folder → Run `/setup`

to:

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1)
```

...and they land in VS Code at `solutions/ess-maker-skills/` with everything wired up except the final Dataverse auth step (`/setup` in Copilot Chat).

> **GitHub Copilot subscription is still required** for the in-editor maker experience. This script installs the toolchain and extension scaffolding; it does not (and cannot) grant the Copilot entitlement.

## GitHub Codespaces (no local install)

> **GitHub Codespaces is a paid feature.** Usage is billed to your GitHub account or organization. See [GitHub Codespaces pricing](https://github.com/features/codespaces#pricing) for details.

For users who prefer a cloud-based development environment — no local toolchain or VS Code desktop install required. Just a browser and a GitHub account with Codespaces access:

👉 [**Create Codespace**](https://github.com/codespaces/new?repo=microsoft/Employee-Self-Service-Agent-Developer-Kit&ref=main&devcontainer_path=.devcontainer%2Fdevcontainer.json)

The Codespace comes pre-configured with Python 3.12, pip dependencies, GitHub Copilot, and opens directly in the `solutions/ess-maker-skills` workspace. Once it starts, run `/setup` in Copilot Chat to connect Dataverse.

## FlightCheck-Only Mode

For users who want to run a pre-deployment readiness check on their Power Platform environment — no coding tools or VS Code required. Just run this command in PowerShell:

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck.ps1)
```

That's it. The script handles everything automatically:

1. Installs Python and Git (if not already present)
2. Opens a browser window for you to sign in with your Microsoft work account
3. Shows your available environments — pick one by number
4. Shows the agents in that environment — pick one (or skip)
5. Runs the full FlightCheck validation and displays results

### Changing your environment or agent

Re-run the same command — it will ask if you want to reconfigure:

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck.ps1)
```

### Running FlightCheck again (after initial setup)

Once you've run the installer once, you can re-run FlightCheck directly without going through setup again:

```powershell
cd $env:USERPROFILE\source\Employee-Self-Service-Agent-Developer-Kit\solutions\ess-maker-skills
python scripts/flightcheck/cli.py --scope full
```

## Files

| File | Purpose |
|---|---|
| `ess-adk-setup.winget.yaml` | Declarative DSC config consumed by `winget configure`. Installs VS Code, Python 3.12, PowerShell 7, Git, GitHub CLI. |
| `Install-EssAdk.ps1` | Orchestrator. Installs toolchain via winget, installs pip dependencies, clones the repo, installs VS Code extensions, launches VS Code. Idempotent. With `-FlightCheckOnly`, installs minimal toolchain and runs interactive environment/agent discovery. |
| `bootstrap.ps1` | One-liner entry point for the full maker kit install. Downloads the installer into `$env:TEMP` and runs it. |
| `bootstrap-flightcheck.ps1` | One-liner entry point for FlightCheck-only install. Downloads the installer and runs it with `-FlightCheckOnly`. |
| `.devcontainer/devcontainer.json` | Codespace configuration. Pre-installs Python 3.12, pip dependencies, Copilot extensions, and sets the workspace folder. |

## How to test it locally (without publishing anything)

> **PowerShell execution policy note.** Windows ships with `Restricted` by default, which blocks `.ps1` files loaded from disk. If you see *"running scripts is disabled on this system"*, use one of these instead of `.\Install-EssAdk.ps1`:
>
> ```powershell
> # One-shot bypass (recommended for one-off runs, no persistent change):
> powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1
>
> # OR enable signed scripts for the current user only (persists):
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> .\Install-EssAdk.ps1
>
> # OR run the bootstrap directly from memory — execution policy does not apply
> # because the script body is piped to Invoke-Expression and never hits disk:
> iex (Get-Content .\bootstrap.ps1 -Raw)
> ```
>
> The published customer entry point (`iex (irm ...)`) uses the third pattern, so end users will not hit this error.

From this folder:

```powershell
# Validate the winget DSC file in isolation:
winget configure validate --file .\ess-adk-setup.winget.yaml

# Or run the full installer end-to-end (note the -ExecutionPolicy Bypass):
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -InstallRoot $env:USERPROFILE\source-test
```

Useful flags during testing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -SkipExtensions      # skip code --install-extension calls
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -SkipClone           # skip git clone (toolchain only)
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -SkipLaunch          # don't open VS Code at the end
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -FlightCheckOnly     # minimal install for FlightCheck only
```

## Customer-facing commands

Full maker kit install (VS Code + Copilot + everything):

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1)
```

FlightCheck-only (no VS Code or Copilot required):

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck.ps1)
```

For customers who prefer to inspect first:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1" -OutFile bootstrap.ps1 -UseBasicParsing
# review bootstrap.ps1
.\bootstrap.ps1
```

For air-gapped / locked-down environments, IT can mirror the files internally and serve them from an intranet URL by passing `-SourceBaseUrl`.

## Design choices worth flagging in review

1. **No admin elevation required by default.** `winget configure` will UAC-prompt only for packages that need it (Python, VS Code system installer). If the customer can't elevate, they can pre-install those via Intune/Company Portal and re-run the script — it'll skip the present packages and continue.
2. **Separate winget YAML vs. PowerShell orchestrator.** The YAML is the IT-reviewable artifact (admins can audit/mirror it). The PS1 handles the "non-declarative" bits (VS Code extensions, git clone, launch) that winget DSC can't cleanly express today.
3. **Pinned Python version (`Python.Python.3.12`)** rather than latest, to match what the kit's `requirements.txt` is tested against. Update in lockstep with upstream.
4. **GitHub CLI included** primarily so the device-code auth flow works smoothly when the Copilot extension signs in.
5. **Idempotent.** Re-running fixes a partial install; we never delete or downgrade.

## Open items before this can ship

- [ ] Confirm exact Python version the kit pins to (3.11 vs 3.12).
- [ ] Decide if we ship a VS Code workspace file in the repo so we can open `.code-workspace` instead of a folder.
- [ ] Add an MSRC-aligned signing story for `Install-EssAdk.ps1` (or document `-ExecutionPolicy Bypass` invocation).
