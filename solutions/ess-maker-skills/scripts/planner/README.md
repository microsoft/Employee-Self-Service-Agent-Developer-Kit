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
| `capture.py` | Observe-mode detectors that read what a Task produced from local kit state (the `/setup` → `environmentId` hand-off, from `.local/config.json`), plus `ask_artifact` for assignee-supplied (mode-b) outputs. |
| `research.py` | Table-of-Contents-first Learn research: parse a fetched `toc.json`, classify child/sibling links, relevance-select the pages to read within a budget, and extract role/output candidates from page text (`extract_signals`). Pure logic except `fetch_toc` / `fetch_page_text` (best-effort network). |
| `facts.py` + `planner_facts.json` | **Non-Learn** planning facts only — scenario *dependencies* (each with an explicit `source`) and a small recognition lexicon for `extract_signals`. This is **not** a business-scenario catalogue: scenarios come from the maker's description grounded in Learn (PM spec FR-1/FR-3). |
| `cli.py` | The command surface the skill invokes (`init`, `pull`, `set-context`, `add-system`, `add-scenario`, `add-scenario-dependency`, `check-deps`, `add-task`, `update-task`, `remove-task`, `assign`, `claim`, `set-state`, `task-brief`, `capture-setup`, `pin-output`, `mine`, `research`, `summary`, `validate`). A global `--store {local,mcp}` selects the persistence backend; `pull` fetches the plan from it (WeveNova with `--store mcp`) and writes the local `.md`. |
| `mcp_client.py` | A tiny stdlib MCP (Streamable-HTTP) client used by the `mcp` store to talk to the `weve-plan` server. `python -m planner.mcp_client --ping` verifies connectivity. |
| `plan_store.py` | The persistence seam: `LocalPlanStore` (`plan.json`) and `McpPlanStore` (WeveNova project plan over MCP). Both render `ESS-scenario-plan.md`. |
| `weve_mapping.py` | Pure bidirectional mapping between the local (camelCase) model and the WeveNova (PascalCase) project-plan/task entities. |

## Persistence backends (`--store`)

The Plan persists to one of two backends; the `ESS-scenario-plan.md` view is
generated from whichever holds the plan:

- **`local`** (default) — `workspace/plan/plan.json` on disk is the source of
  truth.
- **`mcp`** — a **WeveNova project plan** over the `weve-plan` MCP server is the
  **source of truth**. The planner *fetches* the plan for the project/agent being
  configured from WeveNova (context, outputs, status, acceptance criteria, tasks),
  *persists* task changes back to WeveNova, and *generates* `ESS-scenario-plan.md`
  from the WeveNova state. A local `workspace/plan/plan.json` is written only as a
  **cache/mirror** — never read as truth. Select it with `--store mcp` or
  `PLANNER_STORE=mcp`; `python scripts/planner/cli.py --store mcp pull` fetches and
  materializes the view (the resume entry point for a WeveNova-backed agent).

The `mcp` store reads the endpoint from the `weve-plan` server in
`.vscode/mcp.json` (git-ignored, per-environment), e.g.:

```json
{ "servers": { "weve-plan": { "type": "http",
  "url": "https://<tunnel>/mcp",
  "headers": { "X-Tunnel-Skip-AntiPhishing-Page": "true" } } } }
```

`PLANNER_MCP_URL` / `PLANNER_MCP_HEADERS` override the file (used by tests/CI).
Task create/update/delete is the writable path; plan-level context/outputs are
read-only over the current MCP surface (the store says so rather than silently
dropping a plan-level edit), and task writes require a non-terminal plan upstream.

## Local Plan location

The Plan is per-maker runtime state under `workspace/plan/` (git-ignored):

```
workspace/plan/plan.json               the structured Plan (source of truth)
workspace/plan/ESS-scenario-plan.md    editable human-readable view (reconciled back)
workspace/plan/research-context.json   cached Learn-research corpus
```

## Design & tests

- Dev plan: `dev-specs/adk-plan-generation/adk-plan-generation-dev-plan.md`.
- Design detail: `dev-specs/adk-plan-generation/ADK-Plan-Generation-and-Task-Capture-DevDesign.md`.
- Tests: `tests/planner/` (pure logic + local IO; no network, no cassettes).
  Run from the repo root: `python -m pytest tests/planner`. The MCP-backed store
  is unit-tested against an in-memory fake; opt-in live checks (`--run-live` with
  `PLANNER_MCP_URL` set) hit the real `weve-plan` server.

The local store requires nothing external — the Plan is authoritative on disk and
works with WeveNova, tenant inventory, and a roles source all absent. The `mcp`
store adds an optional WeveNova-backed backend without changing that default.
