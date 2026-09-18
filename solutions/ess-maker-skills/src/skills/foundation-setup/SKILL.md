<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# ESS Foundation Setup

Every **Message** block is exact user-facing text. Do not expose internal step IDs,
checkpoint IDs, state paths, or tool narration.

Follow `src/reference/ui-formatting-guidelines.md` for every user-facing
instruction in this flow. Resolve its examples with the actual environment,
agent, product, and connector names before displaying them.

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

At setup start and at the beginning of every subsequent setup turn, write the host's native task list as a complete snapshot of the five stages below. Every task-list update contains all five stages in this order. Use the latest canonical setup state read in this invocation and results observed in this invocation to set their statuses. After each setup action that changes progress, write the complete snapshot again. Preserve completed stages, keep pending stages present, and represent subordinate checks through the status of their owning stage. Before every maker-facing response, including the final handoff, synchronize the complete snapshot once more and mark **Review the setup handoff** complete before finishing. Use the inline fallback only when a native task list is unavailable. Do not expose the eight internal setup-step IDs or show skipped internal records as successful checks.

**Inline fallback message:**

Here's your ESS agent setup:

- {marker} Choose the starting point and target environment
- {marker} Verify access and agent identity
- {marker} Establish an editable Dev agent
- {marker} Materialize the local workspace
- {marker} Review the setup handoff

**End message.**

Use ✅ for completed, 🔄 for the current stage, ⛔ for a blocked stage, and ⬜ for pending. Derive markers only from supplied context, results observed in this invocation, and canonical setup state read in this invocation. Never infer progress from conversation history.

The checklist is a view, not another state model:

- a supplied or selected target completes the first stage;
- direct service validation of an exact editable Dev completes the second and third stages for the existing-agent path;
- a successful package import with direct Dev validation completes the second and third stages for the supplied-package path;
- service inspection of a Prod source completes access and source-identity verification; a directly validated related Dev or successful create-only import completes the editable-Dev stage;
- a successful MOS create followed by direct Dev attachment validation completes access, identity, and editable-Dev establishment for the fresh-agent path;
- only `connectionStatus: workspace-ready` with `connectReady: true` completes local workspace materialization;
- reviewing the factual completion report completes the handoff stage in the conversation and does not write another readiness marker.

Before canonical setup begins, set the first unresolved native task-list stage to in progress and leave later stages pending. When canonical state is blocked, mark only the corresponding visible stage as blocked and preserve its failure causes in the response. Do not mark a stage complete from a skipped internal setup record.

## Choose the sign-in account

After resolving the Python invocation and before the first command that can authenticate, inspect only this workspace's existing AgentBuilder cache:

```text
python scripts/setup_existing_da.py cached-accounts
```

Parse `DA_AGENTBUILDER_ACCOUNTS_JSON:`. This is a local read and does not authenticate.

- For one cached sign-in name, ask **Use {account} for setup?** and offer exactly **Continue with this account** and **Use another account**. Do not preselect either choice.
- For multiple cached sign-in names, ask **Which account should setup use?** and offer each returned sign-in name plus **Use another account**. Do not preselect an account.
- For no cached sign-in names, or after **Use another account**, ask **Do you have a test tenant user?** Allow the maker to enter that account's sign-in name or skip. When multiple cached accounts exist, require a sign-in name after **Use another account** so subsequent setup commands do not reopen account selection.

Retain a confirmed or supplied sign-in name as `{SETUP_ACCOUNT}` and append `--account "{SETUP_ACCOUNT}"` to every `setup_existing_da.py`, `setup_mos_starter.py`, `setup_alm_export.py`, and `setup_alm_import.py` command in this invocation. Never infer a corp account. When the maker skips with no cached accounts, omit `--account` and let Microsoft sign-in present its account picker.

Present account confirmation once per setup invocation. Do not repeat it before later commands.

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

When child guidance shows `python`, substitute the resolved invocation.

## Start

Use context supplied with the current setup request and canonical setup state
read in this invocation. Do not infer a route or mismatch from conversation
history.

When the current request supplies no agent, environment, package, or fresh-agent intent, check for an exact local target before asking for a URL. Prefer canonical setup state; use `.local/config.json` only as a compatibility fallback when canonical state is absent or uses the known older completed format. A usable local target must identify the agent display name, agent ID, environment ID, service ring or validated API endpoint, and local workspace folder. Treat these values only as routing input; they do not prove current access, realm, or readiness.

For a usable local target, ask:

> **{agent display name}** is already connected to this workspace. What would you like to do?

Offer exactly:

- **Continue with this agent**
- **Set up a different agent in a new workspace**
- **Cancel setup**

Do not preselect a choice.

For **Continue with this agent**, complete the one-time account selection above, then inspect the recorded target directly:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{RECORDED_ENVIRONMENT_ID}" \
  --agent-id "{RECORDED_AGENT_ID}" \
  --ring "{RECORDED_RING}"
```

Also pass the recorded validated `--host` and `--api-version` when available. Parse `DA_AGENT_ROUTE_JSON:` and follow the same realm routing used for a supplied URL. Do not ask for the agent or environment URL. When canonical state is incomplete or blocked, label the first choice **Resume setup for this agent** instead, with otherwise identical behavior.

For **Set up a different agent in a new workspace**, follow only [Use a separate workspace when the current folder is occupied](da-mos-starter.md#use-a-separate-workspace-when-the-current-folder-is-occupied). Stop after the workspace handoff; the new workspace owns selection of an existing or fresh agent.

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
not explicitly selected package import, run:

```text
python scripts/setup_existing_da.py inspect-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
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

When the maker explicitly asks for a fresh installation, read
`src/skills/foundation-setup/da-mos-starter.md` and follow it, even when the
current Developer Kit folder already has setup state. That skill owns the
separate-worktree offer for an occupied folder. Without explicit fresh-agent
intent, keep the existing-Dev path for a maker who already has an agent.

When the request identifies an environment but not an agent or fresh-agent intent, read `src/skills/foundation-setup/da-existing-dev.md` and follow its environment-candidate selection path.

When the request does not identify an agent or environment and no usable local target exists, ask:

> Do you already have an ESS agent in Copilot Studio?

Offer exactly:

- **Yes, I have an agent** — ask for its Copilot Studio URL.
- **No, I need a fresh agent** — follow `src/skills/foundation-setup/da-mos-starter.md`.

Do not run Dataverse foundation or onboarding playbooks. Never route from `/setup` into an integration or topic playbook.
