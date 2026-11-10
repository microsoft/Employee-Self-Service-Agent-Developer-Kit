# Topic actions

Enable or disable whole source-defined ESS topic sets, or restore the original
states of topics changed by this skill, on one verified selected native
agent using the computed planner, in-memory approval, single-attempt executor
and readback. **The source-inventory policy intentionally removes central
release admission and prequalification gates.** Matching topics are not proof
of installed-package identity, complete membership, required-topic
classification or custom-dependency coverage. Those unknowns remain warnings;
they are not changed to verified evidence. Effective edit permission is
enforced by the write API, not inferred from authentication or read access.
Native stale-token, batch and draft/published behavior is unqualified.
Dev, Test, Prod and unenrolled native agents are not excluded by realm.
Service authorization or unsupported native API access can still block an
operation. Removing the realm gate does not qualify those targets or make
changes safe for published conversations.
This is not a qualified customer release. Never describe a preview as a
completed enable/disable or promise draft/published isolation.

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

For each remaining pre-write blocker show "No topics were changed." Never
automatically start setup, install packages, repair a connection, switch
targets or resume topic changes after recovery. A new request performs fresh
checks, review and applicable explicit approval. The helper rechecks identity
and direct native access; reads do not prove write permission.

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

Explain the available names, establish exactly one action (`enable`, `disable`
or `restore`) and use the canonical selected target. Enable/disable requires
explicit whole-set keys. Restore derives the recorded sets from the original
state store; do not ask the maker to repeat them or choose a partial restore.
Never infer membership from names, merge source families, expand "all" without
selection, silently narrow a partial set or authorize a topic individually.
Discovery matches exact schema keys to installed component IDs and reports
missing/ambiguous members. Legacy flat definitions remain read-only.

## Read-only preview or same-session execution

Pass one JSON request on standard input to:

`python scripts/topic_actions.py --preview`

The request contains `contractVersion: 1`,
`target: {tenantId, environmentId, agentId}`, `action`,
`setKeys` (distinct exact keys for enable/disable), and `entry: "direct"`.
For restore, omit `setKeys` or supply an empty array; nonempty selections and
`initializeBaseline: true` are rejected for restore. Do not save an input
file. For terminal execution omit private caller context; retain it with the
calling conversation. An in-process caller can use
`run_topic_actions(..., confirm=..., preview=True)` with `entry: "caller"` and
a nonempty `callerContext` JSON object. Never put context, tokens or component
bodies in terminal commands, chat output or files.

Parse `TOPIC_ACTIONS_RESULT_JSON:`. Present the target, selected sets,
observed differences, proposed changes, already-correct topics, protections
and blockers in plain language, including the unverified-assumption warnings.
Observed differences in a blocked plan are **not eligible changes**. Report
all requested sets; missing membership never
becomes a smaller successful action. No user approval can override blockers.
Preview returns `status: "preview"` and `writeStatus: "not_attempted"`. It
does not acquire write scopes or collect executable consent.

For the normal write flow, run `python scripts/topic_actions.py --execute`.
Keep standard input open: send one JSON request line, wait for
`TOPIC_ACTIONS_REVIEW_JSON:`, and display the complete returned review,
including account, target, every selected set/member, proposed changes,
already-correct topics, protections and warnings. Only then obtain the
maker's explicit answer and send `approve`, `deny` or `cancel` as the next
line to **that same process**. Never prefill approval. EOF cancels; ambiguous
answers do not approve. Do not save an approval or replay it in another
process. If the host cannot maintain this interaction, run the command in
an interactive terminal rather than imply approval was collected in chat.

An in-process host uses `run_topic_actions(..., confirm=...)` without
`preview=True`; its callback owns displaying the review and collecting the
maker's explicit answer. Both entry types use this same controller.
Authentication uses neutral ADK authentication utilities and the existing
AgentBuilder cache (`.local/.agentbuilder_token_cache.bin`), not Connect
Workday's authentication or token-cache implementation. Execution requests
the explicit native component read/write scope; preview requests only the
component read scope. A previously cached Workday `.default` token does not
guarantee these scopes are available without sign-in or consent.
Both recheck the exact tenant/account.
No publish operation is requested. Running the CLI
without a mode remains a read-only prerequisite inspection.

## Planning and approval rules

The planner deduplicates selected membership. Known required topics cannot be
valid members and remain defensively protected. Unknown required status does
not block this policy and must remain visible as an unverified-protection
warning. Selected sets do not protect each other. For disable, a fully enabled
outside set protects shared topics; a
partly enabled outside set protects them only when it has an On member outside
the selected union. This protection uses only the source-defined map; its
completeness and custom dependencies remain unverified. Missing or ambiguous
exact members, unknown states, unsupported source variants and a missing
change token still block; no requested set is silently narrowed.

