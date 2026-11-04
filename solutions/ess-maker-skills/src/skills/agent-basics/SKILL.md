---
name: agent-basics
description: >-
  Read or customize a selected ESS agent's displayName and logo in ADK.
  Use for rename agent, change agent name, upload logo, change agent icon, and
  independent or combined name/logo changes. Saves authoring metadata only;
  never publishes, deploys to Test, promotes to Prod or submits for approval.
---

# Agent Basics

Follow the selected-agent setup and explicit preview/approval procedure used by
other authoring skills. Use `scripts/agent_basics.py` for all service operations;
do not write raw HTTP, local branding replacements, or AgentConfiguration
name/icon update payloads. Instructions are outside this skill's scope.

## Target and scope

- Read `.local/config.json` and resolve its `activeAgent` against canonical
  `.local/setup/config.json` schema v4. Never select by mutable displayName,
  landing-page `titleId`, or an inferred filename.
- If setup has not established/materialized the intended target, follow
  `src/skills/foundation-setup/SKILL.md`, retain the original request, then return
  here. Do not require runtime connections, publication or `connect_ready`.
- A maker-supplied target different from the active target requires the existing
  setup target-selection flow first. Never silently substitute an agent.
- The helper checks live native identity, exact ESS product registry membership,
  and, for ALM, both the selected card and explicit Dev configuration. Test and
  Prod cannot be edited. These are quality gates in the same environment.
- Legacy DA-preview and custom-engine agents retain the existing compatible-kit
  handoff. Unknown products, unresolved identity and denied access are distinct
  failures; none permits a write. Do not offer a manual edit as successful ADK
  completion. This implementation authors native ESS Hub, HR and IT only:
  compatible-kit routing is not evidence that legacy authoring is implemented
  or validated. Do not add a speculative Dataverse fallback.
- Name and logo may be changed independently or together. Keeping current
  settings, identical decoded images, cancellation and optional setup
  customization perform no service write.

## Read and validate

For a current-state-only request:

```text
python scripts/agent_basics.py view
```

Consume `AGENT_BASICS_RESULT_JSON:`. Report only returned current values; an
unavailable name or logo is not a default value. Use the host image-viewing tool
on returned `current.colorPreview` and, when present, `current.outlinePreview`.
After displaying them, clean up that review's copies as described below.

