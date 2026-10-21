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

When environments are returned, show their display names followed by **Create
a Power Platform environment**, **Help me decide**, and **Go back**. Let the
maker select one exact environment or the creation route. These picker results
are not the environment-creation baseline. For a selected existing environment, retain its exact environment ID
as `{ENVIRONMENT_ID}`, its service-provided `name` as
`{ENVIRONMENT_DISPLAY_NAME}`, and the selected ring for every later operation
in this invocation.

For **Create a Power Platform environment**, follow **Create a Power Platform
environment** below.

For **Help me decide**, follow the shared contract in `SKILL.md`. Ask which team will own the agent, where that team normally performs development, who administers the environment, and whether isolation in a separate environment is intentional. Recommend an exact returned environment only when the maker's answers identify it. Recommend creating a separate environment only when the maker confirms that isolation is intentional and a Power Platform administrator is available. Otherwise explain which ownership or administration fact must be confirmed.

For **Go back**, retain the selected account and return to the parent setup
choice that entered environment discovery.

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
- For **Create a Power Platform environment**, follow **Create a Power Platform
  environment** below.

- For **Go back**, retain the selected account and return to the parent setup choice that entered environment discovery. Do not rerun environment discovery until the maker selects a setup path. **Use another account** remains the account-switch route on this surface.

## Create a Power Platform environment

This route is entered from either environment-selection surface above. Render
**Environment-creation setup** from `permission-guidance.md` before collecting
environment details.

For **Yes, the required people are present**, retain `{SETUP_ACCOUNT}` as
`{ENVIRONMENT_CREATION_ACCOUNT}`.

For **Yes, but we need to switch accounts**, retain `{SETUP_ACCOUNT}` as
`{RETURN_SETUP_ACCOUNT}`. Before switching, inspect that user's authenticated
identity without another sign-in:

```text
python scripts/setup_power_platform_environment.py inspect-account \
  --ring "{RING}" \
  --account "{RETURN_SETUP_ACCOUNT}"
```

Parse `DA_ENVIRONMENT_ACCOUNT_JSON:` and retain its `account`, `objectId`, and
`tenantId` as the returning user's identity. An unavailable identity does not
prevent environment creation, but it must be resolved before an automated role
grant. Never derive a tenant-local object ID from a sign-in name or
`home_account_id`. Then say:

> Microsoft sign-in will open. Select the Power Platform administrator account
> that should create the environment.
>
> After creation, setup can switch back to `{RETURN_SETUP_ACCOUNT}` and remove
> the administrator account from this workspace's authentication cache.

The read-only location-listing operation below owns this account selection.
Append `--select-account`, parse `DA_AGENTBUILDER_AUTH_JSON:`, require a
non-empty account different from `{RETURN_SETUP_ACCOUNT}`, and retain it as
`{ENVIRONMENT_ADMIN_ACCOUNT}` and `{ENVIRONMENT_CREATION_ACCOUNT}`. If the
returned account is the same, say that a different account was not selected
and return to the environment-creation account choices.

For the resumed **A Power Platform administrator is now available** route,
follow the account choice defined in `permission-guidance.md`. Continuing uses
`{SETUP_ACCOUNT}`. Switching follows the administrator-account selection above.
**Go back** returns to the environment-selection surface that offered creation
without changing the selected account or ring.

List the tenant-supported provisioning locations before asking for the region:

```text
python scripts/setup_power_platform_environment.py list-locations \
  --ring "{RING}" \
  --account "{ENVIRONMENT_CREATION_ACCOUNT}"
```

When selecting an administrator account, replace `--account` with
`--select-account` for this read-only command. Parse
`DA_ENVIRONMENT_LOCATIONS_JSON:` and retain its `tenantId` as
`{ENVIRONMENT_CREATION_TENANT_ID}`, along with `selectionMode`,
selectable choices, and `evidencePath`. The evidence file is the complete
service response. Do not expose the tenant ID or internal location codes.
Use the projected `value` unchanged in the create request. Do not substitute a
geographic code or derive the value from the display label or service ring.

If `selectionMode` is `Region`, present every `locations` row whose
`isDisabled` is false, using `name` as the label and retaining `value` as the
request location. Put the `isDefault` row first without preselecting it. If
`selectionMode` is `MacroRegion`, present every `macroRegions` row using `name`
as the label, retain `value` as the request macro region, and include a
non-empty `dataResidencyNote` in the choice description. If the applicable
collection has no selectable rows, say that Power Platform returned no
provisioning regions for the selected account and present **Use another
account** and **Go back**.

Ask for the environment name, then ask for the environment type with these
choices:

