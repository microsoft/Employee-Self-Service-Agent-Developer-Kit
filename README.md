# Employee Self-Service Agent Developer Kit

A monorepo of solutions, samples, and tooling for the Microsoft Employee Self-Service (ESS) agent built on Microsoft Copilot Studio.

> **This repo is intended as an example or learning tool.** It is not a Microsoft product or a supported service. See [SUPPORT.md](SUPPORT.md) for the support model and [SECURITY.md](SECURITY.md) for reporting security issues.

## Getting started

This repo is a **monorepo of solutions** under [`solutions/`](solutions/). Each solution is a self-contained tool with its own purpose, dependencies, and instructions.

**To use a solution, open its folder in VS Code as the workspace root** — not the repo root. Each solution's slash-commands, Copilot instructions, and scripts are scoped to that folder.

### How to open a solution folder in VS Code

Pick whichever option fits how you work:

- **Command line:**
  ```bash
  git clone https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git
  code Employee-Self-Service-Agent-Developer-Kit/solutions/ess-maker-skills
  ```
  *(The `code` command requires VS Code's CLI to be on your PATH. On macOS/Linux it usually is by default. On Windows, install via the VS Code installer's "Add to PATH" option.)*

- **VS Code menu:** `File` → `Open Folder...` → navigate to the `solutions/ess-maker-skills/` subfolder of your clone → click `Select Folder`.

- **File Explorer / Finder (right-click):** Right-click the `solutions/ess-maker-skills/` folder → `Open with Code` (Windows) or `New VS Code Window at Folder` (macOS, after enabling the Finder integration in VS Code's Code → Preferences → Settings).

Once the folder is open as the workspace root, the `/setup`, `/flightcheck`, and other slash-commands appear in GitHub Copilot Chat.

## Solutions

| Folder | What it does | How to use |
|---|---|---|
| [`solutions/ess-maker-skills/`](solutions/ess-maker-skills/) | Customize your ESS agent using GitHub Copilot in VS Code — no deep platform knowledge required. | Open the folder in VS Code, then type `/setup` in Copilot Chat. |
| `solutions/ess-flightcheck/` *(planned — see [#69](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/issues/69))* | Validate your ESS deployment readiness. Runs licensing, identity, integration, and configuration checks against your live environment. | Open the folder in VS Code and type `/flightcheck` in Copilot Chat — or run `python cli.py --scope full` standalone (no LLM needed). |

Additional solutions will be added under `solutions/` over time.

## Getting Started

There are several ways to set up your environment depending on your needs:

| Option | Best for | Guide |
|--------|----------|-------|
| **One-shot installer** (Windows) | Full maker kit — installs VS Code, Python, Git, and all dependencies | [Setup README](setup/README.md) |
| **One-shot installer** (macOS) | Same as above, using Homebrew | [Setup README](setup/README.md) |
| **GitHub Codespaces** | Browser-based development — no local install required ([free tier available](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-codespaces/about-billing-for-github-codespaces#monthly-included-storage-and-core-hours-for-personal-accounts)) | [Setup README](setup/README.md#github-codespaces-no-local-install) |
| **FlightCheck only** | Pre-deployment validation without the full ADK install | [Setup README](setup/README.md#flightcheck-only-mode) |
| **Manual setup** | Clone the repo and configure your own environment | [Maker Kit README](solutions/ess-maker-skills/README.md#quick-start) |

> **GitHub Copilot subscription is required** for the in-editor maker experience.

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

## Contributing

This project welcomes contributions and suggestions. Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit https://cla.microsoft.com.

Please read our [Contributing Guide](CONTRIBUTING.md) for the full contribution model, security maintenance commitments, scope management policy, privacy posture, and validation guide.

## License

This project is licensed under the [MIT License](LICENSE).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos are subject to those third-party's policies.
