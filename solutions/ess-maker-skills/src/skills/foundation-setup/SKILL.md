<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# ESS Foundation Setup

Every **Message** block is exact user-facing text. Do not expose internal step IDs,
checkpoint IDs, state paths, or tool narration.

Follow `src/reference/ui-formatting-guidelines.md` for every user-facing
instruction in this flow. Resolve its examples with the actual environment,
agent, product, and connector names before displaying them.

## Setup state sources

- **Current setup state:** `.local/setup/config.json`
- **Active agent and workspace:** `.local/config.json`
- **Setup evidence:** `.local/setup/agents/{AGENT_ID}/`

Use the active agent's entry in `.local/setup/config.json` when determining its
setup progress and readiness. Evidence files support that state; they are not a
separate setup record.

Maker-visible setup text consists of the defined **Message** blocks and
questions, their choices, an observed blocker with its supported recovery, and
the final handoff. Operational sequencing and response-policy prose are
instruction-only. Successful internal operations continue directly to the next
defined maker interaction.

This is the DA-GA `/setup` entry point. It owns only:

- maker authentication;
- Power Platform environment and editable Dev agent selection;
- native DA identity and ALM-family validation;
- local workspace materialization;
- resumable setup state and completion reporting.

Workday, ServiceNow, SAP SuccessFactors, connector authentication, extension
packs, and topics are explicitly outside this skill.

---

## Maker-facing progress

Write the exact maker-facing progress checklist below as a complete snapshot at these render points: the first interactive setup surface in a turn, a change to any of its five markers, a blocked state that requires maker action, and the final handoff. Every rendered update contains all five stages in this order and uses the same ordinary Markdown shape: one single-level bullet and one leading status emoji per stage. Send the complete **Message** block as its own chat message. Finish that message before opening the next question or interactive control; the next control begins with its own prompt, explanation, and choices. Use the latest canonical setup state read in this invocation and results observed in this invocation to set their statuses. A sequence of setup operations that retains the same markers continues to its next render point without another progress snapshot. Preserve completed stages and keep pending stages present. Report setup-owned FlightChecks in the separate runtime-readiness table defined by the shared existing-agent completion path; a FlightCheck result does not roll back a completed access, identity, agent-establishment, or materialization stage. Mark **Review the setup handoff** complete in the final snapshot. Do not expose the eight internal setup-step IDs or show skipped internal records as successful checks.

**Message:**

Here's your ESS agent setup:

- {marker} Choose the starting point and target environment
- {marker} Verify access and agent identity
- {marker} Establish an editable Dev agent
- {marker} Materialize the local workspace
- {marker} Review the setup handoff

**End message.**

Use ✅ for completed, 🔄 for the current stage, ⛔ for a blocked stage, and ⬜ for pending. Derive markers only from supplied context, results observed in this invocation, and canonical setup state read in this invocation. Never infer progress from conversation history.

The checklist is a view, not another state model. It tracks local workspace setup actions, not the runtime-readiness verdict:

- a supplied or selected target completes the first stage;
- direct service validation of an exact editable Dev completes the second and third stages for the existing-agent path;
- a successful package import with direct Dev validation completes the second and third stages for the supplied-package path;
- service inspection of a Prod source completes access and source-identity verification; a directly validated related Dev or successful create-only import completes the editable-Dev stage;
- a successful MOS create followed by direct Dev attachment validation completes access, identity, and editable-Dev establishment for the fresh-agent path;
- `connectionStatus: workspace-ready` with canonical workspace evidence and `SETUP-07` in state `done` completes local workspace materialization, independently of `connectReady`;
- reviewing the factual completion report completes the handoff stage in the conversation and does not write another readiness marker.

Before canonical setup begins, mark the first unresolved checklist stage with 🔄 and leave later stages marked ⬜. Mark a checklist stage ⛔ only when the operation named by that stage is itself blocked, and preserve its failure causes in the response. A blocked capacity, connection, or content FlightCheck belongs in the runtime-readiness table and does not change an already completed checklist marker. Do not mark a stage complete from a skipped internal setup record.

## Choose the sign-in account

After resolving the Python invocation and before the first command that can authenticate, inspect only this workspace's existing AgentBuilder cache:

```text
python scripts/setup_existing_da.py cached-accounts
```

Parse `DA_AGENTBUILDER_ACCOUNTS_JSON:`. This is a local read and does not authenticate.

