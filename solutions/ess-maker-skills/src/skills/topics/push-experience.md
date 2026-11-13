# Push experience

Apply the [shared foundation](experience-contract.md). Use this reference for inventory, scoped Push consent and composed results. Every approved save owner uses [Push telemetry](#push-telemetry). Read [Authoring experience](authoring-experience.md) for topic wording review, [Deletion experience](deletion-experience.md) before destructive consent, and [Testing experience](testing-experience.md) only when reaching a testing continuation.

## Contents

- [Component inventory: `{component_inventory}`](#component-inventory-component_inventory)
- [Inventory outcomes](#inventory-outcomes)
- [Entry inventory and choices](#entry-inventory-and-choices)
- [Type-level subset](#type-level-subset)
- [Component-level review](#component-level-review)
- [Compact change comparison](#compact-change-comparison)
- [Push statuses: `{push_statuses}`](#push-statuses-push_statuses)
- [Composed Push report: `{composed_push_report}`](#composed-push-report-composed_push_report)
- [Push telemetry](#push-telemetry)
- [Start the approved execution](#start-the-approved-execution)
- [Interpret the terminal result](#interpret-the-terminal-result)
- [Emit the terminal sequence once](#emit-the-terminal-sequence-once)

## Component inventory: `{component_inventory}`

Discover the component inventory for the selected agent. Preserve each entry's component type, name, exact identity, proposed change and applicability to this push.

Classify changes by their actual content, not their containing filename or YAML formatting. For `agent.mcs.yml`, compare the instruction section with its acknowledged baseline separately from other fields. List an unchanged instruction section as neither pending nor excluded. Represent a changed display name as **Display name**, naming the proposed value and its actual save limitation; do not relabel metadata as instruction changes.

Account for at least these component types:

- **Topics:** new or updated topic drafts.
- **Agent instructions:** instruction-section changes, not unrelated agent metadata.
- **Evaluation test sets:** changed sets; pushing does not imply running them.

The list is semi-fixed, not exhaustive. Include other discovered types when applicable, but offer push only where an owning operation actually supports it. Do not invent types or infer support from a name.

Use `{component_inventory}` for the entry list, type selector, component-level review, results table and Not included section. Derive displayed names, types and counts from its applicable entries.

Not included is a filtered view of `{component_inventory}`: discovered components outside this push's scope or without an available save operation. Reuse their component types and human-readable names throughout entry review, compact comparison and results. Keep the **Not included** heading, labeled component-type sections and one named bullet with its reason per component. Do not collapse exclusions into prose, combine several component names in one bullet, or substitute filename stems for discovered display titles. Do not duplicate entries already represented in the results table.

Show exclusions only when actual discovered changes require an explanation, naming the specific limitation. Do not make unsupported Push a routine branch or advertise retired functionality as an option.

Render each component type as a labeled section with bulleted contents. Omit empty sections. Inventory discovery alone does not establish remote validation.

### Inventory outcomes

Handle at least these cases after observation and appropriate in-scope recovery.

When inspection succeeds and finds nothing to push:

> **No changes to push.**

When inspection still cannot complete:

> **Could not inspect local changes.**
>
> {Cause}
>
> {Next safe action offer}

Explain the cause and offer the next safe action to the user rather than only announcing an action. Do not equate failed inspection with no changes or show runnable Push choices for these outcomes. Explain relevant actual exclusions contextually, without a routine unsupported-Push branch.

### Entry inventory and choices

Render applicable entries from `{component_inventory}`:

> **There are unpushed changes for {Agent}:**
>
> **Topics ({count})**
>
> - {Topic title}
>
> **Agent instructions**
>
> - {Short description of the instruction-section change}
>
> **Evaluation test sets ({count})**
>
> - {Set name}
>
> **Not included**
>
> **{Component type}**
>
> - {Component name}: {Exclusion reason}

Disclose material consequences, including actual evaluation new-copy/reuse and local-replacement effects, before the maker selects a Push action. For topic creation or update, apply Supported authoring scope and show unaccepted or acceptance-unknown response wording using the labels and quotations in [Response wording and local drafts](authoring-experience.md#response-wording-and-local-drafts) before any batch Push approval. Explain that Push accepts the displayed wording for the approved topics as well as authorizing their saves. For topic deletion, show the [deletion summary](deletion-experience.md#deletion-summary-delete_summary) `{delete_summary}`, including contained content and reference effects, rather than requesting response-wording acceptance. Do not require a separate wording approval or repeat owner gates for unchanged reviewed content. Then use:

> - **Summarize each change**
> - **Push all listed changes**
> - **Choose what to push**
> - **Cancel**

Selecting Push all listed changes approves every change in the displayed inventory for the identified agent. No additional approval is required for each component owner. A materially changed scope, intended behavior or consequence requires a revised summary and fresh approval. Cancel leaves all unattempted changes pending.

If inspection finds only excluded changes, explain those actual limitations and leave the changes pending without runnable Push choices. Do not call that an empty inspection or add a routine unsupported-Push response template.

### Type-level subset

Select applicable component types from `{component_inventory}`, starting with nothing selected. Each selected type includes all its changes listed in the inventory. This does not select individual fields or diff hunks.

> **Choose what to push**
>
> - {Component type}

After selection, use this choice control:

> **For the selected changes:**
>
> - **Summarize selected changes**
> - **Push selected changes**
> - **Cancel**

Push selected changes approves only the displayed selection, using the same batch-consent rule. Empty selection never means push everything.

### Component-level review

Review each applicable entry of `{component_inventory}` in turn, either across the full inventory or within the selected component types. Populate the summary using the relevant owner's agreed format.

> **{Component type}: {Name}**
>
> {Change summary}

Follow with a short choice control:

> **Push this change** / **Keep pending** / **Cancel remaining push**

For a topic with unaccepted suggested wording, include **I want to update the response** before Keep pending. Use the [Suggested-response decision](authoring-experience.md#suggested-response-decision) normal-chat revision continuation and return to this component's refreshed review before saving. Keep pending retains the local draft without accepting the suggestion.

Push this change approves and pushes this item, then continues. Keep pending leaves this item unpushed, then continues. Cancel remaining push stops, preserves completed pushes and leaves unprocessed changes pending.

One review item is one component-level push: the proposed edits to one topic, the selected agent's instruction-section edits, or one evaluation test-set deployment even if several cases changed. Two changed topics are two review items even when Topics was selected once. A review item is not a field edit, diff hunk or whole component-type group.

### Compact change comparison

Render `{compact_change_comparison}` in normal chat, separately from the short decision control:

> **Title:** {Topic title}
>
> **Agent:** {Destination agent}
>
> | Item             | Current                     | Proposed                     |
> | ---------------- | --------------------------- | ---------------------------- |
> | {Changed aspect} | {Current value or behavior} | {Proposed value or behavior} |
>
> **Unchanged**
>
> - {Verified preservation fact summary}
>
> **Notes**
>
> - {Note}
>
> **Not included**
>
> **{Component type}**
>
> - {Component name}: {Exclusion reason}

Use the freshly read saved state for Current, include the changed aspects and omit genuinely empty sections. Do not add a draft-link line to this template. Keep entries concise; existing labeled-quotation guidance handles material exact wording when needed, without a separate long-value template.

Before the decision control, populate Not included from the current inventory and selected scope, even when those entries appeared earlier in the conversation. Repeat the labeled type sections and individual name/reason bullets as needed; omit the block only when empty. A sentence such as "all other changes remain pending" does not replace this block.

### Push statuses: `{push_statuses}`

Use at least these applicable result labels:

- **Pushed:** remote save or deletion confirmed.
- **Kept pending:** deliberately left unpushed.
- **Cancelled:** left unattempted because the user stopped the remaining push.
- **Failed:** the push could not be completed and the cause is established; distinguish a pre-write prerequisite problem from an attempted-write failure in Details.
- **Unconfirmed:** the remote outcome cannot yet be established.
- **Pushed with local issue:** remote save or deletion confirmed, but subsequent local recording or bookkeeping failed.

Use Pushed with local issue rather than plain Pushed when that local failure remains. Choose the resulting status after appropriate recovery. Preserve causal details and remaining uncertainty in the Details cell or flexible trailer.

For an authoritatively verified already-satisfied topic, use Pushed with explicit Details that the requested content already existed, or the deletion target was already absent, and no new remote write was needed. Retain the same no-write disclosure with Pushed with local issue if local tracking failed. Do not attribute the existing change to this operation.

The report displays the applicable labels, not this whole explanatory catalog. Not included describes scope, not an additional result status. Do not introduce Blocked as a separate Push status.

If an observed prerequisite prevents the write, use Failed and explain that no write was attempted. If a write may have occurred, use Unconfirmed instead; known remote success followed by local failure remains Pushed with local issue.

### Composed Push report: `{composed_push_report}`

> **Push results**
>
> | Component      | Outcome  | Details                          |
> | -------------- | -------- | -------------------------------- |
> | {Type}: {Name} | {Status} | {Relevant detail or useful link} |
>
> **Not included**
>
> **{Component type}**
>
> - {Component name}: {Exclusion reason}
>
> {Contextual trailer}

Resolve component rows and Not included entries from `{component_inventory}`. Select each Status from `{push_statuses}`. Repeat rows and component-type sections as needed, omit an empty Not included section, and do not duplicate table entries there.

Preserve material owner facts, including known remote success, local recording issues and consequential evaluation-copy/review-state details. A topic and routing correction approved together use this report, with the complete instruction-save statement in its row rather than a second owner outcome block. The trailer carries useful context, including saved-wording conflict assessment and testing readiness, without repeating the table or stacking owner menus. Omit it when no additional context is needed.

Observe the result and attempt appropriate in-scope recovery. Continue with independently safe, already-approved changes. Pause dependent work when an unresolved result could affect its correctness or safety. Judge independence from the requested outcome, not merely different component types or files. User cancellation stops remaining work and preserves completed pushes.

After `{composed_push_report}`, continue already-requested next steps within their authorization rather than asking again. Deleted topics use [Deletion outcomes](deletion-experience.md#deletion-outcomes-delete_outcome_heads), not activation or conversation testing. For confirmed created or updated topics, read [Topic testing continuation](testing-experience.md#topic-testing-continuation). Carry the selected topic, actual save/state, existing authorization and declined corrections; use selection only when the target remains ambiguous.

Preserve required owner links/reminders once in the composed response, without duplicate owner reports or menus. If no follow-up applies, finish without a generic What next form. Pushing evaluations does not itself authorize running them. No publication or expanded scope is implied.

## Push telemetry

The session owns one lifecycle for each approved save batch. **Push all listed changes** and **Push selected changes** each define one batch; **Push this change** defines a one-component batch. A standalone approved topic or instruction save is also one batch. A topic and instruction correction approved together share a batch. Keep the approved scope, lifecycle ownership, observed times and emitted calls in session context. Nested component owners reuse that context and must not emit their own lifecycle. Separate later approvals start separate batches; recovery of the same approved operation does not.

An approved topic deletion pushed to the agent uses this same lifecycle. Local-only deletion and draft discard emit no Push lifecycle.

Apply this section to explicit evaluation Push, including selected evaluations inside a mixed batch. Do not add it to evaluation Run, Request Review or reviewer completion. Preserve their existing deployment and usage owners.

### Start the approved execution

Finish discovery, previews, target checks and applicable consent first. No local changes, a dry run, a draft kept locally or cancellation before execution emits no Push events. Excluded and kept-pending components are outside the approved batch, not failures.

Use the selected agent's verified ID, not its title. Immediately before dispatching the first approved save command, observe the clock:

```powershell
[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
```

Retain the returned integer as the start time, then invoke once:

```powershell
python scripts\emit_capability.py push --event build-start --agent-id "{AgentId}"
```

Dispatch the approved save through its owner. Do not add an initial `push` usage call; that count belongs to the terminal sequence below. Verification, local acknowledgement, in-scope recovery and pauses after start remain inside this execution window.

### Interpret the terminal result

Use observed owner results, not exit code alone. Maker-facing Pushed / Failed / Unconfirmed / Pushed with local issue remain separate from the coarse telemetry outcomes.

| Observed execution result                                                                                   | BuildOutcome | DeployOutcome  | BuildErrorCode         | DeployErrorCode          | ErrorCategory |
| ----------------------------------------------------------------------------------------------------------- | ------------ | -------------- | ---------------------- | ------------------------ | ------------- |
| Approved operations completed successfully, saved state verified, with at least one confirmed remote change | `success`    | `success`      | empty                  | empty                    | empty         |
| Approved operations completed successfully and all verified already-current content without writing         | `success`    | not emitted    | empty                  | empty                    | empty         |
| One or more dispatched component operations ended in error                                                  | `failure`    | `server_error` | `PUSH_PARTIAL_FAILURE` | `DEPLOY_PARTIAL_FAILURE` | `runtime`     |

A returned write error counts as operation failure even when its remote effect remains unconfirmed. `server_error` is the existing aggregate deploy label, not a claim that the service rejected every write. Preserve uncertainty and any confirmed saves in the maker-facing report; never replay a write merely to improve telemetry.

A successful owner result with only a non-fatal baseline-refresh or cleanup warning remains telemetry success. Report the local issue truthfully. If verified remote saves are followed by a hard local persistence or output failure that prevents owner completion, omit the terminal sequence while that failure remains. Do not relabel it as remote failure, downgrade an owner error to a warning, or change save/recovery behavior to produce a telemetry result.

Keep a paused or still-running batch open. On cancellation after execution starts, omit completion, deploy and usage events for that batch, including when some components were already saved. Preserve those confirmed saves and report the remaining cancellations. Separately completed batches retain their events. If execution context or timing is lost, do not fabricate completion.

The already-current mapping requires successful completion and authoritative no-write verification for every approved operation. A zero update count alone is insufficient. Failed, unconfirmed, paused or cancelled operations and unresolved hard local failures do not qualify. Do not force a write or claim a deployment occurred.

### Emit the terminal sequence once

For a mapped terminal result, observe the end clock after final verification, local work and authorized recovery. Subtract the retained start integer from that end integer to obtain `DurationMs`. Include post-start pauses; exclude earlier authoring and review. Use actual clock observations, never estimated conversation time. Missing or negative elapsed time is unavailable evidence, not zero.

Resolve `DeployTarget` only for a result that emits `agent-deploy`, from the target environment, not the agent's Dev/Prod realm. Honor `ESS_ADK_DEPLOY_TARGET` only when it is `sandbox` or `production`. Otherwise classify the selected environment's observed/cached `environmentSku` through the existing SDK. Use only metadata tied to the selected environment; do not borrow another agent's cached SKU. Use an empty string when no matching SKU is available:

```powershell
python -c "import sys; sys.path.insert(0, 'scripts'); import adk_telemetry; print(adk_telemetry.classify_deploy_target(sys.argv[1]))" "{EnvironmentSku}"
```

When the SKU is unavailable, the SDK's empty/unknown-SKU fallback is `production`; this is a telemetry default, not proof of environment type. Do not make an additional environment API request solely for telemetry. Do not switch identity, prompt for authentication or mutate environment configuration solely for telemetry.

Substitute the table's outcome and error fields, using empty strings for successful error fields. Invoke the applicable commands once, in this order. For verified already-current execution, omit the `agent-deploy` command and use build `success` with empty error fields; still emit one `push` usage event:

```powershell
python scripts\emit_capability.py push --event build-complete --agent-id "{AgentId}" --outcome "{BuildOutcome}" --duration-ms {DurationMs} --error-code "{BuildErrorCode}" --error-category "{ErrorCategory}"
python scripts\emit_capability.py push --event agent-deploy --agent-id "{AgentId}" --outcome "{DeployOutcome}" --duration-ms {DurationMs} --deploy-target "{DeployTarget}" --error-code "{DeployErrorCode}" --error-category "{ErrorCategory}"
python scripts\emit_capability.py push
```

These are save-execution events, not activation, publication, promotion or conversation acceptance. Telemetry is best-effort: preserve consent and continue the maker's operation if an emission fails. Exit zero is not ingestion confirmation. Do not retry unknown delivery, repurpose the SDK session ID, create persistent batch state, or include content, paths or raw diagnostic messages in event fields.
