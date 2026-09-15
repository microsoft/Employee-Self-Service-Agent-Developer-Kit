<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# MOS Starter Package Setup

## Scope

This reference defines the safety and evidence contract for DA `/setup`'s
fresh-install path: installing a new Dev agent from an entitled MOS
("AgentSchemaTemplates") starter package when the maker has no existing
agent to connect. It is create-only. It never replaces an existing agent,
never publishes, never promotes, and never calls Dataverse.

`scripts/setup_mos_starter.py` owns discovery, one guarded create dispatch,
and redacted response evidence. It has no persona/ISV matching, no
`resolve` or `status` command, and no product-specific policy -- that
judgment belongs to the maker and
`src/skills/foundation-setup/da-mos-starter.md`. `setup_existing_da.py
attach` (via `attach_existing_dev`) still owns component acquisition,
projection, and canonical workspace completion. The executing session
hands the logged create identity to that existing command instead of
extending the create transaction, and never calls
`validate_existing_dev_connection` separately.

## Current evidence

| Claim | Status |
| --- | --- |
| Listing uses `GET /copilotstudio/minimalBots/agentStarterPackages` with `api-version` and `pageSize` | Live-proven |
| The listing response is an object with a `packages` list and an optional `continuationToken` | Live-proven |
| The listing surface returns only public- and tenant-scoped `AgentSchemaTemplates` entries, not general agent inventory | Documented by the platform team; consistent with observed shape |
| The current catalog returns zero entitled ESS packages in every environment probed so far | Live-proven; a known upstream catalog issue, not a client defect |
| The create route accepts a selected package and hands it to native ALM as a create-only templated package | Stated in the planning record; not independently observed |
| `POST /copilotstudio/minimalBots/agentStarterPackages/{packageId}/create` with an empty JSON body is the create request | **Pending live validation.** |
| The create response uses the same `{cdsBotId, schemaName}` envelope as native ALM import | **Pending live validation.** |
| HTTP 409 means an agent from this package already exists (collision) | **Pending live validation.** |
| Direct native ALM import already creates agents from packages declaring `packageType: "templated"` | Live-proven, using the generic import path, not this surface |

Do not describe a pending-validation claim as supported behavior. No
environment with an entitled ESS starter package has been reachable, so
create dispatch has never been exercised live.
`AgentBuilderClient.create_agent_from_starter_package` is the single place
this assumption lives; its docstring carries the same pending-validation
note. Do not duplicate this assumption anywhere else.

### Why this endpoint and payload

The listing route (`agentStarterPackages`) is live-proven. This API
otherwise always exposes a mutating action as `{collection}/{id}/{verb}` on
an already-proven collection route (for example `alm/{cdsBotId}/export`,
`alm/{cdsBotId}/deploy`, `api/{cdsBotId}/publish`). Extending the proven
collection with `/{packageId}/create` is the leanest defensible guess, not
a confirmed contract. The body is empty JSON because the package ID is
already in the route. Revisit
`AgentBuilderClient.create_agent_from_starter_package` the moment a live
create call is exercised, and update this table alongside it.

## Safety invariants

1. Listing is always read-only and safe to call before any maker
   confirmation; it never mutates the target environment.
2. Resolve the environment and ring the same way every other DA setup path
   does; validate the exact environment-specific API host before sending a
   token.
3. `create` accepts only the exact package ID the maker already confirmed
   from `list` output. It never searches, matches, or guesses a package.
4. Create only. The client never supplies a replacement schema and never
   targets an existing agent.
5. Disable redirects for the mutating POST. It is never retried
   automatically.
6. Write the attempt fuse atomically and durably before the POST is ever
   dispatched.
7. `create_agent_from_starter_package` returns the raw response instead of
   raising or parsing it, so the wrapper can render near-verbatim,
   redacted evidence rather than losing response detail to a discarded
   exception.
8. Redact only secret-bearing fields and headers (recursively,
   case-insensitively); preserve every other field, message, and unknown
   detail as closely to verbatim as possible.
9. End the create transaction after emitting a usable returned identity.
   The executing session must pass that identity to the existing
   `setup_existing_da.py attach` command, which remains the sole Dev
   validation, projection, and canonical-completion boundary.

## Durable command boundary

`scripts/setup_mos_starter.py` owns:

- target and ring resolution through the existing AgentBuilder helpers;
- read-only, paged starter-package discovery (`list`);
- an empty-workspace guard;
- the single attempt fuse;
- one non-retried, non-redirected create request (`create`);
- redacted, near-verbatim response evidence;
- extraction of a usable `{cdsBotId, schemaName}` identity when present;
- a deterministic fuse disposition based only on transport and response
  facts.

It does not:

- match text, persona, or ISV to a package;
- offer a `resolve` or `status` command;
- persist a receipt, a hash-keyed operation record, or a formal status
  taxonomy;
- validate or attach the returned Dev agent;
- fetch or project components itself;
- write canonical setup completion itself;
- install, configure, or infer any hybrid Dataverse extension;
- publish, deploy, or promote the agent.

