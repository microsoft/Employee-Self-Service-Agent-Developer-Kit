<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Select a DA Target Environment

Use this shared path to resolve the Power Platform environment for DA foundation setup without Dataverse discovery or filtering.

## Resolve the service ring

Resolve the ring in this order: a recognized Copilot Studio hostname, supplied target context, an explicit current-request instruction, then `prod`. Map `copilotstudio.microsoft.com` and `copilotstudio.preview.microsoft.com` to `prod`, and infer `test` or `preprod` when the supplied URL explicitly identifies either ring. When earlier evidence does not identify the ring, honor an explicit request to run setup in the Preview, `preprod`/Pre-production, or `test`/Test ring. Otherwise use `prod`. Do not show a ring-selection question or infer an internal ring from an environment name or uncertainty.

Retain `{COPILOT_STUDIO_ORIGIN}`, `{POWER_PLATFORM_ADMIN_ORIGIN}`, and `{POWER_APPS_ORIGIN}` with the ring evidence. An explicit Preview URL or request keeps `RING: prod` but uses `https://copilotstudio.preview.microsoft.com`, `https://admin.preview.powerplatform.microsoft.com`, and `https://make.preview.powerapps.com`. A production target or the implicit `prod` default uses `https://copilotstudio.microsoft.com`, `https://admin.powerplatform.microsoft.com`, and `https://make.powerapps.com`. `preprod` uses `https://copilotstudio.preprod.microsoft.com`, `https://admin.preprod.powerplatform.microsoft.com`, and `https://make.preprod.powerapps.com`. `test` uses `https://copilotstudio.test.microsoft.com`, `https://admin.test.powerplatform.microsoft.com`, and `https://make.test.powerapps.com`. Every later ring-aware portal link must use these retained origins rather than reconstructing an origin from `{RING}` alone.

## Resolve the environment

When an environment URL is supplied, infer its environment ID and resolve its ring through **Resolve the service ring** above. Ask only when the environment ID is unclear.

When the target is not supplied, complete the shared account-selection step in `SKILL.md`. Before showing the shared authorization message or running environment discovery, resolve the ring through the precedence above.

After the account and ring are selected, follow the shared authorization guidance in `SKILL.md`, render the **Environment access check** from `permission-guidance.md`, then list environments visible to that account in the selected ring:

```text
python scripts/setup_existing_da.py list-environments \
  --ring "{RING}"
```

Parse `DA_ENVIRONMENT_LIST_JSON:` as the compact environment-selection result. Retain its `evidencePath` as the complete raw service evidence; the compact fields are sufficient for the picker, so read that file only when richer diagnostics or an unprojected service field is needed. Environment discovery is separate from agent discovery: do not run `list-agents`, infer agent visibility, or describe an empty environment result as an empty agent list. Present every environment returned by the Power Platform API without filtering by URL, Dataverse metadata, or environment type.

When environments are returned, show their display names followed by **Help me decide** and let the maker select one exact environment. Retain its exact environment ID as `{ENVIRONMENT_ID}`, its service-provided `name` as `{ENVIRONMENT_DISPLAY_NAME}`, and the selected ring for every later operation in this invocation.

For **Help me decide**, follow the shared contract in `SKILL.md`. Ask which team will own the agent, where that team normally performs development, who administers the environment, and whether isolation in a separate environment is intentional. Recommend an exact returned environment only when the maker's answers identify it; otherwise explain which ownership or administration fact must be confirmed.

When the command succeeds with an empty `environments` array, say:

> No Power Platform environments were listed for this account. No agent listing was performed.

Use the host's interactive single-selection control and present these standard choices:

- **Use another account**
- **Use an environment URL**
- **Create a Power Platform environment**
- **Go back**

Do not preselect a choice.

