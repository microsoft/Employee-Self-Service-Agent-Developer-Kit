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
| `research.py` | Table-of-Contents-first Learn research: parse a fetched `toc.json`, classify child/sibling links, relevance-select the pages to read within a budget, and extract role/output candidates from page text (`extract_signals`). Pure logic except `fetch_toc` / `fetch_page_text` (best-effort network). |
| `facts.py` + `planner_facts.json` | **Non-Learn** planning facts only — scenario *dependencies* (each with an explicit `source`) and a small recognition lexicon for `extract_signals`. This is **not** a business-scenario catalogue: scenarios come from the maker's description grounded in Learn (PM spec FR-1/FR-3). |
| `cli.py` | The command surface the skill invokes (`init`, `ingest-upload`, `gaps`, `set-context`, `add-system`, `add-scenario`, `add-scenario-dependency`, `check-deps`, `add-task`, `update-task`, `remove-task`, `assign`, `claim`, `set-state`, `task-brief`, `capture-setup`, `capture-discover`, `pin-output`, `mine`, `research`, `summary`, `validate`). `ingest-upload` builds a whole plan from a maker-authored uploaded plan (normalized JSON) in one atomic write and reports the remaining gaps; `gaps` lists the intent slots a plan still lacks. `capture-discover` summarizes a `/discover` run onto the plan's tenant-inventory task. |
| `review.py` | CSV export and read-only review proposals with stable task IDs, version checks, and spreadsheet-formula escaping. No imported review applies edits automatically. |

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
(`environmentPinned` and `agentPinned`). `firstRunSetupTaskId` identifies a ready
provisioning task without changing the workspace-capture `setupTaskId`.

## Local, shared, and confirmed are different states

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

- Tests: `tests/planner/` (pure logic + local IO; no network, no cassettes).
  Run from the repo root: `python -m pytest tests/planner`.

Nothing here requires WeveNova, tenant inventory, or a roles source — the Plan
is authoritative on disk and works with all three absent.