- Ask exactly one account question: **Which Microsoft account should setup use to access the target Power Platform environment?** Explain that this Microsoft sign-in is separate from GitHub/Copilot sign-in.
- Build the choices in this order: **Skip — Use the Microsoft account picker** first, followed by every cached sign-in name. Do not preselect or recommend an option. Allow a different account sign-in name as free-form input. Do not add a separate **Use another account** choice or a follow-up account question.

Retain a confirmed or supplied sign-in name as `{SETUP_ACCOUNT}` and append `--account "{SETUP_ACCOUNT}"` to every `setup_existing_da.py`, `setup_mos_starter.py`, `setup_alm_export.py`, `setup_alm_import.py`, and `reconcile_setup_agent.py` command in this invocation. Never infer a corp account.

When the maker selects **Skip — Use the Microsoft account picker**, omit `--account` and append `--select-account` only to the first command that can authenticate. Parse `DA_AGENTBUILDER_AUTH_JSON:` from that command's output, retain its non-empty `account` as `{SETUP_ACCOUNT}`, and use `--account "{SETUP_ACCOUNT}"` for every later command in this invocation. The picker establishes the identity once; later commands reuse its cached token and sign-in name.

If the first authenticated command succeeds but does not return an account identity, run `setup_existing_da.py cached-accounts` again. Retain its sole account when exactly one is present. When no single identity can be established, state that setup could not retain the selected sign-in and ask which sign-in name the maker selected before continuing.

Account selection does not prove that the maker holds a particular administrator role. Let each service operation validate its own permissions and preserve its specific authorization error instead of rejecting the selected account through a blanket local admin check.

Present account confirmation once per setup invocation. Do not repeat it before later commands.

## Reconcile every selected agent

Whenever one exact environment and agent has been selected, read `src/skills/foundation-setup/product-line-reconciliation.md` and complete that handoff before the next DA-GA-only operation. This applies regardless of whether the identity came from a supplied URL, active local setup state, a configured-agent switch, environment candidate selection, MOS creation, or ALM import. Run it once per selected identity in this invocation and again only when the selection changes.

## Shared authorization message

The account question is the confirmation for a selected account. When the maker chose the Microsoft account picker, show:

> Microsoft sign-in will open. Select the account you use to access this environment. If the expected account is not shown, choose **Use another account**.

If the terminal returns control while that command is waiting for the browser callback, show:

> **Waiting for authorization**
>
> Complete the Microsoft sign-in in your browser. I will continue automatically after authorization finishes.

Do not describe an authorization wait as service processing, start a second command, or ask the maker to provide a token.

---

## Command runtime

Establish a working Python invocation before running setup commands.

Before checking the available Python invocation, render this exact Message
block as a completed response. This is an informational disclosure, not another
setup confirmation. The current `/setup` request or the explicit choice that
entered this skill already confirms the maker's intent. After rendering the
message, proceed directly with runtime discovery:

**Message:**

**Setup command approvals**

VS Code will ask you to approve commands that:

- check Python and prepare the required local tools;
- sign you in and inspect the selected environment and agent;
- perform the setup actions you confirm and prepare the local workspace;
- download required Microsoft components when needed.

To avoid repeated prompts, open the permissions menu below the chat input and
select **Allow all** for this chat session. This applies to every tool used in
the session, not only setup. Provide a screenshot of your chat input if you
need guidance finding the setting.

**End message.**

- Run setup commands from the current ESS Maker Skills workspace folder.
- From the kit root, check each candidate with
  `{PYTHON} -c "import sys; print(sys.executable)"`, one terminal command at a
  time: `py -3`, `python3`, then `python` on Windows; `python3`, then `python`
  on macOS or Linux.
- Reuse the first invocation that succeeds throughout setup.
- If needed, check active virtual environments, common local installation
  paths, and repository-supported repair commands.
- When local recovery options appear exhausted, explain the external action
  needed and offer to perform it.

  After successful runtime and dependency validation, run the next setup
  operation. When validation requires maker action, state the observed failure
  and its single recovery action.

  When child guidance shows `python`, substitute the resolved invocation.

### When command approval is declined

A declined VS Code command approval pauses the current setup operation before
the command runs. Render this exact response, substituting the declined command
and the shell language appropriate for the current platform:

> **Run this command manually**
>
> Setup paused before running this command:

```{SHELL}
{COMMAND}
```

> Run it from the current workspace. When it finishes, return here with the
> result and I'll continue setup from this step.

Resume from the paused operation when the maker returns. Continue from a
successful result; apply the command-failure recovery guidance to a failed
result.

