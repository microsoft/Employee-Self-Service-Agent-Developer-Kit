# ESS Maker Kit

Customize your Employee Self-Service (ESS) agent using GitHub Copilot in VS Code — no deep platform knowledge required. Describe what you need in plain English and the kit generates topic YAML, workflow JSON, adaptive cards, and integration configurations for you.

> **This repo is intended as an example or learning tool.** It demonstrates how to customize Employee Self-Service (ESS) agents using GitHub Copilot in VS Code. It is not a Microsoft product or a supported service. See [SUPPORT.md](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/SUPPORT.md) for the support model and [SECURITY.md](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/SECURITY.md) for reporting security issues.

## Why This Kit

Building and customizing an ESS agent means working across topic YAML, Power Automate workflow schemas, ServiceNow/Workday connector patterns, adaptive card JSON, and Dataverse template configurations. The ESS Maker Kit packages all of that domain knowledge into a VS Code workspace so GitHub Copilot can do the heavy lifting — you describe the scenario, and the agent builds it.

---

## Features

### 🔌 Guided DA-GA Setup

The kit connects VS Code to an existing editable DA Dev agent through the native AgentBuilder API.

- Authenticates with the identity that can open the agent in Copilot Studio
- Validates the selected environment and Dev agent
- Creates a local working copy for safe editing
- Records setup completion after the local workspace is ready

Run `/setup` and follow the prompts.

