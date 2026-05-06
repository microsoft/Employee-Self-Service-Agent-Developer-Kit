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

- **Dependabot alerts** — review and merge weekly Dependabot PRs (Python and GitHub Actions); resolve dependency security alerts promptly.
- **CodeQL alerts** — triage CodeQL findings on the default branch on each push.
- **Dependency hygiene** — bump dependencies to the latest stable versions at minimum every 6 months.
- **Vulnerability reports** — security issues are routed to the Microsoft Security Response Center (MSRC) per [SECURITY.md](SECURITY.md). Do **not** open public GitHub issues for vulnerabilities.
- **Private fix process** — for confirmed vulnerabilities, follow the [Microsoft Open Source private fix process](https://docs.opensource.microsoft.com/security/playbook-security/).

### Scope management

This project's release was registered with the Microsoft Open Source Office (OSS Portal review [55042](https://dev.azure.com/ossmsft/Reviews/_workitems/edit/55042)) under a defined scope: **a VS Code workspace toolkit and reference content for customizing Employee Self-Service (ESS) agents using GitHub Copilot.**

If a future change would expand the project beyond that scope — for example:

- Adding **non-open-source Microsoft code** to the repo, or
- Adding **functionality outside the original approval scope** (a new product surface, a service component, packaged/redistributed binaries, etc.) —

then maintainers **must file a new release request** in the [Open Source Portal](https://repos.opensource.microsoft.com/release) before merging that change. Routine bug fixes, dependency updates, documentation improvements, new prompt files, new sample topics, and additional connector reference content are in-scope and do not require a new release request.

## Privacy

This toolkit:

- **Collects no telemetry.** Microsoft does not receive any data from your use of this kit. There is no telemetry SDK, no usage reporting, no crash reporting, and no opt-in/opt-out switch because there is nothing to switch off.
- **Stores no data on Microsoft systems.** All data flows are between your local VS Code workspace and your own Power Platform / Copilot Studio tenant.
- **Processes no personal data on Microsoft's behalf.** Any customer data you author or test against (topic content, evaluation prompts, sample employee records) stays in your tenant under your existing Copilot Studio / Power Platform license terms.

For privacy questions about Copilot Studio, Power Platform, or GitHub Copilot themselves, see the [Microsoft Privacy Statement](https://privacy.microsoft.com).

## Service dependencies

The toolkit's scripts call the following Microsoft services on your behalf. Every call goes from your machine to your own tenant under your existing license — no data is sent to Microsoft beyond standard authentication exchanges with the services listed below.

| Service | Purpose | Auth | Tenant |
|---|---|---|---|
| Power Platform / Dataverse Web API | Read agent components, push template config records | MSAL (delegated, your identity) | Your Power Platform environment |
| Copilot Studio (via Dataverse) | Read/update topics, push changes | MSAL (delegated) | Your Copilot Studio environment |
| ServiceNow REST API (optional) | Topic integration testing | User-provided OAuth / basic | Your ServiceNow tenant |
| Workday SOAP / REST API (optional) | Topic integration testing | User-provided | Your Workday tenant |
| GitHub Copilot (in VS Code) | LLM that reads prompt and instruction files and generates content | GitHub Copilot license | N/A — GitHub Copilot service |

The toolkit does not call any other Microsoft services.

## Validating your changes

This is a sample/learning toolkit with no formal unit-test suite — the inputs (Copilot Studio topic YAML, Power Automate JSON) are validated end-to-end by `/flightcheck` rather than via unit tests. Before opening a PR:

### 1. Lint and syntax check (matches CI)

```pwsh
ruff check scripts/ src/mcp/
python -m compileall -q scripts/ src/mcp/
```

GitHub Actions runs the same commands on every PR (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

### 2. Smoke test the affected command

If your change touches a Copilot Chat command (`/create`, `/update`, `/flightcheck`, etc.), run that command in VS Code against a **non-production** Copilot Studio environment and confirm:

- It produces the expected file output
- `/flightcheck` returns no errors on the resulting topic / workflow
- `/scan` reports no regressions

### 3. CodeQL

CodeQL runs on every PR (see [`.github/workflows/codeql.yml`](.github/workflows/codeql.yml)). Wait for the check to pass. If CodeQL flags an issue, address it or document why it is a false positive in the PR description.

### 4. CLA bot

The Microsoft CLA bot will comment on your PR if you are an external contributor. You must accept the CLA before the PR can be merged.

### 5. Code quality

- **No fabricated URLs.** Every URL in code (doc links, remediation messages, comments, README references) must point to a page you have confirmed exists. See [`.github/copilot-instructions.md`](.github/copilot-instructions.md#no-fabricated-urls) → "No fabricated URLs" for the verification rule.
