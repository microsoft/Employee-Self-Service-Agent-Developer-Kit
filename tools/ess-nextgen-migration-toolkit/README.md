# ESS NextGen Migration Toolkit

Migrates **ESS Custom Engine Agents (CA)** to **Declarative Agents (DA)**.

This is the buildable toolkit. The specifications that govern it (the source of
truth) live separately under
[`dev-specs/ess-nextgen-migration-toolkit/`](../../dev-specs/ess-nextgen-migration-toolkit/).
This repository follows **Specification-Driven Development (SDD)**: the
specifications define the system, and this code is one implementation of them.

> **Working here?** Read [`AGENTS.md`](AGENTS.md) first, then the specification
> orchestrator at
> [`dev-specs/ess-nextgen-migration-toolkit/AGENTS.md`](../../dev-specs/ess-nextgen-migration-toolkit/AGENTS.md).

## Repository layout

```text
src/
    constants/       Shared constants
    core/
        auth/        Authentication (token_provider.py)
        logging/     Diagnostics framework
        models/      Canonical domain models
        outbound/    Dataverse client (dataverse_client.py)
        pipeline/    Pipeline engine
        utils/       Generic helpers
        modules/
            preprocessing/
            migration/      migration_pipeline.py, steps/
            postprocessing/
    service/         Orchestration (mtk_orchestrator.py)
debug/               Generated, gitignored output
    logs/
    reports/
tests/
    unit/            Mirror src/
    integration/     Dataverse interactions
    golden/          Deterministic migration outputs
    e2e/             Complete migration workflows
scripts/             Developer and CI scripts (mtk dispatcher, .sh and .ps1)
pyproject.toml       Project metadata + tool config (PEP 621, hatchling)
uv.lock              Locked, hashed dependency graph (source of truth)
.python-version      Pinned interpreter for reproducible environments
```

The layout is **frozen** — see `dev-specs/ess-nextgen-migration-toolkit/03_ENGINEERING/REPOSITORY_STRUCTURE.md`.
New capabilities are added by extending existing layers (new Pipeline Steps,
service capabilities, Domain Models), not by reorganizing the repository.

## Getting started

The toolkit uses a **locked, reproducible** environment so that every customer
and contributor runs the exact same dependency versions. Determinism is a core
project principle — see `dev-specs/.../00_META/INVARIANTS.md`.

The setup needs **no pre-installed Python** and **no separate package manager** —
`uv` provisions both.
[`uv`](https://docs.astral.sh/uv/) is a self-contained binary; it provisions the
pinned interpreter (`.python-version`) and the locked dependency graph
(`uv.lock`) itself.

### One-command setup

The toolkit exposes a **single command, `mtk`** (migration tool kit). Run it
from the **monorepo root** via the forwarder (`./mtk.sh`, or `.\mtk.ps1` on
Windows); the dispatcher changes into the toolkit directory implicitly, so it is
cwd-independent and all logic lives in `scripts/mtk.*`. `mtk start` is fully
self-sufficient: it installs `uv` if missing, has `uv` download the pinned
Python (a managed, standalone CPython — no admin rights, no system Python),
creates the project virtual environment (`.venv`) with the exact locked
versions, then runs the toolkit. `uv sync` manages `.venv` automatically — there
is no manual venv step.

```bash
# From the monorepo root — no prerequisites:
./mtk.sh start          # provision runtime env + run (what customers run)
./mtk.sh start --dev    # provision runtime + dev tooling, then run (contributors)
```

On Windows use `.\mtk.ps1 start` (add `-Dev` for tooling).

> **Contributors:** use `--dev`. Plain start provisions a *runtime-only*
> environment (no `ruff`/`mypy`/`pytest`), so `uv run ruff` will fail after it.
> Run `./mtk.sh start --dev` to get the quality-gate tooling.

> **`uv: command not found`?** After a fresh install `uv` lives in
> `~/.local/bin`, which may not be on your shell `PATH` yet. Add it with
> `export PATH="$HOME/.local/bin:$PATH"` (or `uv python update-shell`), or just
> activate the env and call tools directly (`source .venv/bin/activate`).

If `uv` is already installed, the equivalent direct commands are:

```bash
uv python install     # provision the pinned Python (from .python-version)
uv sync --no-dev      # runtime only — creates .venv (what customers run)
uv sync               # with dev tooling — the "dev" group is included by default
uv run pytest         # run anything inside the locked env, no activation needed
```

> **Why `uv run ruff` "just works":** dev tooling is a PEP 735 *dependency-group*
> (`[dependency-groups] dev` in `pyproject.toml`), which `uv` includes by default
> for both `uv sync` and `uv run`. If it were an optional *extra* instead,
> `uv run ruff` would re-sync without the extra and prune the tool first.

### Staying up to date: `mtk refresh`

`mtk refresh` fast-forwards your branch from the remote (customers run this on
`main`), then runs `start` — re-provisioning the **runtime** environment to the
updated lockfile and launching the toolkit. In other words, `refresh` = `git
pull` then `start`:

```bash
./mtk.sh refresh          # pull latest, then start (re-provision runtime + run)
```

`refresh` is the customer update path, so it always provisions a runtime-only
environment. Contributors who want their dev tooling back after a refresh run
`./mtk.sh start --dev`.

It pulls fast-forward-only, so it never rewrites local work.

> **Dependency hygiene:** `uv.lock` is the single source of truth. After
> changing dependencies in `pyproject.toml`, run `uv lock` and commit the
> updated `pyproject.toml` + `uv.lock` together.

## Development workflow

Run gates either by activating the venv (PATH-independent) or via `uv run`:

```bash
source .venv/bin/activate   # then run tools directly: ruff check . | mypy src | pytest
```

```bash
uv run pytest          # Run the test suite
uv run ruff check .    # Lint (includes the no-print rule)
uv run ruff format .   # Format
uv run mypy src        # Type-check
```

### Quality gates run automatically on commit (toolkit-scoped)

`mtk start --dev` installs a **pre-commit git hook for you** (one-time, per
clone). After that, `ruff` + `mypy` run **automatically on every `git commit`**
— you don't run anything by hand. A commit that fails lint or type-checking is
blocked.

This toolkit is **nested inside a larger monorepo** (the repository's `.git`
lives at the repo root and is shared by every solution), so the hook is
**hard-scoped**: every gate is restricted to
`tools/ess-nextgen-migration-toolkit/` and is a **no-op for commits elsewhere**
in the monorepo. It also uses the **locked** tool versions (`uv.lock`), so it
matches `uv run` and CI exactly — no version drift.

You can also run the gates on demand:

```bash
uv run pre-commit run --all-files   # ruff + ruff-format + mypy, toolkit only
```

> The hook config (`.pre-commit-config.yaml`) must be committed OR staged for the hook to
> run; pre-commit refuses to operate on an unstaged config.

## Contributing

1. Resolve your task in `dev-specs/.../04_EXECUTION/TASKS.md` (`TASK-XXX`).
2. Read the task's `References` specifications and the Constitution
   (`00_META/PROJECT.md`, `INVARIANTS.md`, `VOCABULARY.md`).
3. Implement within the correct architectural layer; add tests.
4. Update `TASKS.md` status and `04_EXECUTION/CHANGELOG.md`.
