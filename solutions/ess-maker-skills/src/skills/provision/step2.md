# Provision Step 2: Install ESS Base via PAC Application Install

Every **Message** block is the exact text to show the user. Copy it verbatim.
Do not rephrase, add commentary, or tell the user what tools you are calling.

This step installs the ESS HR or ESS IT base persona pack using PAC CLI's
`pac application install` command. PAC handles the AppSource lookup, install
polling, and dependency resolution internally. This replaces an earlier
BAP REST API approach that turned out to be unreliable (wrong API path
and version).

Read `my/provision/{ENV_NAME}/config.json` for ENV_URL, ENV_NAME, PERSONA.

---

## 2.1 — Skip if already complete

Read `my/provision/{ENV_NAME}/tasks.md`. If "ESS base installed" is `- [x]`,
skip to 2.5.

Check `preExistingSolutions` in config.json (populated by step1.md §1.5).
If a solution starting with `msdyn_copilotforemployeeselfservice{persona}`
is already present, mark the task complete and skip to 2.5.

---

## 2.2 — Resolve application name from persona

Map PERSONA to the AppSource application name:

- PERSONA `hr` → `msdyn_CopilotForEmployeeSelfServiceHR`
- PERSONA `it` → `msdyn_CopilotForEmployeeSelfServiceIT`

Save as APP_NAME.

---

## 2.3 — Ensure PAC is authenticated for the correct ring

In create mode, `create_env.py` already validated and selected the PAC auth
profile. In bind mode, no such check has run yet.

Read RING from `my/provision/{ENV_NAME}/config.json`. Map to PAC cloud:
- RING `preprod` → cloud `Preprod`
- RING `prod` → cloud `Public`

Run silently:

```
pac auth list
```

Check the output for a profile matching the target cloud. If none exists,
show the user:

**Message:**

PAC CLI is not authenticated for the {cloud} cloud. Run:

```
pac auth create --cloud {cloud} --deviceCode
```

Then type **done** to continue.

**End message.**

If a profile exists but is not the active one, run:

```
pac auth select --index {N}
```

where N is the index of the matching profile.

---

## 2.4 — Install via `pac application install`

**Message:**

Installing ESS {persona} base. This typically takes 1-3 minutes.

**End message.**

Run in the terminal:

```
pac application install --environment {ENV_URL} --application-name {APP_NAME}
```

PAC polls AppSource internally and surfaces its own progress output. Let
the user see PAC's output as-is. Do not pre-poll or post-poll yourself.

**If pac returns exit code 0:**

Verify the install landed by querying Dataverse. Use `startswith` because
the AppSource application name (e.g. `msdyn_CopilotForEmployeeSelfServiceHR`)
may differ in casing or suffix from the Dataverse solution unique name:

```
GET {ENV_URL}/api/data/v9.2/solutions?$select=uniquename,version,ismanaged&$filter=startswith(uniquename,'msdyn_copilotforemployeeselfservice{persona}')
```

Expect at least one row with `ismanaged: true`. If no matching row is found,
treat the install as failed and stop the skill with a clear message asking
the user to check PAC's output.

Save to config.json:

```json
{
  "essBase": {
    "uniqueName": "{APP_NAME}",
    "version": "{version from query}",
    "installedAt": "{current ISO datetime}"
  }
}
```

Proceed to 2.5.

**If pac returns non-zero:**

**Message:**

The ESS {persona} install failed.

The most likely causes:

- **PAC auth profile expired or missing.** Re-run
  `pac auth create --cloud Preprod --deviceCode` (or `--cloud Public`
  for prod ring), sign in, then type **retry**.
- **AppSource package not available in your tenant region.** Some preview
  packages are gated. Check that the package shows "Get it now" in the
  marketplace listing for your region.
- **Insufficient permissions on the target env.** You need at least
  System Administrator on the Dataverse environment.

PAC's full output is above. Fix the issue and type **retry**, or
**cancel** to stop.

**End message.**

On retry, re-run `pac application install`. On cancel, stop the skill.

---

## 2.5 — Mark complete

Update `my/provision/{ENV_NAME}/tasks.md` — change "ESS base installed" to `- [x]`.

**Message:**

ESS {persona} base installed (v{version}). The Copilot Studio
**Settings → Customize** tab is now available, which is what the
next step needs to load the Workday extension.

**End message.**

Continue to step3.md.
