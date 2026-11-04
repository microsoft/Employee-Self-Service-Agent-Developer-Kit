# ServiceNow Knowledge status

Run `python scripts\servicenow_kb_connect.py status` from the selected maker
workspace. Report the exact target, scope, `nextStep` and its guide section, missing fields and
blockers from `SERVICENOW_KB_RESULT_JSON`. Display returned `warnings`, including
unresolved permission-property access, even if representative guided validation
has completed. Never display an error as Ready or deferred access as verified.

`not-started` proceeds to [entry](entry.md). An existing journey resumes through
[the lifecycle](SKILL.md). A target mismatch requires approved `start` scope
revalidation, not a sibling-agent fallback. `guided-validated` is limited to
recorded administrator confirmations and representative maker-tested cases,
not published readiness or universal access coverage.

Continue one step at a time through [configuration.md](configuration.md), recording
observed values directly with `confirm`. Do not route missing confirmations into
an Excel handoff. Use **Act**, then **Verify** internally; show the resumed
step's numbered walkthrough in visible chat before its short result question,
including the actual instance/target link, navigation and required values.
Use task-oriented wording and approved create/update guidance if needed, not a
matching questionnaire. Reuse healthy setup without repeating writes; approval
alone is not a verified result. For an unfinished configuration item whose
existence is unknown, show its check location and exact identifier first, then
ask whether it exists before showing the applicable Act instructions. Reuse a
current-scope answer already supplied; Yes/No does not complete the checkpoint.
Do not add existence questions to read-only diagnostics or completed steps.
Version 1 grouped confirmations retain their
existing provenance; they are not newly observed individual configuration checks.

Resume **permission-setup** with direct role/ACL configuration instructions, not
Access Analyzer or a read-test questionnaire. For default Simple, reuse the
current-scope saved role confirmation; do not repeat it or show a table-grant
matrix. Guide any specifically identified, approved correction inline in chat,
not through an external table-access procedure. Its confirmation means **Permissions
configured; access tests pending**, not verified reads. Existing complete source
read evidence can establish that setup is already covered without a fabricated
new checkpoint. Resume the separate source-permission preflight steps before
opening the connector wizard; do not skip them because setup was saved.
For `property-reads`, first guide the Name/Value checks for both actual records
and ask for the result. Reuse an already supplied current-scope observation.
Record `confirmed`, `unreadable` or `unverified` truthfully. With unresolved access,
show Microsoft's restrictive-default/content-exclusion warning, recommend
contacting the ServiceNow administrator and ask a separate continuation question.
Record `proceed-without-access` only after an explicit Yes; No, silence or
cancellation leaves this step pending. Do not start inline ACL troubleshooting.
An old `deferred-to-admin` value is automatic deferral, not consent. Retain its
historical observations and the existing connection, but obtain a fresh decision before
advancing or accepting new reader evidence. Existing verified reads or explicit
continuation approval do not need repeating. Preserve unrelated blockers and
keep unresolved-access warnings visible after user-approved continuation.
If an older walkthrough already opened a draft, complete outstanding source checks
first without requiring the unsaved form to remain open. Reuse reviewed settings
and the existing connection; do not create a duplicate connection.
If old progress only has a Connection ID, retain it as historical data and obtain
the actual connection name shown in ESS Knowledge. Never infer the name from the
ID, ask for another ID or recreate the connection. Adding the missing name does
not erase historical checks or upgrade their provenance. Reuse a known name
without another question. For duplicate names, clarify the matching source.

For an unfinished draft, the **federated-auth** step uses **Custom setup >
Authorize** before Create. Reuse actual authorization success only for unchanged
settings; a legacy settings-only confirmation is insufficient. If needed, perform
Authorize before creation even when the configuration checkpoint was already
recorded. Failure pauses setup; an absent action requires actual-screen inspection,
not an invented button or automatic continuation. Only claim sample-fetch success
if separately displayed. Do not recreate an existing connection to obtain a new
pre-Create result. At
**connection-ready**, require an actual post-Create observation for the recorded
connection name and matching settings, including on legacy resume. Retain prior evidence and the existing
connection, but do not use "Both succeeded" or a grouped Ready flag to bypass this
checkpoint. Supply the saved `--connection-name` for its internal confirmation.
If still processing, wait for a later user observation; on errors, guide correction
against the same connection rather than recreating it.

Finish index verification before moving to ESS: test article/KB, Indexed status
and native/indexed allowed/denied permission comparisons precede source attachment.
If indexing or permissions are pending or failed, pause there instead of switching
to ESS. Then attach/reuse the named connection, isolate it and test the answer/citation.
Older journeys may already have attachment/isolation observations from the previous
order. Retain their history and resume the earliest pending index check; do not
interpret existing attachment as passed indexing or repeat a healthy attachment
just because the steps moved. New ESS confirmations must follow completed index checks.
