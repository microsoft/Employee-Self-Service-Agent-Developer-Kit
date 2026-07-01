# TASK-004 — Dataverse Client

| Field      | Value                     |
| ---------- | ------------------------- |
| ID         | TASK-004                  |
| Workstream | 0 — Repository Foundation |
| Status     | TODO                      |
| Consumes   | —                         |

## Description

Implement the Dataverse client (the REST integration layer at
`src/core/outbound/`). This is the only layer permitted to communicate directly
with Dataverse. Business logic is out of scope.

The client module is named `dataverse_client.py`.

Authentication is **provided externally** (Dataverse Client-005): the client
accepts a valid bearer token and never acquires, refreshes, or persists it.
Tokens are produced by the Token Provider delivered in `TASK-008`; this task
depends on it. The `AuthenticationClient` obtains a fresh token from the
provider immediately before each request — for both reads and writeback — so a
long-running session never issues an expired token.

## Acceptance Criteria

- [ ] The client module is named `src/core/outbound/dataverse_client.py`.
- [ ] Authentication is provided externally via the Token Provider (TASK-008):
  the client accepts a fresh bearer token per request and never acquires,
  refreshes, or persists it.
- [ ] REST helper utilities are implemented.
- [ ] Dependency APIs, Component APIs, Layer APIs, Solution APIs, and Writeback
  APIs are exposed as Dataverse API Clients.
- [ ] All Dataverse communication is confined to `src/core/outbound/`.
- [ ] No business or migration logic is implemented in this layer.

## Deliverables

- REST helpers
- Dependency APIs
- Component APIs
- Layer APIs
- Solution APIs
- Writeback APIs

## References

- 02_ARCHITECTURE/DATAVERSE_CLIENT.md
- 04_EXECUTION/tasks/TASK-008-authentication-token-provider.md (Token Provider,
  consumed by this client for per-request tokens)
