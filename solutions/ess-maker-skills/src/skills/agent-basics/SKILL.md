---
name: agent-basics
description: >-
  Read or customize a selected ESS agent's displayName and logo in ADK.
  Use for rename agent, change agent name or display name, rename a Test or
  Prod quality-gate agent, upload logo, change agent icon, and
  independent or combined name/logo changes. Saves name/logo settings only;
  never publishes, deploys to Test, promotes to Prod or submits for approval.
---

# Agent Basics

Completed setup is mandatory for `/agent-basics`, natural-language name/logo
edits, and landing-page handoffs. Apply the shared completed-setup gate in
`.github/copilot-instructions.md` before viewing current values, collecting
proposed changes, or running authoring commands.

Use `scripts/agent_basics.py` for all service operations;
do not write raw HTTP, local branding replacements, or AgentConfiguration
name/icon update payloads. Instructions are outside this skill's scope.

## Target and scope

- Read `.local/config.json` and canonical `.local/setup/config.json`.
  Require canonical `schema_version: 4` and `connect_ready: true` for the
  agent whose `agent.workspace_slug` matches `activeAgent`. Missing or
  incomplete setup uses the shared setup-required message and stops.
  Materialization alone is not completed setup. Do not change readiness
  markers or treat local `setup: "complete"` as canonical readiness.
  Unreadable or malformed files require supported state recovery; do not
  guess replacement metadata.
- Resolve `activeAgent` against canonical schema v4 `agent.workspace_slug`.
  Require the expected local config version and native DA classification,
  matching `botId`/`id` and `schemaName`/`schema_name`, canonical workspace
  evidence, and `steps.SETUP-07.state: "done"`; the recorded workspace folder
  and `agent_path` must exist. The helper validates these prerequisites again.
  Never select by mutable displayName, landing-page `titleId`, or an inferred
  filename. A page title or link label is not a verified bot ID.
- A maker-supplied target different from the active target requires the existing
  setup target-selection flow first. Recheck completed setup for that target
  before continuing. Never silently substitute an agent.
- The helper checks live native identity, exact ESS product registry membership,
  the selected Dev card, fetched bot ID/schema, and entity revision.
  Dev name/logo authoring does not require a published Dev configuration:
  ALM enrollment is separate from publication, and the configuration API may
  return 404 until a Dev configuration has been published. Do not publish the
  agent just to enable a Dev preview or save. For Test/Prod, the helper still
  requires explicit Dev configuration and ALM-family validation.
  Logo changes are Dev-authored only. Name-only changes may target Dev, Test
  or Prod, with an independent name for each quality gate. Never copy a name
  change to another gate automatically. A rename synchronizes the selected
  gate's agent title (`BotEntity.displayName`) and GPT/chat name
  (`GptComponent.displayName`) to the maker's exact requested name.
- Use `--quality-gate dev|test|prod` to view or rename a quality gate; Dev is
  the default. Preserve a gate explicitly requested by the maker and show it
  before approval. Test/Prod targets are discovered from the selected Dev
  agent's ALM siblings, then checked against the direct card, explicit realm
  configuration, ALM-family ID, schema and fetched component identity. Never
  infer a sibling from its name or schema suffix alone, change the selected
  workspace, or silently fall back to Dev when a gate is unavailable.
- A Test/Prod request containing a logo, including a combined name/logo
  request, is blocked without writing either property. Explain that logos
  must be authored in Dev; obtain a separate name-only proposal for Test/Prod.
- Restricted configuration authoring or unavailable Test/Prod UI does not
  prohibit the supported name-only Configure operation. Do not ask the maker
  to enable broader authoring or open Test/Prod to confirm a name already
  verified through APIs. A local recovery stop is separate from those
  restrictions and still requires reviewed resumption.
- Legacy DA-preview and custom-engine agents retain the existing compatible-kit
  handoff. Unknown products, unresolved identity and denied access are distinct
  failures; none permits a write. Do not offer a manual edit as successful ADK
  completion. This implementation authors native ESS Hub, HR and IT only:
  compatible-kit routing is not evidence that legacy authoring is implemented
  or validated. Do not add a speculative Dataverse fallback.
- In Dev, name and logo may be changed independently or together. Keeping current
  settings, identical decoded images, cancellation and optional setup
  customization perform no service write.

## Read and validate

