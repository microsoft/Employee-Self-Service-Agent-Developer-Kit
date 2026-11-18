# Run Evaluation Test Sets

Prepare and run the selected Copilot Studio evaluation test set through the
shared deployment flow and Power Platform API, or retrieve run results.

Execution requires a configured agent and completed `.local/config.json`.
Commands run from the `solutions/ess-maker-skills/` directory.
Read `src/skills/evaluations/experience-contract.md` and
`src/skills/evaluations/deployment-flow.md`. Run includes required deployment;
never require a separate typed push command or push the same set twice.

## Intent routing

- **Run / execute test sets or evals** -> follow **Flow A**.
- **Show evaluation runs / run IDs / results** -> follow **Flow B**.
- Do not invoke the local evaluation quality validator. This skill executes
  deployed test cases against the configured Copilot Studio agent.

## Flow A: Start an evaluation run

### Draft-only execution

This skill runs evaluations against the draft agent only. Never add
`--published` to a command or submit `runOnPublishedBot: true`.
If the user requests a published-agent evaluation, explain that this skill
supports draft evaluations only and stop. Do not silently substitute a draft
run; obtain explicit approval to test the draft before continuing.

### Mandatory user-selection gate

An ad hoc request such as "run a test set", "run evaluations", or `/run`
authorizes discovery only. It does not authorize executing any test set.

The selection flow for an ad hoc request must use two separate user turns:

1. Run `list-sets --include-local`, display the eligible choices, ask the user to select or
   confirm one, and **STOP**.
2. Only after the user's next message explicitly selects or confirms a
   displayed test set may preparation and the `run-prepared` command proceed,
   subject to deployment consent and connection selection.

Never start a run in the same turn that discovers the candidates. For an ad hoc
request this remains mandatory when there is only one eligible set, when a
fuzzy query returns one match, when a prior conversation mentioned a set, or
when local run history contains only one set. Do not infer selection from any
of those conditions.

**Workflow handoff exception.** Skip the selection question only when the maker
picks a run option (**Are you ready to run this test set in Copilot Studio?** or
**Run this test set**) from a structured next-step menu that ADK showed for one
exact set in this chat, such as after generating, editing, deleting cases, or
completing review. That choice already selects the set. Run
`list-sets --include-local --query "{set name}"` without asking, keep the
handoff's exact set folder, and confirm the returned row has the same
`localFolder`. Then go directly to **2. Prepare the selected set and
connection**. If the folder is not returned, `canPrepare=false`, or review blocks
the run, show the actual reason and fall back to the ad hoc selection flow. The
exception never skips deployment approval or connection selection.

### 1. Discover the test set

If the user names a test set, run:

```text
python scripts/evaluation_runs.py list-sets --include-local --query "{user text}"
```

This explicit preparation discovery includes workspace and current-agent local
sets, not unrelated agents. It distinguishes `canPrepare` from
`currentlyRunnable`, includes `requiresPreparation`, `hasLocalChanges`, exact
`localFolder`, source, current/mapped IDs, and `blockedReason`.

Show currently runnable sets and sets that can be prepared as separate states.
`currentlyRunnable=null` means readiness is unknown: show preparation/connection
checks pending and the returned `readinessReason`, not "runnable".
Do not call a local/dirty set deployed or runnable yet. A valid explicitly
completed local review marker may require synchronization before Run; that is
not permission to complete a pending review. Show the returned reason.
For `canPrepare=false`, show it as unavailable and copy the actual blocker.
Malformed methods/review state must not become a legacy runnable exception.
Never silently choose a fuzzy match. Stop after asking, even for one candidate.

If the user does not name a test set, run:

```text
python scripts/evaluation_runs.py list-sets --include-local
```

Display all returned current-agent/workspace candidates with their actual
preparation state. Ask which eligible exact set to run and stop after asking.

If no match is returned, show the available sets instead of guessing.
Workspace-only sets can be selected for preparation, but cannot start until
verified deployment. A pending `review_requested` blocks Run until explicitly
completed through Flow R2 and synchronized using the existing backend behavior.
An explicit local completion may proceed through preparation, but its shared
marker must be verified before Run. Never clear a pending tag to run.

### 2. Prepare the selected set and connection

Enter this step only when the current user message explicitly selects or
confirms one of the choices displayed in the immediately preceding assistant
turn, or through the workflow handoff exception above.

Retain the selected `localFolder` and source, not a display-name lookup or
possibly stale deployed ID. Follow the shared deployment admission and preview:

```text
python scripts/evaluation_deployment.py preview --set-folder "{set-folder}" --action run
```

