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
