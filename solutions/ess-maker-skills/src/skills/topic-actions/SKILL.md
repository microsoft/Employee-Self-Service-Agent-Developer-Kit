# Topic actions

Manage the intent to enable or disable whole ESS topic sets on one verified
agent. The proposed-catalog discovery, computed planner, in-memory review
controller and single-attempt executor are integrated. **Native writes are
not released:** package authority, effective permission, centrally controlled
admission and native concurrency/draft/published behavior remain unverified.
Never describe a preview as a completed enable/disable.

## Interaction and output

Use the established selected target, action and exact set keys. Ask a
clarifying question only when missing or ambiguous information prevents the
requested operation; do not ask the maker to repeat known selections or
confirm that routine checks should run.

For listing or preview requests, perform the read-only work and show the
result without approval or an unsolicited offer to execute. For an explicit
enable/disable request, use the execution helper's fresh review directly;
do not add a separate preview approval, a "start review" confirmation or a
"ready to proceed" question before it. A previous preview is not executable
approval and does not replace that fresh execution review.

Display the complete required review once, including every selected member,
account, target, changes, already-correct topics, protections and warnings.
Group repeated warnings without omitting distinct risks. Then present one
explicit decision control: **Approve**, **Deny** or **Cancel**, with no
preselected approval. Send the actual decision to the same waiting process;
map explicit denial to `deny` and cancellation to `cancel`. Ambiguous text
is never approval. Do not introduce a second confirmation after approval;
continue with the mandatory fresh checks and readback. Changed evidence or
expired approval still requires a new review and explicit approval.

Keep routine authentication, prerequisite checks and execution bookkeeping
out of the conversation. Use the existing entry/helper instead of inventing
ad hoc shell orchestration for normal operations. Do not paste PowerShell,
Python, shell commands, request JSON, helper source, raw stdout or polling
transcripts into the review or final answer. Give terminal instructions only
when the supported interactive-terminal fallback is necessary or the maker
explicitly requests commands. If diagnostics are requested, provide only
safe supported details; never expose tokens, private context or raw service
bodies.

After the result, give one concise outcome with the selected sets, verified
counts, whether a write was attempted, and any material blocker or
preservation limitation. Distinguish observed state success from incomplete
preservation. Do not repeat the review, narrate routine steps, open another
decision control or append an unsolicited follow-up menu.

These rules govern generated conversation content, not host-rendered tool
panels or permission controls. Do not promise to hide those panels, change
host permission settings or bypass required approvals.

## Entry and prerequisites

This route owns its setup gate. Read `.local/config.json` and
`.local/setup/config.json`; resolve `activeAgent` to exactly one canonical
`agent.workspace_slug`. Require schema version 4, consistent tenant,
environment and agent IDs, DA release line, a recorded workspace folder and
agent path, and `steps.SETUP-07.state: "done"`.

Do not require `connect_ready: true`, a healthy Workday/ServiceNow connection
or employee-data calls. Use `src/reference/ui-formatting-guidelines.md` for
maker-facing guidance. Preserve the requested action, sets and established
target, and distinguish these entry outcomes:

- **Setup not established:** explain that ADK has not established the account,
  agent and environment. Direct the maker to run `/setup` in this workspace,
  then return to this conversation with a new topic-change request.
- **Setup incomplete:** name the unfinished step only when known. Workspace
  preparation is required; connection health is not. Direct the maker to
  `/setup` for the same agent, retaining confirmed completed steps, then ask
  them to return here with a new request.
- **Setup broken or target unverified:** identify only the information that
  cannot be validated. Do not assume `/setup` repairs it or recommend deleting
  setup state, switching targets or creating a replacement. State when the
  supported recovery route or installed-version support is unconfirmed.
- **Selected package or topics missing:** distinguish verified absence of a
  package from missing topics within an installed package. Name the affected
  set and topics when known. Use an existing setup/recovery destination only
  when verified for that problem and installed version; otherwise state that
  the destination is unconfirmed. `/setup` does not install extension packs;
  `/connect` completion is not package or topic evidence.
- **Evidence unavailable or ambiguous:** do not diagnose absence or access
  denial. Unverified installation does not mean a missing package; unresolved
  topic identities can be missing or ambiguous. For unresolved membership,
  ask the ADK administrator to investigate, then return here for a fresh check.
- **Access denied:** describe the denied operation only. A denied read does
  not verify missing topic-edit permission. Only a verified edit denial may
  direct the maker to the administrator responsible for that agent and
  environment to grant topic-edit access. Do not invent a permission-request
  command or infer denial from an unavailable permission check.

For each pre-write blocker show "No topics were changed." Never automatically
start setup, install packages, repair a connection, switch targets or resume
topic changes after recovery. A new request performs fresh checks, review and
applicable explicit approval. The helper rechecks identity and direct native
Dev access; reads do not prove write permission.

