# Plan: Skill 3 — `provision-workday-entra-app`

**Role:** App / Cloud App Administrator (a **consent-capable** role — Application Administrator,
Cloud Application Administrator, Privileged Role Administrator, or Global Administrator — is
required to grant admin consent) · Part of [Workday Setup](./README.md).
**Depends on:** [`shared-building-blocks`](./shared-building-blocks.md),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md),
[`master-checklist`](./master-checklist.md).

## Purpose

Configure the Microsoft Entra app registration for the Workday SSO integration so the agent
can call Workday on behalf of the signed-in user. **Graph-first** — almost every step is
Microsoft Graph (GA), so this skill drives it programmatically — **with a mandatory per-step
portal fallback**. This *extends* the mixed pattern already in `connect/workday/step2.md` (which
uses `az rest` Graph calls and already falls back to the portal for the not-authorized /
portal-only cases) so that **every** step has a fallback — because permission/tenant-policy and
quoting failures are common. Two sub-steps are **not** cleanly Graph-settable and are explicit
gates: the **SAML signing option** (portal-required) and the **NameID claim** (needs a
`claimsMappingPolicy` create+assign, not a one-liner).

## Phases

### Entra SSO gallery app *(Graph-first + portal fallback)*
- Per the [Workday SSO tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial):
  - **Graph (GA):** instantiate the Workday gallery app (`applicationTemplates/{id}/instantiate`);
    set `preferredSingleSignOnMode = saml`; set **Identifier/Entity ID + reply/sign-on/logout
    URLs**; add the **token-signing certificate** (`addTokenSigningCertificate`) **and activate
    it** by setting `preferredTokenSigningKeyThumbprint` (capture thumbprint + expiry).
  - **NameID claim (`user.mail`/UPN):** Graph-doable but only via a **`claimsMappingPolicy`
    create + assign to the service principal** — scope this as its own verified sub-step (no
    in-repo precedent; mark portal/manual if the policy route proves brittle in testing).
  - **"Sign SAML response and assertion" signing option:** **portal-required** — no documented
    Graph property (beta `samlSingleSignOnSettings` exposes only `relayState`). Explicit manual
    gate + verify. A Workday SP that validates signatures will reject the assertion if this is
    wrong, so it must not be silently skipped.
- Every Graph step carries a **portal fallback** for permission/tenant-policy failures.

### Core — connector configuration *(Graph GA; consent-capable role)*
- Expose the `user_impersonation` API scope (`api.oauth2PermissionScopes`).
- Pre-authorize the **Workday** connector **`4e4707ca-5f53-46a6-a819-f7765446e6ff`**
  (`api.preAuthorizedApplications`) via the parameterized shared helper — **never** the
  generic `c26b24aa`.
- Add Microsoft Graph delegated permissions `openid`, `profile`, `User.Read`
  (`requiredResourceAccess`).
- **Grant admin consent via Graph** (create the `oauth2PermissionGrant`) — requires the caller
  to hold a consent-capable role. If not, emit a named-role error and **escalate to manual
  consent**; don't hard-fail silently.
- **Assign the enterprise app** (`appRoleAssignedTo`): if `appRoleAssignmentRequired`, assign
  the maker/test user (preferably the ESS user group), else mark explicitly not-required.
- Capture the **App ID URI** (Entra resource URL) into config.

## Permission gating

- Connector config without an app-management role (Application Administrator / Cloud
  Application Administrator / app owner) → named error + stop.
- Admin consent without a **consent-capable** role (App Admin / Cloud App Admin / Privileged
  Role Admin / Global Admin) → named error naming those roles + **escalate to manual consent**
  (automated when privileged, manual fallback — consistent with the master checklist).

## Validity fix (called out for challenge)

- `app-registration.md` today calls a connector-authorization step with the connector ID
  effectively hardcoded and carries a **misleading comment** that conflates the generic
  `c26b24aa` connector with Workday. This skill does **not** treat that as a ServiceNow bug
  (`c26b24aa` is the *correct* ServiceNow connector). Instead it: (a) **parameterizes connector
  selection** through the shared helper from
  [`shared-building-blocks`](./shared-building-blocks.md) so Workday passes `4e4707ca` and
  ServiceNow passes `c26b24aa`, and (b) **corrects the misleading comment**. Net effect: de-dup
  + accuracy, no behavior change for the ServiceNow path.

## Verification

- **Reuse existing simplified-aware checkpoints** where they already cover skill-3's outputs:
  `WD-CONN-102` (Workday SAML **signing-certificate health**) and `WD-CONN-010` (Entra↔Workday
  **federation alignment**) — both run Graph-only pre-deploy. Only mint genuinely-new IDs:
  `WD-ENTRA-SCOPE-001` (scope exposed + `4e4707ca` pre-authorized + Graph perms),
  `WD-ENTRA-CONSENT-001` (admin consent granted), `WD-ASSIGN-001` (enterprise-app assignment or
  "not required"), `WD-ENTRA-NAMEID-001` and `WD-ENTRA-SIGNOPT-001` (the two at-risk SAML
  sub-steps).
  Run each individually; updates master checklist rows.

## Acceptance criteria

- App exposes `user_impersonation`, authorizes `4e4707ca`, has the three Graph perms, admin
  consent is granted, and enterprise-app assignment is satisfied (or marked not-required) —
  each independently verifiable by a single checkpoint.
- SSO gallery app is **Graph-first with a portal fallback per step**; the **signing option** is
  a portal-required gate and **NameID** is a verified `claimsMappingPolicy` create+assign — both
  explicitly tracked, never silently skipped.
- Token-signing cert is added **and activated** (`preferredTokenSigningKeyThumbprint`); skill-4
  verifies Workday's uploaded cert matches that thumbprint.
- App ID URI persisted for downstream skills (4 and 5).
