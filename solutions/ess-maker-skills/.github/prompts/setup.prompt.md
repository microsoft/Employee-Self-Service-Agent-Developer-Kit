---
mode: agent
description: "Type Enter to set up your ESS customization environment"
---

# Setup

Read `src/skills/foundation-setup/SKILL.md` first. Follow its **Command runtime**
instructions to establish a working Python invocation before running any Python
command.

After reading the foundation skill, write the complete maker-facing progress
checklist below. At the beginning of every subsequent setup turn, write the
same complete checklist again using the latest canonical setup state and
results observed in that invocation. Use the exact ordinary Markdown shape
defined in the foundation skill: one single-level bullet and one leading
status emoji per stage.

- {marker} Choose the starting point and target environment
- {marker} Verify access and agent identity
- {marker} Establish an editable Dev agent
- {marker} Materialize the local workspace
- {marker} Review the setup handoff

Use ✅ for completed, 🔄 for the current stage, ⛔ for a blocked stage, and ⬜
for pending. Every update is a full snapshot containing all five stages in this
order. After each setup action that changes progress, write the complete
snapshot with the updated statuses. Preserve completed stages, keep pending
stages present, and represent subordinate checks through the status of their
owning stage. Before every maker-facing response, including the final handoff,
synchronize the complete snapshot once more.

Run setup commands from the current ESS Maker Skills workspace folder.

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
