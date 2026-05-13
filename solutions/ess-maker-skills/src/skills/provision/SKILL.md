# Provision Skill

Provision a Power Platform environment with ESS base + ISV extension, end to end, in a single command.

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling
or what files you are reading.

**Do NOT show internal variable names or assignments to the user.** Never
display text like `ENV_URL = ...` or `RUN_KEY = ...` in chat.

**CRITICAL RULES:**
- **Execute all scripts and tool calls immediately.** Do not ask the user
  for permission to run commands. The /provision flow is designed to be
  fully automated — prompts like "Shall I run this?" or "Allow?" break the
  UX. The only time to pause and ask is when the step doc explicitly says
  to show a Message block and wait for user input.
- Composition over construction. This skill is mostly orchestration. It calls
  existing scripts (`scripts/auth.py`, `scripts/flightcheck/cli.py`) and
  delegates to other skill step files. Do NOT reimplement what `/setup`,
  `/connect`, or `/flightcheck` already do.
- ESS base AND the Workday ISV are both installed via `pac application install`,
  which pulls from AppSource. This is what enables the Copilot Studio
  **Settings → Customize** tab and avoids unverified direct REST endpoints.
- All provision run state lives under `my/provision/{ENV_NAME}/` — `tasks.md`
  (checklist) and `config.json` (gathered values). This is separate from the
  shared auth/config cache in `.local/` used by core scripts (`auth.py`,
  `/setup`, `/flightcheck`). Re-running the skill picks up the existing run
  rather than restarting from zero.
- "Ready" is strict: ESS installed, ISV imported, 2 connections active,
  all tasks.md items checked, config.json status is `ready`. Loose
  definitions of "ready" let bugs ship.

### ISV extensibility

This PR implements Workday end-to-end. The design is intentionally
ISV-aware so future PRs can add ServiceNow, SuccessFactors, etc. by:

1. **Step 2** — ISV picker already lists all ISVs; just remove the
   "not yet implemented" guard.
2. **step3.md** — ISV-specific sections are marked with `<!-- ISV: workday -->`.
   Add a parallel `step3-servicenow.md` (or conditional blocks) for the new
   ISV's connector IDs, connection ref prefixes, and flow names.
