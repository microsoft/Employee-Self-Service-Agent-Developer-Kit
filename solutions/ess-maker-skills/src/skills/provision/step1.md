# Provision Step 1: Environment Binding

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

This step ensures the provisioning run has a target environment that is
reachable. It handles two modes:

- **`bind`**: ENV_URL is already known from `.local/.env` or interactive
  prompt. Just verify it's reachable.
- **`create`**: ENV_URL is empty. Call the PP Admin API to create a new
  env in the selected RING, poll until Dataverse is provisioned, capture
  the new URL, then verify it's reachable.

Read `my/provision/{ENV_NAME}/config.json` for ENV_URL, ENV_NAME, MODE,
and RING.

---

## 1.1 — Skip if already complete

Read `my/provision/{ENV_NAME}/tasks.md`. If "Environment bound" is `- [x]`,
skip to 1.6.

---

## 1.2 — Create the env (only if MODE = create)

**If MODE = `bind`:** skip this section, go to 1.3.

**If MODE = `create`:** call the create-env helper to provision a new
Power Platform environment in the selected ring.

```
python scripts/create_env.py --ring {RING} --name {ENV_NAME}
```

The helper is a thin wrapper around PAC CLI's `pac admin create`. It:
1. Checks that `pac` is on PATH. If not, prints install instructions
   and exits 1.
2. Checks for an active `pac auth` profile matching the requested cloud
   (`Preprod` for PPE, `Public` for prod). If none, prints the
   device-code command for the user to run themselves, then exits 1.
3. Runs `pac admin create --type Developer --region unitedstates
   --currency USD --language 1033 --name <ENV_NAME>`. Developer type
   is the default because it requires no capacity.
4. Parses pac's stdout for the env URL, env ID, and organization ID.
5. Returns JSON on stdout.

While the helper runs, pac shows its own progress (it polls internally).
Surface its output to the user as-is.

**If exit code is 0:** parse the JSON stdout. Save these fields into
`my/provision/{ENV_NAME}/config.json`:

- `envUrl` from the JSON → save as `envUrl` (also referenced as ENV_URL downstream)
- `envId` from the JSON → save as `envId` (also referenced as ENV_ID downstream). **Required by step3.md.** Without it, downstream `--env-id` arguments expand to empty and helpers fail.
- `organizationId` from the JSON → save as `organizationId` (DATAVERSE_ORG_ID)

Proceed to 1.3.

**If exit code is 1:** show the stderr and stop. Common reasons:

- `pac` CLI not installed. The error message includes the install command.
  After the user installs it, type **retry**.
- No auth profile for the selected cloud. The error message tells the
  user exactly which `pac auth create --cloud X --deviceCode` to run.
  They run it in their terminal, complete sign-in, then type **retry**.
- pac auth expired during the operation. Same fix: re-run the
  device-code command.

**If exit code is 2:** the env could not be created. Parse the stderr to
determine the reason and offer recovery options:

**If the error mentions "limit" or "capacity"** (Developer env limit
reached):

Ask the user what to do:

```json
[
  {
    "header": "Env limit recovery",
    "question": "You've hit the Developer environment limit (3 per user). How would you like to proceed?",
    "options": [
      { "label": "Retry as Sandbox", "description": "Create a Sandbox env instead (uses tenant capacity — check with your admin)", "recommended": true },
      { "label": "Retry as Trial", "description": "Create a Trial env instead (free, but expires after 30 days)" },
      { "label": "Delete an existing env and retry", "description": "Go delete one of your Developer envs, then come back and type retry" },
      { "label": "Use an existing env", "description": "Bind to an env you already have instead of creating a new one" },
      { "label": "Cancel", "description": "Stop provisioning" }
    ],
    "allowFreeformInput": false
  }
]
```

Handle the user's choice:
- **Retry as Sandbox**: re-run `create_env.py` with `--type Sandbox` instead
  of `--type Developer`. Proceed normally on success.
- **Retry as Trial**: re-run `create_env.py` with `--type Trial` instead
  of `--type Developer`. Warn that Trial envs expire after 30 days.
  Proceed normally on success.
- **Delete an existing env and retry**: wait for the user to type **retry**,
  then re-run the original Developer command.
- **Use an existing env**: switch MODE to `bind` and ask for a Dataverse URL
  (same as the bind path in SKILL.md Step 3a). Update config.json with the
  new mode and URL.
- **Cancel**: stop the skill.

**If the error mentions "already exists" or "name is taken":**

Ask the user for a different name and retry with the new name. Update
ENV_NAME and config.json accordingly.

**For any other exit code 2 reason:** show the stderr and stop.

