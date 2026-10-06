<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# ESS Foundation Setup

Every **Message** block is exact user-facing text. Do not expose internal step IDs,
checkpoint IDs, state paths, or tool narration.

Follow `src/reference/ui-formatting-guidelines.md` for every user-facing
instruction in this flow. Resolve its examples with the actual environment,
agent, product, and connector names before displaying them.

Read `src/skills/foundation-setup/permission-guidance.md` whenever setup opens
Microsoft authorization, encounters denied access, names a Power Platform role,
or hands an action to an administrator. That file owns the operation-specific
role language and administrator handoff.

## Setup state sources

- **Current setup state:** `.local/setup/config.json`
- **Active agent and workspace:** `.local/config.json`
- **Setup evidence:** `.local/setup/agents/{AGENT_ID}/`

Use the active agent's entry in `.local/setup/config.json` when determining its
setup progress and readiness. Evidence files support that state; they are not a
separate setup record.

Read `.local/setup/config.json` and `.local/config.json` once per setup
invocation, reusing content already read by the parent prompt. Retain the
resolved workspace environment, active agent, account, service origins, and
operation results for later routing. Reread a source only after an operation in
this invocation changes that source. Do not rerun inventory, reconciliation, or
inspection merely because a later branch needs a value already retained; keep
the explicit post-enrollment reinspection and maker-requested refreshes.

Maker-visible setup text consists of the defined **Message** blocks and
questions, their choices, an observed blocker with its supported recovery, and
the final handoff. Operational sequencing and response-policy prose are
instruction-only. Successful internal operations continue directly to the next
defined maker interaction.

## Standard choices and ad hoc recovery

Choice lists define the standard maker-facing UX for the current decision. Render the listed choices in the documented order with their labels unchanged, initially unselected, and with custom entry disabled inside the interactive control.

The choice list is not an exhaustive recovery contract. If the maker instead types another recovery action in chat, treat that message as current intent and compose the available bounded operations when the requested action can be performed. Preserve existing evidence, obtain the existing confirmation for consequential mutations, and let authoritative service operations validate remote state. Do not reject a recovery solely because it is absent from the presented choices. When the typed intent is ambiguous, explain what must be resolved and present the standard choices again.

Typed intent may select only a documented setup route or bounded read-only recovery. It never authorizes an unlisted mutation or replaces an explicit confirmation required before create, import, replacement, reset, cleanup, or another consequential action.

### Help me decide

On decision surfaces that include **Help me decide**, append it after the substantive choices and before refresh, environment-switch, **Go back**, or cancel actions. Render it as part of the owning closed interactive control. When the maker selects it, resolve that control and continue the conversation in the **Chat view**.

Start by sending this agent response:

> Tell me what you’re trying to accomplish and anything you already know. Plain language is fine.

Wait for the maker to enter a follow-up message in the chat input box. Continue one conversational turn at a time, with one short, targeted question in each agent response followed by the maker's next follow-up message. Keep the conversation focused on the current decision. Compare the documented choices using the maker's answers and relevant facts already established. When a relevant fact remains unknown, explain how the maker can obtain it or which person can confirm it, then continue when the maker supplies that information.

