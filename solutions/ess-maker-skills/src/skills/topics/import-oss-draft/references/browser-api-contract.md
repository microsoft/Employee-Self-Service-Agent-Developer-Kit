# Native browser components protocol - draft evidence

## Evidence and limits

A prior signed-in Brave authoring session added 15 real OSS scenario topics and
preserved one existing scenario. The maker had already installed the shared
template-config setup topic and Conversation Start call; those were not replaced.
Successful saves were followed by component read-back. This is authoring evidence,
not proof that all 16 scenarios execute correctly in Workday.

This note intentionally excludes environment/agent/account IDs, credentials,
captures and customer content. The creation envelope was not persisted as a
sanitized fixture. **Its exact discriminator/identity fields are still a capture
and implementation gate.** Do not substitute a guessed `BotComponentCreate` or
`BotComponentInsert` request.

## Observed operations

Use only the selected environment's validated HTTPS Power Platform host and ring.
Do not use a host pasted into an untrusted file. Existing `agentbuilder.py`
validates host/ring binding; authentication must match the selected tenant.

| Operation | Observed request |
|---|---|
| Read components | `POST /copilotstudio/minimalBots/api/{agentId}/components?api-version=2022-03-01-preview`, body `{}` |
| Save components | `PUT` to that same path/query, with typed Object Model component changes |

The API version is an observed value, not a permanent public compatibility promise.
Do not conflate it with the general AgentBuilder inventory API version.

Current code references, relative to the Maker Kit workspace:

- `scripts/agentbuilder.py`: auth, validated host resolution, Dev configuration,
  component read. `update_bot_entity()` changes the bot entity only; it is not a
  create-topic helper.
- `scripts/agentbuilder_object_model.py`: real .NET SDK YAML/Object Model
  conversion. Review per-item `success`, `elementType` and typed expressions.
- `scripts/minimalbot_evaluation.py`: `update_dialog_components()` implements
  existing-dialog updates with baseline/drift checks, a fresh `changeToken` and
  `$kind: BotComponentUpdate`. It does not create missing dialogs.
- `scripts/push.py`: scoped native topic updates reject create/delete. Preserve
  that release boundary.

Known update envelopes include `changeToken`, `botComponentChanges`, and empty
non-topic change collections. Do not replay an entire baseline or a previous
browser request. Build only the approved deltas against the current read.
Do not copy metadata from one existing customer component into a new component.

## Capturing a creation contract safely

Capture only when the user approved creating the selected real topic in the exact
target. Never create a dummy topic simply to learn the API. If the browser requests
sign-in, let the user complete it; do not request a password or extract credentials.

1. Open the existing editable Dev agent in the user's chosen browser, using
   existing automation/session facilities. Do not copy another profile's cookies.
2. Register the components PUT response listener **before** saving the first
   approved topic. Filter the exact selected host, agent path and method.
3. Create a blank topic, name it, and open **More > Open code editor**. Paste the
   complete selected YAML through normal editor paste semantics, then close the
   editor. Require parsing/canvas completion before Save.
4. Await the actual PUT response and inspect the typed request/response in memory.
   Persist only a reviewed, credential-free structural fixture if needed.
5. Read components again and require one exact nonzero created identity and
   matching canonical dialog. A disappearing "Saving..." indicator is not proof.
6. Compare the captured creation contract with SDK output before implementing
   direct API writes. If it cannot be reproduced without losing fields, stop.

In the earlier session, clicking Monaco's hidden input was intercepted and
multiline `insertText` compounded indentation. A normal clipboard paste event
worked. These are browser observations, not selectors or a supported permanent
interface. Do not use DOM tricks to evade auth, consent or product safety gates.

## Concurrency, transport and errors

- Keep tokens, cookies and CSRF headers out of files, URLs, logs and prompts.
  Prefer existing first-party delegated auth, not an exported browser token.
- Stop on 401/403. Do not downgrade to Dataverse, change identity/ring, disable
  TLS validation, or follow credential-bearing redirects.
- Treat write timeout/network failure as indeterminate. Read by the planned
  identity and compare content before deciding whether anything needs retrying.
- A stale change token or overlapping remote edit invalidates the plan. Refresh,
  show the changed scope and ask again; do not use an unconditional overwrite.
- Verify every returned changed-component ID belongs to the approved scope.
  Stop on unexpected server changes and retain the private baseline for analysis.
- Batch only after one-item create/read-back is established. Default to sequential
  imports and receipts so partial progress can be reconciled without duplicates.

## Gates before a working importer

1. Reviewed creation-envelope fixture from a current approved real save.
2. Create-capable native client with fake-transport tests: host pinning, no secrets,
   no deletes, stale-token/conflict handling, ambiguous-save reconciliation,
   duplicate detection and preservation of unrelated components.
3. Real SDK round-trip and target-version node/type/Power Fx compatibility checks.
   `AnswerQuestionWithAI` remains blocked in this prototype until explicitly
   validated; other kinds are not implicitly approved.
4. Read-before-write and read-back tests for shared configuration and optional
   Conversation Start wiring, including existing maker customizations.
5. Approved non-production end-to-end import, rerun/idempotency and negative tests.
   No publish or Workday write is part of importer validation by default.

Until those gates are satisfied, this branch provides a draft skill and local
planning only. Do not advertise an available `/import-oss` command or native topic
creation support.
