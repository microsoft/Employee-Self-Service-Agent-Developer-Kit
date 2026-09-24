<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# MOS Starter Package Setup

## Scope

This reference defines the safety and evidence contract for installing a new Dev agent from an entitled MOS ("AgentSchemaTemplates") starter package. A workspace may install multiple products into its one recorded Power Platform environment. The path separates read-only discovery, a guarded create request, and ALM enablement. It never publishes, promotes, removes components, or calls Dataverse.

`scripts/setup_mos_starter.py` owns discovery, one guarded create dispatch per explicit request identity, separately invoked ALM enablement, and response evidence. It has no persona/ISV matching, no `resolve` or `status` command, and no product-specific policy -- that judgment belongs to the maker and `src/skills/foundation-setup/da-mos-starter.md`. `setup_existing_da.py attach` (via `attach_existing_dev`) owns component acquisition, projection, and per-agent canonical workspace completion. The executing session composes these operations; the script does not wrap them into a transaction.

## Current evidence

| Claim | Status |
| --- | --- |
| Listing uses `GET /copilotstudio/minimalBots/agentStarterPackages` with `api-version` and `pageSize` | Live-proven |
| The listing response is an object with a `packages` list and an optional `continuationToken` | Live-proven |
| The listing surface returns only public- and tenant-scoped `AgentSchemaTemplates` entries, not general agent inventory | Documented by the platform team; consistent with observed shape |
| An entitled Employee Self-Service package can be listed in a flighted TEST environment | Live-proven |
| The catalog can return the same package entry more than once | Live-observed; preserve service rows rather than silently deduplicating |
| Existing-agent inventory and exact-agent responses expose no stable source-package identity to join against the catalog | Live-proven |
| `POST /copilotstudio/minimalBots/createFromStarterPackage` with `{"packageId":"..."}` creates from the exact selected package | Live-proven |
| Successful create returns HTTP 201 with `{botId, sourcePackage:{packageId,schemaName,version}}` | Live-proven |
| Catalog package revision and `sourcePackage.version` are distinct concepts and can differ | Live-proven (`1.0.6` catalog revision versus `1.0.0` source template in the observed run) |
| Current server source maps a starter-package collision to HTTP 409 | Source-confirmed; live 409 response remains pending |
| A created starter agent is not automatically opted into ALM | Live-proven |
| ALM opt-in uses the full fetched `BotEntity`, adds `configuration.settings["alm.isAlmEnabled"] = true`, and submits an empty `botComponentChanges` list through `PUT /api/{agentId}/components` | Live-proven |
| ALM opt-in persisted and advanced the BotEntity version on read-back | Live-proven |
| Direct Dev-route and component validation can materialize a newly created starter agent while published Dev configuration is absent | Live-proven in TEST |
| Existing-Dev validation and attachment remain separate and expose service-owned prerequisites | Live-proven |
| Direct native ALM import already creates agents from packages declaring `packageType: "templated"` | Live-proven, using the generic import path, not this surface |

Do not describe a pending-validation claim as supported behavior. In particular, non-TEST behavior and product-specific package availability remain open runtime evidence.

**Load-bearing assumption:** HTTP 409 means the selected package collides somewhere in the target environment, but it does not identify the corresponding agent. The UX therefore asks the maker to choose an existing visible Dev agent and does not infer a package-to-agent association.

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
6. Write request-scoped attempt evidence durably before the POST is ever
   dispatched. Environment ID, exact package ID, and a maker-confirmed client
   request UUID identify that attempted mutation.
7. `create_agent_from_starter_package` returns the response so the wrapper can emit the response body as script output.
8. Emit a JSON response as JSON and any other response as text.
9. End create after emitting a usable returned identity. Preserve catalog revision as `catalogPackageVersion` and the service-returned source template version as `templateVersion`; never conflate them.
10. Invoke ALM enablement only after a successful create response in the confirmed setup flow. Fetch the exact agent first, deep-copy and preserve its full `BotEntity`, change only `alm.isAlmEnabled`, and request no component changes.
11. Verify ALM through a second component fetch. A write response without persisted read-back is not success.
12. Return control after every operation. The existing `setup_existing_da.py attach` command remains the sole Dev validation, projection, and canonical-completion boundary. For a newly created starter agent, pass the create response's schema name and validate the direct Dev route plus fetched component identity without requiring published Dev configuration.
13. If attachment reports a service-owned prerequisite, report it and stop. Publishing is not attachment remediation for this path; foundation setup never publishes or removes components.
14. Keep response bodies, internal classifications, step IDs, and request details as diagnostic evidence. Translate supported facts into plain maker language; never render raw technical evidence as ordinary maker-facing copy.

## Durable command boundary

`scripts/setup_mos_starter.py` owns:

- target and ring resolution through the existing AgentBuilder helpers;
- read-only, paged starter-package discovery (`list`);
- same-environment workspace validation;
- request-scoped create-attempt evidence;
- one non-retried, non-redirected create request (`create`);
- response evidence;
- extraction of a usable `{botId, sourcePackage.schemaName}` identity and optional source-template version;
- a deterministic fuse disposition based only on transport and response
  facts;
- separately invoked, full-BotEntity ALM opt-in with persisted read-back.

It does not:

- match text, persona, or ISV to a package;
- offer a `resolve` or `status` command;
- persist a service receipt or formal workflow status taxonomy;
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
`DA_MOS_STARTER_ALM_ANNOTATIONS_JSON:` and the update response when
it writes, then `DA_MOS_STARTER_ALM_JSON:` only after successful read-back.
An already-enabled agent emits only the final result and performs no write.
A failed verification emits `DA_MOS_STARTER_ALM_VERIFY_ANNOTATIONS_JSON:`
with response evidence when available, or
`DA_MOS_STARTER_ALM_VERIFY_JSON:` when read-back completed but the setting
did not persist.

Create annotations report observed operation and fuse facts only. Listing failures emit
`DA_MOS_STARTER_LIST_ANNOTATIONS_JSON:` for HTTP, transport, and invalid-shape
failures; raw response evidence follows when the service returned one.

## Request-scoped create evidence

`create` writes a plain-text file at
`.local/setup/mos-starter/create-attempts/{environmentId}/{packageKey}/{clientRequestId}.txt`
atomically (`O_CREAT|O_EXCL`) and durably (fsynced) before it dispatches the
POST. The file records a UTC start time, target environment ID, client request
ID, and package ID/name/version as an audit note; it is never parsed back for
resume. If that exact request file exists, `create` refuses another dispatch.
The maker's session uses its persistent transcript and read-only environment
inspection to reconcile uncertainty. A separately confirmed create uses a new
client request UUID and independent evidence. Attachment and FlightChecks do
not remove prior create evidence.

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

A connect timeout is treated as pre-dispatch only because `requests` proves the connection never completed. Every other timeout is conservatively kept as uncertain, because the service may already have received and acted on the request. Request-evidence disposition is a duplicate-mutation guard for that exact request identity.

## Response evidence

Response markers contain the service response body. Valid JSON bodies are emitted as JSON; other bodies are emitted as text. Request headers are not part of the response-body output.

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

- the exact service meaning and response shape of HTTP 409 for a selected
  package collision;
- explicit authentication rejection and ambiguous update transport behavior;
- pre-dispatch DNS/connect-refused classification against a live failure;
- behavior outside the TEST ring;
- HR, IT, and connected-system package availability;
- durable, machine-readable package/version persistence and read-back
  verification, to replace the session-transcript-only record above.
