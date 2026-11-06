# Topic actions - nonmutating preview

This is the M1 entry only. It can verify authentication and read access to the
exact selected agent. Discovery, protections, planning, approval and mutation
are not implemented. Do not treat successful reads as write authority,
installed-topic verification, connection health or employee readiness.

<!-- TODO(M2-M7): connect the real discovery/planner and approved execution/UX. -->

## Inputs and setup

Honor the workspace's canonical setup gate in `.github/copilot-instructions.md`
before gathering action, set keys or target IDs. When setup is missing or
incomplete, immediately render that gate's setup-required Message block, telling
the maker to run `/setup`.

Then finish the request without authentication or topic changes. Do not silently
stop or wait for inputs that cannot be resolved before setup. If workspace
configuration is malformed or unreadable, report the configuration blocker
without exposing its contents. A failed prerequisite read or helper invocation
must produce an explicit user-facing blocker and a supported next step, not an
empty response.

Never start, resume or repair setup or a connection automatically. Retain the
caller's context and completed work. If the maker cancels before the check, stop
without authentication or changes.

Use the current canonical target from `.local/setup/config.json` and the
`activeAgent` in `.local/config.json`. Do not borrow the first agent, another
environment, a cached connection target or a previous conversation's identity.

The provisional request is a JSON object with:

- `target`: `tenantId`, `environmentId`, `agentId` from the selected workspace.
- `action`: exactly `enable` or `disable`.
- `setKeys`: a nonempty array of distinct opaque set keys already supplied by
  the caller/maker. Their membership is not verified by M1. Never invent keys,
  expand "all", infer groups from topic names, or offer a fabricated catalog.
- `entry`: `direct` or `caller`.
- `callerContext`: optional private JSON object; required for `caller` entry.
  Keep it with the caller in memory. Do not put it, tokens or component bodies
  in terminal commands, chat output or saved files.

If action or keys are not established, explain that topic-set actions and their
catalog are not available in this preview. Do not invent a selection UI.

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
caller steps incomplete. Return to the existing caller; never invent a
destination or invoke its next mutating step.

## Safety boundary

No component retrieval or update, publishing, connection repair, employee
requests, local topic edits, setup-state updates or operation journal.
No fallback to another skill may perform the requested mutation.

The helper reuses existing authentication caches and native read client.
Telemetry additions are deliberately deferred: this entry adds no collector,
capability events or saved validation data, and existing platform logs stay
unchanged. Final integration must retain the approved data constraints.
