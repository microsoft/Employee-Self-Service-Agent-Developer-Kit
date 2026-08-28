# Run Evaluation Test Sets

Run deployed Copilot Studio evaluation test sets through the Power Platform
API and retrieve run results.

This skill requires a configured agent and completed `.local/config.json`.
Commands run from the `solutions/ess-maker-skills/` directory.

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

1. Run `list-sets`, display the eligible choices, ask the user to select or
   confirm one, and **STOP**.
2. Only after the user's next message explicitly selects or confirms a
   displayed test set may the `run` command be invoked.

Never start a run in the same turn that discovers the candidates. This remains
mandatory when there is only one eligible set, when a fuzzy query returns one
match, when a prior conversation mentioned a set, or when local run history
contains only one set. Do not infer selection from any of those conditions.

### 1. Discover the test set

If the user names a test set, run:

```text
python scripts/evaluation_runs.py list-sets --query "{user text}"
```

The script starts from `{agent.folder}/evaluations/`, reads each EvaluationSet
parent ID from `.component-map.json`, and confirms that ID is active in the
Power Platform API. It excludes every set whose local `review.json` status is
`review_requested`, whether the user named that set or requested the complete
list. This is the only excluded status: sets with no review tag,
`review_completed`, unknown statuses, or unreadable legacy metadata remain
runnable.
Display every returned match with name, test-set ID, state, local folder, and
case count. Ask the user to select or confirm one. Never silently choose a
fuzzy match. Stop after asking; do not invoke `evaluation_runs.py run` in this
turn.

If the user does not name a test set, run:

```text
python scripts/evaluation_runs.py list-sets
```

Display all active deployed test sets represented in the configured agent's
local `evaluations/` folder and ask which one to run. Stop after asking, even
if the list contains only one test set.

If no match is returned, show the available sets instead of guessing.
Workspace-only test sets are not runnable until they are pushed to the
configured agent. Test sets tagged `review_requested` are also not runnable
until their pending review status is cleared or changed to `review_completed`.

### 2. Start the selected set

Enter this step only when the current user message explicitly selects or
confirms one of the choices displayed in the immediately preceding assistant
turn.

Run:

```text
python scripts/evaluation_runs.py run --test-set-id "{id}" --test-set-name "{displayName}"
```

Before starting the run, the script discovers the signed-in user's Microsoft
Copilot Studio connections in the selected environment and keeps only profiles
whose status is `Connected`.

- If exactly one profile is connected, use it automatically.
- If multiple profiles exist, use the one that uniquely matches the signed-in
  Power Apps account.
- If multiple connected profiles remain, automatically use the first profile
  in deterministic name/ID order and try the run without asking the user.
- If none are connected, stop and explain that the user must create or repair
  the connection in Power Apps or Power Automate.

Every run must include a validated `mcsConnectionId`; do not start an
anonymous evaluation run.

Show the test-set name, run ID, initial state, processed/total case count, and
explain that execution continues asynchronously. Always include:

> Running your evaluation may take a while. Please return in 10-15 minutes to
> see the results.

The `run` command also returns this exact text in `userGuidance`. Copy
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

First show:

- Test-set name, run name/ID, state, start/end times, and total cases.
- A completion summary with passed, failed, and pass-rate totals.
- A verdict against a clearly stated target. Use a target returned by the API
  or configured grader when available; otherwise label the default 95% target
  as a reporting target, not an API value.

Then analyze and present:

1. **Results by scenario group** - render every row returned in
   `analysis.scenarioGroups` using this exact table:

   > | Group | Cases | Pass | Fail | Pass rate |
   > |---|---:|---:|---:|---:|

   The script uses the test-set name as a single group when the API supplies no
   reliable finer-grained scenario metadata. Never omit this table merely
   because it contains one row; use that fallback rather than inventing
   categories.
2. **Failure analysis - grouped by observed cause** - render every row returned
   in `analysis.failureGroups` using this exact table:

   > | # | Observed cause | Cases | Owner | Suggested action | Representative evidence |
   > |---:|---|---:|---|---|---|

   The script groups failed cases using metric status/data plus `errorReason`
   and `aiResultReason`. Use its returned category, counts, evidence, and
   suggested action without replacing them with unstructured bullets. These
   are observed failure patterns, not proven root causes. Never invent an
   owner; the script returns `Unassigned` when ownership is unavailable.
3. **Detailed evidence** - retain per-test-case state, every metric type and
   status, error/AI-result reasons, and metric data returned by the API.

End with the strongest evidence-based pattern and the next corrective action.
Do not claim promotion readiness unless the user has configured a promotion
threshold and the run clears it.

The script maps `testCaseId` to local case names using
`.component-map.json` when available. If no local mapping exists, show the
test-case ID rather than inventing a name.

If the run is still queued or in progress, report its current state and invite
the user to request the same run results later. Do not poll indefinitely.
