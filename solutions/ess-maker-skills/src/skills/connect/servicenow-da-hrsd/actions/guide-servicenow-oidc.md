# Guide the ServiceNow OIDC trust and user mapping

Treat ServiceNow OIDC/auth setup as one complete high-level step. Keep the
full runbook, owner role, completion conditions, and non-secret evidence
requirements available to the administrator. Render the returned
`instructionTitle` and `instruction`, followed by one unchanged short
`question`, and pause exactly once. Do not separately render the detailed
internal runbook or pause between role elevation, provider registration,
metadata, claim mapping, and user checks.

Never create or patch ServiceNow security objects.

Read `adminSetup.phaseHandoffs.servicenow-oidc` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, rerun
`identity-mapping-handoff --stage servicenow` to validate the current
target-bound mapping and reconcile any older derived reused handoff. Require
`decision: no-action`; do not ask again. Then return
`ACTION_RESULT = "recorded"` and let the structured checkpoint reverify the
current bundled evidence. A prior result outside `completionStatuses`
requires one new complete OIDC handoff.

## Goal and owner

- **Goal:** make ServiceNow trust App A's delegated user token and resolve the
  signed-in employee to one matching Active ServiceNow user.
- **Owner role:** ServiceNow `admin` or `security_admin`, elevated to
  `security_admin`.

## Complete admin instructions