Before collecting a change, state the selected manifest-compatible profile.
The maker supplied the Microsoft 365 app manifest v1.30
[name](https://learn.microsoft.com/en-us/microsoft-365/extensibility/schema/root-name?view=m365-app-1.30)
and [icon](https://learn.microsoft.com/en-us/microsoft-365/extensibility/schema/root-icons?view=m365-app-1.30)
constraints for this experience. These are publication-manifest constraints,
not proof that AgentBuilder enforces the same limits on native authoring.

| Property | Input |
|---|---|
| displayName | Nonblank, at most 30 Unicode characters; whitespace is preserved, not trimmed |
| Color logo | Local, fully decodable single-frame PNG, exactly 192x192 |
| Outline logo | Local, fully decodable single-frame PNG, exactly 32x32, transparent background and nonempty white artwork |
| Local preview safeguards | At most 1 MiB per PNG and one frame, so ADK can bound local resource use and show the complete static proposal; neither is an asserted native service limit |

Use the maker's exact values. Do not trim, truncate, crop, resize, convert,
generate an outline, or fetch arbitrary remote URLs. Color and outline assets
may be supplied separately: the helper retains the other current asset only
if it meets the selected profile. Show that retained asset as part of the
proposed logo and label it unchanged. If it cannot be retained, collect its
explicit replacement or let the maker keep the current logo/cancel; never
generate it. The manifest's optional 32x32 color asset has no established
independent native authoring mapping; do not claim to save it.

An unread or invalid property must not be written. Explain what needs correcting
and allow an independent valid/readable property to proceed in a separate
preview, only with the maker's agreement. Never silently drop a combined request.
Name-only saves use the existing metadata PUT, with the fetched logo fields
unchanged. A confirmed null color icon, or a decodable 192x192 color icon with
a nonempty outline, meets the inspected service's icon-preservation condition.
Other existing states return `serviceIconProcessingRisk` and
`serviceIconProcessingWarning` in the review instead of blocking the preview.
The existing service may resize/re-encode the color icon and clear the outline
and `colorIcon` fields. This is a risk, not proof that the deployed service
will change this agent's logo. Do not promise unchanged branding.
Do not require replacement images or a new/modified API just to rename.
Proceed only after separate, explicit approval of that possible service-side
processing as described below; otherwise keep the current state without writing.
ADK itself does not resize or replace the logo. Explicit logo/combined edits
still require review of valid supplied assets.

## Preview and explicit approval

Run the matching command with only requested arguments, quoting exact values and
local paths using the host shell's argument-escaping rules:

```text
python scripts/agent_basics.py preview --name "People Support"
python scripts/agent_basics.py preview --logo "C:\branding\color.png"
python scripts/agent_basics.py preview --logo "C:\branding\color.png" --outline "C:\branding\outline.png"
python scripts/agent_basics.py preview --name "People Support" --logo "C:\branding\color.png" --outline "C:\branding\outline.png"
```

Read `AGENT_BASICS_RESULT_JSON:` rather than inferring success from exit code.
If `writesDisabled` is true, keep this review read-only and use **Stop and
reviewed recovery**; do not offer ordinary save approval.
Show the selected product, tenant/environment, stable bot ID and authoring
quality gate, actual current and proposed requested values, and retained
properties. The displayName is not the ESS product identity.
Quote displayName values with JSON escaping where needed so whitespace or
nonprinting characters are not hidden in the current/proposed review.

For logo requests, display **every supplied source file** using the host
image-viewing tool, alongside the returned current previews. For a retained
asset, use its current preview as the unchanged proposed asset. Explain which is
the color and which is the outline asset, including dimensions and a concise
text description for accessibility. Paths, filenames and hashes alone are not
an image preview. If the host cannot render an image, stop the logo write and
explain; name-only may proceed with separate consent.

Use the host's structured question control with **Approve**, **Edit proposal**,
**Keep current**, and **Cancel**. Do not treat the initial edit request, a
generic yes, a digest, or a previous target's approval as approval of a new
review. Keyboard navigation must work; announce validation/conflict messages
in text, not color alone. Obtain approval only after the target, complete
proposed values and actual images have been presented.

In VS Code, use `vscode_askQuestions` with `allowFreeformInput: false` and
those four choices, initially unselected. In other supported hosts, use the
equivalent structured question tool. A dismissed question is not approval.
If the target, property or desired value is ambiguous, use that control to
clarify it before preparing a proposal.

If `serviceIconProcessingRisk` is present, also show its reason and the full
`serviceIconProcessingWarning` before offering approval. Explain that the name
can be submitted without new images, but preserving the current logo is not
guaranteed. Show available current icon previews; label any unavailable asset
honestly. Use a separate structured choice, initially unselected:
**Accept possible service-side icon processing** or **Keep current**.
The initial rename request and ordinary **Approve** do not provide this extra
consent. Only if the maker accepts the risk and approves this same review,
add `--accept-service-icon-processing` to the save command. If the maker
declines, cancels or dismisses either question, clean up and make no write.
Keep this consent bound to the reviewed target, proposal, snapshot and risk;
any new review requires approval again.

The `reviewId` binds target, workspace selection, service snapshot, requested
values, icon-processing risk and exact source bytes. Do not compute or alter it.
On **Approve**, rerun the exact proposal with `save --approval REVIEW_ID`:

```text
python scripts/agent_basics.py save --name "People Support" --approval REVIEW_ID
```

Retain `--logo` and `--outline` too for an approved logo/combined request.
The helper re-reads identity, permissions and state, compares the reviewed
digest and uses the fetched `BotEntity.version` in one protected metadata PUT.
It preserves the fetched entity and sends no component changes. It never
publishes. Do not bypass its checks or retry a PUT yourself.

On `review_again`, the prior approval is invalid: clean up the old review,
run a new preview, show refreshed state and require explicit approval again.
On **Edit proposal**, clean up first, then validate/preview the edited proposal.
**Keep current** and **Cancel** clean up and finish without writing.

## Results and uncertain recovery

- `saved` means authoritative read-back at a newer entity revision confirmed
  every requested property and preservation of unrequested metadata/components,
  including instructions. Local files or HTTP acknowledgment are not proof.
- Report each requested property's `saved`, `failed` or `unverified` result.
  If `preservation` is unverified, the operation remains unfinished, even when
  a requested value was observed. Do not roll back or proceed with more writes.
- For name-only saves, also report `logoPreservation` and any
  `changedLogoFields`. If the name is confirmed saved but logo fields changed,
  say **the rename was saved, but the service also changed the existing icon**.
  Do not call the rename failed or unchanged, claim full preservation, infer
  a visual change from bytes alone, repeat the rename, or silently accept the
  icon changes. Further writes remain stopped pending reviewed recovery,
  even when the maker accepted the pre-save risk.
- A pending-write marker is created before the PUT and retained after an
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
2. Record the affected validation attempt using scrubbed evidence, inform
   participants through the agreed study channel and involve the assigned
   engineering owner. Resolve the cause and review the intended corrective
   action before any more writes. Do not restore instructions through this skill.
3. Only after the owner has cleared the path, show a fresh `view` result and
   obtain explicit structured approval **to resume writes**, distinct from
   approval of any name/logo change. Pass that view's exact `reviewId`:

   ```text
   python scripts/agent_basics.py resume-writes --approval REVIEW_ID
   ```

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
