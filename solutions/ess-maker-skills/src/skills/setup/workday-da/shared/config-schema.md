<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Workday connect state contract

The only writable lifecycle state is:

```text
.local/connect/workday-da/config.json
```

`scripts/workday_connect_store.py` owns locking, migration, validation, atomic
writes, and phase transitions. Skills must use `scripts/workday_connect.py`;
they must not edit this file directly or create a Markdown state mirror.

## Schema version 3

```json
{
  "schemaVersion": 3,
  "provider": "workday",
  "status": "in-progress",
  "scope": {},
  "identifiers": {},
  "endpoints": {},
  "operators": {},
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
- A relevant scope change invalidates the affected phase and all downstream
  phase state, evidence, handoffs, and approvals.
- A phase is complete only after the target has been reread and matching
  evidence exists for every compact required action.
- The provider status becomes `ready` only when all six phases are complete.

Schema-v2 or legacy row-based state is backed up to `config.pre-v3.json`
before one-time migration. Legacy Markdown task files, when present, are
historical snapshots and are never rewritten.
