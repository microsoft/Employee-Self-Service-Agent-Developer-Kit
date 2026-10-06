<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Workday connect state contract

The only writable lifecycle state is:

```text
.local/connect/workday-da/config.json
```

`scripts/workday_connect_store.py` owns locking, migration backup and
invocation, validation, atomic writes, and durable phase transitions.
`scripts/workday_connect_migrations.py` owns every pure legacy and schema-v2
through schema-v9 transformation; it never reads or writes the state file.
`scripts/workday_connect_state_policy.py` owns shared pure reset, invalidation,
and tenant-foundation comparisons used by persistence and migration. Skills
must use `scripts/workday_connect.py`; they must not edit this file directly
or create a Markdown state mirror.

## Schema version 10

```json
{
  "schemaVersion": 10,
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
    "phaseDurationsMs": {},
    "activePhaseStartedAt": {},
    "eventMarkers": [],
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
  random current correlation ID. Each journal record retains the correlation
  ID active when that event occurred. Changing an existing target environment,
  agent identity, Entra tenant, or Workday tenant rotates the current ID while
  preserving bounded prior history. Cumulative phase durations, active segment
  starts, and once-per-lifecycle markers are retained separately so trimming
  the journal cannot change lifecycle behavior. Blocked events may retain a
  bounded `WD-E2E-NNN` remediation ID. The journal never contains free-form
  errors or customer data.
- `phases` contains exactly the six controller phases.

Each phase stores status, completed action keys, optional runtime approval,
evidence, current blocker, and updated time. The Entra and Workday
administrator phases also store:

```json
{
  "administrator": {
    "substage": "not-started",
    "partialEvidence": {},
    "invalidFields": [],
    "updatedAt": null
  }
}
```

The bounded substages are `not-started`, `administrator-engaged`,
`handoff-presented`, `awaiting-completion`, `completion-confirmed`,
`collecting-evidence`, and `evidence-validated`. Each transition advances by
at most one substage; exact replay is allowed. Only allow-listed, non-secret
fields may enter
`partialEvidence`. Invalid fields are removed from partial evidence and
reopened without discarding valid sibling values.

## Identifier invariant

These values are independent and must never be aliases:

| Field                             | Meaning                                                     | Format                            |
| --------------------------------- | ----------------------------------------------------------- | --------------------------------- |
| `identifiers.workdaySamlEntityId` | Workday SAML Service Provider ID and connector resource URL | `http://www.workday.com/{tenant}` |
| `identifiers.entraAppIdUri`       | Entra exposed API Application ID URI                        | `api://{entraAppId}`              |

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

Schema-v2 through schema-v9, or legacy row-based state, is backed up to
`config.pre-v10.json` before one-time migration. Schema-v6 administrator
evidence is preserved as safe partial evidence, while Entra and downstream
phases reopen for the expanded directory, application-pairing, federation, and
least-privilege checks. A previously complete runtime phase is reopened when
it lacks live Workday runtime-template wiring or topic-activation evidence.
Schema-v8 package verification evidence moves from Preflight to Connections
so an existing installation is reused without repeating package installation.
Schema-v9 completed employee evidence with a valid timezone-qualified
timestamp is converted to a grandfathered `maker-smoke-test` completion
record. In-progress employee runtime-evidence attempts are cleared and resume
at Maker validation because run-history windows cannot identify the
conversation that initiated a flow.
Legacy Markdown task files, when present, are historical snapshots and are
never rewritten.