When enough information is available, summarize the maker's situation, say **I’d choose `{option}` because `{reason grounded in the maker's answers or current evidence}`**, and explain when the closest alternative would be preferable. Then render the owning decision's original closed choices again, including **Help me decide**, with every choice initially unselected. The maker completes the decision by selecting one of those choices. If the maker selects **Help me decide** again, continue from the context already shared.

### What does setup do?

Use this orientation automatically only for a context-free setup request with
no usable active local target and no incomplete canonical setup record to
resume. When the current request already identifies an existing agent, fresh
agent, package, agent URL, environment, or resume intent, enter that route
directly.

On an initial setup-routing surface where established context skipped the
automatic orientation, append **What does setup do?** after the substantive
route choices and before **Help me decide**, reset, workspace, **Go back**, or
cancel actions. Selecting it resolves the current control, renders the
orientation below, and then renders that control's original choices again with
every choice initially unselected. Preserve the selected environment, agent,
account, and canonical setup state.

Do not add **What does setup do?** to authentication confirmations, permission
failures, administrator handoffs, remediation controls, rechecks, or final
completion choices.

**Message:**

### What does setup do?

Setup creates an Employee Self-Service agent in a Power Platform environment—or connects to one you already have—and tracks it locally in a VS Code workspace.

#### Why do I need this?

Setup maintains a local copy of the agent in this VS Code workspace. ADK needs this workspace copy to help you:

- inspect and customize agent content;
- create or update topics and configuration;
- review and validate changes; and
- send explicitly approved changes back to the agent.

Local changes do not affect the agent in Copilot Studio until you choose a later update or publishing action.

#### What you need

A Power Platform environment is the cloud location where Copilot Studio stores your agent, connections, and runtime configuration. You need an environment before an ESS agent can be created or connected.

- To use an existing agent, your login needs access to that agent and environment.
- To create a new agent, your login needs permission to create agents in the selected environment.
- When administrator help is required, setup identifies the exact action and prepares information you can forward.

#### What installing an agent means

For a new agent, setup creates an editable ESS agent from a supported agent template in the environment you select.

For an existing agent, setup verifies and connects to that exact agent instead of creating another one.

Installing or connecting an agent does not publish it or make it available to employees.

#### What setup verifies

Setup verifies the selected environment, agent identity, access, editable agent route, local workspace copy, and readiness requirements through Flight Checks.

Setup remains active when a Flight Check needs attention. It does not report successful completion until the readiness requirements are complete.

#### What setup does not do

Setup does not automatically:

- publish the agent;
- make it available to employees;
- promote it to another environment;
- configure an HR or IT system integration;
- allocate capacity or grant permissions; or
- perform administrator actions on your behalf.

**End message.**

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

Write the exact maker-facing progress checklist below as a complete snapshot at these render points: the first interactive setup surface in a turn, a change to any of its five markers, a blocked state that requires maker action, and the final handoff. The already-complete active-agent entry surface defined under **Start** is the only exception: do not render a progress checklist until the maker chooses **Redo setup for this agent**. Every rendered update contains all five stages in this order and uses the same ordinary Markdown shape: one single-level bullet and one leading status emoji per stage. Send the complete **Message** block as its own chat message. Finish that message before opening the next question or interactive control; the next control begins with its own prompt, explanation, and choices. Use the latest canonical setup state read in this invocation and results observed in this invocation to set their statuses. A sequence of setup operations that retains the same markers continues to its next render point without another progress snapshot. Preserve completed stages and keep pending stages present. Report setup-owned FlightChecks in the separate runtime-readiness table defined by the shared existing-agent completion path; a FlightCheck result does not roll back a completed access, identity, agent-establishment, or materialization stage. Mark **Review the setup handoff** complete in the final snapshot. Do not expose the eight internal setup-step IDs or show skipped internal records as successful checks.

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

- When no cached account is returned, do not ask an account question. Use the Microsoft account picker on the first command that can authenticate.
- When exactly one cached account `{CACHED_ACCOUNT}` is returned, ask **Continue with {CACHED_ACCOUNT}?** and present **Continue** and **Use a different user** as the standard choices, with no preselected choice and custom entry disabled inside the control. **Continue** retains that account. **Use a different user** uses the Microsoft account picker on the first command that can authenticate.
- When two or more cached accounts are returned, ask **Which Microsoft account should setup use to access the target Power Platform environment?** Explain that this Microsoft sign-in is separate from GitHub/Copilot sign-in. Build the standard choices in this order: **Use the Microsoft account picker** first, followed by every cached sign-in name, then **Help me decide**. Do not preselect or recommend an option. Disable custom entry inside the control.

For **Help me decide** on the multiple-account surface, follow the shared contract above. Establish whether the maker is accessing an existing agent, creating a fresh agent, or only discovering environments. Explain that an existing-agent path needs the login that created the exact agent, a fresh-agent path needs a login whose environment permissions allow agent creation, and environment discovery needs a login that can access the target environment. Recommend only an account the maker identifies as satisfying the applicable reason; otherwise recommend the Microsoft account picker.

Retain a confirmed cached sign-in name as `{SETUP_ACCOUNT}` and append `--account "{SETUP_ACCOUNT}"` to every `setup_existing_da.py`, `setup_mos_starter.py`, `setup_alm_export.py`, `setup_alm_import.py`, and `reconcile_setup_agent.py` command in this invocation. Never infer a corp account.

When no cached account exists, or the maker selects **Use a different user** or **Use the Microsoft account picker**, omit `--account` and append `--select-account` only to the first read-only command that can authenticate. Parse `DA_AGENTBUILDER_AUTH_JSON:` from that command's output, retain its non-empty `account` as `{SETUP_ACCOUNT}`, and use `--account "{SETUP_ACCOUNT}"` for every later command in this invocation. The picker establishes the identity once; later commands reuse its cached token and sign-in name.

`reconcile_setup_agent.py` does not accept `--select-account`, and a command that may mutate remote state must not establish the selected identity. When reconciliation or a mutating operation would otherwise be the first authenticated command, first run `setup_existing_da.py list-environments --ring "{RING}" --select-account` only to establish `{SETUP_ACCOUNT}`. Do not use its environment rows to replace an already selected target. Parse `DA_AGENTBUILDER_AUTH_JSON:`, retain the selected account, and pass it to reconciliation or mutation with `--account "{SETUP_ACCOUNT}"`. Do not pass `--select-account` to `reconcile_setup_agent.py` or a mutating command.

When the read-only account-establishment operation does not return an
authenticated account, or when a returned account differs from an account the
maker explicitly named, follow the corresponding recovery under **Microsoft
authorization** in `permission-guidance.md` before retaining an account or
using the read-only operation result.

If the first authenticated command succeeds but does not return an account identity, run `setup_existing_da.py cached-accounts` again. Retain its sole account when exactly one is present. When no single identity can be established, state that setup could not retain the selected sign-in and rerun the Microsoft account picker before continuing.

Account selection does not prove that the maker holds a particular administrator role. Let each service operation validate its own permissions and preserve its specific authorization error instead of rejecting the selected account through a blanket local admin check.

Present account confirmation once per setup invocation. Do not repeat it before later commands.

## Confirm people and role availability for the selected path

After the setup path, target environment, and Microsoft login are known,
but before the first agent inventory, exact-agent inspection, or
agent-template listing, render the matching **Setup-path people and role
walkthrough** from `permission-guidance.md`.

This is an upfront planning checkpoint. It identifies the maker access required
now and the administrator personas that may be needed later without claiming
that every administrator is required. The maker's availability answer is not
authorization evidence; every service operation still verifies its own access.

When this file runs the first protected operation directly, complete the
walkthrough here. When a child skill owns that operation, pass whether the
walkthrough was completed and require the child to render it if it was not.
Render it again when the effective setup path changes, including an
existing-agent path entering creation or a fresh-agent collision entering
existing-agent adoption, or after the maker changes the target environment or
Microsoft login.

## Reconcile every selected agent

Whenever one exact environment and agent has been selected, read `src/skills/foundation-setup/product-line-reconciliation.md` and complete that handoff before the next DA-GA-only operation. This applies regardless of whether the identity came from a supplied URL, active local setup state, a configured-agent switch, environment candidate selection, MOS creation, or ALM import. Run it once per selected identity in this invocation and again only when the selection changes.

For a supplied Microsoft Copilot Studio URL, retain its exact `agentBackend` query value as an ordering hint for that handoff. Do not infer existence, product family, support, or ALM enrollment from the hint.

## Shared authorization message

The account question is the confirmation for a selected account. When the maker chose the Microsoft account picker, show:

> Microsoft sign-in will open. Select the account you use to access this environment. If the expected account is not shown, choose **Use another account**.

Signing in does not grant environment, agent, or administrator access. Each
requested operation verifies its own access. When authentication evidence
explicitly identifies missing first-party application approval, follow
**Microsoft authorization** in `permission-guidance.md`; do not use that route
for a generic 401 or 403.

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

These approvals let VS Code run local commands. They do not grant Power
Platform access, approve a Microsoft application, or assign administrator
roles.

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

When an occupied workspace needs a new environment, ask exactly:

> This workspace is currently set up for **{current environment}**. How would you like to set up **{new environment}**?

Use the host's interactive single-selection control and present these choices:

- **Use the new environment in this workspace (Recommended)** -- archive the current local setup and reuse this workspace.
- **Work with both environments side by side** -- create a separate Git worktree for the new environment.
- **Go back**

Until the maker selects and confirms a path, describe the two environments
neutrally. Do not say that setup will switch, reset, reuse, archive, or open a
workspace before the corresponding choice and confirmation.

For **Use the new environment in this workspace (Recommended)**, do not derive or create a fresh destination. Show:

> Reusing this workspace will archive its local setup records, agent files, and FlightCheck results for **{current environment}**. It will not change or delete any agent in Copilot Studio. Continue?

Present these choices:

- **Archive and reuse this workspace (Recommended)**
- **Go back**

Do not preselect a choice. For **Go back**, make no changes and return to the conflicting-environment choice surface. Continue only when the maker selects **Archive and reuse this workspace (Recommended)**, then run the shared reset operation below.

For **Work with both environments side by side**, derive a suggested destination from the current repository folder name by appending `-fresh`. If that sibling exists, append the first available numeric suffix (`-fresh-2`, `-fresh-3`, and so on). Ask:

> Where should setup create the workspace for **{new environment}**?

Present these choices:

- **Use suggested location -- {suggested absolute sibling-folder path}**
- **Choose another location**
- **Go back**

For **Go back**, make no changes and return to the conflicting-environment choice surface. Do not ask the maker to type a path unless they select **Choose another location**. The destination must be a new absolute sibling-folder path outside the current Developer Kit repository. Continue only after the maker selects a destination, then run:

```text
python scripts/prepare_fresh_workspace.py \
  --destination "{NEW_WORKTREE_PATH}" \
  --open-vscode
