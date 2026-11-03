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
`identity-mapping-handoff --stage servicenow` to validate the current
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
with the confirmed Client ID, tenant ID, and User Claim already locked:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} identity-direct-handoff --stage servicenow
```

Require `decision: instructions-required`. Render `ordinaryReply.text`
verbatim, then pass the returned User Field `askUserArguments` object verbatim.
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

The protected file route remains fully supported.

Generate both equivalent local formats:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} identity-mapping-handoff --stage servicenow
```

### XLSX contract

The protected workbook preserves `Steps`, `Worksheet`, and hidden locked
`_metadata`:

- `Steps!B2` is the short title.
- `Steps!B3` immediately shows the bound Entra Client ID and User Claim.
- `Steps!B4` is the complete single-line ServiceNow operation guidance.
- The same bound claim appears in the opening handoff, the YES/reuse check, the
  NO/create `User Claim` setting, and final step `ii`.
- `Worksheet!B6` is the locked confirmed Client ID.
- `Worksheet!A13` is the locked confirmed User Claim name.
- `Worksheet!B13` is the only yellow editable ServiceNow User Field input.

The ServiceNow administrator confirms the actual internal `sys_user` field
that stores the same identity key. There is no `oid`, `upn`, `User ID`, or
`Employee number` default. The reuse branch verifies the existing Client ID
and User Claim against the bound Entra values. The create branch auto-supplies
those same values and leaves only User Field for administrator confirmation.

### CSV contract

The equivalent CSV headers, in order, are:

```text
Format Version,Record,Content,Client ID,User Claim,ServiceNow User Field,Tenant ID,Environment ID,ServiceNow Instance,Provider,Profile,Target Agent Slug,Target Agent ID,Binding SHA256,Candidate Set SHA256
```

It contains exactly two records in this order:

1. `Entra handoff` - the opening bound Client ID/User Claim summary; User Field stays blank.
2. `Steps` - the complete single-line operation guidance; the administrator fills only `ServiceNow User Field`.

Both records must carry identical Client ID, User Claim, binding values, and
candidate-set hash. Content fields must not contain embedded CR/LF.

## Mapping receipt and evidence

Accept the local path of either the completed XLSX or CSV and import it with:

```text
python scripts/connect_servicenow_da.py --provider servicenow-da-itsm --agent-slug {SELECTED_AGENT_SLUG} record-identity-mapping --stage servicenow --workbook-file "<completed-xlsx-or-csv-path>" --yes
```

Import requires the frozen Entra Client ID and one claim name plus exactly one
safe ServiceNow `sys_user` field. It rejects blank/invalid fields, `aud`,
duplicate or conflicting CSV records, changed instructions/context, stale
candidate hashes, frozen-value tampering, or wrong tenant/environment/instance/
provider/profile/agent binding. XLSX and CSV produce the same bounded identity
mapping receipt. Existing issued legacy XLSX files remain importable and are
not rewritten.

The successful import atomically persists the mapping receipt and owning
Manual OIDC handoff. Return `ACTION_RESULT = "recorded"` immediately; do not
ask a saved/configured, claim-mapped, Active-user, or preauthorization
completion question. The receipt proves only the locked claim, actual internal
field, exact target binding, provenance, and hashes. It does not prove that the
OIDC provider is saved or configured, or prove a real token, authentication,
permission, employee match, or business result.
