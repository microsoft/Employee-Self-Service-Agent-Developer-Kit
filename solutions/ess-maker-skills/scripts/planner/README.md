# ESS Maker Kit — Planner (`scripts/planner/`)

The Python package behind the `/planner` skill. It owns the local, structured
**Plan** an ESS rollout is authored into, plus the deterministic helpers the
skill calls (Learn-research selection, output capture, the roles seam).

The skill (Markdown, under `src/skills/planner/`) drives the conversation,
grounding, and confirmations; this package owns the crash-safe writes and the
pure logic.

## Modules

| Module | Responsibility |
|--------|----------------|
| `plan_model.py` | The Plan document — schema, atomic read/write, validation, `ESS-scenario-plan.md` render, and the Flow-2 (grouped-by-role) discovery query. Shaped to match the WeveNova `Plan`/`Task` entities so a future sync is a field copy. |
| `roles.py` | The **absent-safe** roles-source seam (`RoleDirectory` / `RoleSource`). With no backing source wired, validation degrades to a well-formed-id check and enumerations return empty so the skill falls back gracefully. `StaticRoleSource` is a trivial in-memory implementation for demos/tests. |
| `capture.py` | Observe-mode detectors that read what a Task produced from local kit state — the `/setup` → `environmentId` hand-off from `.local/config.json` (`snapshot_config`/`detect_config_artifacts`), and the `/discover` → `tenantInventory` summary from `workspace/discover/results.json` (`summarize_discovery`) — plus `ask_artifact` for assignee-supplied (mode-b) outputs. |
| `research.py` | Scope Learn research after intent capture: select pages from the TOC, cache readable text and provenance for up to 24 hours, and extract role/output candidates without fetching the same pages again. Pure selection helpers plus explicit network/cache IO. |
| `facts.py` + `planner_facts.json` | **Non-Learn** planning facts only — scenario *dependencies* (each with an explicit `source`) and a small recognition lexicon for `extract_signals`. This is **not** a business-scenario catalogue: scenarios come from the maker's description grounded in Learn (PM spec FR-1/FR-3). |
| `cli.py` | The command surface the skill invokes (`init`, `ingest-upload`, `gaps`, `set-context`, `add-system`, `add-scenario`, `add-scenario-dependency`, `check-deps`, `add-task`, `update-task`, `remove-task`, `assign`, `claim`, `set-state`, `task-brief`, `capture-setup`, `capture-discover`, `pin-output`, `mine`, `research`, `summary`, `validate`). `ingest-upload` builds a whole plan from a maker-authored uploaded plan (normalized JSON) in one atomic write and reports the remaining gaps; `gaps` lists the intent slots a plan still lacks. `capture-discover` summarizes a `/discover` run onto the plan's tenant-inventory task. |
| `review.py` | CSV export and read-only review proposals with stable task IDs, version checks, and spreadsheet-formula escaping. No imported review applies edits automatically. |

## First Planner use in a chat

First apply the canonical **Intent gate**: only a requested Planner action or a
genuine continuation starts this flow. A greeting such as "Hi", general help, or
an open/attached `plan.json` alone does not cause plan lookup, workspace bootstrap,
MCP discovery, or shared-access prompts. Passive files can supply the target of
"share and activate it"; they cannot supply the action. This preserves the
normal welcome and other skills' setup gates without adding a confirmation turn
to clear Planner requests.

Whichever Planner flow runs first performs the shared workspace bootstrap:
new planning, imports/edits, assignments, assigned tasks, completion capture,
evaluations, status/reports, or sharing/activation. Direct phase entries use the
same gate in `src/skills/planner/SKILL.md`. It does not require a completed
`/setup` or `.local/config.json`. Before the flow or any shared tool call,
materialize this solution's `.vscode/mcp.json` and validate Planner and its
person-resolution fallback:

