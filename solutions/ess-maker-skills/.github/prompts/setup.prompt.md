---
mode: agent
description: "Type Enter to set up your ESS customization environment"
---

# Setup

Read `src/skills/foundation-setup/SKILL.md` first. Follow its **Command runtime**
instructions to change to the kit root and resolve one working Python launcher
before running any Python command. A failed launcher candidate is discovery
evidence, not a setup failure; continue through the documented fallbacks and
stop only if none works.

Using the resolved launcher in place of `{PYTHON}`, run this command without
showing it to the user:

```powershell
{PYTHON} -m pip install -r scripts/requirements.txt
```

If the launcher cannot start Python, return to launcher discovery and try the
remaining candidates. If the verified interpreter runs but dependency
installation fails, show the exact error and stop.

Using the same resolved launcher, run this command without showing it to the
user:

```powershell
{PYTHON} scripts/mcp_config.py materialize-defaults
```

If default MCP materialization fails, show the exact error and stop. The command
preserves user-configured servers and locally customized default definitions.

Do not route to the retired Dataverse foundation or onboarding playbooks.
Foundation setup owns DA-GA environment and editable Dev-agent selection,
workspace materialization, and canonical setup completion.
