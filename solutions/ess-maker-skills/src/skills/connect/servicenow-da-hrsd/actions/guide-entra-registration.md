# Guide and verify the Entra User Login application

Treat Entra registration as one complete high-level setup step. Use either
the source-faithful direct-capture handoff or the protected XLSX/CSV handoff.
Do not add a separate
Email/UPN/Pay ID routing question or pauses between Create App, claims, scope,
pre-authorization, permissions, and consent.

This is always an admin-owned guided workflow. Never run `az ad app create`,
Graph `POST`/`PATCH`, admin-consent mutation, or any equivalent write
operation. Never request or persist a client secret, certificate, password,
token, or PFX. Connect must not authenticate to Microsoft Graph, request Graph
read scopes, initialize a Graph client, or query the application. The Entra
administrator owns the cloud checks; Connect validates only the returned local
handoff, target binding, and confirmation receipt.

Read `adminSetup.phaseHandoffs.entra-registration` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, rerun
`identity-mapping-handoff --stage entra` to validate the current target-bound
evidence and reconcile any older derived reused handoff. Require
`decision: no-action`; do not ask again. Then return
`ACTION_RESULT = "recorded"` and let
`SN-DA-HRSD-ENTRA-SETUP-001` validate the complete administrator confirmation
locally. A prior `Failed`/`Error` or any other result outside
`completionStatuses` requires one new complete Entra handoff so the Maker can
return corrected bundled evidence.

The retired APP, CLAIMS, SCOPE, and PREAUTH checkpoint IDs are historical
state/audit keys only. Do not invoke them. Their four required information
items remain mandatory fields of the single setup confirmation.

## Shared Identity lookup

Before creating or returning an Entra workbook, run the local-only Shared
Identity lookup:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} shared-reuse-handoff
```

This command reads only the other ESS ServiceNow lifecycle in this workspace.
It makes no API call and considers only compatible administrator-confirmed
Entra application/claim evidence and ServiceNow OIDC/user-mapping evidence.
It does not include instance confirmation, physical connections, topics,
portal URL, agent binding, Test, Publish, lifecycle plan, or consent.

- `none`: continue the normal Entra workbook flow without a reuse question.
- `already-recorded`: continue; the owning Entra and OIDC checkpoints still
  evaluate the current evidence.
- `source-selection-required`: ask one label-only question from the returned
  candidate labels, then rerun with the selected internal `sourceKey`. Do not
  expose the key.
- `question-required`: pass the returned `question` object unchanged through
  the question tool. Its body contains the exact target, source agent, and
  eligible identity items; its `options` are label-only. Translate the
  selected label through `reuseDecisionChoices`.
  - **Reuse shared identity**: run
    `record-shared-reuse --source-key <internal-source-key> --decision accept`.
    This rechecks only local source hash/scope/bindings and imports only the
    listed identity evidence. It does not call Connectivity or mark the owning
    checkpoints Passed.
  - **Configure separately**: run
    `record-shared-reuse --source-key <internal-source-key> --decision decline`
    and continue normally.
  - **Not now**: record nothing and return `ACTION_RESULT = "waiting"`.

After an accepted reuse, rerun `identity-mapping-handoff --stage entra`.
If it returns `decision: no-action`, immediately return
`ACTION_RESULT = "recorded"`. Do not render or generate a workbook, call the
question tool, rerun `record-identity-mapping`, or replace the reused admin
handoff with `record-admin-phase`; the runner-owned Entra checkpoints still
run next. Only `decision: question-required` enters the missing administrator
work below. Partial reuse continues with only the missing administrator work.
Never infer physical-connection readiness from Shared Identity.

## Goal and owner

- **Goal:** register or verify one Entra app and configure the
  access-token identity claim names needed for ServiceNow user matching.
- **Owner role:** Application Administrator or Cloud Application
  Administrator. A Global Administrator may complete the task but is not
  required. An application owner may collaborate on app settings, but an
  appropriately authorized administrator must review any permission
  confirmation shown by the Task 1 claim flow.

## Complete admin instructions

For direct capture, first use the current `resume-handoff` business-group
availability gate. Do not run this command or render administrator instructions
until the Entra availability acknowledgement is current. A No answer pauses
with the returned bring-admin reply and changes no state; a Yes answer is
recorded only by `resume-handoff --roles-available yes` with its exact group ID
and context hash.

After that acknowledgement, return the canonical runtime instructions from
[the shared Entra administrator source](../../shared/runtime-instructions/entra-administrator.md)
and native data questions without writing state:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} identity-direct-handoff --stage entra
```

