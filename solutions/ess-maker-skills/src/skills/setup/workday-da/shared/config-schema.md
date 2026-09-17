# Workday DA Setup — Config Persistence Schema

This file documents the **canonical shape** of the Workday connection config
that the `connect/workday-da` skill's steps read and write. It is a *reference
doc*, not an executable fragment — there are no Message blocks here. The steps
cite this file so they agree on field names, owners, and types.

**Canonical data file:** `.local/connect/workday-da/config.json`

Forked from the CEA `setup/shared/config-schema.md`. The field shapes are the
same; only the file path and the owning steps differ — DA has five steps
(DA-1 install, DA-2 Entra, DA-3 tenant, DA-4 Power Platform integration,
DA-5 runtime validation).

---

## Do NOT confuse the two config files

There are **two distinct** files. Keep them separate.

| File | Owner | Purpose |
|------|-------|---------|
| `.local/connect/workday-da/config.json` | the `connect/workday-da` skill | Workday connection state — URLs, tenant, Entra app, OAuth client, per-step status. **This schema.** |
| `.local/config.json` | foundation-setup + flightcheck | Agent identity, `dataverseEndpoint`, and the installed-agent inventory (`agent`/`agents`). `scripts/flightcheck/cli.py` reads this for the Dataverse endpoint. **Not this schema.** |

Never write Workday connection fields into `.local/config.json`, and never
write agent identity / `dataverseEndpoint` into
`.local/connect/workday-da/config.json`. The only crossover is read-only: a
step may *read* `.local/config.json` for `dataverseEndpoint` / `agent.botId`
when it needs them.

---

## Canonical fields

All fields live at the top level of `.local/connect/workday-da/config.json`
unless noted. A field is written **once** by its owner step and thereafter
read by later steps. Unknown/absent fields are treated as `null`.

### Connection + tenant (tenant URL captured early by DA-2; API-client fields by DA-3)

| Field | Type | Owner | Notes |
|-------|------|-------|-------|
| `baseUrl` | string | DA-2/DA-3 | Workday web host base URL (e.g. `https://wd2-impl.workday.com`). Captured early by DA-2 when the operator has the URL, else by DA-3. |
| `tenant` | string | DA-2/DA-3 | Workday tenant short name. Captured early by DA-2 to pin the Entra app deterministically, else by DA-3. |
| `tokenHost` | string | DA-2/DA-3 | Services host used to build token / REST URLs. Derived by DA-2 when the URL matches a known pattern, else by DA-3. |
| `oauthTokenUrl` | string | DA-3 | `https://{tokenHost}/ccx/oauth2/{tenant}/token`. |
| `restBaseUrl` | string | DA-3 | REST base, **trimmed to `/api`** — see `shared/connection-fields.md`. |
| `soapBaseUrl` | string | DA-3 | SOAP base (`https://{services-host}/ccx/service`). |
| `domainName` | string | DA-3 | Workday domain name, when discovered. |
| `tenantId` | string | DA-2 | **Entra** tenant ID (GUID) — set during Entra setup. |
| `installPath` | string | DA-3/DA-4 | `"simplified"`. |
| `migrationSource` | string | DA-4 | `"legacy-isu-raas"` when upgrading an existing legacy setup; absent for a fresh simplified setup. |
| `status` | string | all | `"in-progress"` \| `"configured"` \| `"ready"`. `"configured"` means setup values are recorded but runtime is not proven. Only DA-5 sets `"ready"` after a signed-in Workday scenario succeeds. |
| `verticals` | array[string] | DA-1 | Always `["hr"]` for this release. ESS DA IT is not supported by `/connect workday`. |
| `vertical` | string | DA-1 | Always `"hr"` for this release. |

### Entra app + OAuth client (owned by DA-2 / DA-3)