## Shared workspace choices

One workspace targets one Power Platform environment, can contain multiple ESS Dev agents from that environment, and has one active agent at a time. `.local/config.json` owns the active agent through `activeAgent` and the matching `agent` entry. Canonical setup state records readiness independently for every configured agent.

When an occupied workspace needs a new environment, offer **Create and open a new workspace**. Derive a suggested destination from the current repository folder name by appending `-fresh`. If that sibling exists, append the first available numeric suffix (`-fresh-2`, `-fresh-3`, and so on). Use the host's interactive single-selection control and offer exactly:

- **Use suggested location -- {suggested absolute sibling-folder path}**
- **Choose another location**
- **Cancel setup**

Do not ask the maker to type a path unless they select **Choose another location**. The destination must be a new absolute sibling-folder path outside the current Developer Kit repository. Then run:

```text
python scripts/prepare_fresh_workspace.py \
  --destination "{NEW_WORKTREE_PATH}" \
  --open-vscode
```

Parse `DA_PREPARED_WORKSPACE_JSON:`. When `outcome` is `workspace-created` and `vscodeOpened` is `true`, say that the new VS Code window is open at `{kitRoot}` and ask the maker to run `/setup` there. For `workspace-created-open-failed`, explain that the workspace was created, give `{kitRoot}`, and ask the maker to open it manually. Stop this invocation after the workspace handoff.

For **Reset and use this workspace**, show:

> Resetting this workspace will archive its current local agent files, setup records, and FlightCheck results. It will not change or delete any agent in Copilot Studio. Continue?

Offer exactly:

- **Reset workspace**
- **Go back**
- **Cancel setup**

Do not preselect **Reset workspace**. Continue only when the maker selects it, then run:

```text
python scripts/reset_local_workspace.py --confirm-reset
```

Parse `DA_RESET_WORKSPACE_JSON:`. When `outcome` is `workspace-reset`, say that the local setup was archived to `{backupRoot}`, then continue from the unoccupied-workspace route. When `outcome` is `nothing-to-reset`, continue without a backup message. For any error, report its `ERROR:` and `NOTE:` output and stop; each note identifies a path that could not be restored.

For **Switch to another configured agent**, show the locally configured agents other than the active one. After the maker selects an exact agent, complete the selected-agent product-line reconciliation before changing the active local selection, then run:

```text
python scripts/setup_existing_da.py select-agent \
  --agent-id "{SELECTED_AGENT_ID}"
```

Parse `DA_ACTIVE_AGENT_JSON:`. Continue setup for that agent when its `connectReady` value is not `true`; otherwise present the completion choices below. This operation changes only local active-agent selection.

The final handoff is the sole completion summary. After it, offer exactly these context-appropriate choices:

- **Finish setup**
- **Switch to another configured agent** -- only when another configured agent exists.
- **Install another product in this environment**
- **Reset and use this workspace**
- **Create and open a new workspace**

Do not preselect a choice. **Finish setup** closes the setup flow. Do not render
another setup completion summary. After the maker selects it, show:

**Message:**

The {agent display name} agent is now active.

- Run `/landing-page` to configure branding and the content employees see.
- Run `/connect` to choose an integration.
- Type `/menu` to see all available capabilities.

**End message.**

Then end the request.

**Install another product in this environment** begins `da-mos-starter.md` at
its first product-installation decision surface with the recorded environment
and ring. Every other selected follow-up begins at that follow-up's first
decision surface rather than rendering another completion summary.

## Start

Use context supplied with the current setup request and canonical setup state read in this invocation. Do not infer a route or mismatch from conversation history.

Treat requests to create a new agent, install another product, or start with a
fresh agent as explicit fresh-install intent. Resolve that intent before
active-agent resume handling. Read canonical setup state and `.local/config.json`
only to compare the recorded workspace environment with the requested target.
For the same environment, retain every configured agent and continue directly
through `src/skills/foundation-setup/da-mos-starter.md`. For a different
environment, follow **Create and open a new workspace**. This route uses the
environment match as its workspace decision; existing-agent readiness remains
unchanged.

When the current request supplies no agent, environment, package, or fresh-agent intent, read canonical setup state and `.local/config.json`. A usable active local target must identify the agent display name, agent ID, environment ID, service ring or validated API endpoint, and local workspace folder. Treat these values only as routing input; they do not prove current access, realm, or readiness.

For a usable local target, ask:

> **{agent display name}** is the active agent in this workspace. What would you like to do?

