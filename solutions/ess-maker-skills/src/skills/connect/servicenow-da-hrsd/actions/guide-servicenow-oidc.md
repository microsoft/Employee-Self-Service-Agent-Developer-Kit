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
5. In `OAuth OIDC Provider Configuration`, set:
   - metadata URL =
     `https://login.microsoftonline.com/<tenant-id>/.well-known/openid-configuration`;
   - cache lifespan = `120`;
   - Application = `Global`;
   - JTI verification = disabled.
6. Set `User Claim` and `User Field`:
   - preferred: `upn` → the ServiceNow field containing the same UPN,
     commonly `user_name`;
   - alternative: `email` → `email`;
   - a verified custom claim is allowed only when its value exactly matches
     the selected field.
7. Open `All` → `User Administration` → `Users` and confirm a real signed-in
   test user has one matching Active record. Do not return the employee's
   identifier to the skill. Do not create a test user as part of this skill.

Do not use a Graph Connector app-only OIDC configuration. Use the Application
client ID, not the object ID, `api://` URI, connector app ID, secret, or
certificate.

## Completion signal and evidence

Ask exactly one completion question for the whole ServiceNow OIDC step:

**Have you completed or re-verified the ServiceNow OIDC provider, claim
mapping, and matching Active user checks in this runbook?**

Offer only **Completed** and **Not yet**. Do not ask for or collect the claim
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
