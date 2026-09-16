---
mode: agent
description: "Type Enter to set up your ESS customization environment"
---

# Setup

Read `src/skills/foundation-setup/SKILL.md` first. Follow its **Command runtime**
instructions to establish a working Python invocation before running any Python
command.

Using the resolved launcher in place of `{PYTHON}`, run this command without
showing it to the user:

```powershell
{PYTHON} -m pip install -r scripts/requirements.txt
```

Check the Microsoft Object Model converter dependencies:

```powershell
{PYTHON} -c "import sys;
sys.path.insert(0, 'scripts');
import agentbuilder_object_model as m;
m.validate_object_model_runtime()"
```

If the check fails, run:

```powershell
{PYTHON} scripts/install_agentbuilder_object_model.py
```

Then rerun the check.

For any command failure, follow the **Command runtime** recovery guidance.

Do not route to Dataverse foundation or onboarding playbooks.
Foundation setup owns DA-GA environment and editable Dev-agent selection,
workspace materialization, and canonical setup completion.