- For **Use another account**, return to **Choose the sign-in account** in `SKILL.md`, require a different account selection, and rerun `list-environments` only after that selection.
- For **Use an environment URL**, ask for the environment URL and continue with its inferred environment ID and ring. The later environment-scoped operation is authoritative for access; absence from the environment list is not proof that the supplied environment is inaccessible.
- For **Create a Power Platform environment**, ask what the environment should
  be called. Retain the answer as `{REQUESTED_ENVIRONMENT_NAME}`, then say:

  > Open the [Power Platform admin center]({POWER_PLATFORM_ADMIN_ORIGIN}/), choose **Environments → New**, and create an environment for Copilot Studio. This DA setup does not require a Dataverse database. When the environment is ready, return here to list environments again or provide its environment URL.

  Environment creation is a **Power Platform administrator** action. Render
  the shared **Forwardable administrator request** from
  `permission-guidance.md` with:
  - `{ADMIN_ACTION_TITLE}` — **Create a Power Platform environment**
  - `{ADMINISTRATOR_ROLE}` — **Power Platform administrator**
  - `{EXACT_ADMINISTRATOR_ACTION}` — **Create a Power Platform environment named {REQUESTED_ENVIRONMENT_NAME} for a Copilot Studio ESS agent. This setup does not require a Dataverse database.**
  - `{EVIDENCE_SUPPORTED_REASON}` — **The requester does not currently have a Power Platform environment available for the agent.**
  - `{ADMIN_DESTINATION_NAME}` — **Power Platform admin center**
  - `{ADMIN_DESTINATION_URL}` — the retained `{POWER_PLATFORM_ADMIN_ORIGIN}/`
  - `{RETURN_CONDITION}` — **Send the requester the new environment URL. They will return to Setup and continue with that environment.**

  Omit the environment, environment URL, agent, and user fields because the
  target does not exist yet. Stop until the maker supplies the new environment
  URL or environment discovery returns the new environment. Do not route into a
  Dataverse provisioning skill.

- For **Go back**, retain the selected account and return to the parent setup choice that entered environment discovery. Do not rerun environment discovery until the maker selects a setup path. **Use another account** remains the account-switch route on this surface.

When environment discovery fails, parse `DA_ENVIRONMENT_LIST_ERROR_JSON:` and preserve it with `DA_ENVIRONMENT_LIST_ERROR_RESPONSE_JSON:` or `DA_ENVIRONMENT_LIST_ERROR_RESPONSE_TEXT:` as diagnostic evidence. Say that the environment list could not be loaded and ask how to continue. Present **Retry**, **Use another account**, **Use an environment URL**, and **Go back** as the standard choices, with no preselected choice. **Retry** reruns the same read-only environment listing. Apply the documented route when one of the other standard choices is selected. When `authorizationFailure` is `true`, render **Environment discovery** from `permission-guidance.md` before the recovery choices. Do not name a missing role, convert the failure into an empty environment list, or prevent a maker-supplied environment from reaching its authoritative environment-scoped operation.

## Retry setup with another target

Use this shared recovery surface when an environment was selected but its environment-scoped setup operation returns no selectable agents or setup options, or cannot load them.

State the observed result in maker language, then ask:

> How would you like to continue setup?

Use the host's interactive single-selection control and present these labels unchanged with the selection initially unset:

- **Try with a different user**
- **Try a different environment**
- **Go back**

For **Try with a different user**, return to **Choose the sign-in account** in `SKILL.md`. After the maker selects or supplies a different user, rerun environment discovery for that account and continue from its environment picker.

For **Try a different environment**, retain the current account and ring, rerun `list-environments`, and continue from the returned environment picker.

For **Go back**, retain the current account, ring, and environment, then return to the parent skill's **What would you like to set up in this environment?** choice surface. Do not rerun the failed environment-scoped operation.

When direct agent lookup remains available after an empty visible-agent list, also offer **Use a Microsoft Copilot Studio URL**. Place it before the three shared choices, ask for the exact Microsoft Copilot Studio URL when selected, and continue through direct inspection in `da-existing-dev.md`.