Show the exact returned target/scope/diff and obtain approval. Keep its
`confirmationToken`; preserve any explicit replacement/deletion consent as
specified in the deployment flow. Do not deploy separately here.
For native `deploymentBehavior=new_copy`, explain before consent that the
existing insert API creates a new deployed ID and retains the old remote copy.
Case omissions affect only the new copy, not the old remote set. Start only the
actual ID returned by preparation; unchanged `reuse` still requires verification.

Select the Microsoft Copilot Studio connection automatically when the result is
clear. For both Dataverse and native MinimalBot agents, run:

```text
python scripts/evaluation_runs.py list-connections
```

When exactly one returned connected profile has `matchesSignedInAccount=true`,
use it without asking and show which user runs the evals:

> These tests will run as **{accountName}** ({displayName}).

Do not ask the maker to confirm or choose a connection in this case. If the
maker asks for a different user, list the connected profiles and use the one
they pick.

Ask only when no connected profile, or more than one, matches the signed-in
account. Then show the returned connected profiles with display name, account
name, creator, and connection ID, ask the user to select with the structured
question control, and **STOP**. A user-supplied explicit connection ID may be
carried forward, but the run command must validate it against this environment
and connected status. Never pick a profile that does not match the signed-in
account without the maker's choice.

If no connected profile is available, explain the actual prerequisite and
offer **Retry connection discovery** after repair; stop instead of running.
Missing, disconnected, or unverified selected profiles block both backends.
Do not invent a connected status or bypass the existing pending-review gates
merely because connection discovery succeeded.

This mandatory profile is the **Microsoft Copilot Studio** evaluation identity.
Other tool connections declared by the agent are optional run bindings: include
an unambiguous connected profile when available, but do not block the whole run
because an unrelated connector such as ServiceNow has no profile. A test case
that actually invokes an unavailable connector may fail at runtime; report that
case result rather than preventing every evaluation from starting.

### 3. Deploy and start exactly once

Only after set selection, deployment consent, and connection selection:

```text
python scripts/evaluation_runs.py run-prepared --set-folder "{set-folder}" --confirmation-token "{confirmationToken}" --yes --mcs-connection-id "{connectionId}"
```

Add `--replace` only if the approved preview used it, and `--force-delete` only
for exact approved Dataverse remote deletions, not native copy omissions.
This command invokes the shared deployment
helper, verifies source/target identity and method/review admission, then starts
the verified deployed set. Do not also call `evaluation_deployment.py deploy`
or `evaluation_runs.py run` for this same operation.

If the preview token is stale, preview and confirm again. If deployment fails,
no run starts: `stage=deployment` is not run success. If deployment succeeded
but start failed, `status=run_failed`, `stage=run` and the returned `deployment`
describe distinct outcomes. Report both stages and the returned recovery
`userGuidance`, not a success link. The set is available in Copilot Studio, so
link only to the returned `evaluationPageUrl` as "[Open the Evaluation page in
Copilot Studio]({evaluationPageUrl})", never as a run link. Inspect run history before retrying
execution, and do not repeat deployment blindly. For multiple explicitly
selected sets, retain separate tokens, approvals, and outcomes; never reuse
one set's ID/link.

Every run must include a validated `mcsConnectionId`; no anonymous evaluation.

Show the test-set name, run ID, returned initial state and any returned
processed/total case count, and explain that execution continues
asynchronously. Native HTTP 202 means accepted, not completed; do not invent
missing progress fields. Copy the returned `userGuidance`, then include the
optional navigation link:

> [Open this run in Copilot Studio]({agentStudioUrl}) (optional)

Use the successful command's `agentStudioUrl` with the same link label as
completed results. Use only its new run ID and actual deployed set identity;
never build a URL from conversation history or a local slug. If no valid run
ID is returned, do not show success or a run link. If a real run started but
`agentStudioUrl` is absent/null, report the run ID/state and that its link is
unavailable, including the returned `navigationWarning`. Do not fabricate a
URL, label the Evaluation page as run details, retry start for navigation, poll, or
wait for completion to show the link.
Do not use the completed-result "Done" wording for an in-progress run.

Always include:

> I've started running your test set in Copilot Studio. This may take 10-15
> minutes. Ask me for the run's status here at any time to check its progress
> and see the results when it's complete; you don't need to open Copilot Studio.

Also include:

> This evaluation tests the current draft agent, which may differ from the published version users see.

