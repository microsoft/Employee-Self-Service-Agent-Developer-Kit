---
mode: agent
description: "Type Enter to set up your ESS customization environment"
---

# Setup

Run this command without showing it to the user:

```powershell
python -m pip install -r scripts/requirements.txt
```

If dependency installation fails, show the error and stop.

Run this command without showing it to the user:

```powershell
python scripts/mcp_config.py materialize-defaults
```

If default MCP materialization fails, show the exact error and stop. The command
preserves user-configured servers and locally customized default definitions.

Read `src/skills/foundation-setup/SKILL.md` and follow it.

Do not route directly to `src/skills/onboarding/SKILL.md`. Foundation setup owns
environment selection, prerequisites, starter installation, and readiness. It
invokes onboarding itself only after the environment is locked and the
foundation is ready.
