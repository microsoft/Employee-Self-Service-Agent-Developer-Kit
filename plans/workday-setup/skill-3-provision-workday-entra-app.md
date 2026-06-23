# Plan: Skill 3 — `provision-workday-entra-app`

**Role:** App / Cloud App Administrator (a **consent-capable** role — Application Administrator,
Cloud Application Administrator, Privileged Role Administrator, or Global Administrator — is
required to grant admin consent) · Part of [Workday Setup](./README.md).
**Depends on:** [`shared-building-blocks`](./shared-building-blocks.md),
[`flightcheck-single-checkpoint`](./flightcheck-single-checkpoint.md),
[`master-checklist`](./master-checklist.md).

## Purpose

Configure the Microsoft Entra app registration for the Workday SSO integration so the agent
can call Workday on behalf of the signed-in user. **Fully automatable via Microsoft Graph —
no Entra portal clicks.** The only possible escalation is admin consent when the caller lacks
a consent-capable role.

## Phases

### Entra SSO gallery app *(fully automated via Graph)*
- Per the [Workday SSO tutorial](https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial):
  instantiate the Workday gallery app (`applicationTemplates/{id}/instantiate`), then via Graph
  set `preferredSingleSignOnMode = saml`, the **Identifier/Entity ID + reply/sign-on/logout
  URLs**, the **NameID claim** (`user.mail`/UPN), "sign SAML response and assertion", and add
  the **token-signing certificate** (`addTokenSigningCertificate`).
- **No Entra portal step is required** — it's all Graph. (The Workday-side consumption of the
  signing cert / SP-ID match is handled in [`skill-4`](./skill-4-configure-workday-tenant.md).)

### Core — connector configuration *(fully automated via Graph; consent-capable role)*
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

- Corrects the hardcoded wrong connector in `app-registration.md` by using the
  parameterized helper from [`shared-building-blocks`](./shared-building-blocks.md).

## Verification

- Flightcheck `AUTH-*` / new `WD-AUTH-*` checkpoints (scope exposed, connector authorized,
  Graph perms present, admin consent granted) + `WD-ASSIGN-*` (enterprise-app user/group
  assignment, or "not required"), run individually. Updates master checklist rows.

## Acceptance criteria

- App exposes `user_impersonation`, authorizes `4e4707ca`, has the three Graph perms, admin
  consent is granted, and enterprise-app assignment is satisfied (or marked not-required) —
  each independently verifiable by a single checkpoint.
- The entire Entra app (SSO gallery app + connector + Graph perms + assignment) is created
  **end-to-end via Graph**; the only possible escalation is admin consent when the caller
  lacks a consent-capable role.
- App ID URI persisted for downstream skills (4 and 5).