Offer exactly these context-appropriate choices:

- **Continue with this agent**, or **Resume setup for this agent** when its canonical agent record is incomplete or blocked.
- **Switch to another configured agent** -- only when another configured agent exists.
- **Install another product in this environment**
- **Reset and use this workspace**
- **Create and open a new workspace**
- **Cancel setup**

Do not preselect a choice. Follow the corresponding shared workspace choice above.

For **Continue with this agent** or **Resume setup for this agent**, complete the one-time account selection and selected-agent product-line reconciliation above, then run:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{RECORDED_ENVIRONMENT_ID}" \
  --agent-id "{RECORDED_AGENT_ID}" \
  --ring "{RECORDED_RING}"
```

Also pass the recorded validated `--host` and `--api-version` when available. Parse `DA_AGENT_ROUTE_JSON:` and follow the same realm routing used for a supplied URL. Do not ask for the agent or environment URL.

For **Cancel setup**, make no changes and stop.

Do not describe a supplied agent as editable, Dev, Test, or Prod until a
server-backed inspection has identified its route realm.

When canonical setup already identifies a local Dev agent, do not announce an
agent mismatch, workspace switch, or refresh merely because the supplied URL
contains another agent ID. A Prod source and its related Dev agent have
different IDs by design. Classify the supplied agent first, then use the
server-reported ALM relationship to determine whether the existing workspace
already targets its related Dev agent.

When the maker supplies a Copilot Studio URL that identifies an agent and has
not explicitly selected package import, infer its environment ID, agent ID,
and service ring. When the URL does not identify the ring, use **Resolve the
service ring** in `src/skills/foundation-setup/da-environment-target.md`
exactly. Ask only when the environment ID or agent ID is unclear. Complete the
selected-agent product-line reconciliation before running:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_ROUTE_JSON:`. Do not infer the realm from names, URLs, or
environment metadata.

- When `realm` is `prod`, read
  `src/skills/foundation-setup/da-prod-to-dev.md` and follow it, passing the
  inspection's internal tenant, environment, host, ring, API version, and agent
  identity where that guidance requests source context. This setup path does
  not emit setup telemetry. Do not continue routing in this file.
- When `realm` is `dev`, continue through
  `src/skills/foundation-setup/da-existing-dev.md`, using the inspected internal
  context for validation and attachment. Do not repeat realm inspection or
  continue routing in this file.
- For any other realm, explain that local authoring requires a Dev agent or a
  Prod agent that can establish Dev, and stop.

Do not display the inspection's internal IDs, API host, service ring, or API
version.

Record anonymous usage telemetry best-effort:

```text
python scripts/emit_capability.py setup
```

When the maker has already supplied a native agent package or explicitly asked to use one, read `src/skills/foundation-setup/da-alm-import.md` and follow it. That skill owns the explicit package handoff and reads the canonical import reference. This is an advanced handoff, not a setup option to advertise or recommend.

When the request identifies an environment and explicitly asks to connect to an existing agent, read `src/skills/foundation-setup/da-existing-dev.md` and follow its environment-candidate selection path.

When the request identifies an environment but not an agent or create-versus-connect intent, retain the resolved environment ID and service ring. Send the current progress snapshot using the shared **Message** contract, then ask exactly:

> What would you like to set up in `{environment name or the selected Power Platform environment}`?

Offer exactly:

- **Create a fresh agent in this environment**
- **Connect to an existing agent in this environment**
- **Cancel setup**

Require an explicit selection; all choices begin unselected.
Resolve the environment label from known context. This question confirms the selected target; the access-verification stage remains current until a service operation succeeds.

- For **Create a fresh agent in this environment**, continue directly through `src/skills/foundation-setup/da-mos-starter.md` with the retained environment and ring.
- For **Connect to an existing agent in this environment**, read `src/skills/foundation-setup/da-existing-dev.md` and follow its environment-candidate selection path with the retained environment and ring.
- For **Cancel setup**, make no changes and stop.

When the request does not identify an agent or environment and no usable local target exists, ask:

> Do you already have an ESS agent in Copilot Studio?

Offer exactly:

- **Yes, I have an agent** — ask for its Copilot Studio URL.
- **No, I need a fresh agent** — follow `src/skills/foundation-setup/da-mos-starter.md`.

Do not run Dataverse foundation or onboarding playbooks. Never route from
`/setup` into an integration or topic playbook. **Finish setup** advertises
separate commands and ends the current request; a command selected afterward
begins its own prompt flow.
