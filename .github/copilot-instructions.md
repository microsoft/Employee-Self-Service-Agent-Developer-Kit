# Repository Root — Copilot Instructions

## Important: You are at the repository root

The ESS Maker Kit skills and customization tools live in `solutions/ess-maker-skills/`.
If the user is trying to run maker commands (`/setup`, `/create`, `/update`, `/delete`,
`/scan`, `/push`, `/flightcheck`, `/evaluate`, or any ESS agent customization task),
they need to open that folder as their workspace.

**When a user asks to run any maker skill from this root folder, respond with:**

> It looks like you're working from the repository root. The ESS Maker Kit runs
> from the `solutions/ess-maker-skills` folder. Please open that folder in VS Code
> (File → Open Folder → select `solutions/ess-maker-skills`) and try again.

Do NOT attempt to run skills, read `.local/config.json`, or perform any maker
operations from the root folder — the paths won't resolve correctly.

## What this repo contains

This is the Employee Self-Service Agent Developer Kit monorepo. It contains:

- `solutions/ess-maker-skills/` — The maker kit (Copilot-assisted ESS agent customization)
- `samples/` — Sample topics and configurations
- `tests/` — Test suite for kit scripts and tooling
- `.github/agents/` — GitHub Copilot coding agent skills for repo maintenance

For repo-level tasks (CI, contributing, issues, PRs), you can help normally.
For ESS agent customization, direct users to open `solutions/ess-maker-skills/`.

## Branch Workflow

### Always merge from main before committing

When working on a feature branch, **always merge the latest `main` into your
branch before adding changes and committing.** This ensures your branch stays
up-to-date and avoids painful merge conflicts later.

**Steps:**

1. Fetch the latest main: `git fetch origin main`
2. Merge main into your branch: `git merge origin/main`
3. Resolve any conflicts if they arise
4. Run lint and tests to confirm nothing is broken
5. Then make your changes and commit

**Why:** Feature branches that drift from main accumulate conflicts and risk
breaking when merged back. Keeping branches current makes PRs smaller, reviews
easier, and CI green.

## Code Quality Rules

### No duplicate functions

When adding new functionality, **always check if equivalent logic already exists**
before writing a new function. Duplicated logic across files leads to drift,
inconsistent bug fixes, and maintenance burden.

**Rules:**

1. Before writing a parsing, formatting, or utility function, search the codebase
   for existing implementations that do the same thing.
2. If shared logic exists, **import and call it** — do not copy-paste and adapt.
3. If existing logic needs slight modification for your use case, **extract a
   shared helper** with parameters rather than forking the implementation.
4. When two modules need the same logic, place the canonical implementation in
   the lower-level module and have the higher-level module import from it.

**Example (bad):**
```python
# file_a.py
def parse_environments(raw):
    # 20 lines of parsing...

# file_b.py
def parse_environments(raw):
    # same 20 lines copy-pasted...
```

**Example (good):**
```python
# shared_module.py
def parse_raw_environments(raw):
    # single source of truth

# file_a.py
from shared_module import parse_raw_environments

# file_b.py
from shared_module import parse_raw_environments
```