Natural-language "agent name", "display name" and "displayName" requests are
the same name-change operation; the single display label does not change
intent recognition. "Rename the test quality gate agent" already selects
Change name and Test, including in a new chat. After the completed-setup gate,
if the replacement is missing, ask only for the new display name using the
structured free-form input below; do not show the operation menu or ask for
the gate again. Do not replace the request with a generic help response.
Reuse completed saved setup; never infer the new name from another chat.

For a bare `/agent-basics`, use a structured question to offer **View current
name/logo**, **Change name**, **Change logo**, and **Change both**, initially
unselected. Preserve any operation already supplied by the maker or caller;
do not ask them to choose it again.

For a current-state-only request:

```text
python scripts/agent_basics.py view
```

Consume `AGENT_BASICS_RESULT_JSON:`. Report only returned current values; an
unavailable name or logo is not a default value. Use the host image-viewing tool
on returned `current.colorPreview`. A returned `current.logo: "none"` confirms
that the source icon is absent; it is not a read failure or a template default.
After displaying them, clean up that review's copies as described below.

Before collecting a change, state the selected manifest-compatible profile
for the requested properties only. A rename requires only the name limits,
not image requirements or a logo preview.
The maker supplied the Microsoft 365 app manifest v1.30
[name](https://learn.microsoft.com/en-us/microsoft-365/extensibility/schema/root-name?view=m365-app-1.30)
and [icon](https://learn.microsoft.com/en-us/microsoft-365/extensibility/schema/root-icons?view=m365-app-1.30)
constraints for this experience. These are publication-manifest constraints,
not proof that AgentBuilder enforces the same limits on native authoring.

| Property | Input |
|---|---|
| displayName | Nonblank, at most 30 Unicode characters; whitespace is preserved, not trimmed |
| Logo source | Local, fully decodable PNG, exactly 192x192; saved as `BotEntity.iconBase64` |
| Derived icons | Owned by the platform; independent outline and 32x32 color-asset customization are not supported |

Do not impose a file-byte limit or single-frame restriction that the referenced
document does not state. Preserve the source bytes for multi-frame PNGs;
validation and save verification account for every frame and animation timing.
A still-image preview alone does not show the complete animation. Native
service acceptance and preservation must still be established by the returned
save and readback results, not assumed from local validation.

If the target or requested value is ambiguous or missing, use a separate
structured clarification with free-form input for a new `displayName` or
agent URL before preparing a proposal. Do not invent a name, use a page title
as the replacement name, or use the closed save-approval choices to collect
these inputs.

Use the maker's exact values. Do not trim, truncate, crop, resize, convert,
generate an outline, or fetch arbitrary remote URLs. A logo edit changes only
the source image in `BotEntity.iconBase64`; no outline upload is required, even
when the stored outline is empty or absent. The platform derives card/package
icons from that source. Do not offer or promise an independently customized
published outline. If the maker requests an outline-only edit or supplies one
alongside another change, explain that it is unsupported and make no write.
Collect a revised supported proposal instead of silently dropping the outline.

An unread or invalid property must not be written. Explain what needs correcting
and allow an independent valid/readable property to proceed in a separate
preview, only with the maker's agreement. Never silently drop a combined request.
Dev renames update both names in one PUT when the GPT/chat name needs changing,
using the fetched bot revision and component change token. Only the GPT
component's displayName changes; its description, instructions and all other
unrequested fields are retained. If the chat name already matches, use the
existing metadata-only PUT. Both paths submit the fetched logo fields unchanged.
Test/Prod name-only saves use the supported ALM Configure API and change
`botName`, plus `gptDisplayName` when that independent binding already exists,
in the selected realm's complete current values map. When the GPT name shares
`botName`, do not invent a separate binding. Flow/connection overrides are not
submitted. Missing or inconsistent
bindings block the operation; never fall back to a components PUT on Test/Prod.
Do not inspect or preview images, collect image inputs, discuss
service-side image processing, or ask for image-processing consent for a rename.
The platform owns icon normalization and derived image fields; these are not
part of rename validation or recovery. ADK itself does not resize or replace
the logo. Explicit logo/combined edits still require review of valid supplied
assets, but never a separate image-processing question.

## Preview and explicit approval

Run the matching command with only requested arguments, quoting exact values and
local paths using the host shell's argument-escaping rules:

```text
python scripts/agent_basics.py preview --name "People Support"
python scripts/agent_basics.py preview --name "People Support Test" --quality-gate test
python scripts/agent_basics.py preview --name "People Support" --quality-gate prod
python scripts/agent_basics.py preview --logo "C:\branding\color.png"
python scripts/agent_basics.py preview --name "People Support" --logo "C:\branding\color.png"
```

Read `AGENT_BASICS_RESULT_JSON:` rather than inferring success from exit code.
Reuse the setup-selected account and cached sign-in for preview and save.
The command passes the setup-selected account to the existing shared
authentication helper, which tries silent authentication when the cached
account is unambiguous. Do not add
`--select-account`, clear token caches, or ask the maker to sign in again
merely because a new stage or command starts. Use `--select-account` only
when the maker explicitly requests switching accounts. A missing or
unusable cached sign-in or a service-required reauthentication can still
require an interactive sign-in; never bypass that requirement.
The command emits flushed `AGENT_BASICS_PROGRESS_JSON:` stage updates and
15-second waiting updates. These are progress only, not verification or success.
It stops its worker after two minutes for reads/previews or three minutes for a
save, including sign-in and service retries. On a timeout, report the last stage
and the returned diagnostic rather than waiting indefinitely. Do not start a
second command while the first is running. If the maker cancels the chat, stop
the running command before continuing; chat cancellation alone may leave it alive.
An interrupted save is unverified: preserve the pending-write marker and follow
reviewed recovery, never automatically retry it. A stopped preview made no save;
a fresh preview can reuse the maker's inputs, but still requires new approval.
If `writesDisabled` is true, keep this review read-only and use **Stop and
reviewed recovery**; do not offer ordinary save approval.
Show the selected product, tenant/environment, stable bot ID and authoring
quality gate, actual current and proposed requested values, and retained
non-image settings. Present a single **Display name** with its current and
proposed value. Do not show separate agent-title/chat-name fields or explain
their internal distinction to the maker, including in completion messages.
For rename-only requests, do not make a logo-preservation guarantee.
Synchronization and verification of the underlying names remain internal.
Requesting the already-current display name can still require synchronization
after approval; follow the helper's `review` or `no_change` result rather than
assuming an identical displayed value is a no-op.
For Test/Prod, also show the returned concurrency limitation: configuration is
refreshed before writing and verified afterwards, but ALM Configure has no
client-revision precondition. Do not promise the Dev metadata PUT's protection
against edits racing between that refresh and the service's own read.
The displayName is not the ESS product identity.
Quote displayName values with JSON escaping where needed so whitespace or
nonprinting characters are not hidden in the current/proposed review.

For logo requests, display **every supplied source file** using the host
image-viewing tool, alongside the returned current source preview. When the
current source is confirmed absent, label it as no current logo rather than
inventing an image. Show dimensions and a concise text description for
accessibility. This reviews the authoring source, not a rendered package or
proof of employee-visible branding. Paths, filenames and hashes alone are not
an image preview. If the host cannot render an image, stop the logo write and
explain; name-only may proceed with separate consent.

Use the host's structured question control with **Approve**, **Edit proposal**,
**Keep current**, and **Cancel**. Do not treat the initial edit request, a
generic yes, a digest, or a previous target's approval as approval of a new
review. Keyboard navigation must work; announce validation/conflict messages
in text, not color alone. Obtain approval only after the target, complete
proposed values and, for logo requests only, actual images have been presented.

In VS Code, use `vscode_askQuestions` with `allowFreeformInput: false` and
those four choices, initially unselected. In other supported hosts, use the
equivalent structured question tool. A dismissed question is not approval.

The `reviewId` binds target, quality gate, ALM family, workspace selection,
service snapshot, requested values and exact supplied source bytes. Do not
compute or alter it.
On **Approve**, rerun the exact proposal with `save --approval REVIEW_ID`:

```text
python scripts/agent_basics.py save --name "People Support" --approval REVIEW_ID
```

Retain `--logo` too for an approved logo/combined request.
Retain the exact `--quality-gate` from the approved proposal. Approval for one
gate does not approve any other gate; each gate-specific name needs its own
preview and approval. The operation does not publish or promote to apply names.
The helper re-reads identity, permissions and state and compares the reviewed
digest. Dev uses the fetched `BotEntity.version` in one protected PUT and
includes the fetched `changeToken` and only the GPT name update when needed.
Logo-only saves send no component changes. Test/Prod refresh
their configuration again and make one ALM Configure POST, preserving all
unrequested values. Both paths verify the same gate afterwards and never
publish. Do not bypass the checks or retry either write yourself.

On `review_again`, the prior approval is invalid: clean up the old review,
run a new preview, show refreshed state and require explicit approval again.
On **Edit proposal**, clean up first, then validate/preview the edited proposal.
**Keep current** and **Cancel** clean up and finish without writing.

## Results and uncertain recovery

- `saved` means authoritative read-back at a newer entity revision confirmed
  every requested property and preservation of unrequested non-image
  metadata/components, including instructions. Local files or HTTP
  acknowledgment are not proof. A rename is saved only when both the agent
  title and GPT/chat name match the approved name. One matching name is not
  successful completion. Server-owned revision/audit fields on the renamed
  GPT component and removal of a now-redundant ALM name binding are allowed.
  Test/Prod Configure rematerializes every component, so server-owned
  `version`/`auditInfo` changes on those components are also allowed. Component
  IDs, schemas, names other than the requested display name, instructions and
  all other unrequested content must remain unchanged. This does not clear an
  existing preservation stop or retrospectively verify an earlier operation.
- Report each requested property's `saved`, `failed` or `unverified` result.
  If `preservation` is unverified, the operation remains unfinished, even when
  a requested value was observed. Do not roll back or proceed with more writes.
- A logo is `saved` only when read-back confirms the approved source image's
  dimensions and decoded pixels at a newer revision. PNG re-encoding and
  platform-owned derived icon fields are not independent requested changes;
  empty/missing stored outlines do not invalidate the source save. A changed
  or unreadable source remains unverified. Name, instructions and all other
  unrequested non-image settings must still be preserved.
- For name-only saves, report the name result without image-processing
  warnings, logo-preservation results or image-related recovery. Service-owned
  image normalization does not invalidate a verified rename or stop further
  writes. Do not claim that image preservation was checked.
- A pending-write marker is created before the service write and retained after an
  uncertain result, preservation mismatch or interrupted process. A verified
  safe result releases it. `writesDisabled: true` means stop and follow the
  recovery procedure below; do not bypass it by changing targets or using HTTP.
- Retain confirmed partial successes. After any required recovery, before offering a retry, run a new
  preview using the original request. The helper removes already-applied fields
  as no-ops. Show the remaining changes, verify that they really remain
  unapplied, then require a fresh approval. If current state remains unreadable,
  do not retry. Never reapply a confirmed successful field.
- Show access denial/request ID when returned, with legitimate maker/environment
  access remediation. Do not expose raw HTTP bodies, tokens or instructions.

### Stop and reviewed recovery

Explain the recovery as a local stop after an uncertain verification, not a
Test/Prod authoring restriction or a requirement for the maker to inspect
unrelated settings. Use authorized APIs for the current-state review.
Publication, approval/audience and employee visibility may remain explicitly
unverified; establishing them is not a prerequisite for a name-only recovery
that does not publish or promote.

A wrong-target write, unauthorized write, silent overwrite, changed instructions
or unrequested settings, or false completion stops further validation writes on
the affected path. The helper automatically stops its workspace after an
uncertain/unsafe save. For an issue detected outside its read-back, run:

```text
python scripts/agent_basics.py disable-writes
```

This local stop persists across helper invocations and target switches. It does
not cancel an in-flight service operation, undo a saved change or disable other
authoring clients. Stop the study path in other workspaces too if they are
affected; do not route around the stop.

1. Retain confirmed saves. Wait for any in-flight operation to settle, then use
   `view` to establish actual authoring state. Establish publication/approval
   state through the supported observations or named human destinations below;
   keep unsupported observations explicitly unverified.
2. Have the responsible maintainer review the issue and intended corrective
   action before any more writes. For an affected validation study, also record
   the attempt using scrubbed evidence, inform participants through the agreed
   study channel and involve its assigned engineering owner. Do not require
   a study channel or participants for an ordinary maker operation.
   Do not restore instructions through this skill.
   The maintainer's review must distinguish a corrected verification defect
   from confirmed unauthorized or unwanted changes. If historical before/after
   evidence is unavailable, do not claim that the earlier operation was
   preserved. The owner may explicitly accept the current API-verified state
   as the baseline for future writes; this does not retrospectively verify the
   earlier operation. Do not silently accept that baseline or ask the maker
   to prove historical preservation through the UI.
3. Only after the owner has cleared the path, show a fresh `view` result and
   obtain explicit structured approval **to resume writes**, distinct from
   approval of any name/logo change. Pass that view's exact `reviewId`:

   ```text
   python scripts/agent_basics.py resume-writes --approval REVIEW_ID
   python scripts/agent_basics.py resume-writes --quality-gate test --approval REVIEW_ID
   ```

   Retain the exact `--quality-gate` from the fresh `view` for resumption,
   including Prod. A Test/Prod view's approval must not be submitted with the
   default Dev gate. Never use a rename preview's digest as recovery approval.

4. Resumption rechecks the target and current state and performs no service
   write. A changed snapshot requires a new review. Afterwards prepare and
   approve a new proposal containing only proven-unapplied or explicitly
   corrective name/logo changes. Never delete marker files manually.

After an authoring save, distinguish these states:

| State | What to report |
|---|---|
| Local artifacts | Not renamed or rewritten; folder, schema and product identity remain stable |
| Authoring | Per-property read-back result on the selected agent |
| Publication | Not performed for this change; no published version is inferred |
| Approval/audience | Unverified for this change |
| Employee visibility | Unverified; an authoring save is not employee-visible proof |

For native ALM, explain the separate maker/owner path in classic Copilot Studio:
publish Dev, validate in Test, then promote the validated version to Prod.
For a required catalog submission, use the production agent's publishing/sharing
options, **Show to everyone in my org**, then **Submit for admin approval**.
The authorized Microsoft 365 administrator uses **Agents > All agents >
Requests**, **Publish to store**, and audience assignment; some tenants retain
**Settings > Integrated apps**. Use the tenant's actual destination, not a
fabricated link. Validate employee branding with an intended employee account
in Microsoft 365 Copilot Chat. Do not claim automatic branding propagation or
ask the maker to repeat an already saved edit. For unenrolled agents, do not
invent a Test/Prod path; report the publication route as unverified.

## Privacy, cleanup and evidence

The helper emits only the controlled `agent_basics` capability through the
existing opt-out-aware telemetry emitter. Never send names, image bytes, source
paths, review digests or raw service payloads to telemetry. Do not add a branding
or instruction history store. Review snapshots exist in process memory, not a
sidecar database. Local agent/setup labels intentionally remain untouched.
The two local write-stop markers contain only fixed recovery instructions,
never branding, target snapshots or instruction history.

The helper creates only current-icon review copies under
`.local/agent-basics-preview/`. Maker source files are never modified/deleted.
After a view, cancellation, edited proposal, or abandoned review, run:

```text
python scripts/agent_basics.py cleanup --approval REVIEW_ID
```

`save` cleans its review copies even on failure. Report cleanup errors and do
not claim transcript or host-cache deletion: displayed images and text follow
the host's retention policy. After an interrupted session, the next helper
invocation also removes only ADK-named preview copies older than one hour.
That is best-effort interrupted-session cleanup, not a retention SLA or proof
that copies disappear while ADK is not running.

Service implementation evidence inspected at BotDesigner revision
`0332f1f5e65` for this route is
`MinimalBotContentPpapiController`'s Editor filter,
`MinimalBotCrudlService.UpdateFromComponentsApiAsync`,
`AgentStorage.UpdateBotInternalAsync`, and
`TransactionHelpers.CreateBotEntityTransaction`'s exact entity-version conflict
check. `TeamsManifestImageHelper.FixTeamsIconsIfRequired` retains a 192x192
color icon with an explicit outline rather than generating one.
For Test/Prod names, the inspected `AlmController.ConfigureAsync` and
`AlmConfigureService.ConfigureExistingAgentAsync` provide the supported
environment-specific `botName` path; components updates otherwise reject
promoted-realm content changes. A successful live configuration update is not
proof that a later deployment or publication preserves or exposes the name.
Source inspection is not live tenant certification. Before release, complete
the spec's EH-1 through EH-4 evidence per supported build/family: input/access
denials, metadata races before refresh and at write, instruction preservation,
actual ALM/package/employee propagation, keyboard/screen-reader review,
temporary/transcript retention and separate operation latency measurements.
Before real-user exposure, the delivery owner must identify the engineering
DRI, verify this disablement/recovery procedure on the actual host, and agree
the participant communication channel. Also obtain the Design review and
Product's input-profile/scope and release decisions. No people, approvals or
live results are inferred by this skill. Applicable legacy release coverage
requires evidence from its compatible implementation; the native path alone
cannot satisfy that release gate.
