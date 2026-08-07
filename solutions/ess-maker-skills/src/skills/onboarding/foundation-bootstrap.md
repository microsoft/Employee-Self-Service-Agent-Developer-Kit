<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Foundation Workspace Bootstrap

Use this path only after foundation setup has completed.

Load the locked environment:

```text
python scripts/setup_state.py show --view report
```

Set ENV_URL to `environment.tenant_endpoint`, stripping any trailing slash.
Create `workspace/onboarding/tasks.md` from `src/skills/onboarding/tasks.md`
only when it is missing. Do not display that checklist.

Create `.vscode/mcp.json` with the locked endpoint:

```json
{
  "servers": {
    "Dataverse": {
      "type": "http",
      "url": "{ENV_URL}/api/mcp"
    }
  }
}
```

Do not recheck environment selection, roles, Dataverse provisioning, or the
Allowed MCP Client prerequisite. Foundation setup already completed them.

Set FOUNDATION_REUSED to true, then read
`src/skills/onboarding/step1b.md` and follow it. Preserve
FOUNDATION_REUSED through `src/skills/onboarding/step2.md`.
