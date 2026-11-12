# Topic actions

Enable or disable whole source-defined ESS topic sets on one verified selected native
agent using the computed planner, short-lived review, single-attempt executor
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

For topic-set listing requests, show the live-agent set overview described
below, without asking which sets to list. For explicit per-topic detail or
preview requests, show the agent, environment, selected sets, short topic
names and observed current states. Both are read-only and need no approval
or unsolicited offer to execute.
Do not turn a topic-list request into an enable/disable plan: omit requested
states, plan columns, change counts and write-specific limitation notes.
Keep unresolved topics and blockers visible; do not imply complete discovery.
For an explicit
enable/disable request with established sets, use the execution helper's fresh review directly;
do not add a separate preview approval, a "start review" confirmation or a
"ready to proceed" question before it. A previous preview is not executable
approval and does not replace that fresh execution review.
Once sets are established, enable and disable requests always enter the `--review`
helper. Verified no-change enable/disable returns `already_correct` after a
fresh readback: render the final result and stop without approval or
`--apply-review`.
Never substitute a read-only list or preview because approval transport
appears unavailable.

Display the complete required review once, including every selected member,
account, target, changes, no-change topics and protections. Then present one
explicit decision control: **Approve**, **Deny** or **Cancel**, with no
preselected approval. Use the structured VS Code question and separate
review/apply commands below, as Connect Workday does;
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

### Fixed maker-facing wording

The helper supplies `userMessage` on every review and result. Render that
field verbatim as Markdown, without paraphrasing, adding a warning section,
exposing internal reason codes or appending the raw diagnostic `message`.
Use the review's text before the one approval control, and the result's text
as the final response. Do not duplicate the review after execution.
Do not regenerate counts, infer missing membership or turn an incomplete
result into success. For multiple independent previews, render each returned
`userMessage`; do not combine them into a newly interpreted successful scope.

The deterministic presentation is owned by
`scripts/topic_actions_presentation.py`. Do not show a "Before you approve"
section, its notes, or a replacement warning section. Limitations and dependency
impact remain available in structured diagnostics for technical questions.
Read-only previews show the topic inventory, not an execution plan,
and never ask for approval. Display the schema-name suffix after `.topic.`
(for example, `WorkdayGetVisas`); keep full identities in structured evidence
and mutation logic. Use "No change" rather than "Already correct" in plans.
Routine diagnostics such as service-enforced edit permission are not
repeated as notices. Structured `warnings`, `blockers`, HTTP status and
other evidence remain intact for callers and requested technical diagnosis;
not displaying raw warning lists does not remove checks or establish trust.
Unknown limitations remain in structured diagnostics rather than review notices.
Only when the maker explicitly requests diagnostics may safe reason codes
and HTTP status accompany the fixed copy. Never expose private evidence,
caller context, service bodies or credentials.

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
- **Selected topics unavailable:** live agent inventory determines which
  topics exist. For each requested set, use every present exact catalog
  match; differing template counts are normal, not missing-topic warnings.
  If no topics from a requested set are present, say
  "<set-key> topics are not available in this agent."
  Do not add administrator escalation or technical membership warnings.
  No topics are changed and no approval is requested for an unavailable set.
  Use an existing setup/recovery destination only
  when verified for that problem and installed version; otherwise state that
  the destination is unconfirmed. `/setup` does not install extension packs;
  `/connect` completion is not package or topic evidence.
- **Evidence unavailable or ambiguous:** do not diagnose absence or access
  denial. Unverified installation does not mean a missing package; unresolved
  topic identities can be missing or ambiguous. Say "I couldn't identify all
  the requested topics in this agent." Do not claim that ambiguous topics
  are absent or add routine administrator escalation.
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

## Action, live set overview and selection

When the action is unknown, ask just the action question first using the
host's structured question tool. Keep Enable, Disable and List in that order,
with the host's "Enter custom answer" fourth:

```json
[
  {
    "header": "Topic actions",
    "question": "What would you like to do?",
    "options": [
      { "label": "Enable topic sets" },
      { "label": "Disable topic sets" },
      { "label": "List topic sets/current states" }
    ],
    "allowFreeformInput": true
  }
]
```

Do not include a set-key question in this first control. Reuse an action
already supplied by the maker. Do not batch the action and set questions
into one call: wait for the action answer before discovery and selection.
After the action is chosen, if the request
is a set listing or enable/disable without established sets, read the
selected agent's inventory using:

`python scripts/topic_actions.py --list-agent-sets`

Pass one JSON request on standard input containing `contractVersion: 1`,
`target: {tenantId, environmentId, agentId}` and `entry: "direct"`.
Omit `action` and `setKeys`; do not invent an enable/disable request to list
sets. Keep private caller context in the calling conversation as below.
Parse `TOPIC_ACTIONS_RESULT_JSON:` and render `userMessage` verbatim.