`create` is the only remotely mutating command. `list` never mutates. An
accepted create response emits the returned identity but does not attach
it or report setup complete. A successful `list` emits
`DA_MOS_STARTER_PACKAGES_JSON:` with a `packages` array plus a
`catalogWarnings` array, empty when every row was valid. A failed `list`
instead emits
`DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` and either
`DA_MOS_STARTER_LIST_RESPONSE_JSON:` or
`DA_MOS_STARTER_LIST_RESPONSE_TEXT:` before the CLI fails. For `create`,
it emits `DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:` followed by either
`DA_MOS_STARTER_CREATE_RESPONSE_JSON:` or
`DA_MOS_STARTER_CREATE_RESPONSE_TEXT:`, and finally
`DA_MOS_STARTER_CREATE_JSON:` on success.

## The attempt fuse

`create` writes a single plain-text file,
`.local/setup/mos-starter/create-attempted`, atomically (`O_CREAT|O_EXCL`)
and durably (fsynced) before it ever dispatches the POST. The file records
a UTC start time, the target environment ID, and the package ID/name/
version as an audit note; it is never parsed back for resume. If it
already exists, `create` refuses a second create outright -- it never
inspects the prior response itself. The maker's session is directed to
inspect its own persistent transcript for that response, then to reconcile
by read-only inspecting the target environment (the existing `list` and
`setup_existing_da.py validate-agent`/`list-agents` commands) before trying
again. The fuse remains after an accepted create response. Once attachment
writes canonical setup state, the empty-workspace guard independently
prevents another create; the fuse remains a plain audit note and does not
become a completion record.

### Fuse disposition matrix

| Observed outcome | Fuse | Safe next action |
| --- | --- | --- |
| Pre-dispatch failure (DNS, refused connection, connect timeout) | Removed | The request never reached the service; retry once the local/DNS/connection issue is resolved |
| 2xx with a usable identity | Retained | Run `setup_existing_da.py attach` with the logged identity and `--setup-source mos-starter`; do not create again |
| 2xx that is malformed or non-JSON (no usable identity) | Retained | Reconcile the target environment read-only; do not retry |
| 3xx (redirects are disabled, so this is unexpected) | Retained | Reconcile read-only; do not retry |
| 400, 401, 403, 404, 409, 412, 422 (definitive normal rejection) | Removed | 409 specifically means a collision: inspect the existing Dev agent instead of retrying; other codes may be retried after resolving the reported cause |
| 408, 425, 429, 5xx, or any other uncertain response | Retained | Reconcile read-only; do not retry |
| Generic timeout, reset, or other ambiguous transport failure | Retained | Reconcile read-only; do not retry |

A connect timeout is treated as pre-dispatch only because `requests` proves
the connection never completed. Every other timeout is conservatively kept
as uncertain, because the service may already have received and acted on
the request.

## Redaction contract

The printed response preserves field names, nesting, messages, details, and
unknown fields as closely to verbatim as possible. Matching is an exact,
normalized comparison (casefolded, separators stripped) against a fixed
list of secret-bearing names -- authorization, cookie/set-cookie,
access_token, refresh_token, id_token, password, secret/client_secret,
assertion, and API key variants including `x-api-key` -- never a
substring test, so a benign lookalike such as `secretaryName`,
`cookiePolicy`, or `authorizationStatus` is left untouched. A matching
field's entire value is replaced with `<redacted>`, recursively and
case-insensitively, by value only (never by key).

Every other string value -- including inside a JSON body, not only a
non-JSON one -- is still passed through the same small, fixed set of
token/credential patterns (a bearer-style scheme token, or a
secret-bearing `key: value`/`key=value` pair), so a credential embedded
in a benign field such as `message` cannot leak merely because its key
is not itself secret-named. Everything else in the text is preserved.
Request headers and tokens are never printed at all.

## Provenance

Canonical setup provenance is `mos-starter`
(`setup_existing_da.SETUP_SOURCE_PRIORITY`), ranked above `prod-to-dev`,
with selection evidence `mos-starter-result`, written only when the
executing session runs `setup_existing_da.py attach --setup-source
mos-starter`. The canonical setup schema is not extended with package
fields: this session's transcript (the printed annotations and response
evidence) is the only durable record of which package, name, and version
were used. Durable, machine-readable package/version persistence and
read-back verification remain a formalization gap pending the real
catalog/create contract; see Open validation.

## Open validation

Before treating this path as complete, validate:

- an entitled ESS starter package exists and is visible to the intended
  maker identity (the catalog currently returns zero items everywhere
  probed);
- the exact create endpoint, payload, and response envelope against a live
  service;
- HTTP 409 collision behavior for a package that already has a created
  agent in the target environment;
- pre-dispatch DNS/connect-refused classification against a live failure;
- behavior outside the TEST ring;
- durable, machine-readable package/version persistence and read-back
  verification, to replace the session-transcript-only record above.