```

Parse `DA_PREPARED_WORKSPACE_JSON:`. When `outcome` is `workspace-created` and `vscodeOpened` is `true`, say that the new VS Code window is open at `{kitRoot}` and ask the maker to run `/setup` there. For `workspace-created-open-failed`, explain that the workspace was created, give `{kitRoot}`, and ask the maker to open it manually. Stop this invocation after the workspace handoff.

For **Reset and use this workspace**, show:

> Resetting this workspace will archive its current local agent files, setup records, and FlightCheck results. It will not change or delete any agent in Copilot Studio. Continue?

Present these standard choices:

- **Reset workspace**
- **Go back**

Do not preselect **Reset workspace**. For **Go back**, make no changes and return to the choice surface that offered **Reset and use this workspace**. Continue only when the maker selects **Reset workspace**, then run:

```text
python scripts/reset_local_workspace.py --confirm-reset
```

This is also the shared reset operation used after **Archive and reuse this workspace (Recommended)**. Parse `DA_RESET_WORKSPACE_JSON:`. When `outcome` is `workspace-reset`, say that the local setup was archived to `{backupRoot}`, then continue from the unoccupied-workspace route. When `outcome` is `nothing-to-reset`, continue without a backup message. For any error, report its `ERROR:` and `NOTE:` output and stop; each note identifies a path that could not be restored.

For **Switch to another configured agent**, do not use the saved `agents` array as the picker inventory. Run `setup_existing_da.py list-agents` against the active agent's exact environment connection and build the picker from the current live result using the established existing-agent candidate rules. Use `.local/config.json` only to match the exact active `botId` and locally configured identities against that live inventory.

Render every live option using its exact service-provided display name. Append **— Current** only to the option whose exact ID matches the active `botId`; do not append a realm, enrollment state, ALM label, preparation status, schema, ID, or workspace slug to any option. Keep the current option visible so the maker can verify which agent is populated in the workspace. If the maker selects it, make no changes and return to the completion choices.

After the maker selects another exact live identity, complete the selected-agent product-line reconciliation. When the selected identity already has a matching local `agents` entry, change only the active local selection by running:

```text
python scripts/setup_existing_da.py select-agent \
  --agent-id "{SELECTED_AGENT_ID}"
