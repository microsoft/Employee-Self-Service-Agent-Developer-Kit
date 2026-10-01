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

### Mandatory user-selection gate

A request such as "run a test set", "run evaluations", or `/run` authorizes
discovery only. It does not authorize executing any test set.

The selection flow must use two separate user turns:

1. Run `list-sets --include-local`, display the eligible choices, ask the user to select or
   confirm one, and **STOP**.
2. Only after the user's next message explicitly selects or confirms a
   displayed test set may preparation and the `run-prepared` command proceed,
   subject to deployment consent and explicit connection selection.

Never start a run in the same turn that discovers the candidates. This remains
mandatory when there is only one eligible set, when a fuzzy query returns one
match, when a prior conversation mentioned a set, or when local run history
contains only one set. Do not infer selection from any of those conditions.

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
Native local completion is not a remote review marker, but does not itself
block preparation. Never clear a pending tag to run.

### 2. Prepare the selected set and connection

Enter this step only when the current user message explicitly selects or
confirms one of the choices displayed in the immediately preceding assistant
turn.

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

Require explicit connection selection, even if only one profile exists or an
automatic account match is possible. For both Dataverse and native MinimalBot
agents, run:

```text
python scripts/evaluation_runs.py list-connections
```

Show returned connected profiles with display name, account name, creator, and
connection ID. `matchesSignedInAccount` is context, not permission to select
automatically. Ask the user to select with the structured question control and
**STOP**. A user-supplied explicit connection ID may be carried forward, but the
run command must validate it against this environment and connected status.
Do not silently choose a profile.

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

Only after explicit set selection, deployment consent, and connection selection:

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
`userGuidance`, not a success link; inspect run history before retrying
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
URL, label an overview as run details, retry start for navigation, poll, or
wait for completion to show the link.
Do not use the completed-result "Done" wording for an in-progress run.

Always include:

> I've started running your test set in Copilot Studio. This may take 10-15
> minutes. Return here to view the results when the run is complete; you don't
> need to open Copilot Studio.

The successful start command returns this exact text in `userGuidance`. Copy
`userGuidance` verbatim into the successful start response. This is a hard
postcondition: never finish a successful run-start turn without it, even when
the initial state is already `Completed` or the run finishes unusually quickly.
If the command is still pending and has not returned a run ID, do not claim
that the run was successfully triggered.

Do not create a local run mapping or results file.

## Flow B: List runs and show results

### 1. List run IDs

Run:

```text
python scripts/evaluation_runs.py list-runs
```

The script queries the Power Platform `testruns` endpoint and joins each run's
`testSetId` to the test-set `displayName` returned by the `testsets` endpoint.
This is the same behavior for makers, judges, and SMEs; no local run mapping is
used.

Display:

> | # | Test set | Run name | Run ID | State | Cases | Started |
> |---|---|---|---|---|---|---|

Ask the user to select a run. If they request all tenant-visible history rather
than recently discussed runs, use the same `list-runs` command and display all
returned entries. Do not show a Target column because the run-history API does
not return whether a run used draft or published agent state.

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
**Eval run complete — {passed} of {total} passed, {failed} failed ({pass-rate}%)**

Verdict: {verdict against the stated target}

**Results by scenario group**

| Group | Cases | Pass | Fail | Pass rate |
|---|---:|---:|---:|---:|
| {group} | {cases} | {passed} | {failed} | {pass-rate}% {status-icon} |

**Expected failures**

{evidence-based explanation, or "No failures were explicitly marked as expected for this run."}

{expected-failure table only when explicit expected-failure evidence exists}

**Failure analysis — grouped by root cause**

| # | Root cause category | Cases | Owner | Suggested action | Representative evidence |
|---:|---|---:|---|---|---|
| {number} | {category} | {count} ({failure-percentage}%) | {owner} | {action} | {evidence} |

📌 Pattern: {strongest evidence-based pattern across the failed cases}

**Who needs to do what**

• {owner}: {consolidated corrective actions}
• Gate: {target and the condition required before promotion}

{one concise question offering the most useful next corrective action}
```

Use `✅` when a scenario group meets the stated target and `❌` when it does not.
Use a target returned by the API or configured grader when available; otherwise
say that 95% is the reporting target, not an API-provided threshold. The verdict
must state whether the run clears that target and identify the concentrated
failure area when the evidence supports one. Do not claim promotion readiness
unless the configured target is cleared.

Render every row returned in `analysis.scenarioGroups`. The script uses the
test-set name as a single group when the API supplies no reliable finer-grained
scenario metadata. Use that fallback rather than inventing categories.

Always render **Expected failures**. Only classify a failure as expected when
the returned run data or selected evaluation metadata explicitly identifies it
that way. When explicit groups exist, introduce why they were expected and use:

> | Group | Cases | Pass | Fail | Pass rate |
> |---|---:|---:|---:|---:|

Otherwise render exactly:

> No failures were explicitly marked as expected for this run.

Render every row returned in `analysis.failureGroups`. The script groups failed
cases using metric status/data plus `errorReason` and `aiResultReason`. Treat
each category as an evidence-based root-cause hypothesis, not a proven fact.
Use returned counts, evidence, and suggested actions. Never invent an owner;
render `Unassigned` when ownership is unavailable.

Build **📌 Pattern** from the largest returned failure group and its percentage
of failures, adding a cross-group conclusion only when supported by returned
evidence. Under **Who needs to do what**, consolidate actions by returned owner;
do not create people, assignments, ticket numbers, commands, or deadlines.
Retain per-test-case states, metric statuses/data, and error/AI-result reasons
internally for follow-up, but do not append another detailed-results table.

After completed results, relevant explicit edit or subsequent workflow actions
may be offered through the shared experience contract. Never automatically
restart a run or repeat deployment after displaying status/results.

The script maps `testCaseId` to local case names using
`.component-map.json` when available. If no local mapping exists, show the
test-case ID rather than inventing a name.

If the run is still queued or in progress, report its current state and invite
the user to request the same run results later. Do not poll indefinitely.