3. **scripts/** — `create_connection.py` accepts `--connector` (generic).
   `bind_connection_refs.py` uses `CONNECTOR_UNIQUE_NAMES` dict — add the
   new ISV's connector names there. `wire_flow_bindings.py` filters flows
   by persona prefix — extend the prefix list.
4. **.env** — Workday keys (`WORKDAY_*`) are ISV-specific. Add a parallel
   set for the new ISV (e.g., `SERVICENOW_INSTANCE_URL`).

---

## Start

If the user invoked this skill with arguments like `/provision ess with workday`,
parse the ISV from the phrase ("workday", "servicenow hr", "servicenow it",
"successfactors"). Save as PRE_SELECTED_ISV. If the invocation had no ISV,
leave PRE_SELECTED_ISV unset — Step 2 will ask.

Do not ask any question here. The first question to the user is Step 1
(persona pick). The ISV question, if needed, comes after persona in Step 2.

---

## Step 0: Load defaults from .env (optional)

Check if `.local/.env` exists (relative to the kit folder
`solutions/ess-maker-skills/`). If yes, read it and parse each line as
`KEY=VALUE`. Ignore blank lines and lines starting with `#`. Trim
whitespace and surrounding quotes from each value. If the file doesn't
exist, ENV is empty and every prompt below runs interactively.

**Matching is case-insensitive and supports aliases.** Different teams
write .env keys in different conventions (UPPER_SNAKE, lower_snake,
short prefixed, vendor-specific naming). For each logical setting,
accept any of the listed key names. Save the resolved value into ENV
using the **canonical key** (left column). Downstream steps reference
ENV with canonical names only.

| Logical setting | Canonical key (used downstream) | Accepted aliases (case-insensitive) |
|-----------------|---------------------------------|-------------------------------------|
| Persona | `PERSONA` | `persona`, `ess_persona` |
| Target env URL | `ENV_URL` | `env_url`, `dataverse_url`, `dataverse_endpoint` |
| Env short name | `ENV_NAME` | `env_name`, `environment_name` |
| Workday SOAP base URL | `WORKDAY_BASE_URL` | `soap_url`, `wd_soap_url`, `wd_base_url`, `workday_soap_url`, `workday_base_url` |
| Workday tenant name | `WORKDAY_TENANT` | `tenant`, `wd_tenant`, `workday_tenant`, `workday_tenant_name` |
| Workday OAuth token URL | `WORKDAY_OAUTH_TOKEN_URL` | `oauth_token_url`, `wd_oauth_token_url`, `workday_oauth_token_url` |
| Workday OAuth client ID | `WORKDAY_OAUTH_CLIENT_ID` | `oauth_client_id`, `wd_oauth_client_id`, `workday_client_id`, `workday_oauth_client_id` |
| Workday Entra app ID URI | `WORKDAY_ENTRA_APP_ID_URI` | `microsoft_entra_resource_url`, `entra_resource_url`, `wd_entra_app_id_uri`, `workday_entra_app_id_uri` |
| ESS Dev Kit custom Entra app client ID | `ESS_DEVKIT_EMPHUB_CLIENT_ID` | `ESS_PROVISION_CLIENT_ID`, `provision_client_id`, `ess_devkit_client_id` |
| Power Platform ring | `RING` | `ring`, `pp_ring`, `power_platform_ring` |

**Lookup procedure for each logical setting:**

1. Pick the canonical key.
2. Try the canonical key first (case-insensitive).
3. If not found, try each alias in order (case-insensitive).
4. First match wins. Store under the canonical key.

Keys not in this table are ignored. Never echo any value from ENV to
chat — these may be sensitive in some setups even though `.local/` is
gitignored.

### Pre-flight checklist

After loading .env, validate that all prerequisites are in place before
starting the interactive flow. Check each item and build a status table:

| Item | How to check | Required? |
|------|-------------|-----------|
| `.local/.env` exists | File exists check | Yes |
| `ESS_DEVKIT_EMPHUB_CLIENT_ID` set | Present in ENV after alias resolution | Yes |
| Workday config keys set | `WORKDAY_BASE_URL`, `WORKDAY_TENANT`, `WORKDAY_OAUTH_TOKEN_URL`, `WORKDAY_OAUTH_CLIENT_ID`, `WORKDAY_ENTRA_APP_ID_URI` all present in ENV | Yes (when ISV = workday) |
| PAC CLI installed | `pac --version` exits 0 | Yes |
| PAC auth profile active | `pac auth list` shows at least one profile | Yes |

**If any required item is missing**, show:

**Message:**

Before I can provision, a few things need to be set up:

| Prerequisite | Status |
|-------------|--------|
| .local/.env file | {OK or MISSING} |
| ESS Dev Kit app client ID | {OK or MISSING — add ESS_DEVKIT_EMPHUB_CLIENT_ID to .local/.env} |
| Workday connection config | {OK or MISSING — add WORKDAY_BASE_URL, WORKDAY_TENANT, etc.} |
| PAC CLI | {OK or MISSING — run: dotnet tool install --global Microsoft.PowerApps.CLI.Tool} |
| PAC auth profile | {OK or MISSING — run: pac auth create --cloud Preprod --deviceCode} |

See the [README](../../README.md) for setup instructions including
Entra app registration and API permissions.

**End message.**

Stop here until the user fixes the missing items and re-runs `/provision`.

**If all required items are present**, continue silently to Step 1.

---

## Step 1: Pick HR or IT persona

ESS ships in two persona bundles. The persona drives which AppSource
package and which ISV extension variant get installed downstream.

**If ENV.PERSONA is set to `hr` or `it`:** save it as PERSONA and skip the
question entirely. Do not show any chat message about it. Continue to
Step 2.

**Otherwise:** ask the user which one to provision:

```json
[
  {
    "header": "Persona",
    "question": "Which ESS persona should this environment use?",
    "options": [
      { "label": "ESS HR", "description": "Employee-facing HR assistant (recommended)", "recommended": true },
      { "label": "ESS IT", "description": "Employee-facing IT assistant" }
    ],
    "allowFreeformInput": false
  }
]
```

Save as PERSONA (`hr` or `it`).

---

## Step 2: Pick the ISV

If PRE_SELECTED_ISV (from intent parsing in Start) is set to `workday`,
save it as ISV and skip this question.

If PRE_SELECTED_ISV is set to any other value (servicenow hr,
servicenow it, successfactors), show:

**Message:**

That ISV is not implemented yet in `/provision`. Workday is the only
supported ISV right now. Re-run with `/provision ess with workday`
or pick Workday from the menu.

**End message.**

Stop here.

**If PRE_SELECTED_ISV is not set,** ask:

```json
[
  {
    "header": "ISV",
    "question": "Which integration should be added on top of ESS {PERSONA}?",
    "options": [
      { "label": "Workday HCM", "description": "Workday HCM extension pack (only Workday is implemented today)" },
      { "label": "ServiceNow HR", "description": "Not yet implemented in /provision" },
      { "label": "ServiceNow IT", "description": "Not yet implemented in /provision" },
      { "label": "SuccessFactors", "description": "Not yet implemented in /provision" }
    ],
    "allowFreeformInput": false
  }
]
```

Save as ISV. If the user picks anything other than Workday HCM, show the
"not implemented" message above and stop.

---

## Step 3: Pick or create the target environment

The skill supports two modes for the target Power Platform environment:

- **Bind**: an env already exists. The skill takes the URL and uses it.
- **Create**: no existing env. The skill creates one via PAC CLI
  (`pac admin create`) in the ring the user selects (preprod or prod).

Decide the mode in this order:

1. **If ENV.ENV_URL is set** (from `.local/.env`): save it as ENV_URL and
   set MODE = `bind`. Skip to Step 3a-ring (ring question below), then
   to Step 3b (env name).
2. **Otherwise**, ask the user to choose:

```json
[
  {
    "header": "Env source",
    "question": "I don't have an env URL in .env. Do you want me to create a new env, or use an existing one?",
    "options": [
      { "label": "Create a new env", "description": "Create via PP Admin API in the ring you pick (recommended for fresh setup)", "recommended": true },
      { "label": "Use an existing env", "description": "Paste a Dataverse URL of an env you already created" }
    ],
    "allowFreeformInput": false
  }
]
```

### 3a — If MODE = `bind` (existing env, user prompted)

Ask for the URL:

```json
[
  {
    "header": "Env URL",
    "question": "Paste the Dataverse URL of the target environment (e.g. https://yourorg.crm.dynamics.com)"
  }
]
```

Save as ENV_URL. Then continue to **3a-ring** below.

### 3a-ring — Resolve ring (both modes, including .env)

Downstream scripts (`create_connection.py`) need the ring to construct
the correct per-env API host. The ring cannot be reliably derived from
the URL alone.

**If ENV.RING is set** (from `.local/.env`) to `preprod` or `prod`: save
it as RING and skip the question.

**Otherwise**, ask:

```json
[
  {
    "header": "Ring",
    "question": "Which ring is this environment in?",
    "options": [
      { "label": "Preprod (PPE)", "description": "Environment is in the Preprod ring (aka.ms/ppacppe)", "recommended": true },
      { "label": "Prod", "description": "Environment is in the Prod ring (aka.ms/ppac)" }
    ],
    "allowFreeformInput": false
  }
]
```

Save as RING (`preprod` or `prod`).

**If MODE = `bind`:** continue to Step 3b.
**If MODE = `create`:** continue below (3a-create).

### 3a-create — If MODE = `create` (new env)

The ring was already resolved in 3a-ring above.

ENV_URL is not known yet. It will be assigned by step1.md after the env
is created via the PP Admin API.

### 3b — Env name (both modes)

**If MODE = `bind`:** derive ENV_NAME from the URL host (e.g. `yourorg`
from `https://yourorg.crm.dynamics.com`). If derivation fails, prompt.

**If MODE = `create`:**

If ENV.ENV_NAME is set (from `.local/.env`), save it as ENV_NAME and skip
the prompt below.

Otherwise ask the user. Be explicit so they know free-text input is
expected — the askQuestions tool with no options renders as a plain text
field and users sometimes submit empty:

```json
[
  {
    "header": "Env name",
    "question": "Type a short name for the new environment and press Enter. Example: essdev-gouthams-wd-20260511 (lowercase, no spaces, will be the env's display name)"
  }
]
```

If the user submits an empty value, do NOT re-prompt. Generate a default
of `essdev-{current-user-alias}-{isv}-{yyyymmdd}` using the current OS
username (e.g. `$env:USERNAME` on Windows or `$USER` on Unix) and proceed.
The user can always rename or delete the env later.

Save as ENV_NAME.

---

## Step 4: Initialize run state

Create the directory `my/provision/{ENV_NAME}/` if it does not exist.

Write `my/provision/{ENV_NAME}/config.json`. The `envUrl` is empty for
create mode (filled in by step1.md after the create call succeeds):

```json
{
  "envName": "{ENV_NAME}",
  "envUrl": "{ENV_URL or empty string if MODE = create}",
  "mode": "{bind or create}",
  "ring": "{RING}",
  "persona": "{PERSONA}",
  "isv": "workday",
  "status": "in-progress",
  "createdAt": "{current ISO datetime}"
}
```

Copy `src/skills/provision/tasks.md` to `my/provision/{ENV_NAME}/tasks.md`
if it doesn't already exist (preserves prior progress on re-runs).

---

## Step 5: Run each provisioning step

Read each step file in order and follow it. The step file is responsible
for updating its own checkbox in `my/provision/{ENV_NAME}/tasks.md`.

If a step file detects its work is already complete (from a previous run),
it should skip and continue.

1. Read `src/skills/provision/step1.md` and follow it.
   (Env binding for existing envs, or env creation via PAC CLI for the
   create mode. Verifies the env is reachable in both cases.)

2. Read `src/skills/provision/step2.md` and follow it.
   (Install the ESS base persona pack via `pac application install`.)

3. Read `src/skills/provision/step3.md` and follow it.
   (Install the Workday ISV via `pac application install`; wire connections.)

4. Read `src/skills/provision/step4.md` and follow it.
   (Verify all provision tasks completed; mark readiness.)

---

## Step 6: Mark complete

When all four step files report success, update
`my/provision/{ENV_NAME}/config.json`:

```json
{
  "status": "ready",
  "completedAt": "{current ISO datetime}"
}
```

**Message:**

Provisioning complete.

| Item | Status |
|------|--------|
| Environment | {ENV_NAME} |
| ESS base | ESS {PERSONA} installed |
| ISV | Workday ({hr or it} extension imported) |
| Connections | Workday OAuthUser + Dataverse OAuth (signed-in user) |
| Flow wiring | Manual in Copilot Studio portal (user confirmed done) |
| Health check | All provision tasks verified via checklist |

Next steps:

| Command | What it does |
|---------|--------------|
| `/setup` | Extract the freshly provisioned agent into your local workspace for editing |
| `/flightcheck` | Run the full 41-check readiness validation |
| `/connect` | Add another ISV (ServiceNow, SuccessFactors) to this env |

**End message.**

Stop here. Do not continue.
