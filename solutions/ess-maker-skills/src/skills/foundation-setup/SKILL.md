<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# ESS Foundation Setup

Every **Message** block is exact user-facing text. Do not expose internal step IDs,
checkpoint IDs, state paths, or tool narration.

Follow `src/reference/ui-formatting-guidelines.md` for every user-facing
instruction in this flow. Resolve its examples with the actual environment,
agent, product, and connector names before displaying them.

This is the single integration-neutral `/setup` entry point. It owns only:

- Power Platform and Copilot Studio prerequisites;
- environment selection and binding;
- preferred unmanaged solution configuration;
- HR and/or IT ESS starter installation;
- baseline readiness;
- the handoff to `/connect`.

Workday, ServiceNow, SAP SuccessFactors, authentication, extension packs, and topics
are explicitly outside this skill.

Treat a clear natural-language setup request ("set up the environment",
"install ESS", or "I'm the admin; start my setup task") exactly like `/setup`.
Enter this flow directly; never ask the maker to rewrite the request as a command.
Retain the assigned task, plan role, chosen HR/IT agent, and pinned environment
through the handoff. A plan nomination is not proof of administrative access:
keep the real environment-access checks, and explain the specific missing
permission rather than repeatedly asking which persona the maker is.

---

## Start

Record anonymous usage telemetry best-effort:

```text
python scripts/emit_capability.py setup
```

Initialize or load state:

```text
python scripts/mcp_config.py materialize-defaults
python scripts/setup_state.py init
```

The command validates the state schema and prints only the current step
summary. If it fails, show the specific error and stop. Never recreate or
overwrite corrupt state silently.

**First run only — decide silently, then ask once.** Work through this gate in a
single pass with **no narration** (do not say "reading state", "no plan found",
"this is a first run"): the maker's first visible output is either the
workspace-binding explanation or the opening question.

- If `init` above shows any completed step or an advanced active step, this is a
  **resume** — go straight to dispatch, no question; `/setup` is never asked again
  once environment setup is under way.
- Otherwise it is a first `/setup` (active step `SETUP-01`, nothing completed).
  Silently run `python scripts/planner/cli.py setup-status` (read-only JSON, no
  narration) and branch on its fields:
  - **No plan** (`hasPlan` false) — ask the opening question below.
  - **Plan, but the environment still needs creating** (`hasPlan` true **and**
    `setupTaskOpen` true **and** `environmentPinned` false) — the plan's "run
    `/setup`" task is still open. Check `environment` as well: an ID without a
    URL is an existing environment whose URL must be resolved through environment
    discovery, not permission to create a replacement. If no environment is
    recorded, **this
    `/setup` IS that task**: the maker running it is the admin who owns
    environment creation. Continue setup directly when this is their assigned
    task or they already asked to set up; otherwise show the opening question.
  - **Environment exists, but no installed agent is recorded** (`environmentPinned`
    true, `agentPinned` false) — reuse the environment and continue foundation
    setup to discover/install ESS. A pinned environment alone does not prove an
    agent is ready for workspace binding. Do not create another environment.
  - **Plan with an existing environment and agent** (`environmentPinned` and
    `agentPinned` true) — distinguish
    the shared rollout from **this person's workspace**. If `.local/config.json`
    is absent, incomplete, or targets a different environment, enter
    `src/skills/onboarding/step1.md` to reuse the plan's environment and bind this
    workspace. Preserve the assigned task; after binding, return to its brief.
    Do not redirect to Planner or provision a second environment. Shared setup
    proves resources exist, not that this caller has permissions.
    If the local workspace already targets that environment, return to the
    assigned task without restarting setup.
  - **Plan without a pinned environment, but no open setup task** — this does
    not prove setup is complete. Follow the explicit setup request or opening
    question; do not loop back to Planner.

If the user already asked to configure/install ESS, or arrived from an assigned
admin setup task, skip the opening question and continue setup. When only workspace
binding is needed, say: "The shared environment is ready. I'll connect your
workspace to it, then return to your assigned task."

