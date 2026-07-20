# Workday Setup — Config Persistence Schema (Shared)

This file documents the **canonical shape** of the Workday setup config that the
six Workday setup skills read and write. It is a *reference doc*, not an
executable fragment — there are no Message blocks here. The skills cite this file
so they agree on field names, owners, and types.

**Canonical data file:** `.local/connect/workday/config.json`

> This is the same working-copy path the connect flow uses for Workday state.
> The setup skills read and write it directly, extending it with additional
> fields — they do not introduce a parallel `my/...` file.

---

## Do NOT confuse the two config files

There are **two distinct** files. Keep them separate.

| File | Owner | Purpose |
|------|-------|---------|
| `.local/connect/workday/config.json` | the connect + setup skills | Workday connection state — URLs, tenant, Entra app, OAuth client, per-skill status. **This schema.** |
| `.local/config.json` | onboarding + flightcheck | Agent identity + `dataverseEndpoint`. `scripts/flightcheck/cli.py` reads this for the Dataverse endpoint and agent list. **Not this schema.** |

Never write Workday connection fields into `.local/config.json`, and never write
agent identity / `dataverseEndpoint` into `.local/connect/workday/config.json`.
The only crossover is read-only: a setup skill may *read* `.local/config.json`
for `dataverseEndpoint` / `agent.botId` when it needs them (see skill-5,
`workday/install-workday-extension-pack.md`).

---

## Canonical fields

All fields live at the top level of `.local/connect/workday/config.json` unless
noted. A field is written **once** by its owner step and thereafter read by
later steps. Unknown/absent fields are treated as `null`.

### Connection + tenant (tenant URL captured early by skill-3; API-client fields by skill-4 — see S4.2)

| Field | Type | Owner | Notes |
|-------|------|-------|-------|
| `baseUrl` | string | skill-3/4 | Workday web host base URL (e.g. `https://wd2-impl.workday.com`). Captured early by skill-3 when the operator has the URL, else by skill-4. |
| `tenant` | string | skill-3/4 | Workday tenant short name. Captured early by skill-3 to pin the Entra app deterministically, else by skill-4. |
| `tokenHost` | string | skill-3/4 | Services host used to build token / REST URLs. Derived by skill-3 when the URL matches a known pattern, else by skill-4. |
| `oauthTokenUrl` | string | skill-4 | `https://{tokenHost}/ccx/oauth2/{tenant}/token`. |
| `restBaseUrl` | string | skill-4 | REST base, **trimmed to `/api`** — see `connection-fields.md`. |
| `soapBaseUrl` | string | skill-4 | SOAP base (`https://{services-host}/ccx/service`). Captured for skill-5. |
| `domainName` | string | skill-4 | Workday domain name, when discovered. |
| `tenantId` | string | skill-3 | **Entra** tenant ID (GUID) — set during Entra setup. |
| `installPath` | string | skill-4 | `"simplified"` for the setup skills (legacy is out of scope here). |
| `status` | string | all | `"in-progress"` \| `"connected"`. |

### Entra app + OAuth client (owned by skill-3 / skill-4)

| Field | Type | Owner | Notes |
|-------|------|-------|-------|
| `entraSSO` | boolean | skill-3 | True once the SSO gallery app + connector authorization exist. |
| `entraAppId` | string | skill-3 | Entra app (client) ID. |
| `entraAppObjectId` | string | skill-3 | Entra app object ID (for Graph calls). |
| `entraAppIdUri` / `appIdUri` | string | skill-3 | Application ID URI (`api://{entraAppId}`). `appIdUri` is the documented alias. |
| `scopeGuid` | string | skill-3 | GUID of the exposed `user_impersonation` scope. |
| `oauthClientId` | string | skill-4 | Workday API **client ID** (distinct from `entraAppId`). |
| `tokenEndpoint` | string | skill-4 | OAuth token endpoint captured from the Workday API client view. Mirrors `oauthTokenUrl` when both are present. |

### Per-skill status fields (owned by each skill via the checklist-updater)

Each setup skill records its own checkpoint outcomes under a `setupStatus`
object, keyed by **Step ID** (`S1.1` … `S6.3`) from the master setup checklist.
This is the durable record the checklist-updater (`checklist-updater.md`) reads
and writes; the rendered `.local/setup/workday/tasks.md` is the human-readable
view of the same data.

```json
{
  "setupStatus": {
    "S3.2": { "state": "done", "checkpoint": "WD-ENTRA-SCOPE-001", "gate": "prog", "verifiedBy": "programmatic" },
    "S4.1": { "state": "pending", "checkpoint": "WD-API-CLIENT-001", "gate": "attest", "verifiedBy": null }
  }
}
```

- `state` ∈ `pending` \| `in-progress` \| `done` \| `blocked`.
- `gate` ∈ `prog` \| `manual` \| `attest` \| `advisory` (from the master checklist row).
- `verifiedBy` ∈ `programmatic` \| `attested` \| `reviewed` \| `null`. A
  `manual`/`attest` row is **never** set to `done` by a flightcheck pass alone —
  it needs an explicit user acknowledgement plus captured evidence (see
  `checklist-updater.md` and `permission-gate.md`). An `advisory` row (no
  checkpoint) completes with `verifiedBy: "reviewed"` once its report has been
  shown; it never blocks.

### Optional ready-made-topics state (owned by the OOTB-topics installer)

The optional installer offered between skill-5 and skill-6
(`install-workday-ootb-topics.md`) is **not** a tracked `setupStatus` row — it
records its own state under a top-level `ootbTopics` object so the router never
re-prompts once the user has installed or declined.

```json
{
  "ootbTopics": {
    "state": "installed",
    "selected": ["msdyn_HRWorkdayHCMEmployeeGetVacationBalance"],
    "installed": ["msdyn_HRWorkdayHCMEmployeeGetVacationBalance"]
  }
}
```

- `state` ∈ `pending` (unset — offer not yet answered) \| `in-progress`
  (selection made, mid-install) \| `installed` \| `declined`.
- `selected` — scenario names the user chose to add (may be mid-install).
- `installed` — scenario names actually pushed to the environment.

The router treats `installed` and `declined` as terminal (skip the offer);
any other value (including unset) means "offer not yet resolved". Owned solely by
the installer; other skills only read it.

---

## Full example (simplified path, mid-setup)

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
  "entraSSO": true,
  "entraAppId": "11111111-1111-1111-1111-111111111111",
  "entraAppObjectId": "22222222-2222-2222-2222-222222222222",
  "appIdUri": "api://11111111-1111-1111-1111-111111111111",
  "scopeGuid": "33333333-3333-3333-3333-333333333333",
  "oauthClientId": "WORKDAY_CLIENT_ID",
  "status": "in-progress",
  "setupStatus": {
    "S3.2": { "state": "done", "checkpoint": "WD-ENTRA-SCOPE-001", "gate": "prog", "verifiedBy": "programmatic" }
  }
}
```

---

## Round-trip contract

Any setup skill that writes a field listed above must:

1. **Read** the existing file first (it may already hold values from connect or
   an earlier skill).
2. **Merge** — set only the fields it owns; never drop fields it doesn't own.
3. **Write** the merged object back.

A value written by one skill must read back identically in a later skill (no
re-derivation, no format drift). The trim rules for `restBaseUrl` /
`soapBaseUrl` are defined once in `connection-fields.md`.