The controller requires explicit approval for all three actions against the exact
target, account, action, selection, memberships, revision, states, protections
and delta. Approval lasts at most five minutes and is rechecked immediately
before dispatch. Denial/cancellation changes nothing. Any drift requires a
fresh review. A nonempty eligible scope already in the desired state is
different from empty scope or an all-protected action.

## Original state and explicit restore

The original baseline is fixed: the topic states before this skill's first
write, not the states before its most recent operation. It is local to this
workspace and exact tenant/environment/agent and survives new conversations
and process restarts. Never overwrite, delete or reinitialize it to make an
operation pass. Another workspace or a lost local store cannot establish
this agent's original state.

Before a new agent's first write, `initializeBaseline: true` permits a
first-use review. This flag is not approval. Display the returned `baseline`
section in the same complete review: approval explicitly confirms these
states precede any topic-actions changes and authorizes saving them before
dispatch. Do not add a separate baseline confirmation. Never supply the flag
when earlier changes are known, or use it to bypass `original_baseline_missing`.
When first use is materially uncertain, clarify it rather than assuming it.
Later requests omit the flag and reuse the saved original. Preview,
denial/cancellation and already-correct enable/disable do not create a baseline.

The helper transactionally persists every topic's component ID, schema name,
original On/Off state and non-state-content digest under the ignored
`.local/topic-actions` directory before the first submission. It saves no
dialogue bodies, authentication tokens, approval or caller context. A storage
failure blocks dispatch. Minimal durable intent bookkeeping prevents another
caller using this store from starting an overlapping write. An operation
interrupted before its outcome is recorded remains blocked; do not clear its
intent or promise automatic recovery.

For `/topic-actions Restore the original topic states`, use `action: "restore"`
through the same preview/execute helper, selected-target checks, five-minute
approval and one-submission flow. Display `restoreStates`, the baseline date,
all recorded members, already-correct topics, protections and warnings.
Treat an explicit request to revert the skill's changes or return to the
initial topic states as restore, not as disabling every set.
The computed delta may contain both On and Off changes. Restore only topics
this skill changed, using current component definitions; do not restore old
dialogue content, connections, membership or published versions.

Missing/recreated identities, changed recorded membership, unknown states or
intervening state/content edits on affected topics block restore. Preserve
unrelated edits and report when unrelated topic states differ from the
original; do not claim the entire agent is identical to its original state.
Required/shared protections still apply. A protected or partially verified
restore is not complete restoration.

An uncertain recorded submission cannot be replayed as a normal action.
A new explicit restore can review affected topics whose current state matches
the recorded before or intended after state and whose content is unchanged.
This does not attribute the previous outcome or reuse its approval.
One approved restore submission is not a qualified atomic server rollback.
Never restore automatically after a failed enable/disable.

For agents already changed before baseline capture was implemented, current
states are not the original. Report `original_baseline_missing`; historical
baseline reconstruction/import is not automated. Do not invent a reset/import
command, manually fabricate a store or silently label today's state original.

## Execution and truthful return

The executor can submit at most one full-component, state-only changeset.
Component reads and writes use the skill-owned `TopicActionsClient` in
`scripts/topic_actions_client.py`. It sends the exact state-only changeset
computed from the freshly revalidated inventory, without a second payload
builder, content merging or automatic conflict handling. Retries and redirects
are disabled. Preservation normalization is owned by topic actions as well.
There is no runtime import of Connect Workday or `minimalbot_evaluation`.
Neutral ADK authentication, host validation and HTTP error utilities remain
shared dependencies; this skill is not a standalone copy of the whole ADK.
`AgentBuilderClient` is used for direct selected-agent identity verification,
without requiring a particular realm or ALM enrollment.
Dispatch and readback are serialized per target within the
process, with durable intents preventing overlapping writes through the same
local store. This does not protect against another workspace or maker or
establish server-side stale-write protection. The native adapter
independently binds submission to its freshly read selected target and an exact
computed state-only payload, and consumes at most one submission attempt.

After any submission, including timeout/conflict/error, the controller reads
back and reports each observed result. Desired state after an uncertain
submission is not attributed to this request. Verify non-state content and
outside-scope preservation; otherwise report partial/unverified. Never replay,
automatically roll back, request publishing, repair or continue a detached write.
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

Only the local original-state baseline and minimal write bookkeeping described
above are persisted. No approval file, full component inventory, new FlightCheck
profile, telemetry collector or diagnostic upload is introduced. Existing auth
caches and platform logs are unchanged. Telemetry additions remain deferred.