| Field | Type | Owner | Notes |
|-------|------|-------|-------|
| `entraSSO` | boolean | DA-2 | True once the SSO gallery app + connector authorization exist. |
| `entraAppId` | string | DA-2 | Entra app (client) ID. |
| `entraAppObjectId` | string | DA-2 | Entra app object ID (for Graph calls). |
| `entraAppIdUri` / `appIdUri` | string | DA-2 | Application ID URI (`api://{entraAppId}`). `appIdUri` is the documented alias. |
| `scopeGuid` | string | DA-2 | GUID of the exposed `user_impersonation` scope. |
| `oauthClientId` | string | DA-3 | Workday API **client ID** (distinct from `entraAppId`). |
| `tokenEndpoint` | string | DA-3 | OAuth token endpoint captured from the Workday API client view. Mirrors `oauthTokenUrl` when both are present. |

### Per-step status fields (owned by each step via the checklist-updater)

Each step records its own checkpoint outcomes under a `setupStatus` object,
keyed by **Step ID** (`DA1.1` … `DA5.1`) from the DA master checklist. This is
the durable record `shared/checklist-updater.md` reads and writes; the
rendered `.local/setup/workday-da/tasks.md` is the human-readable view of the
same data.

```json
{
  "setupStatus": {
    "DA1.1": { "state": "done", "checkpoint": "WD-DA-PKG-001", "gate": "prog", "verifiedBy": "programmatic" },
    "DA2.1": { "state": "pending", "checkpoint": "WD-CONN-102", "gate": "attest", "verifiedBy": null }
  }
}
```

- `state` ∈ `pending` \| `in-progress` \| `done` \| `blocked`.
- `gate` ∈ `prog` \| `manual` \| `attest` \| `advisory` (from the DA master
  checklist row).
- `verifiedBy` ∈ `programmatic` \| `attested` \| `reviewed` \| `null`. A
  `manual`/`attest` row is **never** set to `done` by a flightcheck pass
  alone — it needs an explicit user acknowledgement plus captured evidence
  (see `shared/checklist-updater.md` and `shared/permission-gate.md`, reused
  unchanged from CEA). An `advisory` row (no checkpoint) completes with
  `verifiedBy: "reviewed"` once its report has been shown; it never blocks.

---

## Power Platform integration state

DA-4 records manual evidence for connection references, parameter sharing,
binding, flow state, selected topics, and firewall allowlisting until reliable
DA-scoped APIs are available. It must not reuse CEA checkpoints as proof.
DA4.6 is the exception: its programmatic evidence comes from the checked-in
authorization script.

---

## Full example (mid-setup)

```json
{
  "baseUrl": "https://wd2-impl.workday.com",
  "tenant": "acme_dpt1",
  "tokenHost": "wd2-impl-services1.workday.com",
  "oauthTokenUrl": "https://wd2-impl-services1.workday.com/ccx/oauth2/acme_dpt1/token",
  "tokenEndpoint": "https://wd2-impl-services1.workday.com/ccx/oauth2/acme_dpt1/token",
  "restBaseUrl": "https://wd2-impl-services1.workday.com/ccx/api",
  "soapBaseUrl": "https://wd2-impl-services1.workday.com/ccx/service",
  "tenantId": "00000000-0000-0000-0000-000000000000",
  "installPath": "simplified",
  "verticals": ["hr"],
  "vertical": "hr",
  "entraSSO": true,
  "entraAppId": "11111111-1111-1111-1111-111111111111",
  "entraAppObjectId": "22222222-2222-2222-2222-222222222222",
  "appIdUri": "api://11111111-1111-1111-1111-111111111111",
  "scopeGuid": "33333333-3333-3333-3333-333333333333",
  "oauthClientId": "WORKDAY_CLIENT_ID",
  "status": "in-progress",
  "setupStatus": {
    "DA1.1": { "state": "done", "checkpoint": "WD-DA-PKG-001", "gate": "prog", "verifiedBy": "programmatic" }
  }
}
```

---

## Round-trip contract

Any step that writes a field listed above must:

1. **Read** the existing file first (it may already hold values from an
   earlier step).
2. **Merge** — set only the fields it owns; never drop fields it doesn't own.
3. **Write** the merged object back.

A value written by one step must read back identically in a later step (no
re-derivation, no format drift). The trim rules for `restBaseUrl` /
`soapBaseUrl` are defined once in `shared/connection-fields.md`.