```text
python scripts/mcp_config.py materialize-defaults
python scripts/mcp_config.py validate --server ess-planner
python scripts/mcp_config.py validate --server workiq-preview
```

Run from the solution folder and require `configured` for both servers.
The idempotent helper preserves custom server definitions and the saved draft.
An already-visible tool is not proof that the workspace file exists; a configured
file is not proof that the host started the server. Reuse successful command
results throughout the same chat/workspace, across later turns and phase changes.
Recheck in a new chat, if the workspace/configuration changes, or if no bootstrap
attempt is recorded. Failed bootstrap blocks shared calls, not local drafting;
retry only when requested or after the configuration problem is corrected.
Registration does not grant shared access or require WorkIQ sign-in for local work.
Before reusing a successful check, verify that the file still exists and the
required host tools are available. Missing configuration or an unavailable MCP
connection triggers one materialize/validate recovery, followed by one normal
host start/discovery attempt if needed. Do not loop or overwrite custom servers.
An API response such as `OpenTypeTooLarge` or HTTP 500 is not MCP unavailability.
Resume the draft and honor the requested lifecycle actions: sharing must succeed
before activation. A service error after a real shared call remains a separate
failure; creating the workspace configuration does not resolve it.

## Shared-record size protection

`scripts/planner_payload.py` is the shared export/MCP preflight. It measures
UTF-8 JSON for persisted plan fields, not the whole create HTTP body (inline
tasks are separate records). The ESS cap is 25,600 bytes. Client policy reserves
1,024 bytes per record plus 256 bytes per context entry for server-stamped
metadata. These are conservative allowances, not an exact backend serializer
or a substitute for server-side aggregate validation.

`export-remote-plan` checks the final outgoing metadata. When needed, it packs
generated workstream labels into `taskStreamMap` scalar JSON chunks, each within
the existing value limit. It preserves ordinary context, acceptance criteria,
tasks, and workstream labels. Readers accept both legacy per-task carriers and
versioned maps; older clients retain the unfamiliar map group as ordinary
context for recovery on a later current-client export.

If the result still exceeds the budget, export fails without emitting a body or
altering the local JSON/Markdown draft. Refine redundant prose without silently
dropping requirements, then export again. Local `validate` success alone does
not prove a shared export fits.

Direct MCP creates also check the budget. Metadata patches combine current
persisted fields with the patch before checking; the original If-Match ETag is
retained. Server provenance is covered by headroom rather than counted twice.
Known `OpenTypeTooLarge` responses get non-retry guidance. Generic 500s are not
guessed to be size errors. Diagnostics include the authenticated tenant and
request identifiers, never tokens; a reported tenant mismatch must be resolved
before further writes, not copied into configuration as a new default.
Final retryable HTTP failures and conflict-recovery guidance retain the original
HTTP status, authenticated tenant, and request IDs. Retry limits and the
no-blind-replay ETag policy are unchanged.
After updating the kit, restart a running `ess-planner` MCP server once to load
the new code. Materializing an unchanged definition does not hot-reload Python.

## Scoped research

Capture the requested scenarios and known systems first; an unknown system stays
pending rather than triggering research into every connector. Retrieve the scoped
Learn content and candidate roles/outputs together:

```text
python scripts/planner/cli.py research --fetch --extract --tokens "employee profiles Workday"
```

The response includes readable `pages`, source URLs, timestamps, and `signals`.
Consume that text without downloading the selected pages again.
`research-context.json` preserves existing notes alongside a managed `learnCache`.
TOCs and pages are reused for up to 24 hours; changed scope fetches only missing
or stale pages. Add `--refresh` to explicitly refresh grounding. This command
does not create or modify `plan.json`, and plain status/resume needs no research.

Retrieval errors are visible in JSON and stderr and produce a nonzero exit code.
Successful pages remain cached; a failed refresh does not relabel old text as
fresh. Invalid cache data is reported without overwriting existing notes.

## Scenario-derived experience

