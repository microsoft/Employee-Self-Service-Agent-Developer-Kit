# Set up the ESS Declarative Agent

Use this page if you are a maker setting up or customizing an Employee Self-Service (ESS) Declarative Agent.

> [!IMPORTANT]
>
> Already have a customized ESS Custom Engine Agent? Use the separate [Custom Engine Agent to Declarative Agent migration guidance](../../tools/ess-ca-to-da/README.md) instead of starting with this installer.

## Before you start

You need:

- A GitHub account with an active GitHub Copilot subscription.
- A Microsoft work account that can access the target Power Platform environment and ESS agent.
- PowerShell on Windows or Terminal on macOS. Run the installer as your normal user; do not start the shell as an administrator.

The installer does not grant service access or administrator roles. During `/setup`, the kit identifies any login, environment role, consent, or administrator handoff required for the operation you are performing.

## Install the maker kit

Run the command for your operating system.

**Windows** (PowerShell):

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1)
```

**macOS** (Terminal):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-mac.sh)"
```

When the installer asks which experience you want, choose **Maker** for the recommended guided experience.

## What happens next

1. The installer prepares VS Code, Python, Git, GitHub CLI, the .NET runtime, NuGet, the Copilot extensions, and the maker-kit dependencies.
2. VS Code opens the `solutions\ess-maker-skills` workspace. Review the workspace trust prompt before accepting it.
3. Sign in to GitHub Copilot with the GitHub account that has your Copilot subscription. This enables Copilot Chat; it does not grant access to Power Platform.
4. In the **Quick start** panel, select **Start setup**. This opens Copilot Chat and submits `/setup`.
5. Approve the local setup commands you want VS Code to run. When a separate browser window opens, sign in with the Microsoft work account that can access the target Power Platform environment and agent.
6. Follow the setup choices to select the environment and agent and prepare the local workspace.

## If setup does not start or pauses

- If VS Code does not open, open it manually and select the repository's `solutions\ess-maker-skills` folder.
- If Copilot Chat or setup does not open, select **Start setup** in **Quick start**, or open Copilot Chat and enter `/setup`.
- If workspace trust, sign-in, or command approval interrupts setup, complete the prompt, return to Copilot Chat, and enter `/setup` again. Setup continues from saved progress when available.

For Developer mode, GitHub Codespaces, FlightCheck-only installation, and other advanced options, see the [complete installation guide](../../setup/README.md).
