<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Native DA ALM Import

## Scope

This reference defines the safety and evidence contract for explicit native
Declarative Agent package import. It supports advanced package handoffs and
Prod-to-Dev composition. It is not a normal maker-facing setup option and does
not replace the existing editable-Dev setup path.

The durable import command owns only package observation, one guarded mutation,
safe outcome persistence, and direct identity verification. Existing-Dev setup
owns component acquisition, projection, checkpointing, refresh, and canonical
workspace completion.

## Service evidence

| Claim | Status |
| --- | --- |
| Import uses `POST /copilotstudio/minimalBots/alm/import` | Live-proven in TEST |
| The request uses multipart form data with one binary `package` part | Live-proven in TEST |
| Omitting `schemaName` requests create-only behavior | Live-proven through successful create and HTTP 409 collision |
| Supplying a directly validated Dev schema requests replacement | Live-proven in TEST |
| Replacement can retain the same agent ID and schema | Live-proven in TEST |
| Successful import returns `cdsBotId` and `schemaName` synchronously | Live-proven in TEST |
| Direct import can accept a package declaring `packageType: templated` | Live-proven in TEST |
| A package can fail because a target connection is inaccessible | Live-proven in TEST |
| Replacement is atomic under every service-side failure | Unknown |
| Direct templated-package import is a supported product policy | Unknown |
| Interrupted requests can always be reconciled automatically | Unknown |
| A supported targeted cleanup operation is available | Unknown |
| Import behavior outside TEST matches the observed contract | Unknown |

Do not describe an unknown claim as supported behavior.

## Safety invariants

1. Resolve the environment and ring from a recognized Copilot Studio URL when
   available.
2. Validate the exact environment-specific API host before sending a token.
3. Validate local projection dependencies before remote mutation.
4. Observe package type, schema, and SHA-256 without extracting or rewriting
   package content.
5. Do not print package content, tokens, response bodies, or service
   diagnostics.
6. Do not automatically retry the mutating POST.
7. Disable redirects for the mutating POST.
8. Create by omitting `schemaName`; never send an empty replacement value.
9. Never convert a collision into replacement implicitly.
10. Before replacement, directly validate the exact existing agent as editable
    Dev and obtain approval for that same identity.
11. Persist safe operation evidence before relying on downstream parsing,
    verification, or workspace work.
12. Treat malformed success and response loss as unresolved outcomes, not
    permission to post again.
13. Directly verify the returned agent ID and schema before handing it to
    existing-Dev setup.
14. Keep workspace acquisition and projection out of the import transport.

## Durable command boundary

`scripts/setup_alm_import.py` owns:

- target and ring resolution through existing AgentBuilder helpers;
- local projection-runtime preflight;
- bounded package inspection;
- replacement confirmation and direct Dev validation;
- one non-retried, non-redirected import request;
- per-operation records under `.local/setup/alm-import/`;
- response classification;
- direct verification of the returned identity.

It does not:

- select an existing agent after collision;
- decide whether replacement is desired;
- fetch or project components;
- checkpoint or replace local files;
- write canonical setup completion;
- publish or deploy the agent.

The command emits `DA_ALM_IMPORT_JSON:`. A successful payload contains the
validated context required by `setup_existing_da.py attach`; those values are
internal command inputs and are not maker-facing output.

## Outcome contract

| `kind` | Meaning | Safe next action |
| --- | --- | --- |
| `success` | The service returned an identity and direct Dev validation agreed | Continue through existing-Dev attachment |
| `imported-unverified` | The import returned and persisted a usable identity, but direct Dev verification did not finish | Resolve the reported verification prerequisite, then rerun the identical command to resume verification without another POST |
| `conflict` | Create-only protection found an existing agent | Use the existing agent or separately approve exact replacement |
| `rejected` | The service returned a normal non-409 error | Resolve the reported prerequisite; do not retry automatically |
| `pre-dispatch-failure` | The request did not reach the service | Resolve the local, DNS, or connection failure |
| `invalid-success` | A success response lacked a usable identity | Reconcile the environment; do not post again |
| `ambiguous` | Dispatch may have occurred without a classified response | Reconcile the environment; do not post again |

