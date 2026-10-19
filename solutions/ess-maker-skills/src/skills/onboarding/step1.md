# Step 1: Connect to Dataverse

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

---

## 0.9 — Reuse the foundation environment

If `.local/setup/config.json` exists, run:

```text
python scripts/setup_state.py show --view report
```

Parse the printed state. If `connect_ready` is true and `environment.locked` is
true:

1. Set ENV_URL to `environment.tenant_endpoint`, stripping any trailing slash.
   Retain ENVIRONMENT_ID from `environment.id`.
2. Do not list environments, ask how to provide an environment, or ask the
   maker to select it again.
3. Set FOUNDATION_REUSED to true.
4. Continue directly to section 1.2.

An absent foundation state is expected on a new colleague's workspace.
Continue to section 0.95 when no completed foundation state with a locked
environment exists; do not turn a missing file into an unexplained failure.
Stop on corrupt/unreadable existing state instead of silently recreating it.

## 0.95 — Reuse the ESS deployment's environment

When there is no locked foundation environment, the plan may still record the
environment the Power Platform admin set up for this deployment — every other
maker should connect to **that** one. Check it (read-only; never writes the plan):

```text
python scripts/planner/cli.py setup-status
```

Parse the printed JSON. If `environmentPinned` is **false** (or there is no
plan), continue to section 1.0. If `environmentPinned` is **true**, offer to
reuse it:

```json
[
  {
    "header": "Use the ESS deployment's environment?",
    "question": "An environment was already set up for this ESS deployment: **{displayName or environmentId}** ({environmentUrl}). Connect this kit to that same environment?",
    "options": [
      { "label": "Yes, use this environment", "description": "Connect to the environment the deployment already uses: {environmentUrl}" },
      { "label": "No, choose a different one", "description": "Pick or enter another Power Platform environment" }
    ],
    "allowFreeformInput": false
  }
]
```

- **Yes, use this environment** → set ENV_URL to `environment.environmentUrl`
  (strip any trailing slash), retain `environment.environmentId` as
  ENVIRONMENT_ID, and continue directly to section 1.2. Leave
  FOUNDATION_REUSED false.
- **No, choose a different one** → continue to section 1.0.

## 1.0 — Ask how to provide the environment

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Environment setup",
    "question": "Would you like me to list all the Power Platform environments in your tenant so you can pick one?",
    "options": [
      { "label": "Yes, list my environments", "description": "Sign in and browse available environments" },
      { "label": "No, I'll enter the URL manually", "description": "I already know my environment URL" }
    ],
    "allowFreeformInput": false
  }
]
```

- If the user chose **"Yes, list my environments"** → go to step 1.1.
- If the user chose **"No, I'll enter the URL manually"** → go to step 1.1c.

---

## 1.1 — List environments and let the user pick

**Message (do NOT wait for user response — continue immediately):**

Let me find the Power Platform environments available in your tenant. A
browser window will open for sign-in...

**End message.**

Run this command in the terminal:

```
python scripts/discover.py --list-environments
```

A browser window will open for sign-in. Wait for the script to finish.

**Check the terminal output:**

- **Script printed a table of environments → go to step 1.1a.**
- **Script failed with an auth/permission error → go to step 1.1c.**

---

## 1.1a — Ask the user to pick an environment

Build options from the script's environment table. Each row becomes an option
with `{environment name} — {URL}` as the label and the environment type as the
description. Including the URL in the label keeps duplicate display names
unambiguous.

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Select environment",
    "question": "Which environment is your ESS agent deployed in?",
    "options": [
      { "label": "{env 1 name} — {URL}", "description": "{type}" },
      { "label": "{env 2 name} — {URL}", "description": "{type}" }
    ],
    "allowFreeformInput": false
  }
]
```

Map the selected URL to the unique matching `instanceUrl` in
`ENVIRONMENT_LIST_JSON:` from the same script output.

---

## 1.1b — Use selection

Read the selected object's `instanceUrl` field. Save it as ENV_URL.
Retain its verified environment ID as ENVIRONMENT_ID.
**Strip any trailing slash** from ENV_URL before using it (e.g.,
`https://org.crm.dynamics.com/` becomes `https://org.crm.dynamics.com`).

Go to step 1.2.

---

## 1.1c — Manual URL entry (fallback)

Use the `vscode_askQuestions` tool:

```json
[
  {
    "header": "Environment URL",
    "question": "What's your Power Platform environment URL? Example: `https://yourorg.crm.dynamics.com`. Find it in the Power Platform admin center."
  }
]
```

Save their answer as ENV_URL. **Strip any trailing
slash** from ENV_URL before using it (e.g., `https://org.crm.dynamics.com/`
becomes `https://org.crm.dynamics.com`).

Resolve the ID for that URL with
`python scripts/discover.py --resolve-environment-url "{ENV_URL}"` and use
`SELECTED_ENV_JSON:`. Never substitute a tenant ID or Dataverse organization ID.
If resolution fails, report the error rather than inventing an ID.

## 1.2 — Write the MCP config file

If ENVIRONMENT_ID is still missing (for example, an older plan saved only a URL),
resolve that URL with `discover.py --resolve-environment-url` and retain the
verified ID before extraction. Report a resolution error rather than claiming
the metadata is complete.

Merge the committed defaults, then configure the environment-specific server:

```text
python scripts/mcp_config.py materialize-defaults
python scripts/mcp_config.py configure dataverse --environment-url "{ENV_URL}"
```

These commands normalize the URL and preserve existing server settings. Never
replace `.vscode/mcp.json` with a Dataverse-only object: `ess-planner` and the
other defaults must remain registered. Report a failed command before continuing.

If the host requests trust for `ess-planner`, explain once: "ESS Planner reads
and updates your team's implementation plan and its assignments. Approve this
server if you want shared planning; you can keep drafting locally without it."
Host tool approval is separate from Microsoft sign-in, directory lookup consent,
and permission to administer the environment. Do not imply any one grants the others.

If FOUNDATION_REUSED is true, do not rerun the Allowed MCP Client prerequisite;
it already passed in foundation `SETUP-02.2`. Continue directly to section 1.3.

Check the server-side Allowed MCP Client record:

```text
python scripts/check_dataverse_mcp.py --url "{ENV_URL}"
```

Parse `DATAVERSE_MCP_STATUS_JSON:`:

- If `status` is `enabled`, continue immediately to section 1.3 without asking
  the user.
- If `status` is `disabled` or `missing`, show the Power Platform admin center
  steps below and ask only whether to **Check again**:
  1. Open [Power Platform admin center](https://admin.powerplatform.microsoft.com/environments).
  2. Select the `{ENVIRONMENT_NAME}` environment.
  3. Open `Settings` → `Product` → `Features`.
  4. Turn on **Allow MCP clients to interact with Dataverse MCP server**.
  5. Open `Advanced Settings`.
  6. Open **Microsoft GitHub Copilot** and set `Is Enabled` to `Yes`.
  7. Choose `Save & Close`, then select **Check again** here.
- If the command fails, show its exact error and stop. Do not ask the user to
  attest that the setting is enabled.

## 1.3 — Proceed to agent discovery

The MCP config file is written and admin steps are done. The Dataverse MCP
server will be started later — it's not needed for discovery or setup.

Read `src/skills/onboarding/step1b.md` and follow it.
