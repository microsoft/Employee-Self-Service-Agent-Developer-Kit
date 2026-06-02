# ESS Maker Kit

Customize your Employee Self-Service (ESS) agent using GitHub Copilot in VS Code — no deep platform knowledge required. Describe what you need in plain English and the kit generates topic YAML, workflow JSON, adaptive cards, and integration configurations for you.

> **This repo is intended as an example or learning tool.** It demonstrates how to customize Employee Self-Service (ESS) agents using GitHub Copilot in VS Code. It is not a Microsoft product or a supported service. See [SUPPORT.md](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/SUPPORT.md) for the support model and [SECURITY.md](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/SECURITY.md) for reporting security issues.

## Why This Kit

Building and customizing an ESS agent means working across topic YAML, Power Automate workflow schemas, ServiceNow/Workday connector patterns, adaptive card JSON, and Dataverse template configurations. The ESS Maker Kit packages all of that domain knowledge into a VS Code workspace so GitHub Copilot can do the heavy lifting — you describe the scenario, and the agent builds it.

---

## Features

### 🔌 Guided Dataverse MCP Setup

The kit walks you through connecting VS Code to your Power Platform environment via the Dataverse MCP server. Once connected, the agent can read your agent's components, create template configuration records, and push changes directly to Copilot Studio — all without leaving VS Code.

- Authenticates to your environment
- Discovers your deployed ESS agent and its components
- Creates a local working copy for safe editing
- Validates connectivity before proceeding

Run `/setup` and follow the prompts.

### 📖 Pre-Loaded ESS Documentation, Samples & Best Practices

The kit ships with a complete reference library that the AI agent reads at task time — you don't need to look anything up yourself.

