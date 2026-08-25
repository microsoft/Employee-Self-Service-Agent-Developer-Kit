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

- **Collects pseudonymous usage telemetry** (enabled by default) to help us understand which capabilities are used and where they fail, so we can improve the product. What is emitted is a random per-install `instance_id`, the tenant GUID and organization display name (OII, not developer identity), capability names (e.g. `setup`, `connect`, `topic_create`), FlightCheck run outcomes, latency, and scrubbed error codes. **No developer/user identifier, agent content, credentials, prompts, or personal data is collected.** A one-time notice is printed the first time you run a CLI command. See [Telemetry & Privacy](solutions/ess-maker-skills/README.md#telemetry--privacy) for the full data model and event catalog.
- **Opt out any time** via either of:
  - `python scripts/adk_telemetry.py off` (from `solutions/ess-maker-skills`), or
    - the `ESS_ADK_TELEMETRY` environment variable set to `off` (or `0` / `false`). Set it in your shell before running any ADK command — e.g. `export ESS_ADK_TELEMETRY=off` (bash/zsh), `$env:ESS_ADK_TELEMETRY = "off"` (PowerShell), or `set ESS_ADK_TELEMETRY=off` (cmd.exe). Adding it to your shell profile (`~/.bashrc`, `~/.zshrc`, PowerShell `$PROFILE`) or to your CI environment makes it persist. The env-var overrides the config-file setting.
- **Stores no customer data on Microsoft systems by default.** Data flows for authoring and testing (topic content, sample employee records) go between your local VS Code workspace and your own Power Platform / Copilot Studio tenant under your existing license terms.
- **Optional eval-quality judge sends eval content to GitHub Copilot.** If you run `scripts/evaluate_evals.py`, the evaluation YAML you're grading (test-case inputs and expected outputs) is sent to `api.githubcopilot.com` for LLM scoring under your GitHub Copilot license and its data-use terms. Do not run this script on evaluation sets you are not licensed to share with GitHub Copilot. Skipping the script skips this data flow entirely.
- **Processes no personal data on Microsoft's behalf.** The telemetry above is product-improvement usage data, not customer content — no customer data (Copilot Studio topics, workflow definitions, employee records) is ever transmitted to Microsoft by this toolkit outside of what you explicitly push to your own tenant or send to the optional judge above.

For privacy questions about Copilot Studio, Power Platform, or GitHub Copilot themselves, see the [Microsoft Privacy Statement](https://privacy.microsoft.com).

## Service dependencies

The toolkit's scripts call the following services on your behalf. With telemetry enabled and the optional eval judge skipped, every call is either against your own tenant under your existing license or against Microsoft's Aria/1DS collector for the pseudonymous telemetry described under [Privacy](#privacy). The optional `evaluate_evals.py` judge additionally sends eval YAML content to GitHub Copilot under your Copilot license.

| Service | Purpose | Auth | Tenant |
|---|---|---|---|
| Power Platform / Dataverse Web API | Read agent components, push template config records | MSAL (delegated, your identity) | Your Power Platform environment |
| Copilot Studio (via Dataverse) | Read/update topics, push changes | MSAL (delegated) | Your Copilot Studio environment |
| Power Platform API (`api.powerplatform.com`) | Read licensing/billing policies and PayG environment linkage during `/flightcheck` prerequisite checks | MSAL (delegated) | Your Power Platform tenant |
| BAP / Power Apps / Power Automate APIs (`api.bap.microsoft.com`, `api.powerapps.com`, `api.flow.microsoft.com`) | Enumerate environments, inspect flow runs, and validate connector wiring during `/flightcheck` | MSAL (delegated) | Your Power Platform tenant |
| Azure Resource Manager (`management.azure.com`) | Read subscription state and Consumption budgets for the PayG-linked subscription during `/flightcheck` PRE-005 | MSAL (delegated) | Your Azure subscription |
| Microsoft Graph (optional) | Resolve tenant display name for telemetry. Tries `/organization` under `Organization.Read.All` (silent); falls back to `/me?$select=companyName`, which reads the **signed-in user's Entra profile attribute** (admin-populated in many enterprise tenants) — not tenant metadata. `""` on any failure. | MSAL (delegated) | Your Entra tenant |
| GitHub Copilot API (`api.githubcopilot.com`, optional) | Eval-set quality judging via `scripts/evaluate_evals.py`. Sends the eval YAML being graded to the Copilot chat completions endpoint under your Copilot license. Not called by any other script. | `gh auth token` | GitHub Copilot service |
| Aria / 1DS OneCollector | Pseudonymous usage telemetry (see [Privacy](#privacy); opt out with `python scripts/adk_telemetry.py off` or `ESS_ADK_TELEMETRY=off`) | Instrumentation key, no user auth | N/A — Microsoft telemetry service |
| ServiceNow REST API (optional) | Topic integration testing | User-provided OAuth / basic | Your ServiceNow tenant |
| Workday SOAP / REST API (optional) | Topic integration testing | User-provided | Your Workday tenant |
| GitHub Copilot (in VS Code) | LLM that reads prompt and instruction files and generates content | GitHub Copilot license | N/A - GitHub Copilot service |

Aside from the services listed above, the toolkit does not call other Microsoft or third-party services on your behalf.

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

### 6. Minimal, surgical changes

When modifying a file to add new functionality, **only change what is necessary for the feature**. Do not:

- Rewrite or rephrase existing docstrings, comments, or variable names that are unrelated to your change
- Replace Unicode characters (e.g., `─`) with ASCII equivalents unless the change is specifically about encoding compatibility
- Refactor surrounding code (rename variables, reorder functions, change formatting) unless it's required for your feature to work
- Change function signatures (e.g., removing `required=True` from argparse) unless the new feature explicitly needs it

Each PR should be reviewable by diffing only the lines that matter for the stated goal. Unrelated cosmetic changes create noise, increase merge conflicts, and make `git blame` less useful.

### 7. Clean commits — review before you push

Before committing, **always review what's staged** to avoid accidentally including unrelated files:

- Run `git status` and `git diff --cached` before every commit
- Never use `git add -A` or `git add .` without inspecting untracked files first — prefer `git add <specific-files>`
- Ensure local working files (task trackers, scratch notes, editor artifacts) are covered by `.gitignore` or excluded manually
- If an accidental file slips through, remove it in the same PR — don't leave orphan files for others to clean up

Accidental commits pollute history, can leak internal workflows, and waste reviewer time on irrelevant diffs.
