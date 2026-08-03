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
| `plan_model.py` | The Plan document — schema, atomic read/write, validation, `summary.md` render, and the Flow-2 (grouped-by-role) discovery query. Shaped to match the WeveNova `Plan`/`Task` entities so a future sync is a field copy. |
| `roles.py` | The **absent-safe** roles-source seam (`RoleDirectory` / `RoleSource`). With no backing source wired, validation degrades to a well-formed-id check and enumerations return empty so the skill falls back gracefully. `StaticRoleSource` is a trivial in-memory implementation for demos/tests. |
| `capture.py` | Observe-mode detectors that read what a Task produced from local kit state (the `/setup` → `environmentId` hand-off, from `.local/config.json`), plus `ask_artifact` for assignee-supplied (mode-b) outputs. |
| `research.py` | Table-of-Contents-first Learn research: parse a fetched `toc.json`, classify child/sibling links, relevance-select the pages to read within a budget, and extract role/output candidates from page text (`extract_signals`). Pure logic except `fetch_toc` / `fetch_page_text` (best-effort network). |
| `facts.py` + `planner_facts.json` | **Non-Learn** planning facts only — scenario *dependencies* (each with an explicit `source`) and a small recognition lexicon for `extract_signals`. This is **not** a business-scenario catalogue: scenarios come from the maker's description grounded in Learn (PM spec FR-1/FR-3). |
| `cli.py` | The command surface the skill invokes (`init`, `set-context`, `add-system`, `add-scenario`, `add-scenario-dependency`, `check-deps`, `add-task`, `assign`, `claim`, `set-state`, `task-brief`, `capture-setup`, `pin-output`, `mine`, `research`, `summary`, `validate`). |

## Local Plan location

The Plan is per-maker runtime state under `workspace/plan/` (git-ignored):

```
workspace/plan/plan.json               the structured Plan (source of truth)
workspace/plan/summary.md              generated human-readable view
workspace/plan/research-context.json   cached Learn-research corpus
```

## Design & tests

- Design: `dev-specs/adk-plan-generation/ADK-Plan-Generation-and-Task-Capture-DevDesign.md`.
- Tests: `tests/planner/` (pure logic + local IO; no network, no cassettes).
  Run from the repo root: `python -m pytest tests/planner`.

Nothing here requires WeveNova, tenant inventory, or a roles source — the Plan
is authoritative on disk and works with all three absent.