The skill infers ESS HR or ESS IT from the requested scenarios and confirms the
proposed target with the draft plan, rather than opening with an experience picker.
An explicit or saved target is reused. Mixed/unclear scope is recorded as an
`experience` pending decision without blocking local drafting. The existing
`configuringAgentName` requirement applies when exporting for shared creation;
the skill must resolve it through scenario-based plan review, not guess a value.

## Pending decisions and execution readiness

An unknown system is a saved decision, not an invented system or a global
planning gate:

```text
python scripts/planner/cli.py add-system --area hr-profile-write --pending
python scripts/planner/cli.py add-system --area hr-profile-read --system "Workday" --system "SAP SuccessFactors"
```

`--pending` and common uncertain answers create `pendingDecision` context.
Resolving the same area with `--system` replaces that pending entry. `gaps`
reports deferred decisions separately from unanswered questions. For deferred
owners, keep the grounded task role and use `owner.<role-id>` in the same group.
Known systems are scalar context values; multiple selections are stored together,
not overwritten by successive calls.

Tasks needing a pending system can consume its `system.<area>` key. Resolution
unblocks that decision only; the skill must then model actual integration outputs.
`InProgress` and `Completed` transitions reject unresolved inputs. Completion also
requires declared outputs and a verified ID for Environment artifacts. Graph
validation rejects cycles, and rendered workstream sections preserve dependency
order while keeping independent preparation parallel.

`setup-status` distinguishes an environment from an installed agent
(`environmentPinned` and `agentPinned`). `setupTaskId` and `setupEnvironmentKey`
identify the first unfinished environment-producing task in dependency order:
`provisionedEnvironment` for provisioning or `primaryEnvironment` for the
corresponding setup/binding milestone. `capture-setup` uses that declared key by
default, including with an explicit `--task`; `--key` remains an override.
`firstRunSetupTaskId` identifies ready first-run work before an environment is
pinned. Completing provisioning leaves unsatisfied installation/binding tasks
open. Foundation-only results not yet in `.local/config.json` use the confirmed
`pin-output` path with the same declared key, not a renamed environment output.

## Progress-aware next actions

After a task run or a plan/assignment change, Planner refreshes the same person's
next action from current state rather than retaining a previous recommendation.
Completed work disappears from `mine`; pending shared confirmation still blocks
dependent execution, and another role's newly ready task is not assigned to the
caller implicitly.

`task-brief` reads `.local/config.json` to decide whether this workspace still
needs binding. A completed setup for the same environment and recorded agent
suppresses the `/setup` nudge. Completed/blocked tasks and tasks with unmet inputs
do not get a binding nudge. Missing config is normal first-run state; corrupt
config is reported explicitly. Override the config path for another workspace:

```text
python scripts/planner/cli.py task-brief --task <task-id> --config <config-path> --json
```

This check is read-only; it does not mark work complete or change assignments.
The skill's post-completion handoff captures verified outcomes, synchronizes
eligible shared progress, and recommends the next task without starting it.

Every Planner entry and phase uses the shared UI guideline's next-step handoff:
a separate heading, a bold action, and a copyable prompt, command, or link on its
own line. The first draft can show the ordered lifecycle roadmap; later replies
show one current action, not the whole menu. Imported drafts follow the same
review/share/activate journey rather than jumping straight to admin execution.

Identity and approval questions belong in the main chat. An unavailable question
is not an answer or consent, and a setup role statement does not itself request a
plan assignment. Existing shared-plan roles can be assigned before environment
setup; the actual environment-access checks remain separate.

## Local, shared, and confirmed are different states

An unshared draft's pending work cannot merge into a shared plan based only on
matching titles or local IDs. First-share readback supplies
`import-remote-plan --created-plan-file <successful create_project_plan result>`
alongside the plan/task result files. The create identity must match the
readback before unique title matches can associate newly assigned task IDs.
Missing proof, mismatched identities, or ambiguous first-share task matches stop
replacement and leave the draft intact. Normal resume uses established plan/task
identities and never supplies a create response as a workaround.