The successful start command returns this exact text in `userGuidance`. Copy
`userGuidance` verbatim into the successful start response. This is a hard
postcondition: never finish a successful run-start turn without it, even when
the initial state is already `Completed` or the run finishes unusually quickly.
If the command is still pending and has not returned a run ID, do not claim
that the run was successfully triggered.

Do not create a separate run mapping or results file. The run helper saves each
confirmed run start (only when a run ID is returned) to the agent's local run
history; if it returns `sessionWarning`, show it after the start guidance.

## Flow B: List runs and show results

### 1. List run IDs

Run:

```text
python scripts/evaluation_runs.py list-runs
```

The script queries the Power Platform `testruns` endpoint and joins each run's
`testSetId` to the test-set `displayName` returned by the `testsets` endpoint,
for both supported backends. By default it returns only runs started from ADK
for this agent (`scope=adk`), matched against the local run history. Use
`list-runs --all` only when the maker asks for every run, including runs started
directly in Copilot Studio; each run then has `startedFromAdk`.

Display:

> | # | Test set | Run name | Run ID | State | Cases | Started |
> |---|---|---|---|---|---|---|

Ask the user to select a run. When `otherRunCount` is greater than zero, say
that Copilot Studio has other runs not started from ADK and offer to show all.
When no ADK-started runs exist, say so and offer to show all runs. Report any
`adkRunsNotReturned` entries as started from ADK but not returned by Copilot
Studio; do not invent their state. Show any `sessionWarning`. Do not show a
Target column because the run-history API does not return whether a run used
draft or published agent state.

### 2. Retrieve selected results

Run:

```text
python scripts/evaluation_runs.py results --run-id "{runId}"
```

Use this existing run skill for results; do not route results to a separate
result skill.

When the run has completed, the **first line** of the results response must be:

> Done. I ran your test set through [Copilot Studio]({agentStudioUrl}).

Use the `agentStudioUrl` value returned by the `results` command as the link
target, so "Copilot Studio" opens this run's results directly in the agent's
Evaluate view. If `agentStudioUrl` is absent or `null`, render the same
sentence with "Copilot Studio" as plain text (no link). Never fabricate a
different URL. This line precedes everything below.

After the required first line, render completed results in this exact order and
format. Replace brace-delimited values with returned or deterministically
derived data. Preserve the headings, punctuation, blank lines, and table column
order. Do not prepend a metadata table or repeat the generated-case preview.

```text
**Eval run complete — {passed} of {total} passed, {failed} failed**

Test set: {test-set-name} · Run ID: {run-id}

**Results by scenario group**

| Group | Cases | Pass | Fail |
|---|---:|---:|---:|
| {group} | {cases} | {passed} | {failed} |

**See why test cases passed or failed**

Copilot Studio explains the result of each test case:

1. Open the [Evaluation page]({evaluationPageUrl}).
2. Select the evaluation run you want to analyze.
3. In the pop-up, look at the **Details** section.
```

End the completed-results response after step 3. Do not show expected-failure
sections, failure analysis, root-cause groups, patterns, suggested fixes, a
closing question, or a `What would you like to do next?` question.

The **Test set / Run ID** line identifies exactly which set and run these
results belong to. Use the returned `testSetName` for `{test-set-name}`. When
no name is returned, show the returned `testSetId` instead; when neither is
returned, write `not returned by Copilot Studio`. Never infer the set from the
conversation, a local folder, or a similarly named set. Use the returned
`runId` for `{run-id}`, or the run ID passed to the `results` command when the
response omits it.

Report returned passed, failed, and total case counts only. Do not show
percentages, pass rates, targets, thresholds, verdicts, or pass/fail status
icons, and do not state or imply that the agent is ready to deploy or promote.

Render every row returned in `analysis.scenarioGroups`. The script uses the
test-set name as a single group when the API supplies no reliable finer-grained
scenario metadata. Use that fallback rather than inventing categories.

Use the returned `evaluationPageUrl` for `{evaluationPageUrl}`. If it is absent
or `null`, write "Evaluation page in Copilot Studio" as plain text. Never
fabricate a different URL.

Do not analyze failures in ADK. Copilot Studio's run details are the source for
why each case passed or failed. Retain per-test-case states, metric
statuses/data, and error/AI-result reasons internally for follow-up questions,
but do not append another detailed-results table.

Never automatically restart a run or repeat deployment after displaying
status/results.

The script maps `testCaseId` to local case names using
`.component-map.json` when available. If no local mapping exists, show the
test-case ID rather than inventing a name.

If the run is still queued or in progress, report its current state together
with the same test-set name and run ID identification described above, and invite
the user to request the same run results later. Do not poll indefinitely.