```

Parse `DA_ACTIVE_AGENT_JSON:`. Continue setup for that agent when its `connectReady` value is not `true`; otherwise present the completion choices below. This operation changes only local active-agent selection.

When the selected live identity is not locally configured, continue through the established existing-agent route. Use an exact MakerOperations schema when the matching source object supplies one; otherwise run both exact product-line probes before route inspection. A resolved Dev identity uses normal attachment, an unenrolled identity may offer optional enrollment or `--allow-unenrolled-authoring` under the established rules, and a Prod identity uses the established Prod-to-Dev handoff. A native `not-found`, access failure, or uncertain result must stop without offering enrollment. Do not manufacture a local entry before the selected route validates and attaches the exact identity.

The final handoff is the detailed setup report. Branch on the final
`DA_SETUP_FLIGHTCHECK_JSON:` result before presenting another choice.

When `connectReady` is false or absent, setup is not complete. Keep the
runtime-readiness table and every applicable owning remediation, recheck, and
local-cleanup block visible. After those messages, render every applicable
remediation, recheck, and cleanup action in one host interactive
single-selection control, in runtime readiness order. Across those actions,
append **(Recommended)** to exactly one action: the action owned by the first
unresolved row. Leave every other action untagged. After adding every static
and dynamic action, append **Exit setup** as the final secondary choice. Leave
every choice initially unselected and disable custom entry. Selecting **Exit
setup** uses the incomplete **Exit setup** message under **Start**. Do not
render the ready completion choices, durable completion snapshot, or general
post-setup capabilities. The global router's explicit
`/connect`-after-materialization exception remains available only when the
maker requests it; do not advertise it as incomplete setup.

When `connectReady` is true, setup is complete. Resolve the terminal
continuation:

1. When the current request explicitly states `/landing-page` as the supported
   next goal, render the final setup report, say **Setup is complete. You asked
   to configure the landing page next, so I'll continue there.**, and begin
   `/landing-page` at its first decision surface. Do not render the setup
   terminal choice control.
2. When the current request explicitly states `/connect` as the supported next
   goal, recommend **Add or change an integration**.
3. Otherwise, when authoritative product-specific evidence shows that an
   applicable supported integration is configured, render the setup terminal
   choice control without a recommended action.
4. Otherwise, recommend **Add or change an integration**.

Do not treat **Connections: Not required**, an aggregate diagnostic row, or the
presence or absence of native logical connector references as authoritative
evidence that an applicable integration is configured. Those observations
establish only the Foundation requirement or broad diagnostic state. Use only
evidence whose owning integration route defines the checked configuration
surface to suppress the default integration recommendation. The integration
recommendation reflects the absence of completion evidence; it does not claim
that an integration is missing or broken.

Before the choice control, render the applicable maker-facing recommendation
only when **Add or change an integration** is recommended:

- For the default integration recommendation, say: **I recommend Add or change
  an integration so this agent can communicate with your HR or IT systems.
  Setup did not find authoritative evidence that an applicable integration is
  configured.**
- For an explicitly requested `/connect` action, state that it matches what the
  maker asked to do next and explain that integrations let the agent
  communicate with HR or IT systems.

Then present these choices in one host interactive single-selection control:

- **Add or change an integration{CONNECT_RECOMMENDATION_SUFFIX}**
- **Switch to another configured agent** -- when the latest live agent list contains at least one selectable identity other than the active agent.
- **Set up another agent in this environment**
- **Exit setup**

Set `{CONNECT_RECOMMENDATION_SUFFIX}` to ` (Recommended)` only when **Add or
change an integration** is recommended; otherwise set it to an empty string.
Omit **Switch to another configured agent** when it is unavailable. Leave every
choice initially unselected, disable custom entry, and always render **Exit
setup** after every static and dynamic choice. **Add or change an integration**
begins `/connect` at its first decision surface. **Exit setup** acknowledges the
displayed results and renders a durable completion snapshot as the final chat
message without rerunning checks. Reuse the exact agent link, final readiness
rows, statuses, evidence summaries, Overall verdict, and every applicable
local-cleanup block from the final handoff in this invocation. Do not read new
state or infer a value from an earlier turn. After the maker selects **Exit
setup**, show:

**Message:**

The {agent display name} agent is now active.

Here's your ESS agent setup:

- ✅ Choose the starting point and target environment
- ✅ Verify access and agent identity
- ✅ Establish an editable Dev agent
- ✅ Materialize the local workspace
- ✅ Review the setup handoff

> **Open [{USER_FRIENDLY_AGENT_NAME}]({ACTUAL_AGENT_URL}) in Classic Copilot Studio.**

{FINAL_RUNTIME_READINESS_BLOCK}

{APPLICABLE_LOCAL_CLEANUP_BLOCKS}

These are the readiness results you acknowledged when you finished setup. No checks were rerun.

Next steps:

{POST_SETUP_COMMAND_REMINDERS}

**End message.**

Then end the request.

Replace `{FINAL_RUNTIME_READINESS_BLOCK}` with the complete `### Runtime
readiness` block already rendered in the final handoff during this invocation.
Reuse that block verbatim, including the five rows, statuses, evidence summaries,
observation times, and Overall verdict. Do not regenerate the table from
placeholders or read state again.

Replace `{APPLICABLE_LOCAL_CLEANUP_BLOCKS}` with the body of every unresolved
local-cleanup block from the detailed handoff, in the same order.
Omit each block's outer `**Message:**` and `**End message.**` markers so the
durable snapshot remains one complete Message block. Omit the placeholder when
no block applies.

Build `{SUPPORTED_INTEGRATION_SHORTCUTS}` only from authoritative product
identity and the active agent's supported connection routes. Include the
`/connect workday` shortcut only for a supported HR architecture. Include
another shortcut only when its route explicitly supports the resolved product.
Render no shortcut lines when product identity is unresolved or the active
agent does not support them.

Build `{POST_SETUP_COMMAND_REMINDERS}` from the same recommendation and evidence
used for the ready choice control. Render exactly one of these non-interactive
command lists, with the recommended command first:

- For the default integration recommendation:
  - Run `/connect` **(Recommended)** to add or change an integration so this agent can communicate with your HR or IT systems. Setup did not find authoritative evidence that an applicable integration is configured.
    {SUPPORTED_INTEGRATION_SHORTCUTS}
  - Run `/landing-page` to configure the branding and content employees see.
  - Type `/menu` to see all available capabilities.
- For the evidence-based landing-page recommendation:
  - Run `/landing-page` **(Recommended)** to configure the branding and content employees see. An applicable integration is already configured, so this is the next useful customization step.
  - Run `/connect` to add or change an integration.
    {SUPPORTED_INTEGRATION_SHORTCUTS}
  - Type `/menu` to see all available capabilities.
- For an explicitly requested `/connect` action:
  - Run `/connect` **(Recommended)** to add or change an integration. This matches what you asked to do next, and integrations let this agent communicate with your HR or IT systems.
    {SUPPORTED_INTEGRATION_SHORTCUTS}
  - Run `/landing-page` to configure the branding and content employees see.
  - Type `/menu` to see all available capabilities.

Every exit from setup when the active canonical agent has `connect_ready` equal
to `true` must end with the same `{POST_SETUP_COMMAND_REMINDERS}` used in the
durable completion snapshot. These reminders are text, not another choice
control.

Do not render the case labels above. Replace
`{POST_SETUP_COMMAND_REMINDERS}` with only the three bullets for the applicable
case, and replace or omit `{SUPPORTED_INTEGRATION_SHORTCUTS}` under the
`/connect` bullet using the authoritative product rule above.

**Set up another agent in this environment** begins `da-mos-starter.md` at
its first agent-setup decision surface with the recorded environment
and ring. Every other selected follow-up begins at that follow-up's first
decision surface rather than rendering the durable completion snapshot.

## Start

Use context supplied with the current setup request and canonical setup state read in this invocation. Do not infer a route or mismatch from conversation history.

Treat requests to create or set up a fresh agent as explicit fresh-install
intent. Resolve that intent before
active-agent resume handling. Read canonical setup state and `.local/config.json`
only to compare the recorded workspace environment with the requested target.
For the same environment, retain every configured agent and continue directly
through `src/skills/foundation-setup/da-mos-starter.md`. For a different
environment, follow the conflicting-environment flow under **Shared workspace
choices**. This route uses the environment match as its workspace decision;
existing-agent readiness remains unchanged.

When the current request supplies no agent, environment, package, or fresh-agent intent, read canonical setup state and `.local/config.json`. A usable active local target must identify the agent display name, agent ID, environment ID, service ring or validated API endpoint, and local workspace folder. Treat these values only as routing input; they do not prove current access, realm, or readiness.

Whenever the current request resolves a target environment, compare it with the
retained workspace environment before any ALM enrollment, import, attachment,
reset, or other remote or local mutation. If an occupied workspace targets a
different environment, follow **Shared workspace choices** before continuing
the selected-agent route. Preserve the resolved target, account, ring, and
service origins across that choice. Do not run attachment to discover this
conflict; `.local/config.json` already owns the workspace environment. A
read-only identity probe may still validate supplied target data when needed,
but no target-side mutation may precede the workspace choice.

For a usable local target whose canonical agent record has `connect_ready` equal to `true`, do not render the maker-facing progress checklist. Ask:

> Setup is already complete for **{agent display name}**, and this workspace is ready to use. What would you like to do?

Build the recommended post-setup action and render the same ready completion
choices defined above, inserting these choices immediately before **Exit
setup**:

- **Redo setup for this agent**
- **What does setup do?**

Use the same recommendation suffixes and maker-facing recommendation. Leave
every choice initially unselected, disable custom entry, and keep **Exit setup**
as the final choice. Selecting **Exit setup** uses the ready exit message below.

For a usable local target whose canonical agent record is incomplete or blocked, render the maker-facing progress checklist and ask:

> **{agent display name}** is the active agent in this workspace. What would you like to do?

Present these context-appropriate choices in one host interactive
single-selection control:

- **Resume setup for this agent**
- **Switch to another configured agent** -- when the latest live agent list contains at least one selectable identity other than the active agent.
- **Set up another agent in this environment**
- **Reset and use this workspace**
- **Create and open a new workspace**
- **What does setup do?**
- **Exit setup**

Leave every choice initially unselected, disable custom entry, and keep **Exit
setup** as the final choice. Follow the corresponding shared workspace choice
above. For **Create and open a new workspace**, use the location-selection and
worktree handoff defined under **Work with both environments side by side**,
using the recorded environment as the target; this choice does not imply an
environment change.

For **Redo setup for this agent**, begin the existing setup route, render its progress checklist before the first setup operation, complete the one-time account selection and selected-agent product-line reconciliation above, then run the inspection command below. Do not create a separate redo workflow or state model.

For **Resume setup for this agent**, continue the same existing setup route by completing the one-time account selection and selected-agent product-line reconciliation above, then run:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{RECORDED_ENVIRONMENT_ID}" \
  --agent-id "{RECORDED_AGENT_ID}" \
  --ring "{RECORDED_RING}"
```

