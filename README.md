# Employee Self-Service Agent Developer Kit

A monorepo of solutions, samples, and tooling for the Microsoft Employee Self-Service (ESS) agent built on Microsoft Copilot Studio.

> **This repo is intended as an example or learning tool.** It is not a Microsoft product or a supported service. See [SUPPORT.md](SUPPORT.md) for the support model and [SECURITY.md](SECURITY.md) for reporting security issues.

## Getting started

This repo is a **monorepo of solutions** under [`solutions/`](solutions/). Each solution is a self-contained tool with its own purpose, dependencies, and instructions.

### Which build to clone (releases, not `main`)

This kit ships **two agent flavors**, each with its own **release line**. Clone the latest **release tag** for your flavor rather than cloning a trunk branch directly — releases are reviewed, known-good snapshots, while the trunk branches (`main`, `main-ca`) are active development and can change at any time.

| Agent flavor | Clone the latest… | Cut from trunk |
|---|---|---|
| **Declarative Agent (DA)** — [`samples/WorkdayDeclarativeAgent/`](samples/WorkdayDeclarativeAgent/) | **`da-v*`** release tag | `main` |
| **Custom Engine Agent (CEA)** — [`samples/WorkdayCustomEngineAgent/`](samples/WorkdayCustomEngineAgent/) | **`cea-v*`** release tag | `main-ca` |

```bash
# Declarative Agent (DA) — clone the latest DA release
git clone --branch da-v1.0.0-rc.1 https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git

# Custom Engine Agent (CEA) — clone the latest CEA release
git clone --branch cea-v1.0.0-rc.1 https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git
```

Check the [**Releases**](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/releases) page for the newest `da-v*` / `cea-v*` tag and substitute it above. Clone `main` (DA) or `main-ca` (CEA) directly only if you specifically want the latest in-development changes. See [Branches and releases](#branches-and-releases) for what each branch is.

### Pick your setup path

There are several ways to set up your environment depending on your needs:

| Option | Best for | Guide |
|--------|----------|-------|
| **One-shot installer** (Windows) | Full maker kit — installs VS Code, Python, Git, and all dependencies | [Setup README](setup/README.md) |
| **One-shot installer** (macOS) | Same as above, using Homebrew | [Setup README](setup/README.md) |
| **GitHub Codespaces** | Browser-based development — no local install required ([free tier available](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-codespaces/about-billing-for-github-codespaces#monthly-included-storage-and-core-hours-for-personal-accounts)) | [Setup README](setup/README.md#github-codespaces-no-local-install) |
| **FlightCheck only** | Pre-deployment validation without the full ADK install | [Setup README](setup/README.md#flightcheck-only-mode) |
| **Manual setup** | Clone or download the repo and open it in VS Code yourself | [Maker Kit README](solutions/ess-maker-skills/README.md#quick-start) — see also the [step-by-step walkthrough below](#how-to-open-ess-maker-skills-as-a-workspace-no-terminal-needed) |

> **GitHub Copilot subscription is required** for the in-editor maker experience.

### ⚠️ Important: open the right folder in VS Code

The kit's slash-commands (`/setup`, `/flightcheck`, etc.) **only appear when you open a specific solution folder as your VS Code workspace** — not the top-level repo folder. If you open the wrong folder, Copilot Chat will not know about the kit and `/setup` will do nothing.

> The **one-shot installer** and **GitHub Codespaces** paths above open the correct folder for you automatically. The walkthrough below is for the **Manual setup** path.

### How to open `ess-maker-skills` as a workspace (no terminal needed)

1. **Get the code — from a release, not a trunk branch.**
   The recommended way is to **clone the latest release tag** for your agent flavor (see [Which build to clone](#which-build-to-clone-releases-not-main) above):

   ```bash
   git clone --branch da-v1.0.0-rc.1 https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git
   ```

   Substitute the newest `da-v*` (Declarative Agent) or `cea-v*` (Custom Engine Agent) tag from the [Releases](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/releases) page. **No terminal?** On that same Releases page, open the newest release for your flavor and download **Source code (zip)**, then unzip it somewhere on your computer (for example, `Documents\Employee-Self-Service-Agent-Developer-Kit`). *(Avoid the green `< > Code` → `Download ZIP` button — it gives you the in-development `main` branch, not a release.)*

2. **Open VS Code.**

3. **Click `File` → `Open Folder…`** (keyboard shortcut: `Ctrl+K Ctrl+O`).

4. **Navigate INSIDE the unzipped folder, then INTO `solutions`, and select `ess-maker-skills`.**

   The full path you select should look like:
   ```
   Employee-Self-Service-Agent-Developer-Kit\solutions\ess-maker-skills
   ```

   ✅ **Correct** — pick this:
   ```
   Employee-Self-Service-Agent-Developer-Kit\
     solutions\
       ess-maker-skills\    ← select this folder, then click "Select Folder"
   ```

   ❌ **Wrong** — do NOT pick the top-level folder:
   ```
   Employee-Self-Service-Agent-Developer-Kit\    ← do NOT pick this
   ```

5. **Click `Select Folder`.** VS Code will open with `ess-maker-skills` as your workspace root.

6. **Open Copilot Chat.** Click the chat icon in the left sidebar (or press `Ctrl+Alt+I`).

7. **Type `/setup`** and press Enter. The kit will guide you from there.

### "I opened the wrong folder — now what?"

If you typed `/setup` and nothing happened, you probably opened the top-level repo folder. Check the file Explorer in VS Code's left sidebar:

- If you see `solutions`, `samples`, `LICENSE`, `CONTRIBUTING.md` — **you're at the wrong level.**
- If you see `.github`, `scripts`, `src`, `workspace` — **you're in the right place.**

To fix it: `File` → `Open Folder...` again, this time double-click into `solutions`, click on `ess-maker-skills` once to select it, then click `Select Folder`.

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

## Branches and releases

The repo keeps **one trunk per agent flavor**, and each trunk has its own **release line**:

| Branch | Trunk for | Release line |
|---|---|---|
| [`main`](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/tree/main) | **Declarative Agent (DA)** | `da-v*` (e.g. `da-v1.0.0-rc.1`) |
| [`main-ca`](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/tree/main-ca) | **Custom Engine Agent (CEA)** | `cea-v*` (e.g. `cea-v1.0.0-rc.1`) |

Releases are cut from these trunks (`da-v*` from `main`, `cea-v*` from `main-ca`). **Consume the kit from a release tag, not from a trunk** — see [Which build to clone](#which-build-to-clone-releases-not-main).

**Where to send a contribution:**

- **DA-only** change (e.g. `samples/WorkdayDeclarativeAgent/`) → PR into **`main`**.
- **CEA-only** change (e.g. `samples/WorkdayCustomEngineAgent/`) → PR into **`main-ca`**.
- **Shared** change (`solutions/`, `setup/`, `docs/`, common samples, tooling) → open a PR into **both `main` and `main-ca`** so the two release lines stay in sync.

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
