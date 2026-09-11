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
agent sets live under the agent's `evaluations/` folder. The lifecycle supports
quality validation, optional SME review, promotion into the configured agent,
scoped push, execution, run history, and results analysis. Run `/evaluate` to
create or manage sets, and `/run` to execute a pushed set or inspect results.

### 🚀 Local-First Authoring

Every supported change follows the same safe local pipeline:

```
Checkpoint (backup) → Local edit → Error scan
```

The `/push` command remains discoverable but reports that native DA-GA
deployment is not yet available. It does not fall back to the retired
Dataverse mutation path.

### ✈️ FlightCheck — Pre-Deployment Readiness Validation

In a DA-GA workspace, `/flightcheck` validates the extracted local agent files without requiring Dataverse or remote-service authentication. The separate standalone FlightCheck install retains the comprehensive live-environment checks for licensing, identity, infrastructure, integrations, agent configuration, and publishing readiness.

Run `/flightcheck` from Copilot Chat, or run the local-files scope directly from this solution's directory:

```bash
cd solutions/ess-maker-skills
python scripts/flightcheck/cli.py --scope local
```

**Standalone install (no VS Code or Copilot required):**

If you only need to run FlightCheck, this single command handles everything — installs dependencies, signs you in, lets you pick your environment, and runs the check:

```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck.ps1)
```

Re-run the same command to change your environment or agent. See [`setup/README.md`](../../setup/README.md) for details.

**What it checks (41+ automated checks across 8 categories):**

| Category | What's validated |
|----------|------------------|
| Prerequisites | M365 Copilot, Copilot Studio, and Teams licenses; Global Admin and PP Admin roles |
| Environment | Power Platform environment, Dataverse provisioning, DLP policies |
| Authentication | Entra ID configuration, Conditional Access policies, user sync |
| External Systems | Workday, ServiceNow, and SAP flow discovery and status |
| Workday Deep | Environment variables, connection references, flow status, 17 SOAP workflow tests |
| Agent Files | Agent instructions, starter prompts, required topics, variables, template configs |
| Configuration | Per-agent validation across all extracted agents (HR and IT) |
| Publishing | Golden prompts, UAT sign-off, managed solution export, admin approval |

**Key capabilities:**
- **Multi-agent** — automatically scans every agent under `workspace/agents/`, not just the active one
- **HTML report** — opens in your browser with color-coded results, priority highlighting, and clickable remediation links
- **Run history** — every run is archived in `workspace/flightcheck/history/` for trend tracking
- **Workday SOAP tests** — tests all 17 ESS workflows against the actual Workday API (reads credentials from `.vscode/mcp.json`, prompts for ISU password at runtime — never saved to disk)
- **Auto-fix offer** — after presenting results, the agent offers to fix issues it can handle (run `/connect`, `/scan`, enable flows) and re-runs the check
- **Graceful degradation** — runs whatever checks your permissions allow; skips the rest with clear messages

**Scopes** for targeted re-runs:

| Scope | What it checks |
|-------|----------------|
| `full` | Everything (default) |
| `workday` | Workday connections, flows, env vars, and SOAP workflow tests |
| `local` | Agent files only — no API calls |
| `prerequisites` | Licenses and roles only |

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
- Deploy local DA-GA changes, install product extensions, or configure their connectors
- Provide official Microsoft support beyond what is described in [SUPPORT.md](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/SUPPORT.md)

---

## Integrations

> **DA-GA boundary:** ServiceNow, Workday, and other integrations are delivered
> through separate product extensions. The current release does not install
> those extensions, configure their connections, or enter the retired CEA or
> DA-Preview setup flows. The detailed material below is reference-only until
> DA-GA product-extension guidance is available.

The reference sections below describe how these integrations were configured in
earlier Dataverse-based releases. They are not executable setup paths in the
current DA-GA release.

### ServiceNow (HRSD / ITSM)

Connect your agent to ServiceNow for IT tickets, HR cases, and service catalog items. Run `/connect servicenow` to start.

**What the kit sets up:**
- **Entra ID app registration** for SSO — employees use their Microsoft work account to authenticate, with automatic token refresh
- **OAuth or Certificate auth** for service-to-service flows — configurable per environment
- **Power Platform connector** — the `shared_service-now` connector, pre-authorized against your Entra app
- **Extension pack installation** — installs the ServiceNow HRSD/ITSM extension in Copilot Studio with all connection references wired up