Run this fresh for the current invocation and selected target. Earlier chat
lists, cached questions and source catalog definitions are not availability
evidence. Only `status: "sets_listed"` supplies the live `sets` choices. The overview
shows how many supported sets this agent has, each friendly integration/set
name, its present topic count and aggregate state:
**Enabled** means every present topic is On; **Disabled** means every present
topic is Off; **Mixed** means both On and Off; **Unknown** means a state or
membership could not be resolved. Absent sets are omitted. Do not populate
the overview from the source catalog alone or expand it into individual
topic rows unless the maker explicitly requests topic details.

For **List topic sets/current states**, stop after this overview. Do not
ask for set selection or approval. For **Enable** or **Disable**, when
`discoveryComplete` is true and `sets` is nonempty, pass the helper's
`selectionQuestion` unchanged as the sole next structured question. The
helper supplies exactly one option per present set with only its friendly
name, such as "Workday HR Topics" or "ServiceNow IT Topics". Use this
name-only pattern for all four supported sets: no state/count suffix or
description in picker options. Counts and states belong only in the overview.
Multi-select is enabled, with no custom-answer field and no preselected
choices. Map answered option labels to the `key` of each
matching entry in the same response's `sets`; retain keys internally.
Do not reconstruct, expand or supplement the helper's options, even if the
catalog or earlier conversation lists additional integrations or HR/IT sets.
Never use `--list-sets` to populate this control. If `selectionQuestion` is
absent/null, do not invent a picker or use a catalog fallback.
Empty/dismissed selection cancels without a
review or write. Failed or incomplete discovery must not become an empty
successful list or a guessed selection; render its result and stop.

After selection, use the normal fresh `--review` flow. The overview is not
approval or write evidence. If the maker already supplied an unambiguous
enable/disable action and sets, skip the action/overview/selection detour
and go directly to that fresh review.

### Proposed source catalog

Read `src/reference/topic-actions/catalog.provisional.json` or run
`python scripts/topic_actions.py --list-sets` to list **source definitions**.
This is not installed availability. The catalog deliberately retains unknown
required-topic classifications, package IDs and coverage, and provisional
approval. Do not change those labels to make a plan pass.

For changes, establish exactly one action (`enable` or `disable`) and use
the canonical selected target with the selected whole-set keys internally.
Restore and undo of previous Topic Actions changes are not supported.
Do not translate an undo request into the opposite action, since earlier
topic states may have been mixed. Explain the limitation and ask for the
desired action only when it is not established, then use live set selection
above when sets are unknown.
Never infer membership from names, merge source families, expand "all" without
selection or authorize a topic individually. Live inventory is the source
of topics to enable/disable. The catalog maps exact schema keys to the
requested sets; only members actually present in this agent enter the scope.
An agent with 10 matching topics does not need the 15 topics another agent
has. Absent template members are ignored, not reported as incomplete.
Ambiguous identities still block. Legacy flat definitions remain read-only.

## Read-only preview or chat review and apply

Pass one JSON request on standard input to:

`python scripts/topic_actions.py --preview`

The request contains `contractVersion: 1`,
`target: {tenantId, environmentId, agentId}`, `action`,
`setKeys` (distinct exact keys), and `entry: "direct"`.
Only enable/disable is accepted; `initializeBaseline` is no longer an input.
Do not save an input file. For terminal execution omit private caller context; retain it with the
calling conversation. An in-process caller can use
`run_topic_actions(..., confirm=..., preview=True)` with `entry: "caller"` and
a nonempty `callerContext` JSON object. Never put context, tokens or component
bodies in terminal commands, chat output or files.

Parse `TOPIC_ACTIONS_RESULT_JSON:` and render its `userMessage`.
For preview, it presents the agent, environment, selected topics and observed
current states in fixed plain language, plus any blocker preventing resolution.
Execution reviews additionally present proposed changes, no-change topics
and protections. Limitations remain in structured diagnostics.
Observed differences in a blocked plan are **not eligible changes**. Report
all requested sets using their present members. A requested set with no
present members blocks rather than disappearing from the request.
No user approval can override blockers.
Preview returns `status: "preview"` and `writeStatus: "not_attempted"`. It
does not acquire write scopes or collect executable consent.

For the normal write flow, pass the request on standard input to:

`python scripts/topic_actions.py --review`

This command finishes; it does not wait for terminal input. Parse
`TOPIC_ACTIONS_RESULT_JSON:`. Only `status: "review_ready"` supplies a
`reviewId` and permits asking for approval. Display its complete `userMessage`,
including account, target, every selected set/member, proposed changes,
no-change topics and protections. Do not append approval notes. Keep `reviewId` and
expiry metadata internal. For any other status, render the returned
`userMessage` without asking for approval and stop.

