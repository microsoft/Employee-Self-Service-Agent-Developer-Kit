<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step 1 — Scope

Use `vscode_askQuestions` to collect and lock one target environment.

0. **First, offer the environment already created for this ESS deployment.**
   Before asking how to choose an environment, check whether the plan already
   records one. The Power Platform admin's setup task pins the environment the
   whole deployment uses, and every other maker should connect their kit to
   **that** environment rather than pick or create a new one. Read it — this is
   **read-only** and never writes the plan (`/setup` stays plan-unaware; the
   planner records task completion separately):

   ```text
   python scripts/planner/cli.py setup-status
   ```

   Parse the printed JSON. If `environmentPinned` is **false** (or there is no
   plan), say nothing about a pinned environment and continue to step 1. If
   `environmentPinned` is **true**, read `environment.environmentUrl`,
   `environment.environmentId`, and `environment.displayName`, and offer to reuse
   it:

   ```json
   [
     {
       "header": "Use the ESS deployment's environment?",
       "question": "An environment was already set up for this ESS deployment: **{displayName or environmentId}** ({environmentUrl}). Connect this kit to that same environment?",
       "options": [
         { "label": "Yes, use this environment", "description": "Connect to the environment the deployment already uses: {environmentUrl}" },
         { "label": "No, choose a different one", "description": "Pick or create another Power Platform environment" }
       ],
       "allowFreeformInput": false
     }
   ]
   ```

   - **Yes, use this environment** → treat `environment.environmentUrl` as the
     manually-entered environment URL (strip any trailing slash) and skip the
     choice in step 1: continue exactly as manual entry — step 5 (verify the
     maker's role), then step 6 (resolve metadata), then persist the scope. Do
     **not** write anything back to the plan here.
   - **No, choose a different one** → continue to step 1 and let them choose or
     create an environment.

1. First ask how the maker wants to provide the environment:

   ```json
   [
     {
       "header": "Environment setup",
       "question": "How would you like to choose your Power Platform environment?",
       "options": [
         {
           "label": "Yes, list my environments",
           "description": "Sign in and browse available environments"
         },
         {
           "label": "No, I'll enter the URL manually",
           "description": "I already know my environment URL"
         },
         {
           "label": "Create a new environment",
           "description": "Create an environment with Dataverse in the Power Platform admin center"
         }
       ],
       "allowFreeformInput": false
     }
   ]
   ```

2. If the maker chooses to list environments:
   - Run `python scripts/discover.py --list-environments`.
   - Present each option as `{name} — {URL}` with platform type in its
     description so duplicate environment names remain unambiguous.
   - Ask the maker to select one.
   - Parse `ENVIRONMENT_LIST_JSON:` from that same command and select the
     corresponding object by environment ID or exact URL. Do not list
     environments a second time.

3. If the maker chooses manual entry, ask:

   ```json
   [
     {
       "header": "Environment URL",
       "question": "What's your Power Platform environment URL? Example: `https://yourorg.crm.dynamics.com`. Find it in the Power Platform admin center."
     }
   ]
   ```

   Strip the trailing slash from the supplied URL.

4. If the maker chooses to create an environment, explain that a Power Platform
   or Dynamics 365 administrator and at least 1 GB of available database
   capacity are required. Then show:

   1. Open the [Power Platform admin center](https://admin.powerplatform.microsoft.com).
   2. Select `Manage` → `Environments`.
   3. Select `New`.
   4. Enter the environment name, region, type, and purpose.
   5. Set `Add a Dataverse data store` to `Yes`.
   6. Keep the release cycle standard by not enabling early features.
   7. Select `Next`, then choose the language, unique URL, currency, and security
      group.
   8. Select `Save` and wait until provisioning finishes.
   9. In the new environment, open `Settings` → `Users + permissions` →
      `Users`, select the setup user, and assign **System Administrator**.

   Link to the
   [Microsoft environment creation instructions](https://learn.microsoft.com/power-platform/admin/create-environment?tabs=new#create-an-environment-with-a-database).
   After the maker confirms creation is complete, run
   `python scripts/discover.py --list-environments`, present the returned
   environments, and ask them to select the newly created environment. Parse
   the selected object from `ENVIRONMENT_LIST_JSON:`. Never assume creation
   succeeded without rediscovering the environment.

5. As soon as an environment URL is selected, entered, or obtained after
   creation, verify the maker's
   role in that environment:

   ```text
   python scripts/check_environment_roles.py --url "{ENVIRONMENT_URL}"
   ```

   Parse `ENVIRONMENT_ROLE_ACCESS_JSON:`:

   - When `eligible` is true, continue immediately without asking for
     confirmation.
   - When `eligible` is false, do not lock the environment. Show:

     Your account needs the **System Administrator** role in **{environment
     name}** to use this environment for ESS setup. Ask your Power Platform
     administrator to assign the role, or select a different environment.

     Explain that the plan's Power Platform administrator nomination and the
     Dataverse System Administrator permission are different. Offer to check
     this environment again after access is granted, or pause this task.
     Do not restart persona detection or environment selection in a loop.
     Choose another environment only if the maker explicitly requests it; a
     shared rollout must not silently switch environments.
   - If the command fails, show the exact error and stop. Do not treat an
     unavailable role result as successful access.

   The check must include roles assigned directly and through team membership.
6. For manual entry, resolve the environment metadata without displaying the
   tenant's environment list:

   ```text
   python scripts/discover.py \
     --resolve-environment-url "{ENVIRONMENT_URL}"
   ```

   Parse `SELECTED_ENV_JSON:` for the environment ID, name, type, and URL. If
   the URL cannot be resolved, show the exact error and stop.
7. Use the environment type returned in `SELECTED_ENV_JSON:` as
   `ENVIRONMENT_PLATFORM_TYPE`. Do not ask the maker to classify the
   environment.
Persist the locked scope:

```text
python scripts/setup_state.py set-scope \
  --environment-id "{ENVIRONMENT_ID}" \
  --environment-name "{ENVIRONMENT_NAME}" \
  --environment-type "{ENVIRONMENT_PLATFORM_TYPE}" \
  --tenant-endpoint "{ENVIRONMENT_URL}"
```

The command records the locked environment, type, endpoint, and setup intent
directly on `SETUP-01`, then completes the step atomically.

**Message:**

Setup is locked to **{environment name}**.

**End message.**