- **ESS documentation** — Overview, customization patterns, integration guides for ServiceNow (HRSD/ITSM), Workday (HCM/Payroll/Absence), and more
- **Official samples** — Real topic YAMLs, template config XMLs, and workflow JSON from the [CopilotStudioSamples](https://github.com/microsoft/CopilotStudioSamples) repo, covering Workday employee/manager scenarios, ServiceNow HRSD/ITSM/Catalog, and Facilities
- **Best practices** — Evaluation strategies, conversational design patterns, responsible AI test sets, and the ESS template config + shared flow architecture
- **Integration-specific guidance** — Connector setup, SOAP/REST template patterns, and extensibility docs for each supported system

The agent uses this knowledge automatically when generating topics, workflows, or test sets.

### ✏️ Create, Update & Delete Topics

Build new conversation topics from a plain-English description. The agent generates the full topic YAML — trigger phrases, model descriptions, action chains, adaptive cards, variable bindings — and writes it to your agent folder.

- **Create** (`/create`) — Describe the scenario and the agent builds the topic, including template config records for ServiceNow/Workday integrations
- **Update** (`/update`) — Modify trigger phrases, messages, conditions, or conversation flow in existing topics
- **Delete** (`/delete`) — Remove topics cleanly with dependency checking

The agent handles the full pipeline: checkpoint → local edit → error scan → dry-run diff → push to Copilot Studio → verify.

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

Create structured CSV test sets that you upload to the Copilot Studio Evaluation portal. The agent reads your topics and generates tests across multiple quality dimensions.

- **Topic Triggering** — Verifies each topic fires on its trigger phrases plus paraphrased variants
- **Responsible AI** — Standard guardrail tests for harmful, adversarial, and policy-bypass prompts
- **Sensitive Topics** — Escalation scenarios for harassment, discrimination, and workplace safety
- **Emotional Intelligence** — Empathy and tone tests for emotionally charged requests
- **Ambiguous Prompts** — Verifies the agent clarifies vague requests instead of guessing
- **Integration Data** — Validates external system data retrieval with placeholder-based expected responses
- **General Knowledge** — Open-ended quality checks against loaded knowledge sources

Test sets are written to `workspace/tests/{date}/` in the exact CSV format Copilot Studio expects (`Prompt, Expected response, Test Method Type, Passing Score`). Run `/evaluate` to generate them.

### 🚀 Push to Copilot Studio

Every change follows the same safe deployment pipeline:

```
Checkpoint (backup) → Local edit → Error scan → Dry-run diff → Push → Verify
```

The `/push` command compares your local files against the last-known baseline, detects new/modified/deleted components, and syncs them to your Copilot Studio environment via the Dataverse API. Rollback is always one command away.

### ✈️ FlightCheck — Pre-Deployment Readiness Validation

Run a comprehensive readiness check against your live environment and all extracted agents before going to production. FlightCheck validates licensing, identity, infrastructure, integrations, agent configuration, and publishing readiness — then generates an HTML report you can share with stakeholders.

Run `/flightcheck` from Copilot Chat, or directly from the CLI (run from this solution's directory):

```bash
cd solutions/ess-maker-skills
python scripts/flightcheck/cli.py --scope full
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

- **Authoring Copilot Studio topics** for ESS agents (Workday, ServiceNow HRSD/ITSM, custom integrations)
- **Generating Power Automate workflow JSON** for connector integrations that don't have an ESS shared orchestrator
- **Authoring template config records** for shared ESS orchestrators (Workday and ServiceNow)
- **Local validation** via `/flightcheck` and `/scan` before pushing to Copilot Studio
- **Working in a single Copilot Studio environment** (dev, test, or prod tenant of your choice)

## Unsupported scenarios

This toolkit does NOT:

- Replace Copilot Studio's own validation, evaluation, or runtime safety controls
- Provide hosted runtime, SLAs, or ongoing operations for the agents you build
- Manage cross-tenant or cross-environment promotion (no built-in CI/CD for Copilot Studio)
- Ship a production-ready packaged agent — you are authoring components in your own tenant
- Provide official Microsoft support beyond what is described in [SUPPORT.md](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/SUPPORT.md)

---

## Integrations

The ESS agent connects to external HR systems through Power Platform connectors and shared orchestrator flows. The kit automates the setup process — gathering credentials, configuring identity providers, creating service accounts, and installing extension packs — so you can go from zero to a working integration without reading platform docs.

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

**What the kit sets up:**
- **SAML SSO via Entra ID** — verifies or creates the Entra enterprise app, configures SAML trust with Workday, and pre-authorizes the Power Platform connector
- **Integration System Users (ISUs)** — automatically creates `ISU_WQL_COPILOT` (for reports) and `ISU_GENERIC_COPILOT` (for API calls) via the Workday SOAP API
- **Security groups and domain permissions** — guides you through creating `ISSG_WQL_COPILOT` and `ISSG_GENERIC_COPILOT` with the correct domain policies
- **OAuth API client** — walks you through registering a SAML Bearer Grant client (for Entra SSO) or Authorization Code Grant client (for Basic auth)
- **WD_User_Context RaaS report** — verifies or guides creation of the custom report that maps Workday usernames to employee context data
- **Extension pack installation** — installs the Workday extension in Copilot Studio with all three SOAP connection references configured

**Supported auth methods:**
| Method | Use case |
|--------|----------|
| Microsoft Entra ID Integrated | Production — employees SSO through Microsoft, SAML token exchange with Workday |
| Basic auth | Dev/test only — ISU username/password directly |

**Verify-first approach:** The kit runs API checks against your Workday tenant before asking you to configure anything. If ISU accounts, auth policies, permissions, or the RaaS report are already set up (common on shared tenants), those tasks are automatically skipped.

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
- Access to a Power Platform environment with an ESS agent deployed
- **Dataverse MCP server** enabled in your Power Platform environment with the "Microsoft GitHub Copilot" client allowed. Admin setup: Power Platform admin center → environment → Settings → Features → Dataverse Model Context Protocol → check "Allow MCP clients (GA version)" → Advanced Settings → enable "Microsoft GitHub Copilot". See [Connect Dataverse MCP with VS Code](https://learn.microsoft.com/en-us/power-apps/maker/data-platform/data-platform-mcp-vscode).

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

1. **Clone this repo** and open the folder in VS Code
2. **Run `/setup`** in GitHub Copilot Chat to configure your environment

Setup connects to your Power Platform environment, discovers your ESS agent, and creates a local working copy.

---

## Available Commands

| Command | What it does |
|---------|-------------|
| `/setup` | First-time environment setup — authenticate, discover agent, extract, configure |
| `/connect` | Connect an external system (ServiceNow, Workday) — guided setup with MCP verification |
| `/create` | Create a new topic or workflow |
| `/update` | Modify an existing topic or workflow |
| `/delete` | Delete a topic or workflow from your agent |
| `/scan` | Scan your agent for compile errors and fix them |
| `/evaluate` | Generate evaluation test sets for your agent |
| `/flightcheck` | Run pre-deployment readiness validation — licenses, environment, integrations, agent files |
| `/push` | Push all local changes to Copilot Studio |
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
Changes are pushed to Copilot Studio via the Dataverse API
```

## Repository Structure

```
solutions/ess-maker-skills/
  .github/             Per-solution copilot-instructions and prompt files
  .vscode/             VS Code workspace settings + recommended extensions
  scripts/             Python automation: setup.py, push.py, checkpoint.py, flightcheck/
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

## Contributing

See the repository [Contributing Guide](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/CONTRIBUTING.md) for the contribution model, the Microsoft CLA process, security maintenance commitments, scope policy, and validation guide.

## License

This project is licensed under the [MIT License](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/blob/main/LICENSE).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos are subject to those third-party's policies.