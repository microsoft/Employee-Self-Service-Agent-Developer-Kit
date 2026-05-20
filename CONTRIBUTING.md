# Contributing

This project welcomes contributions and suggestions. Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need to
provide a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the
instructions provided by the bot. You will only need to do this once across all repositories using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Pre-PR Checklist (REQUIRED)

Before opening a pull request, confirm each of the following. The PR template
([`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)) will
ask you to tick these off — incomplete PRs may be sent back for cleanup.

- [ ] **Rebased on latest `main`** — `git fetch origin && git rebase origin/main`
- [ ] **PR diff shows ONLY files you intended to change** — review the "Files changed" tab; no accidental deletions or unrelated edits
- [ ] **Local lint / tests pass** — `pytest tests/ -q` clean, or note in the PR description why end-to-end testing wasn't possible (e.g., no tenant access)
- [ ] **No references to files outside the repo** — header comments and docs should not point to internal source-of-truth files
- [ ] **Defaults match repo conventions** — output paths default to `workspace/flightcheck/...`; risky operations (writes, deletions, destructive API calls) are opt-in via explicit flags
- [ ] **FlightCheck integration** — new checks wired into a scope in `solutions/ess-maker-skills/scripts/flightcheck/cli.py` (`SCOPE_MAP` and `FULL_SCOPE`); new tests live under `tests/flightcheck/checks/`
- [ ] **API tier registry honored** — every new external API call references the tier assigned in `tests/fixtures/cassettes/INDEX.md`; any new tier rows added there with rationale (see [`solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md`](solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md))
- [ ] **Docs updated** — relevant `README.md` / `AGENTS.md` updated to mention the new check, scope, or behavior change

> **Why "rebased on latest `main`" matters:** Stale branches can silently
> delete files added after your branch was cut. We've already caught one
> case of this in a sibling repo. GitHub branch protection enforces this
> rule automatically.

## Maintenance

### Security maintenance

This is a non-production sample/learning toolkit. Maintainers commit to:

- **Dependabot alerts** - Dependabot opens weekly PRs for Python and GitHub Actions. Maintainers acknowledge new alerts within **5 business days** and merge or assign a fix branch within **15 business days** for High/Critical severity, **30 business days** for Medium/Low.
- **CodeQL alerts** - CodeQL runs on every push and PR to the default branch. Maintainers triage new alerts within **5 business days**: confirm/dismiss false positives, file an issue for confirmed findings, and aim to land a fix within **30 business days** for High/Critical.
- **Dependency hygiene** - Dependabot is the primary cadence (weekly). The 6-month floor only applies to dependencies Dependabot does not track (e.g., pinned tooling versions in docs); for those, maintainers refresh at least every 6 months.
- **Vulnerability reports** - security issues are routed to the Microsoft Security Response Center (MSRC) per [SECURITY.md](SECURITY.md). Do **not** open public GitHub issues for vulnerabilities.
- **Private fix process** - for confirmed vulnerabilities, follow the [Microsoft Open Source private fix process](https://docs.opensource.microsoft.com/security/playbook-security/).

### Scope management

This project's release was registered with the Microsoft Open Source Office (OSS Portal review [55042](https://dev.azure.com/ossmsft/Reviews/_workitems/edit/55042)) under a defined scope: **a VS Code workspace toolkit and reference content for customizing Employee Self-Service (ESS) agents using GitHub Copilot.**

If a future change would expand the project beyond that scope - for example:

- Adding **non-open-source Microsoft code** to the repo, or
- Adding **functionality outside the original approval scope** (a new product surface, a service component, packaged/redistributed binaries, etc.) -

then maintainers **must file a new release request** in the [Open Source Portal](https://repos.opensource.microsoft.com/release) before merging that change. Routine bug fixes, dependency updates, documentation improvements, new prompt files, new sample topics, and additional connector reference content are in-scope and do not require a new release request.

## Privacy

This toolkit:

- **Collects no telemetry.** Microsoft does not receive any data from your use of this kit. There is no telemetry SDK, no usage reporting, no crash reporting, and no opt-in/opt-out switch because there is nothing to switch off.
- **Stores no data on Microsoft systems.** All data flows are between your local VS Code workspace and your own Power Platform / Copilot Studio tenant.
- **Processes no personal data on Microsoft's behalf.** Any customer data you author or test against (topic content, evaluation prompts, sample employee records) stays in your tenant under your existing Copilot Studio / Power Platform license terms.

For privacy questions about Copilot Studio, Power Platform, or GitHub Copilot themselves, see the [Microsoft Privacy Statement](https://privacy.microsoft.com).

## Service dependencies

The toolkit's scripts call the following Microsoft services on your behalf. Every call goes from your machine to your own tenant under your existing license - no data is sent to Microsoft beyond standard authentication exchanges with the services listed below.

| Service | Purpose | Auth | Tenant |
|---|---|---|---|
| Power Platform / Dataverse Web API | Read agent components, push template config records | MSAL (delegated, your identity) | Your Power Platform environment |
| Copilot Studio (via Dataverse) | Read/update topics, push changes | MSAL (delegated) | Your Copilot Studio environment |
| ServiceNow REST API (optional) | Topic integration testing | User-provided OAuth / basic | Your ServiceNow tenant |
| Workday SOAP / REST API (optional) | Topic integration testing | User-provided | Your Workday tenant |
| GitHub Copilot (in VS Code) | LLM that reads prompt and instruction files and generates content | GitHub Copilot license | N/A - GitHub Copilot service |

The toolkit does not call any other Microsoft services.

## Validating your changes

This is a sample/learning toolkit with no formal unit-test suite - the inputs (Copilot Studio topic YAML, Power Automate JSON) are validated end-to-end by `/flightcheck` rather than via unit tests. Before opening a PR:

### 1. Lint and syntax check (matches CI)

Run from the repository root so the paths match what CI runs:

```pwsh
ruff check solutions/ess-maker-skills/scripts/ solutions/ess-maker-skills/src/mcp/
python -m compileall -q solutions/ess-maker-skills/scripts/ solutions/ess-maker-skills/src/mcp/
```

GitHub Actions runs the same commands on every PR (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). Lint failures are blocking - fix them before requesting review.

### 2. Smoke test the affected command

If your change touches a Copilot Chat command (`/create`, `/update`, `/flightcheck`, etc.), run that command in VS Code against a **non-production** Copilot Studio environment and confirm:

- It produces the expected file output
- `/flightcheck` returns no errors on the resulting topic / workflow
- `/scan` reports no regressions

### 3. CodeQL

CodeQL runs on every PR. See the [repo's CodeQL alerts](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/security/code-scanning) for current state. Wait for the check to pass. If CodeQL flags an issue, address it or document why it is a false positive in the PR description.

### 4. CLA bot

The Microsoft CLA bot will comment on your PR if you are an external contributor. You must accept the CLA before the PR can be merged.

### 5. Code quality

- **No fabricated URLs.** Every URL in code (doc links, remediation messages, comments, README references) must point to a page you have confirmed exists. See [solutions/ess-maker-skills/.github/copilot-instructions.md#no-fabricated-urls](solutions/ess-maker-skills/.github/copilot-instructions.md#no-fabricated-urls) for the verification rule.