Require `decision: instructions-required`. Render `ordinaryReply.text`
verbatim, then pass every returned `askUserArguments` object verbatim through
the active `ask_user` tool. The returned question list intentionally excludes
availability because `resume-handoff` owns and deduplicates that gate. Record
the non-secret values only after the administrator answers the separate Client
ID and User Claim prompts. Keep an accepted Client ID in the current
conversation turn; if the handoff must be regenerated before the claim answer,
pass `--client-id "<application-client-id-guid>"` so the next returned
question is the claim rather than asking for Client ID again. This hint is
validated but not persisted, so a new chat without an atomic receipt may ask
for Client ID again.

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-identity-direct --stage entra --client-id "<application-client-id-guid>" --claim-name "<selected-claim-name>" --yes
```

The protected file route remains fully supported:

Generate both equivalent local handoff formats before the administrator pause:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} identity-mapping-handoff --stage entra
```

The result returns `workbookPath` / `workbookUri` and `csvPath` / `csvUri`.
The administrator completes exactly one format and returns its local path.

### XLSX contract

The protected workbook has one visible `Entra Handoff` sheet and one hidden,
locked `_metadata` sheet. The visible interface contains English headers and
exactly one entry row:

| Column | Header | Ownership |
| --- | --- | --- |
| A | `Instructions` | Locked single-line guidance; internal line breaks are spaces. The Microsoft Learn non-email/UPN guidance is the cell hyperlink. |
| B | `Client ID` | Yellow editable cell for the exact Application (client) ID. |
| C | `User Claim` | Yellow editable cell for exactly one selected claim name. |

Only the non-secret Application (client) ID and one claim **name** are
collected. Do not enter Object ID, tenant user identifiers, email/UPN values,
personal IDs, token contents, secrets, certificates, or keys. The instructions
mention the optional Access claims `Aud`, `Email`, and `UPN`; `aud` is only for
audience validation and is never valid in the `User Claim` field.

The instruction row covers both paths: reuse an existing Entra app and share
its client ID/selected claim, or register a new app, leave Redirect URL blank,
add the Access optional claims, accept the Microsoft Graph permission prompt
when shown, and follow the linked extra work when the selected claim is not
email or Entra UPN.

### CSV contract

The equivalent CSV contains one header and exactly one data record. Headers,
in order, are:

```text
Format Version,Instructions,Client ID,User Claim,Tenant ID,Environment ID,ServiceNow Instance,Provider,Profile,Target Agent Slug,Target Agent ID,Binding SHA256
```

The administrator edits only `Client ID` and `User Claim`. Every field must be
single-line with no embedded CR/LF. The remaining fields are generated binding
and provenance values and must not be changed.

## Completion signal and evidence

Render the returned `instructionTitle` and `instruction`, then send the
returned short `question` unchanged. The question remains the single visible
pause and accepts the local path of either the completed XLSX or CSV.

Import the returned file with the same command for both formats:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-identity-mapping --stage entra --workbook-file "<completed-xlsx-or-csv-path>" --yes
```

Import validates the exact target binding, metadata/provenance, format,
instructions, non-empty GUID Client ID, and one safe selected claim name. It
fails closed for missing or invalid Client ID, blank/malformed claim, `aud`,
duplicate CSV records, formulas, changed headers/instructions/protection,
stale hashes, or a different tenant, environment, instance, provider, profile,
or agent. It never selects the first candidate or defaults to `oid`, `upn`, or
another claim.

Successfully imported XLSX and CSV produce the same scoped
`identityClaimCandidates` receipt with one confirmed claim. Existing issued
legacy XLSX handoffs remain importable through the legacy parser; generation
does not rewrite issued runtime files or lifecycle state.

A valid current handoff containing one Application client ID GUID and exactly
one safe User Claim name completes the Manual Entra identity phase. The import
atomically derives the completed target-bound handoff evidence; there is no
separate Entra completion question. Historical app-registration, claim,
scope, pre-authorization, permission, or consent fields remain preserved when
present, but they are not inferred and do not gate this phase.

This completion does not prove app configuration, claim emission,
`user_impersonation`, connector pre-authorization, a real token,
authentication, permission, or a business result. Later connection, binding,
and functional Test checks remain independent. Return
`ACTION_RESULT = "recorded"` after the direct or file import succeeds.