Repeating an operation returns its cached outcome without another POST.
`--retry-safe-failure` is permitted only for a recorded normal rejection or
pre-dispatch failure, after its cause is resolved and the maker approves a new
request. It never permits retry of an ambiguous or invalid-success outcome.

## Replacement contract

Replacement requires all of the following:

- an exact environment;
- a directly addressable editable Dev agent;
- the directly validated schema for that agent;
- explicit approval naming the agent;
- matching `--replace-agent-id` and `--confirm-replace-agent-id` values.

The service receives the validated schema, not the agent ID. The returned
`cdsBotId` and `schemaName` must still match the approved target. Identity drift
is a hard failure recorded after the response; it must not trigger another
POST.

## Receipt and recovery contract

Each operation has a deterministic record derived from its safe input identity:

- environment, tenant, host, ring, and API version;
- package SHA-256, declared type, and schema;
- create or replacement mode;
- replacement agent ID and schema when applicable.

Records never contain tokens, package paths, package content, or raw response
bodies.

An `imported` record means the service returned a usable identity but direct
verification did not finish. Rerunning resumes verification without replaying
the import. A `verified` record returns the cached verified result. An
unresolved record blocks replay of that same operation. Records are evidence,
not a global workflow lock; the session interprets unrelated records before
selecting another operation.

For create-only recovery, `--resume-create-after-cleanup` with the expected
ALM-family identity can resume direct verification or return the verified
result for the sole matching create after its disposable package has already
been removed. This explicit recovery does not inspect another package, send
another import request, or apply to replacement.

### Recover an imported but unverified agent

If direct verification does not finish after the service returns an identity:

1. Keep the `imported` record and package unchanged.
2. Confirm the returned agent is visible in the exact target environment.
3. Resolve the reported verification prerequisite without importing again.
4. Rerun the identical import command. The command resumes direct verification
   from the receipt and must not send another import request.
5. Continue to workspace attachment only after the command returns
   `kind: success`.

If verification still fails, stop and retain the receipt. Do not replace the
agent, delete the receipt, or retry the package import.

### Reconcile an ambiguous or invalid-success outcome

Recovery is an operator procedure:

1. Stop all import attempts and preserve the receipt. Keep caller-owned package
   bytes unchanged. For a transient Prod export, complete local cleanup and
   preserve the package hash in the receipt rather than retaining the archive.
2. Record the target environment, operation mode, package schema, and receipt
   timestamp.
3. Wait for service-side activity to settle, then inspect the exact environment
   through read-only inventory and Copilot Studio.
4. For create, look for a newly created agent that can be tied to the operation
   without relying on display name alone. For replacement, inspect only the
   previously approved target.
5. If an exact agent is identified, use the read-only validator before
   attachment.
6. If the outcome cannot be proven, stop and escalate with the receipt. Absence
   from an eventually consistent listing is not proof that the mutation failed.

The command provides no override for `ambiguous` or
`invalid-success`. Never edit or remove a receipt to enable another POST.

## Workspace handoff

After `kind: success`, call `setup_existing_da.py attach` with the returned
validated context and `--setup-source alm-import`.

For a fresh workspace, attachment fetches and projects the imported Dev agent.
For an existing managed workspace, attachment may require explicit
checkpoint-and-refresh approval. That refresh is local and read-only with
respect to the imported agent; it does not repeat the package mutation.

Import `kind: success` is not setup completion. After existing-Dev attachment
reports `connectionStatus: workspace-ready`, setup must refresh the native
FlightCheck step evidence. Setup is complete only when the final maintained
FlightCheck result reports `connectReady: true`.
