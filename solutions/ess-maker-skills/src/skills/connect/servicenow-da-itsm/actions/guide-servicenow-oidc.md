# Guide the ServiceNow OIDC trust and user mapping

Treat ServiceNow OIDC/auth setup as one complete high-level step. Keep the
full runbook, owner role, and non-secret evidence requirements available to
the administrator. Render the canonical instructions, collect only the actual
internal User Field when it is missing, and record the current mapping receipt.
Do not add a separate completion question or pause between role elevation,
provider registration, metadata, claim mapping, and user checks.

Never create or patch ServiceNow security objects.

When the lifecycle state carries `existingIdentity` (the maker said ESS should
reuse an existing Knowledge, single sign-on, or Microsoft Graph sign-in setup),
`identity-direct-handoff` returns the compatibility-review handoff. Send it
verbatim; the setup steps in it are reference only and ESS never changes the
shared sign-in configuration. See `existing-identity-handoff` in `entry.md`.

When the other ESS ServiceNow agent already completed sign-in setup here (and the
marker is not set), `identity-direct-handoff` returns the second-agent
reuse-review handoff instead; send it verbatim. See "Second ESS agent reusing
this instance's sign-in setup" in `entry.md`.

Read `adminSetup.phaseHandoffs.servicenow-oidc` first. If it is already
`completed` or `reused` and stored checkpoint results are empty or all in the
phase's `completionStatuses`, rerun
`identity-direct-handoff --stage servicenow` to validate the current
target-bound mapping and reconcile any older derived reused handoff. Require
`decision: no-action`; do not ask again. Then return
`ACTION_RESULT = "recorded"` and let the structured checkpoint reverify the
current bundled evidence. A prior result outside `completionStatuses`
requires one new complete OIDC handoff.

## Goal and owner

- **Goal:** record one current exact-target receipt that pairs the locked
  Entra-confirmed User Claim with the actual ServiceNow user field.
- **Owner role:** ServiceNow `admin` or `security_admin`, elevated to
  `security_admin`.

## Complete admin instructions

The ServiceNow handoff is not ready until the same scoped Entra receipt has a
valid Application (client) ID and exactly one selected User Claim name. Missing,
multiple-unselected, stale, or wrong-bound evidence must return waiting; never
choose the first claim or apply a default.

For direct capture, first use the current `resume-handoff` business-group
availability gate. Do not run this command or render administrator instructions
until the ServiceNow `security_admin` availability acknowledgement is current.
A No answer, or any answer other than a clear Yes, pauses through
`resume-handoff --roles-available no`: send its returned `chatMessage` verbatim
as plain chat, end the turn, and change no state. A
Yes answer is recorded only by `resume-handoff --roles-available yes` with its
exact group ID and context hash.

An administrator reply the maker has already pasted or typed (in whole or in
part) is evidence, never a reason to ask availability. Do not run the
availability gate and never write your own "Are you available…" card: run the
`record-identity-direct` command in this guide with the supplied values right
away, show its `chatMessage`, and follow its `endTurn` and `nextCommand`; the
checklist comes from the next `resume-handoff` `renderBlock.text`, which you
send verbatim. A mismatch comes
back as plain chat; send it verbatim. Only `resume-handoff` ever asks an
availability question, only when the next step needs an administrator, and
its question already names who must act.

After that acknowledgement, return the controller-built first-agent ServiceNow administrator message, which follows the PM spec's step structure and shares its underlying steps with
[the shared ServiceNow administrator source](../../shared/runtime-instructions/servicenow-administrator.md)
with the confirmed Client ID and User Claim already locked:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} identity-direct-handoff --stage servicenow
```

A maker message that says a custom claim is wanted but not confirmed by the
Entra administrator is answered only with the "Custom claim not confirmed"
Message from `claim-confirmation-handoff --custom-claim` (see `Clarification and recovery
Messages` in `src/skills/connect/servicenow/entry.md`), verbatim; do not
improvise steps, suggest email, or record anything.

A maker message that only states a claim name (for example "it is X") is not a
confirmation. Never ask a clarifying card and never record the name: run
`record-identity-direct --stage entra` with the stated name and without the
claim-setup confirmation option described in the Entra registration guide. It
records nothing and returns the "We have the claim name" Message in
`chatMessage`; send it verbatim and end the turn. Add that option only when the
Entra administrator's reply confirms the claim setup is complete. The standard `email` and `upn` claims need no
such confirmation. Only a recorded, confirmed claim makes the ServiceNow
administrator message below necessary again.

When the maker or an administrator reports the actual saved metadata URL and it
contains `/v2.0`, run `metadata-url-handoff --metadata-url "<reported URL>"`
and send its `chatMessage` verbatim (the "Metadata URL with `/v2.0` reported"
Message in `servicenow/entry.md`). Use it only when the actual URL is given,
never from a generic failure; it records nothing and never overwrites shared
identity configuration.

When the maker returns from a pause with an administrator reply outstanding,
do not render the instructions again: follow the "Maker pauses for an
administrator" messages in `servicenow/entry.md`, then record the reply below.

Require `decision: instructions-required`. Render `ordinaryReply.text`
verbatim; it already contains the plain-text lead-in before the
Ready-to-send fenced block, so do not rewrap or edit either part. Then pass the returned User Field `askUserArguments` object verbatim. When the
handoff is regenerated after a User Field was already captured, the returned
`ordinaryReply.text` is only a short acknowledgement of the recorded field;
render it verbatim and do not ask for the field again.
The question list intentionally excludes availability because `resume-handoff`
owns and deduplicates that gate. Record only the administrator-confirmed
internal `sys_user` field; the command does not accept Client ID or User Claim
overrides:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} record-identity-direct --stage servicenow --user-field "<internal-sys_user-field>" --yes
```

This command validates the locked Client ID and claim, exact target binding,
field syntax, source provenance, candidate hash, and relationship hash, then
atomically persists the mapping receipt and owning Manual OIDC handoff. Return
`ACTION_RESULT = "recorded"` after it succeeds. A subsequent direct handoff
must return `decision: no-action`; do not repeat availability, instructions,
or the User Field question.

## Mapping receipt and evidence

Recording requires the frozen Entra Client ID and one claim name plus exactly
one safe ServiceNow `sys_user` field. It rejects blank or invalid fields,
`aud`, frozen-value tampering, stale candidate hashes, or a wrong
tenant/environment/instance/provider/profile/agent binding.

A successful `record-identity-direct` atomically persists the mapping receipt and owning
Manual OIDC handoff. Return `ACTION_RESULT = "recorded"` immediately; do not
ask a saved/configured, claim-mapped, Active-user, or preauthorization
completion question. The receipt proves only the locked claim, actual internal
field, exact target binding, provenance, and hashes. It does not prove that the
OIDC provider is saved or configured, or prove a real token, authentication,
permission, employee match, or business result.