- **Sandbox (Recommended):** For development, testing, and team-managed
  customization.
- **Production:** For long-lived use under the organization's production
  governance.
- **Trial:** For temporary evaluation. Availability and expiration depend on
  the organization's licenses and policies.

Ask for one service-provided region or macro region from the retained choices.
Then show:

**Message:**

Create this Power Platform environment?

| Setting          | Value                            |
| ---------------- | -------------------------------- |
| Name             | `{ENVIRONMENT_NAME}`             |
| Type             | `{ENVIRONMENT_TYPE}`             |
| Region           | `{ENVIRONMENT_REGION_NAME}`      |
| Creating account | `{ENVIRONMENT_CREATION_ACCOUNT}` |

**End message.**

Present **Create environment**, **Change details**, and **Go back** with no
preselected choice. **Change details** returns to the three environment fields.
**Go back** returns to the environment-selection surface that offered creation.

Only after **Create environment**, capture a fresh pre-create environment list
under the exact creation account, tenant, and ring:

```text
python scripts/setup_existing_da.py list-environments \
  --ring "{RING}" \
  --tenant-id "{ENVIRONMENT_CREATION_TENANT_ID}" \
  --account "{ENVIRONMENT_CREATION_ACCOUNT}"
```

Require `DA_AGENTBUILDER_AUTH_JSON:` to identify
`{ENVIRONMENT_CREATION_ACCOUNT}` and `DA_ENVIRONMENT_LIST_JSON:` to identify
`{ENVIRONMENT_CREATION_TENANT_ID}` and `{RING}`. Retain every returned environment
ID as `{ENVIRONMENT_IDS_BEFORE_CREATE}`, with that account, tenant, ring, and
evidence path. The returned evidence path retains this specific listing; use it
rather than the shared latest inventory. A successful empty list is a valid baseline; a failed or
identity-mismatched read is not. Do not submit creation until this baseline is
established. If the creation account, tenant, or ring changes, capture a new
baseline before submitting creation. Never reuse the original setup user's
picker results after an administrator switch. Use the creation account, not the
original setup account, in any baseline-read failure guidance.

Then generate a new client request UUID and run the applicable command:

```text
python scripts/setup_power_platform_environment.py create \
  --ring "{RING}" \
  --tenant-id "{ENVIRONMENT_CREATION_TENANT_ID}" \
  --account "{ENVIRONMENT_CREATION_ACCOUNT}" \
  --display-name "{ENVIRONMENT_NAME}" \
  --environment-type "{ENVIRONMENT_TYPE}" \
  --location "{ENVIRONMENT_LOCATION_VALUE}" \
  --client-request-id "{NEW_CLIENT_REQUEST_UUID}"
```

For `MacroRegion`, replace `--location` with `--macro-region`. Retain the UUID,
and never generate another UUID or dispatch another create command for the same
maker confirmation. The command uses only the exact cached account established
by the preceding read-only operation.

Parse `DA_ENVIRONMENT_CREATE_JSON:` even when the command exits nonzero. Retain
its request ID, outcome, operation status, returned environment identity, and
evidence path. Preserve `DA_ENVIRONMENT_CREATE_ERROR_JSON:` and
`DA_ENVIRONMENT_CREATE_ERROR_RESPONSE_JSON:` when present.

When the result is `created` or `accepted`, rerun the same `list-environments`
command under `{ENVIRONMENT_CREATION_ACCOUNT}`,
`{ENVIRONMENT_CREATION_TENANT_ID}`, and `{RING}`. Require the same authenticated
account and list tenant/ring before using its result. If the create response returned an
environment ID, require an exact ID match. Otherwise, compare the new list to
`{ENVIRONMENT_IDS_BEFORE_CREATE}` and accept exactly one newly returned
environment whose service-provided name exactly matches
`{ENVIRONMENT_NAME}`. Do not select an older same-name environment or choose
between multiple candidates. Retain the exact match as `{ENVIRONMENT_ID}` and
`{ENVIRONMENT_DISPLAY_NAME}`.

When no exact environment can yet be established, say:

**Message:**

`{ENVIRONMENT_NAME}` was accepted for creation, but setup cannot find the new
environment yet.

**End message.**

Present **Check again**, **Open Power Platform admin center**, **Use a different
environment**, and **Go back**. **Check again** reruns only
`list-environments`. **Open Power Platform admin center** opens
`[Power Platform admin center]({POWER_PLATFORM_ADMIN_ORIGIN}/)` using the
retained ring-specific origin. **Use a different environment** returns to the
environment picker. **Go back** returns to the standard fresh-agent
target-selection route. Do not dispatch environment creation from any of these
choices.