Also pass the recorded validated `--host` and `--api-version` when available. Parse `DA_AGENT_ROUTE_JSON:` and follow the same realm routing used for a supplied URL. Do not ask for the agent or environment URL.

For **Exit setup** when canonical `connect_ready` is `true`, make no changes and do not rerun checks. Show:

**Message:**

Setup remains complete for **{agent display name}**. No checks were rerun.

Next steps:

{POST_SETUP_COMMAND_REMINDERS}

**End message.**

Then end the request.

For **Exit setup** when canonical setup is incomplete or blocked, make no changes and show:

**Message:**

Setup has not been completed for **{agent display name}**.

Run `/setup` when you are ready to resume.

**End message.**

Then end the request. Do not advertise post-setup capabilities while canonical `connect_ready` is not `true`.

Do not describe a supplied agent as editable, Dev, Test, or Prod until a
server-backed inspection has identified its route realm.

When canonical setup already identifies a local Dev agent, do not announce an
agent mismatch, workspace switch, or refresh merely because the supplied URL
contains another agent ID. A Prod source and its related Dev agent have
different IDs by design. Classify the supplied agent first, then use the
server-reported ALM relationship to determine whether the existing workspace
already targets its related Dev agent.

When the maker supplies a Microsoft Copilot Studio URL that identifies an agent and has
not explicitly selected package import, infer its environment ID, agent ID,
service ring, and optional `agentBackend` ordering hint. When the URL does not
identify the ring, use **Resolve the service ring** in
`src/skills/foundation-setup/da-environment-target.md` exactly. Ask only when
the environment ID or agent ID is unclear. If this invocation has not already
received the environment's service-provided display name, run `list-environments`
for the resolved ring and retain the exact matching environment record's `name`
as `{ENVIRONMENT_DISPLAY_NAME}`. A failed or missing exact match does not
invalidate the URL target; leave the display name unavailable rather than
inferring it. Complete the selected-agent
product-line reconciliation before running:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_ROUTE_JSON:`. The command reads the exact direct
`MinimalBotCard` identity and normalizes its Swagger-defined nullable `realm`
into explicit `alm.isEnrolled`. It does not call the ALM `/realms` endpoint.
Do not infer the realm from names, URLs, or environment metadata.

- When `routeStatus` is `not-established` and `alm.isEnrolled` is `false`, the
  direct native metadata still proves that the agent exists. Say that setup
  could not establish an ALM authoring route for that agent, then read
  `src/skills/foundation-setup/alm-enrollment.md` and follow its
  exact choice surface and bounded operation sequence. Do not call the agent
  missing and do not continue directly from this file. The shared path may
  return to local attachment without an ALM route only after the maker selects
  **Skip enrollment** and exact supported native product identity is already
  established.
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

Present these standard choices:

- **Create a fresh agent in this environment**
- **Connect to an existing agent in this environment**
- **What does setup do?**
- **Help me decide**
- **Cancel setup**

Continue when the maker selects a standard choice or supplies a clear setup intent in chat; all standard choices begin unselected.
Resolve the environment label from known context. This question confirms the selected target; the access-verification stage remains current until a service operation succeeds.

- For **Create a fresh agent in this environment**, continue directly through `src/skills/foundation-setup/da-mos-starter.md` with the retained environment and ring.
- For **Connect to an existing agent in this environment**, read `src/skills/foundation-setup/da-existing-dev.md` and follow its environment-candidate selection path with the retained environment and ring.
- For **What does setup do?**, follow the shared orientation contract above and return to this choice surface.
- For **Help me decide**, follow the shared contract under **Standard choices and ad hoc recovery**. Establish whether an agent already exists in this environment whose current content should become the workspace's authoring source, or whether the maker wants a separate agent created from an available agent template. Include the creator-login requirement for an existing agent and the creation-permission requirement for a fresh agent in the comparison.
- For **Cancel setup**, make no changes and stop.

When the request does not identify an agent or environment, no usable local
target exists, and no incomplete canonical setup record must resume, render
the **What does setup do?** orientation above, then ask:

> Do you already have an ESS agent in Copilot Studio?

Present these standard choices:

- **Yes, I have an agent** — ask for its Microsoft Copilot Studio URL.
- **No, I need a fresh agent** — follow `src/skills/foundation-setup/da-mos-starter.md`.
- **Help me decide**

For **Help me decide**, follow the shared contract under **Standard choices and ad hoc recovery**. Establish whether anyone has already created an ESS agent whose content must be preserved, whether the maker has its Microsoft Copilot Studio URL and creator login, or whether the intended outcome is a new agent from an available agent template.

Do not run Dataverse foundation or onboarding playbooks. Begin a downstream
playbook only when a maker whose setup is complete selects its documented ready
completion action. **Exit setup** ends the current request; another selected
ready completion action begins its own prompt flow.
