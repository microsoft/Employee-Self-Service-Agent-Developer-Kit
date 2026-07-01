# TASK-001 — Repository Scaffold

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-001                  |
| Workstream | 0 — Repository Foundation |
| Status     | DONE                      |
| Consumes   | —                         |

## Description

Create the repository structure defined in
`03_ENGINEERING/REPOSITORY_STRUCTURE.md`. This establishes the frozen folder
layout, the developer experience, and the build configuration. No business
logic is introduced.

## Acceptance Criteria

- [ ] The `src/` layout exists exactly as specified in
  `03_ENGINEERING/REPOSITORY_STRUCTURE.md` (`constants/`, `core/`, `modules/`,
  `service/`, `output/`, and `service/mtk_orchestrator.py`).
- [ ] The `tests/` layout exists (`unit/`, `integration/`, `golden/`, `e2e/`).
- [ ] The toolkit-root `output/` folder is present (generated, gitignored, kept
  via `.gitkeep`) for per-execution session bundles.
- [ ] `scripts/`, `README.md`, and `pyproject.toml` are present.
- [ ] No business logic or migration transformation is implemented.

## Deliverables

- Folder scaffold
- Source layout
- Test layout
- `output/` folder (session bundles)
- Scripts folder
- README
- `pyproject.toml`

## References

- 03_ENGINEERING/REPOSITORY_STRUCTURE.md