> **Accounts used during setup:** Sign in to GitHub Copilot to activate Copilot Chat, where you run `/setup`. When `/setup` connects your agent, use the separate Microsoft work account that can access the target Power Platform environment and agent. GitHub Copilot authentication does not grant Power Platform access. See [Authentication prompts](../../setup/README.md#authentication-prompts) for the full sequence and the standalone FlightCheck exception.

### 🎨 Customize the ESS Landing Page

Configure the active agent's tenant landing page directly from chat. Run
`/landing-page`, ask `Customize my landing page`, or use the **Customize landing
page** Quick Action.

- **Categorized starter prompts** help employees understand the agent's
  capabilities and guide them into common scenarios.
- **Accent colors** apply your light/dark brand colors to buttons, links, chat
  bubbles, and loading indicators.
- **Quick links** give employees direct access to important tenant resources.
- **Stay up to date** shows personalized, actionable cards for in-progress
  ticket status, required follow-ups, and time-sensitive tasks.

The agent can apply exact changes directly or open rich editors for exploratory
updates. Landing-page configuration is saved through the production
AgentConfiguration service and does not use the local topic push pipeline.

Landing-page configuration requires the target agent to be published from
Copilot Studio and deployed to the organization. `/setup` installs and extracts
the Power Platform agent; publication, admin approval, and Integrated apps
deployment are separate steps.

### 📖 Pre-Loaded ESS Documentation, Samples & Best Practices

The kit ships with a complete reference library that the AI agent reads at task time — you don't need to look anything up yourself.

- **ESS documentation** — Overview, customization patterns, integration guides for ServiceNow (HRSD/ITSM), Workday (HCM/Payroll/Absence), and more
- **Official samples** — Real topic YAMLs, template config XMLs, and workflow JSON from the [CopilotStudioSamples](https://github.com/microsoft/CopilotStudioSamples) repo, covering Workday employee/manager scenarios, ServiceNow HRSD/ITSM/Catalog, and Facilities
- **Best practices** — Evaluation strategies, conversational design patterns, responsible AI test sets, and the ESS template config + shared flow architecture
- **Integration-specific guidance** — Connector setup, SOAP/REST template patterns, and extensibility docs for each supported system

The agent uses this knowledge automatically when generating topics, workflows, or test sets.

### ✏️ Create, Update & Delete Topics

Create or update simple conversation topics from plain English, an approved
eval scenario, or existing evaluation files. The agent first creates an eval
contract, then writes the topic YAML and matching native evaluations.

- **Create** (`/create`) — Approve the intended evals, then generate a new
  simple informational, clarification, routing, or handoff topic
- **Update** (`/update`) — Approve updated and regression evals, then modify an
  existing simple topic and create or refresh its generated evals
- **Delete** (`/delete`) — Remove topics cleanly with dependency checking

Workday, ServiceNow, SAP, connector-backed, and flow-backed customization
requires the corresponding DA-GA product extension guidance, which is not yet
available in this release.

The current pipeline is checkpoint → local edit → error scan. Native DA-GA
deployment is not yet available, so the kit leaves the live agent unchanged.

### ⚡ Create, Update & Delete Workflows

Generate Power Automate cloud flows for integrations that don't have an ESS shared orchestrator (custom APIs, Jira, ADP, etc.).

- Generates `workflow.json` with proper trigger/action structure and Copilot Studio response bindings
- Creates connection reference entries for new connectors
- Wires the workflow into your topic's `InvokeFlowAction`

For ServiceNow and Workday, the kit uses the **template config + shared flow** pattern instead — no standalone workflows needed.

### 🔍 Error Scanning & Cleanup

Catch and fix compile errors before they reach production. The `/scan` command analyzes your entire agent for issues and walks you through fixes interactively.

- Detects broken variable references, missing workflow bindings, malformed YAML, and dependency conflicts
- Groups errors by severity and type
- Proposes fixes and applies them with your confirmation
- Re-scans after each fix to verify resolution

### 📊 Generate Evaluation Test Sets

Create Copilot Studio-native evaluation sets from configured agent topics, or
generate catalogue-grounded starter sets for named ESS scenarios before an
agent is configured. Each set produces synchronized `.mcs.yml` and CSV
artifacts from the same test cases.

- **Topic Triggering** — Verifies each topic fires on its trigger phrases plus paraphrased variants
- **Responsible AI** — Standard guardrail tests for harmful, adversarial, and policy-bypass prompts
- **Sensitive Topics** — Escalation scenarios for harassment, discrimination, and workplace safety
- **Emotional Intelligence** — Empathy and tone tests for emotionally charged requests
- **Ambiguous Prompts** — Verifies the agent clarifies vague requests instead of guessing
- **Integration Data** — Validates external system data retrieval with placeholder-based expected responses
- **General Knowledge** — Open-ended quality checks against loaded knowledge sources

Catalogue-grounded sets are staged under `workspace/evaluations/`; configured
agent sets live under the agent's `evaluations/` folder. New evaluation sets
use **Compare Meaning** only and require an expected response for every prompt.
Multi-turn generation is not supported by this single-response feature.

Generated previews show full prompts and expected responses, with separate
in-scope and out-of-scope sections and a downloadable CSV. Returning to an
existing set offers editing or adding cases without replacing the original.
Quality review assesses the authored test set; it does not prove that the
deployed agent passes the tests in your tenant.

After quality review, choose to request human review, run in Copilot Studio,
edit the set, or run another quality review. **Run** and **Request Review**
include their required scoped deployment, with confirmation and the existing
review/connection prerequisites. A separate push command is not required;
explicit evaluation push remains available outside this menu. Successful run
initiation includes the current run's Copilot Studio link.

These flows use the existing push APIs. Dataverse push stores `review.json`
metadata in the evaluation-parent description. New or changed native MinimalBot
YAML uploads a **new copy with a new deployed ID**, retaining the old remote copy;
unchanged YAML, including local review-only changes, reuses its verified copy. The preview explains
this before consent. Removing cases from a new native copy does not delete
them from the old remote set.

Native push uploads YAML only: review status is retained locally but is **not
published as shared review metadata** or copied into the deployed baseline.
Request Review and reviewer completion
still perform the existing push in the same flow and report this limitation;
they do not claim another user can discover the local review marker. New native
in-place-update APIs and cross-user-review parity are not part of this change.
Files are retained when preparation or deployment cannot complete. Run
`/evaluate` to create or manage sets and `/run` to prepare a selected set for
execution or inspect its history/results.

### 🚀 Local-First Authoring

Every supported change follows the same safe local pipeline:

```
Checkpoint (backup) → Local edit → Error scan
```

For topics and workflows, `/push` reports that native DA-GA deployment is not
yet available; it does not fall back to the retired Dataverse mutation path.
Explicit evaluation push uses its separate selected-set deployment flow and
the existing evaluation APIs, including the native new-copy behavior described
above. It does not add new native update/delete or review-metadata endpoints.

### ✈️ FlightCheck — Agent Setup Diagnostics

Run `/flightcheck` to inspect the selected agent's setup and find what needs
attention. Checks cover agent configuration, connections, environment and
licensing observations, knowledge sources, and applicable integrations.
Workday and ServiceNow checks depend on what the agent uses; an unused
integration is not a setup problem. The number of checks varies with the
agent's configuration.

DA diagnostics are read-only: they do not change your agent or environment.
You can run them before connection setup is complete. Use `local` scope when
you want to check only the agent files in your ADK workspace, without signing
in to remote services.

Run `/flightcheck` from Copilot Chat, or run the equivalent full command directly from this solution's directory:

```bash
cd solutions/ess-maker-skills
python scripts/flightcheck/cli.py --scope full
```

Chat and standalone runs use the same checks for the same selected agent and
scope. Both save a browser report (`report.html`) and detailed results
(`results.json`).

| Scope | What it checks |
|-------|----------------|
| `full` | The selected agent and its applicable setup checks (default) |
| `workday` | Applicable Workday setup checks |
| `servicenow` | Applicable ServiceNow setup checks |
| `local` | Agent files in the ADK workspace only; no remote API calls |

For example: `python scripts/flightcheck/cli.py --scope local`.

**Standalone install (no VS Code or Copilot required):**

If you only need to run FlightCheck, this single command handles everything — installs dependencies, signs you in, lets you pick your environment, and runs the check:

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck.ps1)
```

Re-run the same command to change your environment or agent. See [`setup/README.md`](../../setup/README.md) for details.

**Reading your report:** The summary identifies the agent and environment
checked and separates passed checks, problems, warnings and items needing
manual verification. Findings that need attention explain the next step and
who can help. Search or filter the report to focus on those items.

Some settings require inspection in Copilot Studio or help from an
administrator. Missing access means a setting could not be verified, not
necessarily that it is configured incorrectly. Follow the specific finding;
you do not need administrator approval just to start diagnostics.

The **Technical details** appendix and JSON results provide supporting
information for administrators and support. FlightCheck does not publish the
agent, execute employee tasks, or certify production readiness. Local-file
checks do not prove that the deployed agent has the same content.

For a focused Workday litmus, use `/flightcheck WD-RUN-001` or
`/flightcheck wd litmus test`, or run the CLI from the maker-kit directory:

```powershell
python scripts/flightcheck/cli.py --checkpoint WD-RUN-001
```

This reads recent Workday flow history. If there is no recent response to
inspect, the report guides you through a read-only question in the Copilot
Studio Test pane and a rerun. A passed observation is not a guarantee that
every employee scenario works.

For the detailed check inventory, coverage limits and contributor guidance,
see the [FlightCheck validation matrix](src/reference/ess-docs/flightcheck/validation-matrix.md#da-maker-diagnostic-scope).
For help with a finding, see the
[remediation guide](src/reference/ess-docs/flightcheck/remediation-guide.md).
Legacy/custom-engine documentation is available on
[`main-ca`](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/tree/main-ca).

---

## Supported scenarios

This toolkit is designed for:

- **Connecting to an existing editable DA Dev agent**
- **Authoring supported Copilot Studio components locally**
- **Generating evaluation files**
- **Local validation** via `/flightcheck`, `/scan`, and `/review`
- **Browser-driving the currently deployed agent for runtime observation**

## Unsupported scenarios

This toolkit does NOT:

- Replace Copilot Studio's own validation, evaluation, or runtime safety controls
- Provide hosted runtime, SLAs, or ongoing operations for the agents you build
- Manage cross-tenant or cross-environment promotion (no built-in CI/CD for Copilot Studio)
- Ship a production-ready packaged agent — you are authoring components in your own tenant
- Provision arbitrary product extensions or create connector credentials on the maker's behalf
- Provide official Microsoft support beyond what is described in [SUPPORT.md](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/SUPPORT.md)

---

## Integrations

Run `/connect` to choose an available integration, or start Workday directly
with `/connect workday` or `/connect-workday`.

### Workday (HCM / Payroll / Absence)

Connect your agent to Workday for employee data, compensation, time off and org
lookups. For Declarative Agents, this release supports the **ESS HR Agent**.
Workday integration with the ESS IT Agent is not supported in this release.

The guided experience helps you:

- Prepare the agent's local workspace if needed, then continue the same
  connection request without asking you to restart.
- Share setup workbooks with your Microsoft Entra and Workday administrators
  and check their completed responses.
- Install or verify the Workday package, guide you through connection and
  sharing settings, and apply approved runtime configuration.
- Complete a signed-in end-to-end Workday scenario in the Copilot Studio Test
  pane before finishing the connection.

The skill explains the access needed at each stage and saves your progress.
Administrators make the Entra and Workday changes; the kit does not create
connector credentials for you. DA Workday uses employee sign-in through
Microsoft Entra ID and does not require ISU service accounts.

FlightCheck readiness checks run at the relevant stages. Settings that cannot
be verified automatically require maker or administrator confirmation.

**Test and Production:** Promote the agent using your organization's approved
process, then return to `/connect workday` for the promoted target. The skill
reuses verified administrator setup and guides the remaining connections,
permissions, sharing and maker validation for that target. Topic enabling and
content changes happen only in Development; Test and Production verify the
promoted content without changing it.

Connecting Workday does not publish or promote the agent. See the
[Workday walkthrough](src/skills/connect/workday/SKILL.md) for the guided
procedure and the [runtime authorization guide](scripts/alm/README.md) for
administrator details. Custom-engine Workday guidance is maintained on
[`main-ca`](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/tree/main-ca).

### ServiceNow (HRSD / ITSM)

Guided ServiceNow setup is not yet available in ADK. You can configure the ServiceNow connection manually in Copilot Studio or contact admin.

### Developer integration tools

The repository also includes [Workday](src/mcp/workday/) and
[ServiceNow](src/mcp/servicenow/) MCP tools for separate development tasks.
These are not required by the guided DA Workday connection.

---

## Getting Started

### Prerequisites

- [VS Code](https://code.visualstudio.com/) (latest version)
- [GitHub Copilot](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot-chat) extension (with an active subscription)
- Access to a Power Platform environment with an editable DA Dev agent
- Permission to open that agent in Copilot Studio

### Recommended Models

This kit relies on structured instructions and multi-step tool use. Not all models handle this reliably. Behaviors below were observed during kit development; results may change as models are updated.

**Last tested:** 2026-05-04

| Model | Status | Notes |
|-------|--------|-------|
| **Claude Sonnet 4.6** | ✅ Recommended | Reliable tool use, follows multi-step instructions accurately |
| **Claude Opus 4.6** | ✅ Recommended | Reliable tool use, follows multi-step instructions accurately |
| **Codex 5.4 Medium** | ✅ Recommended | Successfully handles MCP tool detection and setup flows |
| **GPT-4o** | ⚠️ Not recommended | Fails to detect MCP tools reliably, struggles with multi-step setup flows |
| **GPT-4.1** | ⚠️ Not recommended | Unreliable string substitution, fails MCP tool detection, produces malformed URLs |
| **GPT 5.4** | ⚠️ Not recommended | Unreliable MCP tool detection, inconsistent multi-step instruction following |
| **Codex 5.3 High** | ⚠️ Not recommended | Inconsistent MCP tool detection, unreliable multi-step setup flows |
| **Codex 5.3** | ⚠️ Not recommended | Inconsistent MCP tool detection, false negatives on server connectivity |
| **Codex 5.3 Medium** | ⚠️ Not recommended | Fails MCP tool detection, insufficient reasoning for multi-step setup flows |
| **Claude Sonnet 4** | ⚠️ Not recommended | Fails MCP tool detection, insufficient reasoning for multi-step setup flows |

### Quick Start

**Option A: One-shot Windows installer** (installs VS Code, Python, Git, and everything else):

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1)
```

**Option B: GitHub Codespaces** (no local install — runs in your browser; [60 free hours/month](https://github.com/features/codespaces#pricing)):

👉 [**Create Codespace**](https://github.com/codespaces/new?repo=microsoft/Employee-Self-Service-Agent-Developer-Kit&ref=main&devcontainer_path=.devcontainer%2Fdevcontainer.json)

Select the 2-core machine type. Once it starts, open `solutions/ess-maker-skills` (File → Open Folder) and run `/setup` in Copilot Chat.

**Option C: Manual setup** — clone the repo and open `solutions/ess-maker-skills` in VS Code yourself.

Then **run `/setup`** in GitHub Copilot Chat to configure your environment.

---

## Available Commands

| Command | What it does |
|---------|-------------|
| `/setup` | Connect this workspace to an existing editable DA Dev agent |
| `/landing-page` | Configure landing-page branding and content |
| `/connect` | Choose an available integration |
| `/connect-workday` | Connect the ESS HR agent to Workday |
| `/create` | Create a topic, workflow, or evaluation test set locally |
| `/update` | Update a topic, workflow, or evaluation test set locally |
| `/delete` | Report that DA-GA deletion is not yet available |
| `/scan` | Scan your agent for compile errors and fix them |
| `/review` | Review local topics or evaluation test sets tagged for review |
| `/evaluate` | Generate evaluation test sets for your agent |
| `/run` | Prepare and run selected evaluation sets, or inspect history and results |
| `/test` | Drive topics in the currently deployed agent; DA-GA workflow diagnostics are not yet available |
| `/flightcheck` | Check the selected agent's setup and show what needs attention |
| `/push` | Push explicitly selected evaluation sets where supported; other native DA-GA deployment remains unavailable |
| `/backup-template-configs` | Capture hybrid Workday reference-data template configs before an extension update |
| `/restore-template-configs` | Restore hybrid Workday reference-data template configs after an extension update |
| `/menu` | See all available commands |

You can also describe what you want in plain English — the agent will figure out the right approach.

---

## How It Works

```
You describe what you need
        ↓
GitHub Copilot reads the kit's reference docs and templates
        ↓
The agent generates topic YAML, workflow JSON, or adaptive cards
        ↓
Files are written to your local agent folder
        ↓
The kit reports the current DA-GA deployment boundary
```

## Repository Structure

```
solutions/ess-maker-skills/
  .github/             Per-solution copilot-instructions and prompt files
  .vscode/             VS Code workspace settings + recommended extensions
  scripts/             Python automation: setup, checkpoints, local checks, flightcheck/
  src/
    reference/         ESS docs, integration guides, customization patterns
    skills/            Step-by-step instructions the agent follows for each command
    mcp/               Workday + ServiceNow MCP servers
    templates/         Starting points for topics and workflows
  workspace/           Your files (gitignored): agents/, tests/, flightcheck/history/
  .local/              Kit-internal state (gitignored): .baseline/, .checkpoints/,
                       .token_cache.bin, .component-map.json, config.json
```

`workspace/` and `.local/` scaffold dirs are committed (just `.gitkeep` files); contents are gitignored. Reference samples (topic YAMLs, template configs, evaluation test sets) live at the repo root in [`samples/`](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/tree/main/samples), peer to `solutions/`.

## Telemetry & Privacy

The ADK collects **pseudonymous** usage telemetry to help us understand which
capabilities are used and where they fail, so we can improve the product. It is
**enabled by default**; you can opt out at any time (see below).

**What is collected**

- A random **instance ID** (a GUID generated per installation) — used to count
  active installs and DAU/WAU/MAU. It is **not** tied to your identity.
- Your **tenant ID** (the Entra tenant GUID) — identifies the enterprise tenant,
  not an individual user.
- The **tenant display name** (organization display name for that tenant ID) —
  resolved best-effort via a Microsoft Graph lookup on the auth path. Tries
  `/organization` under `Organization.Read.All` (silent) first; if that isn't
  admin-consented, falls back to `/me?$select=companyName`, which reads the
  **signed-in user's Entra profile `companyName` attribute** (a user-profile
  field, not tenant metadata — enterprise admins routinely populate it with the
  tenant display name, so it is a useful label when the authoritative
  `/organization` call is blocked). This is org-level Organization Identifiable
  Information (OII), not a personal identifier. Left blank when neither call
  succeeds silently. See
  [Service dependencies](../../CONTRIBUTING.md#service-dependencies) for the
  Graph call details.
- A derived **tenant class** (`internal`, `customer`, or `unknown`) — a coarse,
  three-value flag computed from the tenant ID so we can report Microsoft-internal
  dogfood usage separately from external customer usage. It is non-identifying and
  lower sensitivity than the tenant ID it is derived from.
- Non-identifying context: ADK version, surface, session ID, event name, and
  per-event enums/metrics (e.g. FlightCheck verdicts, durations, check categories).
- A short **toolkit git SHA** (7-char) and a **toolkit branch classification** —
  System Metadata that lets us distinguish "install is on latest bits" from
  "install is on an older tree at the same extension version". The SHA is
  validated as hex before emission (non-SHA overrides become `unknown`). The
  branch is collapsed to a **bounded set** — one of `main`, `main-ca`, `detached`,
  `other`, or `unknown` — so raw branch names (which could otherwise carry
  personal / customer labels) are never emitted.
- Scrubbed, non-sensitive **error categories** when something fails.
- During **installation**, the one-shot installers (which run before Python is
  available) emit the same kind of event natively from PowerShell/bash: an
  install **start**, **per-step** progress, and a **completion**
  (`success` / `failure` / `cancelled`) carrying the installer variant
  (ADK or FlightCheck — the ADK-lite installer is not instrumented), platform,
  which step failed, and a scrubbed
  error category. This measures setup reliability. It is fail-open (a telemetry
  problem never breaks your install) and honors the same opt-out below.

**What is _not_ collected**

- No developer, user, or account identifier (no AAD OID, email, or name).
- No agent content, prompts, credentials, file contents, or personal data.

**How to opt out**

Run from the `solutions/ess-maker-skills` directory:

```bash
python scripts/adk_telemetry.py off      # disable telemetry
python scripts/adk_telemetry.py on       # re-enable telemetry
python scripts/adk_telemetry.py status   # show current setting
```

You can also set an environment variable, which takes precedence over the
config file. Syntax varies by shell:

```bash
# bash / zsh — one-shot inline, current session, or persistent in ~/.bashrc:
ESS_ADK_TELEMETRY=off python scripts/adk_telemetry.py status
export ESS_ADK_TELEMETRY=off
```

```powershell
# PowerShell — current session (add to $PROFILE to persist):
$env:ESS_ADK_TELEMETRY = "off"
```

```cmd
:: cmd.exe — current session; use `setx` to persist across new shells:
set ESS_ADK_TELEMETRY=off
```

**Storage, retention & deletion**

- Your preference is stored per-machine in `~/.adk/config`. Delete that file to
  reset to the default (enabled).
- Opting out stops all future collection immediately; it does not delete data
  already collected.
- Collected telemetry is retained for at most **30 days**.
- For full details and data-deletion requests, see
  [https://aka.ms/adk-telemetry](https://aka.ms/adk-telemetry).

---

## Contributing

See the repository [Contributing Guide](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/CONTRIBUTING.md) for the contribution model, the Microsoft CLA process, security maintenance commitments, scope policy, and validation guide.

## License

This project is licensed under the [MIT License](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/LICENSE).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos are subject to those third-party's policies.