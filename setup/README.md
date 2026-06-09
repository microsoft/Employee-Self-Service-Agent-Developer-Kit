# ESS ADK — One-Shot Installer

A single command that installs everything needed for the ESS Maker Kit: VS Code, Python 3.12, Git, GitHub CLI, Copilot extensions, pip dependencies, and clones the repo.

**Windows** (PowerShell):

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1)
```

**macOS** (Terminal):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-mac.sh)"
```

Once complete, VS Code opens at `solutions/ess-maker-skills/`. Run `/setup` in Copilot Chat to connect your Dataverse environment.

> **GitHub Copilot subscription is required** for the in-editor maker experience. This script installs the toolchain and extension scaffolding; it does not grant the Copilot entitlement.

## GitHub Codespaces (no local install)

> **Free tier available:** GitHub accounts include [120 core-hours/month of free Codespaces usage](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-codespaces/about-billing-for-github-codespaces#monthly-included-storage-and-core-hours-for-personal-accounts) (60 hours on a 2-core machine). Compute is only billed while the Codespace is running — it stops automatically after 30 minutes of inactivity. For organizational accounts, your admin may need to enable Codespaces — see [managing Codespaces for your organization](https://docs.github.com/en/codespaces/managing-codespaces-for-your-organization).

For users who prefer a cloud-based development environment — no local toolchain or VS Code desktop install required. Just a browser and a GitHub account:

👉 [**Create Codespace**](https://github.com/codespaces/new?repo=microsoft/Employee-Self-Service-Agent-Developer-Kit&ref=main&devcontainer_path=.devcontainer%2Fdevcontainer.json)

The Codespace comes pre-configured with Python 3.12, pip dependencies, and GitHub Copilot. Select the **2-core** machine type (sufficient for the maker kit). Once it starts:

1. Open the `solutions/ess-maker-skills` folder (File → Open Folder → `/workspaces/Employee-Self-Service-Agent-Developer-Kit/solutions/ess-maker-skills`)
2. Run `/setup` in Copilot Chat to connect your Dataverse environment

### FlightCheck via Codespaces

The same Codespace environment can be used to run FlightCheck without the full maker kit setup. After creating the Codespace above:

1. Open the `solutions/ess-maker-skills` folder (File → Open Folder → `/workspaces/Employee-Self-Service-Agent-Developer-Kit/solutions/ess-maker-skills`)
2. Open a terminal and run:
   ```bash
   python scripts/flightcheck/cli.py --scope full
   ```
3. Follow the prompts to sign in and select your environment

## FlightCheck-Only Mode

For users who want to run a pre-deployment readiness check on their Power Platform environment — no coding tools or VS Code required. Just run this command:

**Windows** (PowerShell):

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck.ps1)
```

**macOS** (Terminal):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck-mac.sh)"
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

**Windows:**
```powershell
cd $env:USERPROFILE\source\Employee-Self-Service-Agent-Developer-Kit\solutions\ess-maker-skills
python scripts/flightcheck/cli.py --scope full
```

**macOS:**
```bash
cd ~/source/Employee-Self-Service-Agent-Developer-Kit/solutions/ess-maker-skills
../../.venv/bin/python scripts/flightcheck/cli.py --scope full
```

## Files

| File | Purpose |
|---|---|
| `Install-EssAdk.ps1` | Windows orchestrator. Installs toolchain via winget, pip dependencies, clones repo, installs extensions, launches VS Code. With `-FlightCheckOnly`, installs minimal toolchain and runs FlightCheck. |
| `install-ess-adk.sh` | macOS orchestrator. Same as above but uses Homebrew. Set `FLIGHTCHECK_ONLY=true` for FlightCheck-only mode. |
| `bootstrap.ps1` | Windows one-liner entry point (full maker kit). |
| `bootstrap-flightcheck.ps1` | Windows one-liner entry point (FlightCheck only). |
| `bootstrap-mac.sh` | macOS one-liner entry point (full maker kit). |
| `bootstrap-flightcheck-mac.sh` | macOS one-liner entry point (FlightCheck only). |
| `ess-adk-setup.winget.yaml` | Declarative DSC config consumed by `winget configure` (optional Windows path). |
| `.devcontainer/devcontainer.json` | Codespace configuration. Pre-installs Python 3.12, pip dependencies, and Copilot extensions. |

## Dependencies

The installer provisions the following dependencies. Users do not need to install these manually — the one-shot installer or Codespace handles everything.

### System tools (installed via winget on Windows / Homebrew on macOS)

| Tool | Version | Purpose | FlightCheck only? |
|------|---------|---------|:-----------------:|
| Python | 3.12 | Runtime for FlightCheck and maker scripts | ✅ |
| Git | Latest | Clone the repo, version control | ✅ |
| GitHub CLI (`gh`) | Latest | Device-code auth flow for private repo clone | ❌ |
| VS Code | Latest | Editor and Copilot host | ❌ |
| PowerShell 7 | Latest | Script execution (Windows only) | ❌ |

### Python packages (installed via pip from `scripts/requirements.txt`)

| Package | Purpose |
|---------|---------|
| `msal` | Microsoft Authentication Library — Entra ID auth for FlightCheck |
| `requests` | HTTP client for Dataverse / Graph API calls |
| `urllib3` | HTTP transport layer (requests dependency, pinned) |
| `PyYAML` | YAML parsing for topic schema validation |
| `defusedxml` | Safe XML parsing for Workday SOAP responses (XXE-hardened) |

### VS Code extensions

| Extension | Purpose |
|-----------|---------|
| `GitHub.copilot` | GitHub Copilot AI completions |
| `GitHub.copilot-chat` | Copilot Chat — the primary maker interface |
| `ms-python.python` | Python language support, linting, debugging |

### Codespaces environment

The devcontainer provides an equivalent pre-built environment:
- **Base image:** `mcr.microsoft.com/devcontainers/python:3.12` (includes Python, git, common dev tools)
- **Python packages:** Installed from `scripts/requirements.txt` via `postCreateCommand`
- **VS Code extensions:** Copilot, Copilot Chat, Python (specified in `customizations.vscode.extensions`)
- **Additional features:** GitHub CLI (via devcontainer features)

## How to test it locally

### Windows

From this folder:

```powershell
# Run the full installer end-to-end:
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -InstallRoot $env:USERPROFILE\source-test
```

Useful flags during testing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -SkipExtensions      # skip code --install-extension calls
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -SkipClone           # skip git clone (toolchain only)
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -SkipLaunch          # don't open VS Code at the end
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1 -FlightCheckOnly     # minimal install for FlightCheck only
```

For air-gapped / locked-down environments, IT can mirror the files internally and serve them from an intranet URL by passing `-SourceBaseUrl`.

### macOS

From this folder:

```bash
# Full installer:
bash install-ess-adk.sh

# FlightCheck only:
FLIGHTCHECK_ONLY=true bash install-ess-adk.sh

# Custom install location:
ESS_ADK_INSTALL_ROOT=~/projects bash install-ess-adk.sh

# Test against a branch:
ESS_ADK_BRANCH=my-feature bash install-ess-adk.sh
```

For air-gapped environments, set `ESS_ADK_SOURCE_URL` in the bootstrap scripts to point at your internal mirror.
