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

Show one setup checklist when `/setup` starts and when the maker explicitly resumes it. Do not expose the eight internal setup-step IDs or show skipped internal records as successful checks.

**Message:**

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
- only `connectionStatus: workspace-ready` with `connectReady: true` completes local workspace materialization;
- reviewing the factual completion report completes the handoff stage in the conversation and does not write another readiness marker.

Before canonical setup begins, show the first unresolved stage as current and leave later stages pending. When canonical state is blocked, mark only the corresponding visible stage as blocked and preserve its failure causes in the response. Do not mark a stage complete from a skipped internal setup record.

## Shared authorization message

Before a command that can open Microsoft sign-in, show:

> Microsoft sign-in will open. Select the account you use to access this environment. If the expected account is not shown, choose **Use another account**.

If the terminal returns control while that command is waiting for the browser callback, show:

> **Waiting for authorization**
>
> Complete the Microsoft sign-in in your browser. I will continue automatically after authorization finishes.

Do not describe an authorization wait as service processing, start a second command, or ask the maker to provide a token.

---

## Command runtime

The first terminal operation must change to the kit root, which is the directory
containing `scripts/`. Do not rely on the terminal's inherited working
directory. Run every setup command from that location; when shell state may not
persist between commands, prefix the command with an explicit change to
`{KIT_ROOT}`.

Before the first Python command, resolve one working launcher and reuse it for
the rest of setup:

- on Windows, prefer `py -3`; if it is unavailable, use a working `python3` or
  `python`;
- on macOS or Linux, prefer `python3`; if it is unavailable, use a working
  `python`.

Verify the selected launcher with
`{PYTHON} -c "import sys; print(sys.executable)"`. Do not use a setup command as
the launcher probe. A missing or nonworking candidate is not a setup failure;
continue to the next candidate. If no launcher works, report the missing Python
prerequisite and stop. When child guidance shows `python`, substitute the
resolved launcher.

## Start

Use context supplied with the current setup request and canonical setup state
read in this invocation. Do not infer a route or mismatch from conversation
history.

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

When the request identifies an environment but not an agent, read `src/skills/foundation-setup/da-existing-dev.md` and follow its environment-candidate selection path.

When the maker has no existing agent and wants a fresh installation, read
`src/skills/foundation-setup/da-mos-starter.md` and follow it. That skill
lists entitled MOS starter packages and creates a new Dev agent from the
maker's exact confirmed choice; it never replaces the default existing-Dev
path for a maker who already has an agent.

When the request does not identify an agent or environment, ask:

> Do you already have an ESS agent in Copilot Studio?

Offer exactly:

- **Yes, I have an agent** — ask for its Copilot Studio URL.
- **No, I need a fresh agent** — follow `src/skills/foundation-setup/da-mos-starter.md`.

Do not run Dataverse foundation or onboarding playbooks. Never route from `/setup` into an integration or topic playbook.
