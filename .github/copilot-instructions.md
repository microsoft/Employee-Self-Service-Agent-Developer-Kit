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