**Supported auth methods:**
| Method | Use case |
|--------|----------|
| Microsoft Entra ID (interactive) | Production — employees SSO through Microsoft |
| Certificate (service-to-service) | Non-interactive integrations |
| OAuth2 (ServiceNow credentials) | Separate ServiceNow login |
| Basic auth | Dev/test only |

**What you can build after connecting:**
- Look up or create ServiceNow incidents, HR cases, and catalog requests
- Query CMDB items, knowledge articles, and user records
- New scenarios use the **template config + shared flow** pattern — no standalone workflows needed

### Workday (HCM / Payroll / Absence)

Connect your agent to Workday for employee data, compensation, time off, and org lookups. Run `/connect workday` to start.

**Two supported install paths** — the kit detects which one applies and routes automatically:

- **Simplified** (Microsoft's default for new installs) — just one Workday connection (OAuthUser via Entra ID) plus Dataverse. No ISU service accounts, security groups, or custom reports. User context comes from the Workday REST `/workers/me` endpoint.
- **Legacy** — the older setup with ISU accounts, security groups, domain permissions, and the `WD_User_Context` RaaS report. Still fully supported for existing installs.

**What the kit sets up (simplified path):**
- **SSO via Entra ID** — verifies or creates the Entra enterprise app, configures trust with Workday, and pre-authorizes the Power Platform connector
- **Extension pack installation** — installs the Workday extension in Copilot Studio with the OAuthUser and Dataverse connection references configured (including the Workday REST base URL)

**What the kit additionally sets up on the legacy path:**
- **Integration System Users (ISUs)** — automatically creates `ISU_WQL_COPILOT` (for reports) and `ISU_GENERIC_COPILOT` (for API calls) via the Workday SOAP API
- **Security groups and domain permissions** — guides you through creating `ISSG_WQL_COPILOT` and `ISSG_GENERIC_COPILOT` with the correct domain policies
- **OAuth API client** — walks you through registering a SAML Bearer Grant client
- **WD_User_Context RaaS report** — verifies or guides creation of the custom report that maps Workday usernames to employee context data

**Supported auth methods:**
| Method | Use case |
|--------|----------|
| Microsoft Entra ID Integrated | Both paths — employees SSO through Microsoft, token exchange with Workday |
| Basic auth | Legacy path's ISU connections (`d6081`, `0786a`) |

**Verify-first approach:** The kit runs API checks against your Workday tenant before asking you to configure anything. On the legacy path, if ISU accounts, auth policies, permissions, or the RaaS report are already set up (common on shared tenants), those tasks are automatically skipped.

**What you can build after connecting:**
- Look up employee information, compensation, service anniversary, cost center
- Check time off balances and request time off
- Query emergency contacts, national IDs, passports, visas, certifications
- Update email and phone number
- New scenarios use the **template config + shared flow** pattern — no standalone workflows needed

### Workday MCP Server

The kit includes a local Workday MCP server (`src/mcp/workday/`) that enables direct Workday API access from VS Code during setup and development. It supports:

- **SOAP API** — Create integration systems, ISU accounts, and call any Workday web service
- **RaaS (Reports as a Service)** — Query custom reports like `WD_User_Context`
- **Worker data** — Get employee details, time off balances, org data
- **Connection testing** — Verify ISU authentication and permissions

The MCP server uses Basic auth with ISU credentials and is configured automatically during `/connect workday`.

### ServiceNow MCP Server

The kit also includes a local ServiceNow MCP server (`src/mcp/servicenow/`) for direct ServiceNow API access:

- **REST API** — Query and create records in any ServiceNow table
- **Connection testing** — Verify instance connectivity and credentials

Configured automatically during `/connect servicenow`.

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
| `/connect` | Explain the DA-GA product extension requirement |
| `/create` | Create a topic, workflow, or evaluation test set locally |
| `/update` | Update a topic, workflow, or evaluation test set locally |
| `/delete` | Report that DA-GA deletion is not yet available |
| `/scan` | Scan your agent for compile errors and fix them |
| `/review` | Review local topics or evaluation test sets tagged for review |
| `/evaluate` | Generate evaluation test sets for your agent |
| `/run` | Run pushed evaluation test sets and inspect history or results |
| `/test` | Drive topics in the currently deployed agent; DA-GA workflow diagnostics are not yet available |
| `/flightcheck` | Validate local agent files; standalone FlightCheck retains its full mode |
| `/push` | Report that native DA-GA deployment is not yet available |
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