# Guide the ServiceNow OIDC trust and user mapping

Treat ServiceNow OIDC/auth setup as one complete high-level step. Keep the
full runbook, owner role, and non-secret evidence requirements available to
the administrator. Render the canonical instructions, collect only the actual
internal User Field when it is missing, and record the current mapping receipt.
Do not add a separate completion question or pause between role elevation,
provider registration, metadata, claim mapping, and user checks.

Never create or patch ServiceNow security objects.

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
A No answer pauses with the returned bring-admin reply and changes no state; a
Yes answer is recorded only by `resume-handoff --roles-available yes` with its
exact group ID and context hash.

After that acknowledgement, return the canonical runtime instructions from
[the shared ServiceNow administrator source](../../shared/runtime-instructions/servicenow-administrator.md)
with the confirmed Client ID and User Claim already locked:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} identity-direct-handoff --stage servicenow
```

Require `decision: instructions-required`. Render `ordinaryReply.text`
verbatim; it already contains the plain-text lead-in before the
Ready-to-send fenced block, so do not rewrap or edit either part. It also ends
with the User Field question as plain chat text. The returned `questions` list
is empty: do not call `ask_user` or any input card for the User Field; stop
after the reply and wait for the maker to type it. When the
handoff is regenerated after a User Field was already captured, the returned
`ordinaryReply.text` is only a short acknowledgement of the recorded field;
render it verbatim and do not ask for the field again.
The handoff excludes availability because `resume-handoff`
owns and deduplicates that gate. Take the field name from the maker's typed
reply, or from the ServiceNow administrator's pasted reply. If the reply gives
only a display label, ask once in plain words for the field's column name
instead of guessing. Record only the administrator-confirmed
internal `sys_user` field; the command does not accept Client ID or User Claim
overrides:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-hrsd --agent-slug {SELECTED_AGENT_SLUG} record-identity-direct --stage servicenow --user-field "<internal-sys_user-field>" --yes
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
