# ESS Copilot Kit

Customize your Employee Self-Service (ESS) agent using GitHub Copilot in VS Code — no deep platform knowledge required. Describe what you need in plain English and the kit generates topic YAML, workflow JSON, adaptive cards, and integration configurations for you.

## Why This Kit

Building and customizing an ESS agent means working across topic YAML, Power Automate workflow schemas, ServiceNow/Workday connector patterns, adaptive card JSON, and Dataverse template configurations. The ESS Copilot Kit packages all of that domain knowledge into a VS Code workspace so GitHub Copilot can do the heavy lifting — you describe the scenario, and the agent builds it.

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

Test sets are written to `my/tests/{date}/` in the exact CSV format Copilot Studio expects (`Prompt, Expected response, Test Method Type, Passing Score`). Run `/evaluate` to generate them.

### 🚀 Push to Copilot Studio

Every change follows the same safe deployment pipeline:

```
Checkpoint (backup) → Local edit → Error scan → Dry-run diff → Push → Verify
```

The `/push` command compares your local files against the last-known baseline, detects new/modified/deleted components, and syncs them to your Copilot Studio environment via the Dataverse API. Rollback is always one command away.

---

## Getting Started

### Prerequisites

- [VS Code](https://code.visualstudio.com/) (latest version)
- [GitHub Copilot](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot-chat) extension (with an active subscription)
- Access to a Power Platform environment with an ESS agent deployed
- **Dataverse MCP server** enabled in your Power Platform environment with the "Microsoft GitHub Copilot" client allowed. Admin setup: Power Platform admin center → environment → Settings → Features → Dataverse Model Context Protocol → check "Allow MCP clients (GA version)" → Advanced Settings → enable "Microsoft GitHub Copilot". See [Connect Dataverse MCP with VS Code](https://learn.microsoft.com/en-us/power-apps/maker/data-platform/data-platform-mcp-vscode).

### Recommended Models

This kit relies on structured instructions and multi-step tool use. Not all models handle this reliably.

| Model | Status | Notes |
|-------|--------|-------|
| **Claude Sonnet 4.6** | ✅ Recommended | Reliable tool use, follows multi-step instructions accurately |
| **Claude Opus 4** | ✅ Recommended | Reliable tool use, follows multi-step instructions accurately |
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
| `/create` | Create a new topic or workflow |
| `/update` | Modify an existing topic or workflow |
| `/delete` | Delete a topic or workflow from your agent |
| `/scan` | Scan your agent for compile errors and fix them |
| `/evaluate` | Generate evaluation test sets for your agent |
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
src/
├── reference/      ESS documentation, integration guides, customization patterns
├── skills/         Step-by-step instructions the agent follows for each command
├── examples/       Official samples — topics, template configs, evaluation test sets
└── templates/      Starting points for topics and workflows
my/                 Your local config, agent files, and test outputs (gitignored)
```

## Contributing

This kit is maintained by the ESS team. To contribute patterns, examples, or improvements, open a pull request.

## License

Microsoft Internal
