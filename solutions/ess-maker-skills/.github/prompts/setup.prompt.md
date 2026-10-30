---
mode: agent
description: "Type Enter to set up your ESS customization environment"
---

# Setup

Read `src/skills/foundation-setup/SKILL.md` first. Follow its **Command runtime**
instructions to establish a working Python invocation before running any Python
command.

After reading the foundation skill, use its explicit progress render points.
Apply its unavailable-user and automated-answer guard to every interactive
choice. A host placeholder or automatic reply is not an account, ALM, create,
import, reset, or replacement selection; stop with that question pending.
At the first interactive setup surface in a turn, write the complete
maker-facing progress checklist below using the latest canonical setup state
and results observed in that invocation. Use the exact ordinary Markdown shape
defined in the foundation skill: one single-level bullet and one leading
status emoji per stage. Begin every snapshot with:

Here's your ESS agent setup:

- {marker} Choose the starting point and target environment
- {marker} Verify access and agent identity
- {marker} Establish an editable Dev agent
- {marker} Materialize the local workspace
- {marker} Review the setup handoff

Use ✅ for completed, 🔄 for the current stage, ⛔ for a blocked stage, and ⬜
for pending. Every rendered update is a full snapshot containing all five
stages in this order. Render it at the first interactive surface in a turn,
when a marker changes, when a blocked state requires maker action, and in the
final handoff. A sequence of setup operations that retains the same markers
continues to its next render point without another progress snapshot.

Run setup commands from the current ESS Maker Skills workspace folder.

Using the resolved launcher in place of `{PYTHON}`, first verify the installed
distribution versions against the actual setup manifest. This is a local,
no-network, no-mutation check:

```powershell
{PYTHON} -m pip install --dry-run --no-index --disable-pip-version-check -r scripts/requirements.txt
```

When the manifest check succeeds, verify that the setup modules also load:

```powershell
{PYTHON} -c "import cryptography, defusedxml, httpx, mcp, msal, msal_extensions, pythonnet, requests, urllib3, yaml; print('ESS setup dependencies ready')"
```

When both checks succeed, keep the resolved launcher and skip package
installation. A successful import by itself does not prove that an installed
distribution satisfies the manifest's version constraint.

Only when the manifest check reports a missing or incompatible distribution,
identify the selected interpreter's platform:

```powershell
{PYTHON} -c "import platform, sys; print(f'{sys.platform}:{platform.machine()}')"
```

For `win32:ARM64`, run the repository's ARM64-safe dependency command:

```powershell
{PYTHON} -m pip install --disable-pip-version-check --prefer-binary --only-binary cryptography -r scripts/requirements.txt
```

For every other platform, run:

```powershell
{PYTHON} -m pip install --disable-pip-version-check --prefer-binary -r scripts/requirements.txt
```

These commands intentionally target only `scripts/requirements.txt`. Do not
invoke VS Code environment creation and do not add any
`src/mcp/**/requirements.txt` file. The main requirements file includes the
shared setup authentication dependency; connector-specific dependencies are
installed only by the connector path that owns them.

Rerun both checks after installation. When the manifest check succeeds but the
module-load check fails, preserve the exact import/runtime error and follow the
foundation skill's command-runtime recovery guidance; do not reinstall the
same packages. Apply the same recovery guidance to a manifest-check failure
that is not a missing or incompatible distribution.

On Windows ARM64, a missing binary wheel must fail fast; do not fall back to a
Rust/MSVC source build.

When the current request or canonical local state already selects an exact
agent, complete the foundation skill's account selection and product-line
reconciliation now. If reconciliation stops this setup path, complete its
kit-switch handoff and do not install or validate the Microsoft Object Model
converter.

Only after reconciliation allows DA-GA setup to continue, or when no exact
agent has been selected yet, check the Microsoft Object Model converter
dependencies:

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

After successful runtime, dependency, and converter checks, run the next setup
operation. If an exact agent is selected later, complete product-line
reconciliation before the next DA-GA-only operation. When a check requires
maker action, state the observed failure and its single recovery action.

For a supplied target URL, complete the foundation skill's local
`resolve-target` step before account selection, authentication, environment
listing, or agent discovery. Reuse its returned ring; do not compose a ring
argument from the URL text.

For any command failure, follow the **Command runtime** recovery guidance.

Do not route to Dataverse foundation or onboarding playbooks.
Foundation setup owns DA-GA environment and editable Dev-agent selection,
workspace materialization, and canonical setup completion.