Keep the original `{ENVIRONMENT_IDS_BEFORE_CREATE}` and its account, tenant,
ring, and evidence path unchanged during every read-only reconciliation retry.
Do not replace it with a post-create list. If the original baseline is no
longer available, require an exact environment ID from the create response;
otherwise leave the target unresolved rather than selecting by name.

When creation fails or is rejected, state the returned operation status and
supported error evidence without inferring a missing role from a generic 401
or 403. Present **Use another account**, **Open Power Platform admin center**,
**Change details**, and **Go back**. The portal choice uses the retained
`{POWER_PLATFORM_ADMIN_ORIGIN}`.

After the exact new environment is established, say:

> `{ENVIRONMENT_DISPLAY_NAME}` was created.

When creation did not use a temporary administrator account, retain
`{SETUP_ACCOUNT}` and return to `da-mos-starter.md`.

When creation used `{ENVIRONMENT_ADMIN_ACCOUNT}`, first follow **Optional
setup-user access** below. Complete or explicitly skip that interaction while
the administrator's cached authorization is still available. Then ask:

> Environment creation used `{ENVIRONMENT_ADMIN_ACCOUNT}`. Which account should
> setup continue with?

Present only:

- **Switch back to {RETURN_SETUP_ACCOUNT} and forget
  {ENVIRONMENT_ADMIN_ACCOUNT}**
- **Continue with {ENVIRONMENT_ADMIN_ACCOUNT}**

Do not preselect a choice and do not offer another account on this surface.

For **Switch back**, run:

```text
python scripts/setup_power_platform_environment.py forget-account \
  --account "{ENVIRONMENT_ADMIN_ACCOUNT}"
```

The command removes the selected administrator's account records and tokens
across client applications from both the AgentBuilder and shared toolkit
caches. It does not sign out browser or PAC sessions.

Parse `DA_AGENTBUILDER_FORGET_ACCOUNT_JSON:`. A `removed` or `already-absent`
status completes cleanup only when both `caches` entries also report one of
those statuses. Retain `{RETURN_SETUP_ACCOUNT}` as `{SETUP_ACCOUNT}` and say:

> Switched back to `{RETURN_SETUP_ACCOUNT}`.
>
> `{ENVIRONMENT_ADMIN_ACCOUNT}` is no longer in this workspace's
> toolkit authentication caches.

If cleanup fails, retain `{RETURN_SETUP_ACCOUNT}` as `{SETUP_ACCOUNT}`, preserve
the cleanup error and any per-cache completion notes, and say:

> Switched back to `{RETURN_SETUP_ACCOUNT}`, but setup could not finish removing
> `{ENVIRONMENT_ADMIN_ACCOUNT}` from this workspace's toolkit authentication
> caches.
>
> The environment was created successfully.

Present **Try removing the cached account again** and **Continue fresh-agent
setup**.

For **Continue with {ENVIRONMENT_ADMIN_ACCOUNT}**, retain that account as
`{SETUP_ACCOUNT}`.

Return to `da-mos-starter.md` with the selected environment and account.
Render its existing **Fresh-agent setup** people and role walkthrough before
listing agent templates. That downstream walkthrough owns any later account
change needed for the **Environment Maker** role.

When environment discovery fails, parse `DA_ENVIRONMENT_LIST_ERROR_JSON:` and preserve it with `DA_ENVIRONMENT_LIST_ERROR_RESPONSE_JSON:` or `DA_ENVIRONMENT_LIST_ERROR_RESPONSE_TEXT:` as diagnostic evidence. Say that the environment list could not be loaded and ask how to continue. Present **Retry**, **Use another account**, **Use an environment URL**, and **Go back** as the standard choices, with no preselected choice. **Retry** reruns the same read-only environment listing. Apply the documented route when one of the other standard choices is selected. When `authorizationFailure` is `true`, render **Environment discovery** from `permission-guidance.md` before the recovery choices. Do not name a missing role, convert the failure into an empty environment list, or prevent a maker-supplied environment from reaching its authoritative environment-scoped operation.

## Optional setup-user access

After reconciling an exact newly created environment, offer this interaction
only when creation used `{ENVIRONMENT_ADMIN_ACCOUNT}` and setup retained
`{RETURN_SETUP_ACCOUNT}`.

The receiving user's `objectId` must come from its authenticated identity in
`{ENVIRONMENT_CREATION_TENANT_ID}`. When the retained identity is missing or
belongs to another tenant, resolve it with:

```text
python scripts/setup_power_platform_environment.py inspect-account \
  --ring "{RING}" \
  --tenant-id "{ENVIRONMENT_CREATION_TENANT_ID}" \
  --account "{RETURN_SETUP_ACCOUNT}"
```

Whether retained before switching or resolved here, retain the matching
`account`, `tenantId`, and `objectId` as
`{RETURN_SETUP_ACCOUNT}`, `{RETURN_SETUP_TENANT_ID}`, and
`{RETURN_SETUP_OBJECT_ID}`. Do not use another user's identity or an object ID
from another tenant. If cached authorization is unavailable, use the existing
read-only account-establishment path for that exact returning user and tenant
before inspecting again. Do not let a grant command establish an identity.
When the identity cannot be established, explain that setup cannot confirm the
receiving user in this tenant and offer **Try again** or **Skip for now**.
Skipping retains the existing manual role walkthrough.

Show the following as a standalone chat message:

**Message:**

Grant **Environment Maker** to `{RETURN_SETUP_ACCOUNT}` in
`{ENVIRONMENT_DISPLAY_NAME}` so that user can create the agent?

**End message.**

Finish that message before opening the **Setup-user access** interactive
single-selection control. Present **Grant Environment Maker** and **Skip for now**,
with no preselected choice. Do not repeat the grant question in the control's
message, title, or description. Skipping changes no permissions and continues to
the account-continuation question.

Only after **Grant Environment Maker**, inspect the current roles as the
selected administrator:

```text
python scripts/setup_power_platform_environment.py list-roles \
  --ring "{RING}" \
  --tenant-id "{ENVIRONMENT_CREATION_TENANT_ID}" \
  --account "{ENVIRONMENT_ADMIN_ACCOUNT}" \
  --environment-id "{ENVIRONMENT_ID}"
```

This read-only operation may establish authorization for the role API using the
existing application. Parse `DA_ENVIRONMENT_ROLES_JSON:` and retain its complete
response and evidence path. A qualifying assignment must identify the exact
environment's `EnvironmentMaker` role and the exact returning user's object ID,
tenant ID, and `User` principal type. An administrator's assignment, a different
role, or another user's assignment does not qualify. If the assignment already
exists, do not submit a grant. Use the same verified-access confirmation below.

Otherwise generate a new client request UUID for the confirmed grant and run:

```text
python scripts/setup_power_platform_environment.py grant-maker \
  --ring "{RING}" \
  --tenant-id "{ENVIRONMENT_CREATION_TENANT_ID}" \
  --account "{ENVIRONMENT_ADMIN_ACCOUNT}" \
  --environment-id "{ENVIRONMENT_ID}" \
  --principal-id "{RETURN_SETUP_OBJECT_ID}" \
  --principal-account "{RETURN_SETUP_ACCOUNT}" \
  --principal-tenant-id "{RETURN_SETUP_TENANT_ID}" \
  --client-request-id "{NEW_GRANT_REQUEST_UUID}"
```

The operation submits only this one user's Environment Maker assignment. It
does not create a user, assign an administrator role, or add a PowerShell
dependency. Parse `DA_ENVIRONMENT_MAKER_GRANT_JSON:` even when the command exits
nonzero, and preserve any error markers and evidence path. An HTTP success alone
does not establish the assignment. An `unconfirmed` outcome is not a completed
grant.

After a grant response or uncertain transport outcome, rerun only `list-roles`
and inspect the exact assignment. Do not replay a grant because a response was
lost, role readback failed, or the assignment is not yet visible. Keep the
original request UUID and evidence; another write requires fresh confirmation.
An unreadable role response is not an empty role list.

Confirm Environment Maker access only after readback contains the qualifying
assignment. Immediately show the verified access result before asking which
account to continue with, forgetting the administrator, or performing another
operation:

**Message:**

**Environment Maker** access is confirmed for `{RETURN_SETUP_ACCOUNT}` in
`{ENVIRONMENT_DISPLAY_NAME}`. Setup is not complete yet.

**End message.**

Do not show this confirmation for skipped access or an unavailable, unreadable,
or nonmatching role result. Carry that verified fact into the existing fresh-agent role
walkthrough without asking the maker to repeat the assignment manually. This
does not establish agent, connector, capacity, ALM, or publishing readiness.

When readback is unavailable or lacks the exact assignment, state the observed
result and offer **Check again**, **Ask an administrator**, and **Skip for now**.
Checking again performs only role inspection. Asking an administrator uses the
existing forwardable Environment Maker request in `permission-guidance.md`.
Skipping leaves the role unresolved and returns to the account-continuation
question. Preserve the created environment and all service evidence.

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