`firstRunSetupTaskId` identifies a ready provisioning task even when a separate
later workspace-binding task produces `primaryEnvironment`. Prefer that task
for the admin's handoff; never start a blocked binding task just because its
title says setup.

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Where would you like to start?",
    "question": "Before we set up your environment — which is closest to what you need right now?",
    "options": [
      { "label": "Plan your ESS rollout", "description": "Work out what to build, which systems to connect, and who owns each part. Choose this if you don't have an ESS environment yet, you're still exploring what ESS can do, or you're not sure where to start." },
      { "label": "Set up the environment now", "description": "You're ready to configure a Power Platform environment and install ESS. This needs Power Platform admin access." }
    ],
    "allowFreeformInput": true
  }
]
```

- If the maker chooses **"Plan your ESS rollout"** — or says anything like
  "plan", "help me figure out ESS", "I don't have an environment yet", "where do
  I start", or "create a plan" — this is a planning request. Read
  `src/skills/planner/SKILL.md` and follow it instead; do **not** continue the
  foundation setup below. Planning is allowed before setup and emits "run
  `/setup`" as a task once an environment is actually needed.
- If the maker chooses **"Set up the environment now"**, or already asked to
  configure or install the environment, continue with the foundation setup below.

If `connect_ready` is true, inspect `.local/config.json`:

- If its `setup` value is `"complete"`, show that foundation and workspace setup
  are complete and direct the maker to `/connect`.
- Otherwise read `src/skills/onboarding/foundation-bootstrap.md` and follow it.
  The bootstrap must reuse `environment.tenant_endpoint`, must not render
  another setup checklist, and must proceed directly to the installed-agent
  inventory choice.

On the first invocation or when explicitly resuming `/setup`, render the
checklist from `src/skills/foundation-setup/steps.md`. Derive completed rows from
`completed_steps` and the current row from `active_step`:

- `done` = ✅
- `in-progress` = 🔄
- `blocked` = ⛔
- `pending` = ⬜

**Message:**

Here's your ESS foundation setup:

- {marker} Choose and lock the target environment
- {marker} Verify environment access and Dataverse
- {marker} Confirm MCP, capacity, billing, and governance prerequisites
- {marker} Reverify the locked environment
- {marker} Configure the preferred unmanaged solution
- {marker} Select, install, and bind an ESS product
- {marker} Verify baseline agent readiness
- {marker} Confirm the setup-to-connect handoff

**End message.**

The persisted `active_step` is authoritative. Dispatch to it immediately.
Resumption does not require user input.

Never infer the active step from prior conversation, a previously read
playbook, or the last command that ran. If persisted `active_step` is not
`SETUP-02.1` or `SETUP-02.2`, do not read or execute
`foundation-setup/prerequisites.md`. A completed prerequisite step must never be
rechecked during resume unless state is explicitly reopened by a state command.

Every step persists only its note, mode, checkpoint, and recorded timestamp.
Keep canonical facts in the environment, prerequisites, ALM, and product
sections; do not create a separate validations collection or duplicate evidence.

---

## Dispatch

| Active step | Playbook |
|---|---|
| `SETUP-01` | `src/skills/foundation-setup/scope.md` |
| `SETUP-02.1` | `src/skills/foundation-setup/prerequisites.md` |
| `SETUP-02.2` | `src/skills/foundation-setup/prerequisites.md` |
| `SETUP-03` | `src/skills/foundation-setup/environment.md` |
| `SETUP-04` | `src/skills/foundation-setup/alm-baseline.md` |
| `SETUP-05` | `src/skills/foundation-setup/install-starters.md` |
| `SETUP-06` | `src/skills/foundation-setup/readiness.md` |
| `SETUP-07` | `src/skills/foundation-setup/handoff.md` |

Read and follow the playbook for the active step. After it returns, run
`python scripts/setup_state.py show --view current`, show only the completed
result and next required action, then dispatch directly to the returned
`active_step`. Do not rerender the full checklist between steps.

Never route from `/setup` into an integration or topic playbook.
