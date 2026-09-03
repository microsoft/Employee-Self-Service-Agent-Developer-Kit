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

---

## Start

Record anonymous usage telemetry best-effort:

```text
python scripts/emit_capability.py setup
```

Initialize or load state:

```text
python scripts/setup_state.py init
```

The command validates the state schema and prints only the current step
summary. If it fails, show the specific error and stop. Never recreate or
overwrite corrupt state silently.

If `connect_ready` is true, inspect `.local/config.json`:

- If its `setup` value is `"complete"`, show that foundation and workspace setup
  are complete. Tell the maker they can run `/landing-page` or `/connect`, or
  type `/menu` to see every capability.
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