The first draft is saved in the workspace, not just the chat. First sharing and
activation each require consent. Every completion path queues `pendingSync`;
partial artifacts use `pendingOutputs` without pretending their task is complete.
`pending-sync` emits the supported operation, task ETag, and compact output
payload. Local Agent/EntraApp kinds map to remote Custom artifacts with
`artifactType` metadata.

Pull reconciliation retains pending work until task state **and expected output
values** are confirmed, keeps original ETags on stale pulls, and rejects cross-plan
replacement while writes are pending. Partial outputs have no standalone remote
write endpoint: finish the task or agree to a genuine milestone split. Noncompletion
shared edits are tool-first; they are not implicitly covered by the completion queue.
Starting dependent work on a shared plan waits for the consumed metadata's shared
confirmation. Retrospective capture can still save already-completed offline work
and its evidence, without claiming it has reached the team.

## Spreadsheet review

```text
python scripts/planner/cli.py export-review --output "workspace/plan/review-v1.csv"
python scripts/planner/cli.py review-changes --input "workspace/plan/review-v1.csv"
```

Edit Title/Description or add Review notes in Excel or another spreadsheet. Keep
IDs, versions, and other columns intact. `review-changes` returns proposals only;
confirm them and use the normal CLI/shared-tool edit flow. Stale or malformed
reviews are rejected, and exports never overwrite existing review files. Markdown
rows also carry stable hidden `task-id` markers; Step numbers are not task IDs.

Scenario evaluation cases are saved as `evaluationCase` context. Planner invokes
the existing eval-driven topic or evaluation-generation skill in the selected
build flow, retaining its approval gates. Draft cases, generated files, published
tests, and actual runtime results are reported separately.

## Local Plan location

The Plan is per-maker runtime state under `workspace/plan/` (git-ignored):

```
workspace/plan/plan.json               the structured Plan (source of truth)
workspace/plan/ESS-scenario-plan.md    editable human-readable view (reconciled back)
workspace/plan/research-context.json   cached Learn-research corpus
```

## Tests

- Tests: `tests/planner/` (pure logic + local IO; research fetches are mocked
  except for the separately opted-in live TOC check).
  Run from the repo root: `python -m pytest tests/planner`.

Nothing here requires WeveNova, tenant inventory, or a roles source — the Plan
is authoritative on disk and works with all three absent.

### Two-account live service validation

`tests/mcp/planner/test_planner_live.py` exercises the real stdio MCP and shared
service with a maker and a different administrator in a dedicated test tenant.
It covers a shared draft, explicit activation, deferred owners/systems,
independent progress, caller-scoped tasks, completion acknowledgment, and
environment metadata releasing dependent work.

Set `ESS_PLANNER_LIVE_TENANT_ID`, `ESS_PLANNER_LIVE_MAKER_UPN`,
`ESS_PLANNER_LIVE_ADMIN_UPN`, and `ESS_PLANNER_LIVE_ENVIRONMENT_URL` locally.
To authorize test writes, set `ESS_PLANNER_LIVE_ALLOW_WRITES` to that same tenant
ID. Never commit these settings or authentication data. Then run from the root:

```text
python -m pytest tests/mcp/planner/test_planner_live.py --run-live -q -s --tb=short --no-showlocals
```

Browser sign-in verifies each identity; the administrator also signs in for
read-only Power Platform environment lookup. Tokens stay in memory, separate
from normal kit sign-in caches. The test refuses to run over existing plans,
creates the ESS project only if absent, and archives only its own test plan.
Do not use a tenant where someone else is concurrently creating/activating plans.
No environment is provisioned, no ESS package is installed, and no tenant role
is granted. This is service/protocol evidence, **not** a conversational VS Code ER
or proof that `/setup` ran successfully.
