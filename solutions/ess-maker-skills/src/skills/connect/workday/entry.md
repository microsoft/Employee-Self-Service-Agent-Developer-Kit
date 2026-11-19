# Enter Workday Connect

This is the DA Workday-specific entry point selected through `integration.json`.
Generic integration selection belongs in `src/skills/connect/SKILL.md`.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not narrate tools, files, or internal routing.

## Preserve the Workday journey

Treat an explicit promotion statement such as **I promoted the agent to
Test**, **the Workday agent moved to Production**, or **configure the promoted
Workday realm** as Workday already selected. Preserve the stated target realm
when entering the native DA Workday lifecycle. Do not ask which integration
the user means, and do not invent a realm-specific slash command.

A request such as **Promote the Workday agent to Test** preserves the Workday
selection, but is not a claim that promotion finished. Route it to the native
DA lifecycle's promotion guidance and confirmation, not directly to
promoted-target discovery. If `/setup` was required first, carry the original
Workday selection and target intent through setup completion; do not ask which
integration again.

## Verify the active agent

Check whether `.local/config.json` exists before reading it. If it exists,
resolve `activeAgent` against `agents`, and fall back to the legacy `agent`
object only when needed. For a DA agent, also check whether canonical
`.local/setup/config.json` exists before reading it. A missing `.local`
directory, missing configuration file, or `Path does not exist` read result
is expected unprepared state. Do not retry the missing read, reconstruct
deleted metadata, or show the global setup-required welcome message.
Follow **Prepare missing prerequisites at entry** below, after applying any
already-known unsupported-product boundary. Unknown targets use Setup's normal
selection and authorization controls; remaining workspace files do not prove
setup completion. Do not treat access-denied or malformed-file errors as absence;
preserve their diagnostic and use supported state recovery.

For readable configuration, require top-level `schema_version: 4`
and its `agents` record keyed by the active `botId`, checking that
`agent.workspace_slug` matches `activeAgent`. Require canonical workspace evidence and
`steps.SETUP-07.state: "done"`; do not require `connect_ready: true`, because
Workday connection configuration may be the remaining readiness blocker.

If there is no concrete active agent, its architecture cannot yet be resolved,
or required setup preparation is missing, follow **Prepare missing prerequisites
at entry** below. When a concrete unsupported product is already known, apply
the product boundaries below before invoking Setup; preparation cannot make
an unsupported Workday target supported.

Treat these current MOS schemas and legacy DA aliases as Declarative Agents:

- `gptagent_copilotforemployeeselfservicehr`
- `gptagent_copilotforemployeeselfserviceit`
- `msdyn_copilotforemployeeselfservicedahr`
- `msdyn_copilotforemployeeselfservicedait`

Also treat another active agent with `releaseLine: "da"` as Declarative.
Never infer architecture from retired product inventory or the first installed
agent.

For the ESS DA IT Agent, show:

**Message:**

Workday integration with the ESS IT Agent isn't supported in this release.
Please contact your administrator.

**End message.**

Stop immediately without creating Workday state or running a package check.

For another unsupported DA target, show:

**Message:**

Workday integration is available for the ESS HR Agent in this release.
Please select the ESS HR Agent or contact your administrator.

**End message.**

Stop immediately without creating Workday state or entering a lifecycle.

For `gptagent_copilotforemployeeselfservicehr`, first satisfy the entry
prerequisites above. If they are already satisfied, skip Setup entirely even
when `connect_ready` is false. Then read
`src/skills/connect/workday/SKILL.md` and follow it. That lifecycle uses
`WD-DA-PKG-001`. Do not create CEA Workday lifecycle state or run
`WD-PKG-001`: DA packages share some Workday connection-reference names with
CEA, so the CEA package fingerprint is not an architecture discriminator.
Preserve explicit Test or Production intent so the lifecycle can run
promoted-target discovery instead of restarting DEV.

For the classic DA HR schema `msdyn_copilotforemployeeselfservicedahr`, explain
that the simplified Workday lifecycle currently supports only the native ESS
HR agent. Stop without creating or changing Workday state.

For a CEA agent, show:

**Message:**

This branch supports DA agents only. CEA Workday Connect is available on the
`main-ca` branch. Use that branch's CEA guidance for this agent.

**End message.**

Stop without running package checks, reading CEA lifecycle state, creating
Workday state, or changing branches automatically.

## Prepare missing prerequisites at entry

This automatic handoff is only for the start of a Connect request, before
entering the six-phase Workday lifecycle. Setup and Connect are independent
skills; Connect depends on Setup's verified workspace preparation. Do not
invoke Setup between Workday phases or after Workday completion.

When setup is missing, no usable agent is selected, or canonical workspace
materialization is incomplete, show:

**Message:**

I'll prepare your agent workspace first, then continue connecting Workday.

**End message.**

Immediately read `src/skills/foundation-setup/SKILL.md` and follow **Prepare
the workspace for an integration** in the same invocation. Preserve Workday
as the selected integration, the original request, supplied agent/environment
and realm intent, and any already verified maker. Do not ask the maker to
type `/setup`, ask for confirmation just to enter Setup, or ask them to repeat
Connect afterward. Unknown targets and sign-ins still use Setup's normal
selection and authorization controls; do not silently choose or create an
agent.

Do not create Workday state, run package installation, or enter a Workday
phase before preparation succeeds. If setup is blocked, cancelled, or exited,
preserve the original request and show its actual blocker or disposition;
do not continue Connect or repeatedly invoke Setup.

When Setup returns a materialized workspace, reread both local configuration
files and reapply this entry's exact agent, environment, schema-version,
workspace, and supported-product guards before reading `workday/SKILL.md`.
Do not treat the handoff alone as proof, require `connect_ready: true`, or
manually mark setup records done. Continue directly into the original
Workday request without showing the integration menu again. After a
successful handoff, a failed prerequisite recheck reports the specific error
instead of entering an automatic Setup loop.

Malformed or inconsistent canonical state requires Setup's supported
state/target recovery. Preserve the diagnostic and local edits; do not
overwrite state, switch workspace agents, or guess a target.

## Workday ownership

All Workday phase guides, guarded actions, administrator workbooks, and the
state contract live in this provider directory. DA Workday state remains at
`.local/connect/workday-da/config.json`; reorganizing guidance does not migrate
or reset it. Foundation agent installation remains in
`src/skills/foundation-setup/`.
