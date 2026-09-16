<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# MOS Starter Package Setup

## Scope

This reference defines the safety and evidence contract for DA `/setup`'s fresh-install path: installing a new Dev agent from an entitled MOS ("AgentSchemaTemplates") starter package when the maker has no existing agent to connect. It separates read-only discovery, one guarded create, and one explicit ALM opt-in. It never publishes, promotes, removes components, or calls Dataverse.

`scripts/setup_mos_starter.py` owns discovery, one guarded create dispatch, a separately invoked ALM opt-in, and redacted response evidence. It has no persona/ISV matching, no `resolve` or `status` command, and no product-specific policy -- that judgment belongs to the maker and `src/skills/foundation-setup/da-mos-starter.md`. `setup_existing_da.py attach` (via `attach_existing_dev`) still owns component acquisition, projection, and canonical workspace completion. The executing session composes these operations; the script does not wrap them into a transaction.

## Current evidence

| Claim | Status |
| --- | --- |
| Listing uses `GET /copilotstudio/minimalBots/agentStarterPackages` with `api-version` and `pageSize` | Live-proven |
| The listing response is an object with a `packages` list and an optional `continuationToken` | Live-proven |
| The listing surface returns only public- and tenant-scoped `AgentSchemaTemplates` entries, not general agent inventory | Documented by the platform team; consistent with observed shape |
| An entitled Employee Self-Service package can be listed in a flighted TEST environment | Live-proven |
| The catalog can return the same package entry more than once | Live-observed; preserve service rows rather than silently deduplicating |
| `POST /copilotstudio/minimalBots/createFromStarterPackage` with `{"packageId":"..."}` creates from the exact selected package | Live-proven |
| Successful create returns HTTP 201 with `{botId, sourcePackage:{packageId,schemaName,version}}` | Live-proven |
| Catalog package revision and `sourcePackage.version` are distinct concepts and can differ | Live-proven (`1.0.6` catalog revision versus `1.0.0` source template in the observed run) |
| Current server source maps a starter-package collision to HTTP 409 | Source-confirmed; live 409 response remains pending |
| A created starter agent is not automatically opted into ALM | Live-proven |
| ALM opt-in uses the full fetched `BotEntity`, adds `configuration.settings["alm.isAlmEnabled"] = true`, and submits an empty `botComponentChanges` list through `PUT /api/{agentId}/components` | Live-proven |
| ALM opt-in persisted and advanced the BotEntity version on read-back | Live-proven |
| Existing-Dev validation and attachment remain separate and expose service-owned prerequisites | Live-proven |
| Direct native ALM import already creates agents from packages declaring `packageType: "templated"` | Live-proven, using the generic import path, not this surface |

Do not describe a pending-validation claim as supported behavior. In particular, 409 collision semantics, non-TEST behavior, and product-specific package availability remain open runtime evidence.

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
9. End create after emitting a usable returned identity. Preserve catalog revision as `catalogPackageVersion` and the service-returned source template version as `templateVersion`; never conflate them.
10. Invoke ALM opt-in only after separate maker confirmation. Fetch the exact agent first, deep-copy and preserve its full `BotEntity`, change only `alm.isAlmEnabled`, and request no component changes.
11. Verify ALM through a second component fetch. A write response without persisted read-back is not success.
12. Return control after every operation. The existing `setup_existing_da.py attach` command remains the sole Dev validation, projection, and canonical-completion boundary.
13. If attachment reports a service-owned prerequisite, report it and stop. This path never publishes or removes components.
14. Keep response bodies, internal classifications, step IDs, and request details as diagnostic evidence. Translate supported facts into plain maker language; never render raw technical evidence as ordinary maker-facing copy.

## Durable command boundary

`scripts/setup_mos_starter.py` owns:

- target and ring resolution through the existing AgentBuilder helpers;
- read-only, paged starter-package discovery (`list`);
- an empty-workspace guard;
- the single attempt fuse;
- one non-retried, non-redirected create request (`create`);
- redacted, near-verbatim response evidence;
- extraction of a usable `{botId, sourcePackage.schemaName}` identity and optional source-template version;
- a deterministic fuse disposition based only on transport and response
  facts;
- separately invoked, full-BotEntity ALM opt-in with persisted read-back.

It does not:

- match text, persona, or ISV to a package;
- offer a `resolve` or `status` command;
- persist a receipt, a hash-keyed operation record, or a formal status
  taxonomy;
- validate or attach the returned Dev agent;
- fetch or project components itself;
- write canonical setup completion itself;
- install, configure, or infer any hybrid Dataverse extension;
- publish, deploy, promote, or remove components from the agent.

`create` and `enable-alm` are separate remotely mutating commands. Neither invokes the other or attachment. `list` never mutates. An accepted create response emits the returned identity but does not opt in, attach, or report setup complete. A successful `list` emits
`DA_MOS_STARTER_PACKAGES_JSON:` with a `packages` array plus a
`catalogWarnings` array, empty when every row was valid. A failed `list`
instead emits
`DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` and either
`DA_MOS_STARTER_LIST_RESPONSE_JSON:` or
`DA_MOS_STARTER_LIST_RESPONSE_TEXT:` before the CLI fails. For `create`,
it emits `DA_MOS_STARTER_CREATE_ANNOTATIONS_JSON:` followed by either
`DA_MOS_STARTER_CREATE_RESPONSE_JSON:` or
`DA_MOS_STARTER_CREATE_RESPONSE_TEXT:`, and finally
`DA_MOS_STARTER_CREATE_JSON:` on success. `enable-alm` emits
`DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:` and the redacted update response when
it writes, then `DA_MOS_STARTER_ALM_JSON:` only after successful read-back.
An already-enabled agent emits only the final result and performs no write.
A failed verification emits `DA_MOS_STARTER_ALM_VERIFY_ANNOTATIONS_JSON:`
with response evidence when available, or
`DA_MOS_STARTER_ALM_VERIFY_JSON:` when read-back completed but the setting
did not persist.

Create annotations report observed operation and fuse facts only. Listing failures emit
`DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` for HTTP, transport, and invalid-shape
failures; raw response evidence follows when the service returned one.

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
`setup_existing_da.py validate-agent`/`list-agents` commands). The fuse
remains after an accepted create response. Once attachment
writes canonical setup state, the empty-workspace guard independently
prevents another create; the fuse remains a plain audit note and does not
become a completion record.

### Fuse disposition matrix

| Observed outcome | Fuse disposition |
| --- | --- |
| Pre-dispatch failure (DNS, refused connection, connect timeout) | Removed |
| 2xx with a usable identity | Retained |
| 2xx that is malformed, non-JSON, or identifies a different source package | Retained |
| 3xx (redirects are disabled, so this is unexpected) | Retained |
| 400, 401, 403, 404, 409, 412, 422 (definitive normal rejection) | Removed |
| 408, 425, 429, 5xx, or any other uncertain response | Retained |
| Generic timeout, reset, or other ambiguous transport failure | Retained |

A connect timeout is treated as pre-dispatch only because `requests` proves the connection never completed. Every other timeout is conservatively kept as uncertain, because the service may already have received and acted on the request. Fuse disposition is evidence and a duplicate-mutation guard.

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
were used. Durable, machine-readable package/version persistence and read-back verification remain a formalization gap; see Open validation.

## Open validation

Remaining runtime coverage:

- HTTP 409 collision behavior for a package that already has a created
  agent in the target environment;
- explicit authentication rejection and ambiguous update transport behavior;
- pre-dispatch DNS/connect-refused classification against a live failure;
- behavior outside the TEST ring;
- HR, IT, and connected-system package availability;
- durable, machine-readable package/version persistence and read-back
  verification, to replace the session-transcript-only record above.
