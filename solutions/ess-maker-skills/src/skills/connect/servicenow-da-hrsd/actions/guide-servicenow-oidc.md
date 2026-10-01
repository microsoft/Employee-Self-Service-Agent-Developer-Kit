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

1. Open **All -> System OAuth -> Application Registry -> New** and confirm
   **Configure an OIDC provider to verify ID tokens** is available. If it is
   unavailable, enable the tenant-supported OIDC or Multi-Provider SSO
   capability before continuing.
2. From the profile menu, select **Elevate role** and elevate to
   `security_admin`. If **New** is missing in the security configuration, the
   role is not elevated.
3. Open **All -> System OAuth -> Application Registry -> New -> Configure an
   OIDC provider to verify ID tokens**.
4. Reuse the exact valid ESS OIDC entity when the ServiceNow Admin confirms it
   matches the verified App A and settings below. Otherwise create or repair
   the missing or unhealthy entity:
   - Client ID = verified App A Application client ID;
   - if the form requires **Client secret**, the connector does not use that
     value for this flow; the admin enters a tenant-approved placeholder
     locally and never returns or persists it;
   - entity Active.
5. In **OAuth OIDC Provider Configuration**, set:
   - metadata URL =
     `https://login.microsoftonline.com/<tenant-id>/.well-known/openid-configuration`;
   - cache lifespan = `120`;
   - Application = `Global`;
   - JTI verification = disabled.
6. Set **User Claim** and **User Field**. Prefer `upn` mapped to the
   ServiceNow field containing the same UPN (commonly `user_name` or `email`).
   An evidence-based alternative is allowed only when claim and field values
   match exactly.
7. Open **All -> User Administration -> Users** and confirm a real signed-in
   test user has one matching Active record. Do not return the employee's
   identifier to the skill. Do not create a test user as part of this skill.

Do not use a Graph Connector app-only OIDC configuration. Use the Application
client ID, not the object ID, `api://` URI, connector app ID, secret, or
certificate.

## Completion signal and evidence

Ask one completion question for the whole ServiceNow OIDC step. Accept one
structured response such as `upn, user_name` after the Maker confirms that
OIDC capability is available, the entity is Active, and one matching Active
user exists. While the question is pending, do not return an action result. If
the admin is not done or answers **Not sure**, return
`ACTION_RESULT = "waiting"`.

After verification or completion, record one bundled phase handoff. Use
`reused` for a valid existing mapping and `completed` when configuration or
repair was required:

```text
python scripts/connect_servicenow_da.py record-admin-phase --phase servicenow-oidc --status <completed|reused> --claim <claim> --user-field <field>
```

Return `ACTION_RESULT = "recorded"` after the phase handoff is persisted. The
phase's `Manual` result is structured attestation because no supported
read-only ServiceNow security-object API is used.
