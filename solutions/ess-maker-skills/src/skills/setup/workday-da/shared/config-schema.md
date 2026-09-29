<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday connect state contract

The only writable lifecycle state is:

```text
.local/connect/workday-da/config.json
```

`scripts/workday_connect_store.py` owns locking, migration, validation, atomic
writes, and phase transitions. Skills must use `scripts/workday_connect.py`;
they must not edit this file directly or create a Markdown state mirror.

## Schema version 6

```json
{
  "schemaVersion": 6,
  "provider": "workday",
  "status": "in-progress",
  "scope": {},
  "identifiers": {},
  "endpoints": {},
  "operators": {},
  "tenantFoundation": null,
  "lifecycle": {
    "correlationId": "random UUID",
    "startedAt": "UTC timestamp",
    "retryCount": 0,
    "resumeCount": 0,
    "journal": []
  },
  "phases": {},
  "migration": null,
  "updatedAt": "UTC timestamp"
}
```

- `scope` contains exact agent, Dataverse environment, architecture, package,
  Entra tenant, and Workday tenant targeting.
- `identifiers` contains non-secret Entra and Workday identifiers.
- `endpoints` contains validated non-secret Workday endpoints.
- `operators` contains safe account and tenant provenance.
- `tenantFoundation` contains reusable Entra and Workday administrator
  evidence scoped to one exact Entra tenant, Workday tenant, application,
  signing certificate, and endpoint set.
- `lifecycle` contains the bounded privacy-safe transition journal and its
  random correlation ID. It never contains free-form errors or customer data.
- `phases` contains exactly the six controller phases.

Each phase stores status, completed action keys, optional runtime approval,
evidence, current blocker, and updated time.

## Identifier invariant

These values are independent and must never be aliases:

| Field | Meaning | Format |
| --- | --- | --- |
| `identifiers.workdaySamlEntityId` | Workday SAML Service Provider ID and connector resource URL | `http://www.workday.com/{tenant}` |
| `identifiers.entraAppIdUri` | Entra exposed API Application ID URI | `api://{entraAppId}` |

## Persistence rules

- Never persist passwords, client secrets, access or refresh tokens, cookies,
  certificate bodies, private keys, or employee data.
- Persist account usernames and tenant IDs only as authentication provenance.
- Controller-owned runtime mutations must carry an exact plan hash.
- A relevant scope, identifier, endpoint, or operator change invalidates the
  owning deployment phase and downstream state, evidence, blockers, and
  approvals. It does not delete a previously captured tenant foundation.
- After a deployment reset, the exact Entra application must be reread. When
  that evidence still matches `tenantFoundation`, the Workday administrator
  phase is restored without asking the administrator to repeat configuration.
- Tenant-foundation evidence is never reused across a different Entra tenant,
  Workday tenant, application, SAML Service Provider ID, signing certificate,
  or endpoint set.
- A phase is complete only after the target has been reread and matching
  evidence exists for every compact required action.
- The provider status becomes `ready` only when all six phases are complete.

Schema-v2, schema-v3, schema-v4, schema-v5, or legacy row-based state is backed up to
`config.pre-v6.json` before one-time migration. When Entra and Workday
administrator phases were already complete, migration captures their evidence
as the reusable tenant foundation. A previously complete runtime phase is
reopened when it lacks live Workday topic activation evidence. Legacy Markdown
task files, when present, are historical snapshots and are never rewritten.
