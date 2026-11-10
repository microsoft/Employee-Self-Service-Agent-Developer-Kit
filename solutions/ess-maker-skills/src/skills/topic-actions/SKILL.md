# Topic actions - nonmutating entry

M1 verifies account and selected-agent read access only. Discovery, planning,
approval and execution are not available in this milestone. No topic writes
or publishing are supported.

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

Direct entry and a calling skill use the same nonmutating target verifier. Preserve
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

## Run the read-only check


Pass the request JSON on standard input to
`python scripts/topic_actions.py`, from this solution's workspace.
For terminal execution, omit `callerContext` and use `entry: "direct"` for the
check itself; the calling conversation retains its original private context.
An in-process caller may instead use `inspect_request` and receive its context
unchanged in memory. Use the existing Microsoft work-account selection;
`--account` binds a known account, not mutation consent.

Parse `TOPIC_ACTIONS_RESULT_JSON:`. Render the returned `message` as text,
without displaying raw inputs, exceptions, tokens or response bodies.
`implementation_pending` means only the account and exact-agent read check
succeeded. It is not completion of the requested enable/disable action.

All exits have `completed: false` and `writeStatus: "not_attempted"`. Report
missing/incomplete/broken setup, an unverified target, denied access or
cancellation truthfully. Preserve all caller progress and leave unresolved
caller steps incomplete. Use only a verified existing caller return; never invent a destination
or invoke its next mutating step.

## Safety boundary

No component retrieval or update, publishing, connection repair, employee
requests, local topic edits, setup-state updates or operation journal.
No fallback to another skill may perform the requested mutation.

The helper reuses existing authentication caches and native read client.
Telemetry additions are deliberately deferred: this entry adds no collector,
capability events or saved validation data, and existing platform logs stay
unchanged. Final integration must retain the approved data constraints.