The workbook includes one standalone
[Task 2 setup instruction](https://review.learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/declarative-agent-servicenow-hr-it?branch=main#task-2-register-oidc-provider-in-servicenow)
reference.

1. Open [this ServiceNow instance]({SERVICENOW_INSTANCE_URL}) using the exact
   preflight URL, then from the profile menu select `Elevate roles`, select
   `security_admin`, and
   select `Update`. If the role is unavailable or the admin is not authorized,
   stop, keep the handoff waiting, and do not bypass permissions, create a
   role, or record completion evidence.
2. Select `All`, search for `OAuth`, then open `System OAuth` →
   `Application Registry`. If Application Registry is absent after authorized
   elevation, stop, keep the handoff waiting, and do not record completion
   evidence.
3. Look for an existing registry entry whose Client ID is the exact
   Task 1 Application client ID. Reuse or repair only that entry. Select `New`
   only when no exact entry exists, then select
   `Configure an OIDC provider to verify ID tokens`. For an exact existing
   registry entry, open its existing form instead of selecting the new-entry
   option.
   - If this option is still unavailable after correct elevation, stop and
     tell the ServiceNow Admin to confirm the tenant's OIDC / Multi-Provider
     SSO capability according to tenant policy.
   - Do not continue, guess a specific plugin, or record phase completion.
4. Create or reuse the exact valid ESS OIDC entity:
   - Name = `Microsoft Entra ID - ESS Copilot`;
   - Client ID = verified App A Application client ID;
   - Entity state = `Active`;
   - Scope Restriction = `Broadly scoped`;
   - if `Client secret` is required, enter a tenant-approved non-empty
     non-secret unused placeholder locally; never create an Entra client
     secret or return/persist this local placeholder.
   - This delegated-user provider is separate from any Knowledge/Graph
     Connector app-only provider. Do not reuse the Graph Connector client ID,
     audience, entity, or app-only user mapping. If both configurations exist,
     the ServiceNow admin must verify their entity names, client IDs,
     audiences, token purposes, and user mappings remain distinct; evaluate
     metadata URL reuse or uniqueness separately under the constraints below.
   - Treat a Graph Connector app-only provider as a separate integration, not
     as the delegated-user provider required here.
   - Before creating another provider configuration, have the ServiceNow /
     security admin inspect whether this tenant metadata URL is already used
     and whether that configuration belongs to a Graph Connector app-only
     integration. ServiceNow versions and tenant policies can differ, so do
     not claim a universal one-provider limit; do honor any metadata uniqueness
     or provider-reuse constraint the current tenant enforces.
   - Do not duplicate the same tenant metadata into a second provider merely
     to make the entities look distinct. Do not treat an existing Graph
     Connector app-only user mapping as the Power Platform delegated-user
     mapping, and do not invent a different metadata URL.
   - If the Graph Connector and Power Platform requirements conflict and the
     ServiceNow / security admin cannot identify a supported coexistence
     configuration, stop and keep the handoff waiting. Do not record completion
     evidence until that admin resolves the conflict.
5. In `OAuth OIDC Provider Configuration`, select the lookup/search icon and
   inspect existing provider configurations. Select the configuration for this
   integration. Select `New` only when no suitable configuration exists and
   the instance's reuse or uniqueness rules allow it. Do not duplicate or
   modify another integration. Then set:
   - OIDC Provider / Provider Name = a name representing the Microsoft Entra
     tenant;
   - metadata URL =
     `https://login.microsoftonline.com/<tenant-id>/.well-known/openid-configuration`
     using the hyperlink in that workbook action;
   - cache lifespan = `120`;
   - Application = `Global`;
   - JTI verification = disabled;
   - submit the child configuration, select it on the parent registry entry,
     then save or update the parent entry.
   - if the scoped identity requirement is custom/non-email and the Entra
     policy uses custom signing, the ServiceNow and Entra admins must confirm
     a compatible validation metadata/JWKS route, issuer, and token version
     before completion. Application-specific metadata may require an `appid`
     query. Do not assume the default tenant metadata is compatible, blindly
     switch token versions, enable keys, or change policy. Keep the handoff
     waiting until the supported route is confirmed.
6. Generate the protected ServiceNow selection workbook. It opens on
   stage-specific `Steps`, then uses the two-column `Worksheet`; hidden locked
   `_metadata` remains parser-only. It freezes the exact Entra-confirmed
   candidate claim names in the exact returned order; there is no manual
   recopy or default/optional-claims guess. Frozen claim cells are gray and
   locked; current-stage ServiceNow User Field cells are yellow and unlocked.
   The ServiceNow admin:
   - keeps the OIDC form open and, in a separate browser tab, opens
     `User Administration` → `Users` to compare each candidate with actual
     values on an Active `sys_user` record;
   - in that same lookup tab, uses Dictionary or Configure Dictionary to
     identify the matching `sys_user` internal column name (for example
     `email`, `user_name`, `employee_number`, or an approved custom `u_*`
     field), not a display label or dotted `table.field` name;
   - fills the ServiceNow User Field cell on exactly one yellow row;
   - leaves every unselected row blank;
   - returns to the OIDC configuration tab, then sets OIDC `User Claim` to the
     exact locked claim name on that row and `User Field` to the exact adjacent
     internal column name, preserving case;
   - does not add, delete, rename, or reorder candidate claims and never returns an employee value.
   - if no candidate matches safely, stops, keeps the handoff waiting, and asks
     the Entra admin to confirm an approved custom employee claim instead of
     guessing or recording completion evidence.
7. Open `All` → `User Administration` → `Users` and confirm a real signed-in
   test user has one matching Active record. Do not return the employee's
   identifier to the skill. Do not create a test user as part of this skill.
8. Confirm with the Maker that Task 1 already preauthorized ServiceNow
   connector application `c26b24aa-7874-4e06-ad55-7d06b1f79b63`. If not,
   keep the handoff waiting and do not record completion evidence; this is an
   Entra Task 1 action, not a ServiceNow cloud permission change.

Do not use a Graph Connector app-only OIDC configuration. Use the Application
client ID, not the object ID, `api://` URI, connector app ID, secret, or
certificate.

## Completion signal and evidence

Before the single visible handoff, run:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} identity-mapping-handoff --stage servicenow
```

Render the exact returned `instructionTitle` and `instruction` first. They are
the Step 2 explanation and contain `Purpose`, `Owner`, `Known target`, and
`Action`, with the generated protected workbook URI and plain absolute path.
Then send the returned short `question` object unchanged through the question
tool. Both its `header` and `question` are exactly
`Please enter the returned ServiceNow admin handoff workbook URL.` Do not use
the Step title as the question header, reconstruct a static checklist, add a
separate completion question, or add an unsupported placeholder field. The
question uses `allowFreeformInput: true`.

If candidates are missing or stale, return `ACTION_RESULT = "waiting"` and
resume the Entra phase. Sheet protection prevents accidental edits but does
not prove authorization; import validation checks the exact
`Steps` / `Worksheet` / hidden `_metadata` structure, every frozen candidate,
context value, editable marker, and selected pair. The visible question says
“admin handoff workbook URL” because that is the approved Maker-facing term,
but the accepted value remains the local path (or supported local file URI) of
the administrator-completed template. The generated workbook URI and plain
`workbookPath` in `instruction` identify the blank template to open; they are
not the returned answer. The Maker may return that same local file after the
administrator fills it, or a returned copy saved locally. While the question
is pending, do not return an action result. No answer or cancellation returns
`ACTION_RESULT = "waiting"` and writes no mapping or phase completion.

Import only the exact local path returned by the question. Supplying a path is
not completion: protected structure, stage, target binding, frozen candidate
set, one selected claim, and one internal ServiceNow User Field must all
validate before any mapping or phase evidence is recorded:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-identity-mapping --stage servicenow --workbook-file "<completed-xlsx-path>" --yes
```

The import requires the exact frozen candidate set and exactly one non-empty
ServiceNow User Field. Then record one bounded bundled phase handoff:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-admin-phase --phase servicenow-oidc --status completed
```

Return `ACTION_RESULT = "recorded"` after the phase handoff is persisted. The
phase remains `Manual`, not a fake live `Passed`: this bounded structured
attestation proves only that the Maker completed or re-verified the entire
runbook in the current invocation. It does not prove an unseen admin action or
expose mapping data because no supported read-only ServiceNow security-object
API is used.

Source contract: PR #217 S4.3/S4.4 is authoritative. Microsoft Learn's current
ServiceNow connector User Login/OIDC setup is a secondary reference only.
