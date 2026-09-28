# Employee Self-Service Agent Developer Kit

A monorepo of solutions, samples, and tooling for the Microsoft Employee Self-Service (ESS) agent built on Microsoft Copilot Studio.

> **This repo is intended as an example or learning tool.** It is not a Microsoft product or a supported service. See [SUPPORT.md](SUPPORT.md) for the support model and [SECURITY.md](SECURITY.md) for reporting security issues.

## Getting started

One command installs everything (VS Code, Python 3.12, Git, GitHub CLI, .NET runtime, NuGet, Copilot extensions, pip dependencies) and opens `ess-maker-skills` in VS Code so `/setup` works out of the box.

**Windows** (PowerShell):

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1)
```

**macOS** (Terminal):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-mac.sh)"
```

See [`setup/README.md`](setup/README.md) for GitHub Codespaces, FlightCheck-only, and Maker vs Developer mode selection. Prefer to clone and open the repo yourself? See the [maker kit quick start](solutions/ess-maker-skills/README.md#quick-start). A **GitHub Copilot subscription is required** for the in-editor maker experience.

## Solutions

| Folder | What it does | How to use |
|---|---|---|
| [`solutions/ess-maker-skills/`](solutions/ess-maker-skills/) | Customize your ESS agent using GitHub Copilot in VS Code — no deep platform knowledge required. | Open the folder in VS Code, then type `/setup` in Copilot Chat. |
| `solutions/ess-flightcheck/` *(planned — see [#69](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/issues/69))* | Validate your ESS deployment readiness. Runs licensing, identity, integration, and configuration checks against your live environment. | Open the folder in VS Code and type `/flightcheck` in Copilot Chat — or run `python cli.py --scope full` standalone (no LLM needed). |

Additional solutions will be added under `solutions/` over time.

## Samples

Reference content used directly by customers — topic YAMLs, template-config XMLs, evaluation test sets, and integration walkthroughs — lives at the root under [`samples/`](samples/), peer to `solutions/`. Samples are first-class reference resources, not implementation details of any single solution.

## Repository structure

```
.github/                Repo-level CI, CodeQL, Dependabot, issue templates, labels
solutions/
  ess-maker-skills/     Maker kit — customize your ESS agent in VS Code with Copilot
  ess-flightcheck/      (planned) Standalone deployment-readiness validator
samples/                Reference topics, template configs, evaluation test sets (peer to solutions/)
LICENSE                 MIT
SECURITY.md             Microsoft MSRC reporting path
CODE_OF_CONDUCT.md      Microsoft Open Source Code of Conduct
CONTRIBUTING.md         Contribution guide, maintenance, privacy posture, validation
SUPPORT.md              Support model
```

## Telemetry

The ESS Maker Skills CLI collects pseudonymous usage telemetry (enabled by
default) to help improve the product. No developer identity, agent content, or
personal data is collected.

**To opt out**, run either of the following (both are persistent and take effect immediately):

```bash
# 1. From the solutions/ess-maker-skills directory:
python scripts/adk_telemetry.py off

# 2. Or set the ESS_ADK_TELEMETRY environment variable to off (any shell / CI).
#    Syntax varies by shell — set it before running any ADK command.
```

Setting `ESS_ADK_TELEMETRY=off` inline before a command works in bash / zsh
(`ESS_ADK_TELEMETRY=off python scripts/...`). To persist it, add it to your
shell profile:

```bash
# bash / zsh (~/.bashrc, ~/.zshrc):
export ESS_ADK_TELEMETRY=off
```

```powershell
# PowerShell ($PROFILE) — persistent:
$env:ESS_ADK_TELEMETRY = "off"
# ...or for the current session only, run the same line at the prompt.
```

```cmd
:: cmd.exe — current session only:
set ESS_ADK_TELEMETRY=off
:: For persistence use setx ESS_ADK_TELEMETRY off (takes effect in new shells).
```

The env var overrides the config-file setting.

Re-enable later with `python scripts/adk_telemetry.py on` or by unsetting the
env var. See
[Telemetry & Privacy](solutions/ess-maker-skills/README.md#telemetry--privacy)
for the full data model and event catalog.

## Contributing

This project welcomes contributions and suggestions. Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit https://cla.microsoft.com.

Please read our [Contributing Guide](CONTRIBUTING.md) for the full contribution model, security maintenance commitments, scope management policy, privacy posture, and validation guide.

## License

This project is licensed under the [MIT License](LICENSE).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos are subject to those third-party's policies.
