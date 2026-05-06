# Solutions

This folder contains the individual solutions in the Employee Self-Service Agent Developer Kit monorepo.

A **solution** is a self-contained, customer-runnable artifact: a VS Code workspace, a CLI, an evaluation harness, etc. Each solution lives in its own subfolder with its own README, dependencies, and license header. Solutions are independently versioned and installable.

For reference content (sample topics, template configs, evaluation test sets), see [`samples/`](../samples/) at the repository root - peer to `solutions/`.

## Available solutions

| Solution | Description |
|----------|-------------|
| [`ess-maker-skills/`](ess-maker-skills/) | VS Code workspace toolkit. Customize and deploy your ESS agent using GitHub Copilot. |

## Adding a new solution

New solutions are scoped additions, not free-for-alls. See [CONTRIBUTING.md](../CONTRIBUTING.md) at the repo root for the contribution model and the scope-management policy that governs whether a new solution is in or out of the original OSS Portal release scope (review #55042).

## Pointers

- Repo root: [README.md](../README.md)
- Reference content: [`samples/`](../samples/)
- Contribution guide: [CONTRIBUTING.md](../CONTRIBUTING.md)
- Support model: [SUPPORT.md](../SUPPORT.md)
- Security reporting: [SECURITY.md](../SECURITY.md)