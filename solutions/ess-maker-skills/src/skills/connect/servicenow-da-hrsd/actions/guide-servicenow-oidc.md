# Guide the ServiceNow OIDC trust and user mapping

Treat ServiceNow OIDC/auth setup as one complete high-level step. Give the
Maker the full runbook, owner role, completion conditions, and non-secret
evidence requirements, then pause exactly once. Do not pause between role
elevation, provider registration, metadata, claim mapping, and user checks.

Never create or patch ServiceNow security objects.

Read `adminSetup.phaseHandoffs.servicenow-oidc` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, do not ask again; return
`ACTION_RESULT = "recorded"` and let the structured checkpoint reverify the
current bundled evidence. A prior result outside `completionStatuses`
requires one new complete OIDC handoff.

## Goal and owner

- **Goal:** make ServiceNow trust App A's delegated user token and resolve the
  signed-in employee to one matching Active ServiceNow user.
- **Owner role:** ServiceNow `admin` or `security_admin`, elevated to
  `security_admin`.

## Complete admin instructions

Open the stable instance root once:

[this ServiceNow instance]({SERVICENOW_INSTANCE_URL})

Use the exact URL from preflight discovery `links.serviceNowInstance.url`.

1. From the profile menu, select `Elevate role` and elevate to
   `security_admin`. If **New** is missing in the security configuration, the
   role is not elevated.
2. Go to `All` → `System OAuth` → `Application Registry` → `New`.
3. Select `Configure an OIDC provider to verify ID tokens`.
   - If this option is still unavailable after correct elevation, stop and
     tell the ServiceNow Admin to confirm the tenant's OIDC / Multi-Provider
     SSO capability according to tenant policy.
   - Do not continue, guess a specific plugin, or record phase completion.
4. Create or reuse the exact valid ESS OIDC entity:
   - Name = `Microsoft Entra ID - ESS Copilot`;
   - Client ID = verified App A Application client ID;
   - Entity state = `Active`;
   - if `Client secret` is required, enter a tenant-approved non-empty
     placeholder locally; never return or persist it.
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
     configuration, stop. The Maker must choose **Not yet** and must not attest
     this phase as Completed until that admin resolves the conflict.
5. In `OAuth OIDC Provider Configuration`, set:
   - metadata URL =
     `https://login.microsoftonline.com/<tenant-id>/.well-known/openid-configuration`;
   - cache lifespan = `120`;
   - Application = `Global`;
   - JTI verification = disabled;
   - Scope Restriction = `Broadly scoped`.
6. Set `User Claim` and `User Field`:
   - preferred: `upn` → the ServiceNow field containing the same UPN,
     commonly `user_name`;
   - alternative: `email` → `email`;
   - for a non-email/non-UPN identifier, use only the exact custom access-token
     claim configured by the Entra admin. Confirm its emitted non-email value
     exactly matches the selected ServiceNow user field for the same employee;
   - a verified custom claim is allowed only when its value exactly matches
     the selected field. Do not collect or persist the employee value.
7. Open `All` → `User Administration` → `Users` and confirm a real signed-in
   test user has one matching Active record. Do not return the employee's
   identifier to the skill. Do not create a test user as part of this skill.

Do not use a Graph Connector app-only OIDC configuration. Use the Application
client ID, not the object ID, `api://` URI, connector app ID, secret, or
certificate.

## Completion signal and evidence

Ask exactly one completion question for the whole ServiceNow OIDC step. Render
`{CURRENT_PROGRESS}`, `{SERVICENOW_INSTANCE_URL}`, the verified App A client
ID, and tenant ID in this exact visible handoff payload. The question itself
must contain all seven operations:

<!-- visible-handoff-question:v1 -->
```json
[
  {
    "header": "ServiceNow OIDC",
    "question": "{CURRENT_PROGRESS}\n\nPurpose: make ServiceNow trust App A's delegated user token and resolve the signed-in employee to one matching Active ServiceNow user.\n\nOwner: ServiceNow `admin` or `security_admin`, elevated to `security_admin`.\n\nOpen this ServiceNow instance: {SERVICENOW_INSTANCE_URL}\n\nComplete or re-verify all seven operations:\n1. Elevate to `security_admin`; if **New** is missing, the role is not elevated.\n2. Open All -> System OAuth -> Application Registry -> New.\n3. Select `Configure an OIDC provider to verify ID tokens`. If unavailable after elevation, stop and confirm tenant OIDC / Multi-Provider SSO capability; do not guess a plugin or record completion.\n4. Create or reuse `Microsoft Entra ID - ESS Copilot` with the verified App A client ID and Active state only after the admin inspects whether this tenant metadata URL is already used and whether it belongs to a Knowledge/Graph Connector app-only integration. ServiceNow versions and tenant policies differ, so do not assume a universal one-provider limit; honor the current tenant's metadata uniqueness/provider-reuse constraints. Keep entity name, client ID, audience, and token purpose distinct. Do not duplicate the same metadata into a second provider merely to look distinct, reuse a Graph Connector app-only user mapping as the Power Platform delegated-user mapping, or invent a different metadata URL. If the requirements conflict and the ServiceNow/security admin cannot identify a supported coexistence configuration, STOP, choose Not yet, and do not attest Completed. If a client-secret field is required, enter a tenant-approved non-empty placeholder locally and never return it.\n5. Set metadata URL `https://login.microsoftonline.com/{tenant-id}/.well-known/openid-configuration`, cache lifespan `120`, Application `Global`, JTI verification disabled, and Scope Restriction `Broadly scoped`.\n6. Set the verified User Claim/User Field mapping: prefer `upn` to the matching UPN field (commonly `user_name`), or `email` to `email`. For a non-email/non-UPN identifier, use only the exact custom access-token claim configured by the Entra admin and verify its non-email value exactly matches the selected ServiceNow user field. Do not return the employee value.\n7. Confirm one real signed-in test user has one matching Active User record. Do not return that employee identifier or create a test user.\n\nDo not use a Graph Connector app-only setup, object ID, `api://` URI, connector app ID, secret, or certificate.\n\nHave you completed or re-verified the ServiceNow OIDC provider, claim mapping, and matching Active user checks?",
    "options": [
      { "label": "Completed", "recommended": true },
      { "label": "Not yet" }
    ],
    "allowFreeformInput": false
  }
]
```

Do not ask for or collect the claim
name, ServiceNow field name, employee identifier, mapping value, or other
identity data. While the question is pending, do not return an action result.
If the Maker selects **Not yet**, return `ACTION_RESULT = "waiting"` and do
not record phase completion.

After **Completed**, record one bounded bundled phase handoff:

```text
python scripts/connect_servicenow_da.py record-admin-phase --phase servicenow-oidc --status completed
```

Return `ACTION_RESULT = "recorded"` after the phase handoff is persisted. The
phase remains `Manual`, not a fake live `Passed`: this bounded structured
attestation proves only that the Maker completed or re-verified the entire
runbook in the current invocation. It does not prove an unseen admin action or
expose mapping data because no supported read-only ServiceNow security-object
API is used.

Source contract: PR #217 S4.3/S4.4 is authoritative. Microsoft Learn's current
ServiceNow connector User Login/OIDC setup is a secondary reference only.
