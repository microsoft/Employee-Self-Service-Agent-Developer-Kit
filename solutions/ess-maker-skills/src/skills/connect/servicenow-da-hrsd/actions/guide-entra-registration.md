# Guide and verify the Entra User Login application

Treat Entra registration as one complete high-level setup step. Use the
source-faithful direct-capture handoff. Do not add a separate
Email/UPN/Pay ID routing question or pauses between Create App, claims, scope,
pre-authorization, permissions, and consent.

This is always an admin-owned guided workflow. Never run `az ad app create`,
Graph `POST`/`PATCH`, admin-consent mutation, or any equivalent write
operation. Never request or persist a client secret, certificate, password,
token, or PFX. Connect must not authenticate to Microsoft Graph, request Graph
read scopes, initialize a Graph client, or query the application. The Entra
administrator owns the cloud checks; Connect validates only the returned local
handoff, target binding, and confirmation receipt.

When the lifecycle state carries `existingIdentity` (the maker said ESS should
reuse an existing Knowledge, single sign-on, or Microsoft Graph sign-in setup),
`identity-direct-handoff` returns the compatibility-review handoff. Send it
verbatim; the setup steps in it are reference only and ESS never changes the
shared sign-in configuration. See `existing-identity-handoff` in `entry.md`.

When the other ESS ServiceNow agent already completed sign-in setup here (and the
marker is not set), `identity-direct-handoff` returns the second-agent
reuse-review handoff instead; send it verbatim. See "Second ESS agent reusing
this instance's sign-in setup" in `entry.md`.

Read `adminSetup.phaseHandoffs.entra-registration` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, rerun
`identity-direct-handoff --stage entra` to validate the current target-bound
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

Before returning the Entra administrator instructions, run the local-only Shared
Identity lookup:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} shared-reuse-handoff
```

This command reads only the other ESS ServiceNow lifecycle in this workspace.
It makes no API call and considers only compatible administrator-confirmed
Entra application/claim evidence and ServiceNow OIDC/user-mapping evidence.
It does not include instance confirmation, physical connections, topics,
portal URL, agent binding, Test, Publish, lifecycle plan, or consent.

- `none`: continue the normal Entra direct-capture flow without a reuse question.
- `already-recorded`: continue; the owning Entra and OIDC checkpoints still
  evaluate the current evidence.
- `question-required`: pass the returned `question` object unchanged through
  the question tool. Its body contains the exact target, source agent, and
  eligible identity items; its options are only Yes/No. Several sources are
  asked one at a time; never show a source picker. Translate the selected
  label through `reuseDecisionChoices`. When `moreCandidates` is true, a
  **No** is recorded and then `shared-reuse-handoff` is rerun to ask about the
  next source.
  - **Yes** (reuse the shared identity): run
    `record-shared-reuse --source-key <internal-source-key> --decision accept`.
    This rechecks only local source hash/scope/bindings and imports only the
    listed identity evidence. It does not call Connectivity or mark the owning
    checkpoints Passed.
  - **No** (configure separately): run
    `record-shared-reuse --source-key <internal-source-key> --decision decline`
    and continue normally.

After an accepted reuse, rerun `identity-direct-handoff --stage entra`.
If it returns `decision: no-action`, immediately return
`ACTION_RESULT = "recorded"`. Do not render instructions, call the
question tool, rerun `record-identity-direct`, or replace the reused admin
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

After that acknowledgement, return the controller-built first-agent Entra administrator message, which follows the PM spec's step structure and shares its underlying steps with
[the shared Entra administrator source](../../shared/runtime-instructions/entra-administrator.md)
(the source file is reused as-is for realm messages), and native data questions without writing state:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} identity-direct-handoff --stage entra
```

When the maker or an administrator says employees are identified by a payroll
or other custom employee ID, add `--custom-identifier` to this first command
(see `Custom employee identifier` in `src/skills/connect/servicenow/entry.md`).
Later `identity-direct-handoff` calls keep the wording through the stored
marker; render the returned text verbatim.

Require `decision: instructions-required`. Render `ordinaryReply.text`
verbatim; it already contains the plain-text lead-in before the
Ready-to-send fenced block, so do not rewrap or edit either part. Then pass every returned `askUserArguments` object verbatim through
the active `ask_user` tool. The returned question list intentionally excludes
availability because `resume-handoff` owns and deduplicates that gate. Do not
ask the maker for the claim up front: the maker answers one prompt by pasting
the Entra administrator's non-sensitive reply or the Client ID. Read the claim
name only from that reply: a custom claim name the administrator states, or
`email` or `upn` when the administrator states that the standard email or UPN
claim applies. Never guess a name from a phrase such as "payroll claim", never
default one, and never accept `aud`. When the reply has a Client ID but no
claim name, keep the Client ID in the current conversation turn and rerun the
handoff with `--client-id "<application-client-id-guid>"`; it returns the
single claim follow-up question, which begins with an acknowledgement of the
Client ID. Show the returned question verbatim. This hint is validated but not
persisted, so a new chat without an atomic receipt may ask for Client ID again.
Record the non-secret values only after the reply supplies both.

For a reply that proposes a custom claim without configuring it, and the maker says a custom claim is wanted, show the
"Custom claim not confirmed" Message (run `claim-confirmation-handoff --custom-claim`)
verbatim and nothing else; never suggest email as a fallback. For a reply that names two
claims, gives a name without completion confirmation, reports missing
attributes, an email format, or an Entra error, or that the maker is waiting
for the claim, show the matching Message in `Clarification and recovery
Messages` of `src/skills/connect/servicenow/entry.md`. Record nothing until
the administrator's reply supplies the Client ID and a confirmed claim name.
A custom claim name (anything other than `email` or `upn`) is recorded only
with `--claim-setup-confirmed`, added when the Entra administrator confirms the
claim setup is complete. Without it the command records nothing and returns the
"We have the claim name" Message in `chatMessage`; send it verbatim, end the
turn, and never ask a clarifying card about the name.

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-identity-direct --stage entra --client-id "<application-client-id-guid>" --claim-name "<selected-claim-name>" --yes
```

Recording validates the exact target binding, a non-empty GUID Client ID, and
one safe selected claim name. It fails closed for a missing or invalid Client
ID, a blank or malformed claim, `aud`, or a different tenant, environment,
instance, provider, profile, or agent. It never selects the first candidate or
defaults to `oid`, `upn`, or another claim.

A valid current handoff containing one Application client ID GUID and exactly
one safe User Claim name completes the Manual Entra identity phase. Recording
atomically derives the completed target-bound handoff evidence; there is no
separate Entra completion question. Historical app-registration, claim,
scope, pre-authorization, permission, or consent fields remain preserved when
present, but they are not inferred and do not gate this phase.

This completion does not prove app configuration, claim emission,
`user_impersonation`, connector pre-authorization, a real token,
authentication, permission, or a business result. Later connection, binding,
and functional Test checks remain independent. Return
`ACTION_RESULT = "recorded"` after the direct record succeeds.
