<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Foundation Workspace Bootstrap

Use this path only after foundation setup has completed.

Load the locked environment:

```text
python scripts/setup_state.py show --view report
```

Set ENV_URL to `environment.tenant_endpoint`, stripping any trailing slash.
Set ENVIRONMENT_ID to `environment.id`; keep both together through extraction.
Create `workspace/onboarding/steps.md` from `src/skills/onboarding/steps.md`
only when it is missing. Do not display that checklist.

Merge the committed server defaults and the locked Dataverse endpoint:

```text
python scripts/mcp_config.py materialize-defaults
python scripts/mcp_config.py configure dataverse --environment-url "{ENV_URL}"
```

Never replace `.vscode/mcp.json` with a Dataverse-only object. These commands
preserve `ess-planner`, `ess-landing-page-config`, other servers, and overrides.
If either fails, report the error; do not announce successful MCP setup.

Do not recheck environment selection, roles, Dataverse provisioning, or the
Allowed MCP Client prerequisite. Foundation setup already completed them.

Set FOUNDATION_REUSED to true, then read
`src/skills/onboarding/step1b.md` and follow it. Preserve
FOUNDATION_REUSED through `src/skills/onboarding/step2.md`.
