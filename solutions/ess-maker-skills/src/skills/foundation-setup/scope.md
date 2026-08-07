<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Setup Step 1 — Scope

Use `vscode_askQuestions` to collect and lock one target environment.

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

     Then return to environment selection.
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