Direct entry and a calling skill use the same planner/controller. Preserve
confirmed completed caller/setup progress and return its context in memory
without completing unresolved caller steps. Returning a JSON object is not
proof that setup has consumed it. Use an existing caller continuation only
when its contract and installed-version support have been verified; otherwise
explain that automatic return is unavailable and keep the result in this
conversation. Do not promise persistent resume, invent a destination, mark
the topic step complete or start the caller's next mutation.

Before writes, **Cancel** or **Not now** ends the request. Show "Canceled.
No topics were changed." Direct entry remains in this conversation. Caller
entry preserves completed steps and leaves the topic step incomplete unless
the requested state was independently verified, using only the supported
caller return. Closing the control or an ambiguous custom answer is not
approval. No automatic retry or resume follows cancellation.

## Selection and proposed catalog

Read `src/reference/topic-actions/catalog.provisional.json` or run
`python scripts/topic_actions.py --list-sets` to list **source definitions**.
This is not installed availability. The catalog deliberately retains unknown
required-topic classifications, package IDs and coverage, and provisional
approval. Do not change those labels to make a plan pass.

Explain the available names, establish exactly one action (`enable` or
`disable`) and explicit whole-set keys, and use the canonical selected target.
Never infer membership from names, merge source families, expand "all" without
selection, silently narrow a partial set or authorize a topic individually.
Discovery matches exact schema keys to installed component IDs and reports
missing/ambiguous members. Legacy flat definitions remain read-only.

## Run and explain the preview

Pass one JSON request on standard input to:

`python scripts/topic_actions.py --preview`

The request contains `contractVersion: 1`,
`target: {tenantId, environmentId, agentId}`, `action`,
`setKeys` (distinct exact keys), and `entry: "direct"`. Do not save an input
file. For terminal execution omit private caller context; retain it with the
calling conversation. An in-process caller can use
`run_topic_actions(..., confirm=...)` with `entry: "caller"` and a nonempty
`callerContext` JSON object. Never put context, tokens or component bodies in
terminal commands, chat output or files.

Parse `TOPIC_ACTIONS_RESULT_JSON:`. Present the target, selected sets,
observed differences, proposed changes, already-correct topics, protections
and blockers in plain language. Observed differences in a blocked plan are
**not eligible changes**. Report all requested sets; missing membership never
becomes a smaller successful action. No user approval can override blockers.
The CLI is a nonmutating preview; it does not collect executable consent.

## Planning and approval rules

The planner deduplicates selected membership. Required topics cannot be valid
members and remain defensively protected. Selected sets do not protect each
other. For disable, a fully enabled outside set protects shared topics; a
partly enabled outside set protects them only when it has an On member outside
the selected union. Unknown relevant membership, state or protection blocks
the action. Customer dependency coverage must be verified, not assumed.

The controller requires explicit approval for both actions against the exact
target, account, action, selection, memberships, revision, states, protections
and delta. Approval lasts at most five minutes and is rechecked immediately
before dispatch. Denial/cancellation changes nothing. Any drift requires a
fresh review. A nonempty eligible scope already in the desired state is
different from empty scope or an all-protected action.

## Execution and truthful return

The executor can submit at most one full-component, state-only changeset.
Its isolated transport disables retries and redirects without changing
Workday defaults. Dispatch and readback are serialized per target within the
process; that does not protect against another process or maker, which still
requires verified server-side stale-write protection. The native adapter independently denies submission while
release admission is unavailable. No request parameter, local flag, digest
or OAuth scope supplies that authority.

After any submission, including timeout/conflict/error, the controller reads
back and reports each observed result. Desired state after an uncertain
submission is not attributed to this request. Verify non-state content and
outside-scope preservation; otherwise report partial/unverified. Never replay,
automatically roll back, publish, repair or continue a detached write.
Any later attempt needs new evidence and approval.

Preservation comparison tolerates `version` and `auditInfo.modifiedTimeUtc`
updates only on topics in the approved delta, and generated `diagnostics` and
`structuredCondition` within dialogue definitions, including dependent topics.
Other content, identity, membership and outside-scope state/revision changes
remain strict. This normalization applies only to post-submission readback;
review freshness and state-only payload checks remain unchanged. A genuine
preservation failure must be distinguished from observed state success.
Enabled state does not establish runtime health or resolved diagnostics.

For an unsuccessful submission, report the safe failure category and
`submissionHttpStatus` when available. Do not expose exception messages or
service response bodies. A rejected request is not successful completion;
readback observations do not authorize a retry.

Distinguish blocked, denied, cancelled, review-required, already-correct,
completed, completed-with-protections, partial and unverified outcomes.
Protected topics are never reported as disabled. Partial, protected or
uncertain scope must not complete the caller's whole-set request.

No new FlightCheck profile, telemetry collector, saved inventory, approval
file, operation journal or diagnostic upload is introduced. Existing auth
caches and platform logs are unchanged. Telemetry additions are explicitly
deferred pending review of the approved data constraints.
