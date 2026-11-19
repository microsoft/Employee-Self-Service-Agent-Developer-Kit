# Review Evaluation Test Sets

Handle reviewer, judge, or SME requests to review evaluation test sets that a
maker tagged with `review_requested`.

This is a workflow review, not a quality-validation request. Do not invoke the
evaluation validate subagent when entering this skill.

## Step 1: Discover tagged test sets

The reviewer must not be asked to pull or refresh test sets manually.

Read `.local/config.json` and `src/skills/evaluations/deployment-flow.md`.
Dataverse pushes review metadata in the evaluation-parent description. Native
MinimalBot pushes YAML only and retains review sidecars locally; do not block
the existing local review workflow on a new shared-metadata prerequisite.
Do not turn a successful native YAML upload into a cross-user review-availability
claim or invent remote metadata.

Apply this backend gate before any refresh, MCP invocation, or remote discovery:

- When `.local/config.json` has `releaseLine: "da"` or a
  `powerPlatformApiEndpoint` and no `dataverseEndpoint`, treat it as native.
  Run only `python scripts/evaluation_review.py --list-all`, select rows whose
  `localStatus` is `review_requested`, and never invoke Dataverse MCP,
  `fetch_and_setup.py --refresh`, or the Dataverse-only `--list --status`
  command. A Dataverse authentication prompt in this branch is a routing error,
  not a prerequisite.
- Only a configured agent with a real `dataverseEndpoint` uses the Dataverse
  refresh and synchronized remote-marker discovery below.
- With no configured agent, use local-inclusive discovery without either remote
  backend.

For a Dataverse configured agent, and only after the backend gate selects the
Dataverse branch, refresh before listing review work:

```text
python scripts/fetch_and_setup.py --refresh
```

The refresh flow creates a checkpoint before replacing local agent files and
rebuilds the baseline from the latest Copilot Studio state. Show a short
progress message such as:

> Refreshing the latest evaluation test sets from Copilot Studio...

Do not ask for a separate confirmation or instruct the reviewer to run
`/setup --refresh`. If refresh fails, report the actual authentication, API, or
setup error and stop rather than presenting a stale review list.

When no configured agent exists, skip the refresh and continue discovery so
the command can report any eligible local state. The local working status alone
is not proof that a configured-agent review tag was pushed.

For Dataverse review discovery, from the solution root run:

```text
python scripts/evaluation_review.py --list --status review_requested
```

This command compares each configured-agent working set with its matching
`.baseline/evaluations/{set}/` snapshot from the latest pull or successful
push. It returns only sets whose `localStatus` and `deployedStatus` are both
`review_requested`.
Use this command's JSON output as the complete Dataverse pending-review list. Do not
replace it with a broad file-search or glob. The command filters out local-only review requests that have not been pushed,
review completions waiting to be pushed, and `review_completed` sets. It
returns each set's source, folder, test-case count, local status, deployed
status, synchronization state, and next action.

For native local review, use the existing local-inclusive discovery instead:

```text
python scripts/evaluation_review.py --list-all
```

Select returned rows with `localStatus=review_requested` and label them
**Review requested locally**, not remotely assigned/shared review work. The
sidecar stays in the selected local/promoted folder and confirmed plan
fingerprint, not deployed `.baseline`. Do not require a remote review refresh
or matching `deployedStatus`/`nextAction=review` to inspect this local work.
An explicit local review completion remains distinct from remote publication.
Use the command output, never an ad hoc sidecar glob or a cross-agent search.

## Step 2: List before reviewing

Before reading cases or running any validation, present the pending sets:

> | # | Test set | Source | Test cases | Review status |
> |---|---|---|---|---|
> | 1 | Compensation | Configured agent | 8 | Review requested |

If no tagged sets are available on Dataverse, say that no test sets from the
latest pulled Copilot Studio state are currently available for review. On
native, say no eligible locally tagged sets were returned; shared-review
discovery is not provided by the existing YAML-only push. On Dataverse, do not
treat a local `review_requested` change with `nextAction=push_review_request`
as shared review work. Native local review does not wait for that shared marker.
Do not run the quality validator as a fallback.

Use the available structured question control (dropdown or choice buttons)
with one option per returned test set. Each option must include the test-set
name, source, and case count. Ask exactly:

> Which test set would you like to review?

Do not call the test sets "pending" in the user-facing question. The
`review_requested` status already communicates that internally.
Wait for the user to select before continuing.

## Step 3: Continue the review workflow

After the user selects a set, read
`src/skills/evaluations/update/SKILL.md` and follow **Flow R2 — Review assigned
test sets**, beginning with showing its prompts and expected responses.

The reviewer inspects prompts and expected responses and provides feedback,
suggestions, or recommendations for the maker. The reviewer does not edit
test-case source files in this flow, so quality validation is not invoked.
Never describe this workflow as "view-only"; it produces an actionable review
handoff.

Before ending, the reviewer must be offered a structured choice to **Provide
feedback or recommendations for the maker** or **Mark review complete without
feedback**. If recommendations are supplied, state that the maker owns the
official edits, validation, push, and subsequent evaluation run.

Retain all feedback for the same selected set and ask whether to **Provide more
feedback** or **Mark review complete**. Explicit completion follows update Flow
R2 and `src/skills/evaluations/deployment-flow.md` in the same workflow:
save explicit local completion and continue the existing scoped push. Dataverse
verifies the published marker. Native reports the uploaded/reused ID,
`reviewMetadataPersisted=false`, `deployedReviewStatus=null`, and `reviewWarning`;
completion is local, not published to other users. Run remains subject to its
existing gates. Failed/cancelled completion deployment stays local/pending.
Never infer completion from maker activity, quality scores, or an ordinary push.