**If exit code is 3:** the pac command returned an error we did not
recognize. Show the full stderr to the user and stop the skill.

---

## 1.3 — Authenticate and verify env is reachable

This skill talks to Power Platform Admin, Dataverse, and the Marketplace
install API on the user's behalf. Authentication is via MSAL interactive
browser flow with on-disk token caching (`auth.py`). On first run, a
browser tab opens for sign-in; subsequent calls reuse the cached token
silently.

The `scripts/whoami.py` helper does both auth (opens a browser tab on
first run if needed) and a WhoAmI probe in one shot. Run it silently:

```
python scripts/whoami.py --env-url {ENV_URL}
```

Capture stdout and the exit code.

**If exit code is 0:** parse the JSON stdout. Save `organizationId` as
DATAVERSE_ORG_ID in `my/provision/{ENV_NAME}/config.json`. Proceed to 1.4.

**If exit code is 1 (auth failed or access denied):**

**Message:**

I couldn't authenticate to the environment. Two things to check:

- **Did you sign in with the right Microsoft account?** Use the account
  that has access to the target Power Platform environment.
- **Does your account have permission on the target env?** You need at
  least the System Customizer role on the Dataverse environment.

Type **retry** when ready, or **cancel** to stop.

**End message.**

Wait for the user. On retry, re-run the script.

**If exit code is 2 (network or DNS failure):**

**Message:**

The environment URL doesn't resolve. You gave me `{ENV_URL}` — check
that it's a Power Platform environment URL (typically ending in
`.crm.dynamics.com`).

Type **back** to enter a different URL.

**End message.**

On `back`, return to SKILL.md Step 3 to re-collect ENV_URL.

**If exit code is 3 (unexpected error):** show the stderr text from the
script directly to the user and stop the skill. This is an
unrecoverable condition that needs investigation.

---

## 1.3b — Warm up Power Platform Connectivity token

The connection-creation step (step3, §3.4) needs a Power Platform
Connectivity API token. Acquire it now so the user does all browser
sign-ins upfront instead of being interrupted mid-flow.

Read `ESS_DEVKIT_EMPHUB_CLIENT_ID` from ENV (loaded in Step 0).

```
python scripts/create_connection.py --env-id {ENV_ID} --env-url {ENV_URL} --ring {RING} --connector _warmup --client-id {ESS_DEVKIT_EMPHUB_CLIENT_ID}
```

The `_warmup` connector acquires and caches the token without creating
anything, then exits 0.

If a browser sign-in opens, tell the user:

**Message:**

Please sign in to the Power Platform API in the browser window that
just opened. This is the last sign-in — all subsequent steps will
reuse this token.

**End message.**

On success, the token is cached in `.local/` for step3 to reuse silently.

---

## 1.4 — Derive env ID for bind mode (only if MODE = bind)

In `create` mode, `create_env.py` already emits `envId` and §1.2 saved it.
Skip this section.

In `bind` mode, the user pasted a Dataverse URL but the Power Platform env
GUID (`envId`) is not in the URL. Now that auth is established (§1.3),
derive it via:

```
GET {ENV_URL}/api/data/v9.2/organizations?$select=environmentid
```

Use the bearer token cached by §1.3's `whoami.py` run (auth.py persists
the token cache so subsequent Dataverse calls reuse it silently).

Take the first row's `environmentid` value and save as `envId` in
`my/provision/{ENV_NAME}/config.json`. Downstream helpers require it.

---

## 1.5 — Detect existing state

Silently check whether ESS or any ISV solution is already installed in
this env. This affects whether step2 and step3 skip or run.

Use the Dataverse Web API (the bearer token is the one cached by step 1.3):

```
GET {ENV_URL}/api/data/v9.2/solutions?$select=uniquename,version,ismanaged&$filter=startswith(uniquename,'msdyn_copilotforemployeeselfservice') or startswith(uniquename,'msdyn_essh') or startswith(uniquename,'msdyn_essit')
```

Parse the response. For each found solution, save to config.json:

```json
{
  "preExistingSolutions": [
    { "uniqueName": "...", "version": "...", "isManaged": true }
  ]
}
```

This is informational only — step2 and step3 will use this to decide whether
to skip work.

---

## 1.6 — Mark complete

Update `my/provision/{ENV_NAME}/tasks.md` — change "Environment bound" to `- [x]`.

**Message:**

Bound to environment **{ENV_NAME}**.

| Check | Status |
|-------|--------|
| Dataverse auth | OK |
| Power Platform API auth | OK |
| Pre-existing ESS solutions | {count from preExistingSolutions} |

**End message.**

Continue to step2.md.

---