Then use `vscode_askQuestions` (or the host's structured question tool):

```json
[
  {
    "header": "Topic changes",
    "question": "Apply the topic changes shown above?",
    "options": [
      { "label": "Approve" },
      { "label": "Deny" },
      { "label": "Cancel" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave every option initially unset. Only the maker's explicit **Approve**
maps to `approve`; **Deny** maps to `deny`. **Cancel**, a dismissed question,
or an ambiguous response maps to `cancel`, never approval. After the answer,
run the fixed command with the returned ID and the actual decision:

`python scripts/topic_actions.py --apply-review "{REVIEW_ID}" --decision "{DECISION}"`

This consumes the pending review exactly once, including denial or cancellation.
It needs no stdin continuation, background terminal, named pipe, computer
control, or ad hoc bridge. Do not request desktop access or fall back to manual
terminal instructions merely because the host cannot send input to a waiting
process. Never prefill approval, save an approval for later, automatically retry
an apply command, or recreate a consumed review silently.

The pending review expires after five minutes. Apply authenticates again,
rechecks the selected target, full evidence and exact review, then performs
the existing fresh pre-dispatch checks and readback. A changed account,
target, catalog, membership, content or topic state
invalidates the review. Expiry is not extended by authentication or discovery.
An expired, missing, consumed or changed review requires a new complete review
and explicit approval; do not treat an old answer as approval of a new plan.
Render the apply command's final `userMessage`; review creation is not completion.

If a structured question tool is genuinely unavailable, report that specific
blocker. Only then offer the existing interactive-terminal alternative, or use
it when the maker explicitly requests terminal commands:
`python scripts/topic_actions.py --execute`. That alternative reads one request
line, emits `TOPIC_ACTIONS_REVIEW_JSON:`, and requires the actual decision as
the next line in the same process. EOF cancels. It is not the normal chat route.

An in-process host uses `run_topic_actions(..., confirm=...)` without
`preview=True`; its callback owns displaying the review and collecting the
maker's explicit answer. All entry types use this same controller.
Authentication uses neutral ADK authentication utilities and the existing
AgentBuilder cache (`.local/.agentbuilder_token_cache.bin`), not Connect
Workday's authentication or token-cache implementation. Execution requests
the explicit native component read/write scope at apply time; preview and
review preparation request only the component read scope. A previously cached Workday `.default` token does not
guarantee these scopes are available without sign-in or consent.
Both recheck the exact tenant/account.
No publish operation is requested. Running the CLI
without a mode remains a read-only prerequisite inspection.

## Planning and approval rules

The planner deduplicates selected membership. Known required topics cannot be
valid members and remain defensively protected. Unknown required status does
not block this policy and remains visible as a plain-language limitation
before approval. Selected sets do not protect each other. For disable, a fully enabled
outside set protects shared topics; a
partly enabled outside set protects them only when it has an On member outside
the selected union. This protection uses only the source-defined map; its
completeness and custom dependencies remain unverified. Absent template members
are excluded from both selected and outside sets. Ambiguous exact matches,
unknown states of present members, unsupported source variants and a missing
change token still block. Every requested set must have present members.

The controller requires explicit approval for actual enable/disable changes
against the exact target, account, action, selection, memberships, revision,
states, protections and delta. Approval lasts at most five minutes and is rechecked immediately
before dispatch. Denial/cancellation changes nothing. Any drift requires a
fresh review. A nonempty eligible scope already in the desired state is
different from empty scope or an all-protected action.

## Current-state operations

Every enable/disable request uses current live topic states. No original-state
baseline is captured or required, and no first-use or previous-change question
is needed. Earlier changes, a new workspace, and absent or corrupt legacy
baseline files do not change this flow. Leave existing original-state files
untouched; they are no longer read or updated. The skill cannot restore an
earlier configuration.

After an uncertain submission, never retry or infer that the requested change
succeeded. A later explicit request starts with new live evidence and requires
a new approval for any actual changes. It is not a replay or recovery of the
previous operation.

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
process. Independent processes, workspaces or makers can still overlap;
there is no durable cross-process write lock. This does not
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

For an unsuccessful submission, use the fixed plain-language failure text.
Keep the safe failure category and `submissionHttpStatus` in the diagnostic
result; show them only when technical details are requested. Do not expose
exception messages or service response bodies. A rejected request is not successful completion;
readback observations do not authorize a retry.

Distinguish blocked, denied, cancelled, review-required, already-correct,
completed, completed-with-protections, partial and unverified outcomes.
Protected topics are never reported as disabled. Partial, protected or
uncertain scope must not complete the caller's whole-set request.

Only short-lived pending reviews are persisted under `.local/topic-actions`.
Pending reviews contain only the non-secret target/request, evidence/review fingerprint and
expiry metadata; they never contain an approval, caller context, token or full
component inventory. A pending review is not permission to write. Its ID is
atomically consumed before execution, and cannot resume or replay a write.
No new FlightCheck profile, telemetry collector or diagnostic upload is introduced. Existing auth
caches and platform logs are unchanged. Telemetry additions remain deferred.
