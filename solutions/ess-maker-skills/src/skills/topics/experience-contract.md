# Topic authoring and Push experience

Read this contract before collecting topic requirements, presenting a topic or Push summary, asking for a decision, reporting an outcome, or offering testing. Use the owning operation for execution and authoritative readback.

## Presentation and scope

A template quote block contains only literal response/control content and simple substitution placeholders. Render the literal wording and paragraph structure, applying the stated bindings and conditions. Place any additional relevant context separately from the literal block. Keep instructions, variable definitions, status meanings, conditions, bindings and rendering rules outside template quote blocks. Do not present an instruction block as a response template.

Every UX instruction list is an **at-least baseline**, not an exhaustive closed list. This includes component types, summary fields, formatting guidance, choices, outcome heads, statuses, readiness cases and examples.

Include the defined baseline items where applicable and add relevant supported items when context requires them. Preserve approved fixed wording when reusing a head or choice. Keep the agreed omission of empty or unaffected sections.

Extensibility does not reintroduce explicitly excluded rules or options, invent capabilities, or expand consent. A displayed inventory, selected batch or approved debugging scope remains concrete and bounded; unlisted work is not silently authorized.

Use ordinary chat for open-ended requirements and revisions. Do not put a free-text-only exchange in a structured question. Retain structured controls for genuine choices; render summaries and previews in normal chat before a separate short control, not inside a long question description.

Use terse, external, semi-technical language about behavior and interfaces, without internal node labels. Use bold labels with whitespace between sections, short bullets for multiple inputs/outputs and required/optional markings where useful, inline code only for technical names the developer needs, and a link to the full draft for detail. Follow `src/reference/ui-formatting-guidelines.md` for UI actions.

Omit genuinely empty sections. Unresolved information is not absence: identify it as unresolved rather than omitting it or calling it absent. When exact proposed wording matters, use a labeled blockquote beneath the relevant description. Describe dynamic or grounded responses by content and source rather than inventing an exact quote. For lengthy wording, provide a clearly labeled excerpt and access to the full text.

## Authoring summaries

Resolve `{Topic title}` and `{Destination agent}` from the selected topic and target. Describe Behavior, accepted parameters/collected information under Inputs, returned values and employee-visible behavior under Outputs, and triggering scope under Starts when. `{Draft link}` is the actual local draft. An advisory alone does not add an acknowledgement gate.

### Advisory entries in Notes

Present advisories within Notes using the following structure. Repeat the advisory bullet as needed. Ordinary factual notes retain their existing form.

> **Notes**
>
> - {Advisory issue}. {Practical effect}.
>
>   **Suggested action:** {Concrete next action}.

`{Concrete next action}` is a specific, relevant recommended step to investigate or address the issue, identifying what to inspect, test or change and its purpose. `{Note}` in the summaries below represents an ordinary factual note. Include factual notes and advisory entries only when applicable.

For Create, state that creation is inactive and unpublished; activation is a separate choice in the testing follow-up. Render:

> **Title:** {Topic title}
>
> **Agent:** {Destination agent}
>
> **Behavior:** {Concise behavior description}
>
> **Inputs**
>
> - {Input}: {Input description}
>
> **Outputs**
>
> - {Output description}
>
> **Starts when:** {Triggering scope}
>
> **Notes**
>
> - {Note}
>
> - {Advisory issue}. {Practical effect}.
>
>   **Suggested action:** {Concrete next action}.
>
> [Full draft]({Draft link})

For Update, include only affected fields, concise before/after details where useful, and important verified preservation points. Preserve the existing active state. Render:

> **Title:** {Topic title}
>
> **Agent:** {Destination agent}
>
> **Behavior:** {Behavior change}
>
> **Inputs:** {Input changes}
>
> **Outputs:** {Output changes}
>
> **Starts when:** {Trigger changes}
>
> **Unchanged**
>
> - {Preserved behavior}
>
> **Notes**
>
> - {Note}
>
> - {Advisory issue}. {Practical effect}.
>
>   **Suggested action:** {Concrete next action}.
>
> [Full draft]({Draft link})

Follow either summary with a separate short choice control:

> **Push topic to agent** / **Keep as draft**

Keep as draft leaves the draft local without a remote write. Do not offer a runnable remote test for a draft-only outcome.

### Authorization and recovery

Ordinary authoring requires separate topic and instruction approvals. A topic save does not implicitly approve an instruction save.

A displayed Push batch has the scoped consent described below; do not repeat independent approvals for its unchanged approved operations. Carry the exact target, selected changes and material consequences into each owner.

Ordinary update approval covers safe recovery that still achieves the same approved change and preserves unrelated content, subject to owner safety/concurrency guards. Re-show the change-focused summary and obtain fresh approval for a materially changed target, behavior, scope or treatment of conflicting edits.

The scoped debugging exception is not blanket permission attached to a command named `/test`. A test-only request must not silently authorize edits. Establish the debugging objective and editable scope from an explicit request or the state-aware test-and-fix offer below. Carry that authorization into delegated topic or instruction work; an owner does not ask again for necessary in-scope fixes and pushes.

Within that authorization, repeated necessary fixes, pushes and retests do not each need fresh approval. Ask again for expanded scope, changed intended behavior or additional consequential actions. Preserve concurrency safeguards, known outcomes and uncertainty; do not blindly repeat an uncertain operation. The exception does not itself authorize publication, unrelated changes or unsupported capabilities.

### Topic outcomes

The head catalog `{topic_outcome_heads}` covers at least these resulting outcomes:

- Confirmed remote push: **Topic pushed to agent.**
- Draft retained locally without a remote change: **Draft kept locally. Agent unchanged.**
- Blocked before saving, or confirmed rejection: **Topic was not pushed.**
- Remote outcome remains uncertain: **Topic push could not be confirmed.**
- Remote save confirmed, but a subsequent local write failed: **Topic pushed; workspace update incomplete.**

Select the head from the resulting known state after observation and appropriate session-led recovery. Add the flexible factual trailer. Preserve known remote success after a local failure; do not claim the agent is unchanged when its remote outcome is uncertain.

The flexible trailer carries relevant identity, observed state, draft link, cause, pending work or next safe action. Render:

> **{Outcome head}**
>
> {Contextual trailer}

During composed Push, contribute these known facts to the single composed report instead of stacking owner reports.

## Component inventory: `{component_inventory}`

Discover the component inventory for the selected agent. Preserve each entry's component type, name, exact identity, proposed change and applicability to this push.

Account for at least these component types:

- **Topics:** new or updated topic drafts.
- **Agent instructions:** instruction-section changes, not unrelated agent metadata.
- **Evaluation test sets:** changed sets; pushing does not imply running them.

The list is semi-fixed, not exhaustive. Include other discovered types when applicable, but offer push only where an owning operation actually supports it. Do not invent types or infer support from a name.

Use `{component_inventory}` for the entry list, type selector, component-level review, results table and Not included section. Derive displayed names, types and counts from its applicable entries.

Not included is a filtered view of `{component_inventory}`: discovered components outside this push's scope or support boundary. Reuse their identities and labels, give the reason, and do not duplicate entries already represented in the results table.

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

Disclose material consequences, including actual evaluation new-copy/reuse and local-replacement effects, before the maker selects a Push action. Then use:

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

Push this change approves and pushes this item, then continues. Keep pending leaves this item unpushed, then continues. Cancel remaining push stops, preserves completed pushes and leaves unprocessed changes pending.

One review item is one component-level push: the proposed edits to one topic, the selected agent's instruction-section edits, or one evaluation test-set deployment even if several cases changed. Two changed topics are two review items even when Topics was selected once. A review item is not a field edit, diff hunk or whole component-type group.

### Compact change comparison

Render `{compact_change_comparison}` in normal chat, separately from the short decision control:

> **Title:** {Topic title}
>
> **Agent:** {Destination agent}
>
> | Item | Current | Proposed |
> | --- | --- | --- |
> | {Changed aspect} | {Current value or behavior} | {Proposed value or behavior} |
>
> **Unchanged**
>
> - {Verified preservation fact summary}
>
> **Notes**
>
> - {Note}

Use the freshly read saved state for Current, include the changed aspects and omit genuinely empty sections. Do not add a draft-link line to this template. Keep entries concise; existing labeled-quotation guidance handles material exact wording when needed, without a separate long-value template.

### Push statuses: `{push_statuses}`

Use at least these applicable result labels:

- **Pushed:** remote save confirmed.
- **Kept pending:** deliberately left unpushed.
- **Cancelled:** left unattempted because the user stopped the remaining push.
- **Failed:** the push could not be completed and the cause is established; distinguish a pre-write prerequisite problem from an attempted-write failure in Details.
- **Unconfirmed:** the remote outcome cannot yet be established.
- **Pushed with local issue:** remote save confirmed, but subsequent local recording or bookkeeping failed.

Use Pushed with local issue rather than plain Pushed when that local failure remains. Choose the resulting status after appropriate recovery. Preserve causal details and remaining uncertainty in the Details cell or flexible trailer.

The report displays the applicable labels, not this whole explanatory catalog. Not included describes scope, not an additional result status. Do not introduce Blocked as a separate Push status.

If an observed prerequisite prevents the write, use Failed and explain that no write was attempted. If a write may have occurred, use Unconfirmed instead; known remote success followed by local failure remains Pushed with local issue.

### Composed Push report: `{composed_push_report}`

> **Push results**
>
> | Component | Outcome | Details |
> | --- | --- | --- |
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

Preserve material owner facts, including known remote success, local recording issues and consequential evaluation-copy/review-state details. The trailer carries useful context without repeating the table or stacking owner menus. Omit it when no additional context is needed.

Observe the result and attempt appropriate in-scope recovery. Continue with independently safe, already-approved changes. Pause dependent work when an unresolved result could affect its correctness or safety. Judge independence from the requested outcome, not merely different component types or files. User cancellation stops remaining work and preserves completed pushes.

After `{composed_push_report}`, continue already-requested next steps within their authorization rather than asking again. When a relevant testing step has not already been requested, offer it once for confirmed pushed topics using the testing continuation below. Carry or infer the topic and use selection only when the target remains ambiguous.

Preserve required owner links/reminders once in the composed response, without duplicate owner reports or menus. If no follow-up applies, finish without a generic What next form. Pushing evaluations does not itself authorize running them. No publication or expanded scope is implied.

## Topic testing continuation

Check `scripts/native_topic_test.py` directly before offering runnable conversation testing. If unavailable, report conversation acceptance as pending and the actual capability gap; do not imply that a save/readback tested the conversation.

### Scoped runtime correctness goal

Debug and fix the topic under test so its observed runtime behavior meets the latest authoring request, within the authorized scope. Make a lightweight, best-effort check that the behavior and proposed fixes preserve matching eval intent; keep those evals read-only. Continue useful in-scope investigation and corrections, checking the affected runtime behavior after changes. When conflicting goals or constraints prevent progress, recommend a concrete reconciliation. When tools, access or available evidence prevent further safe progress, explain the limitation and offer practical assistance, including manual testing guidance where appropriate. Honor explicit test-only, pause and stop requests.

Use relevant existing cases and useful probes as advisory intent checks, not a graded eval run or a mandatory case-by-case coverage exercise. A fixable in-scope mismatch calls for further investigation and correction, not merely a recommendation to the maker. Do not weaken the authoring goal or edit evals to manufacture agreement.

### Topic debugging outcome: `{topic_test_results}`

Use `{topic_test_results}` to summarize the requested goal and current observed runtime outcome in normal chat. Describe behavior and its limits rather than attempts or iterations. This is an informational report, not another approval gate. Ask separately only for genuine human input or a new scope decision; necessary in-scope fixes and retests already have authorization. Finish without an automatic follow-up form.

Resolve `{Topic title}`, `{Agent name}` and `{Environment name}` from the selected target. `{Latest authoring goal}` is the requested behavior, not whatever reply happens to be saved. `{Observed runtime outcome}` states the behavior actually observed without claiming exhaustive validation.

When the requested behavior is observed, render:

> **Topic debugging outcome**
>
> **Topic:** {Topic title}
>
> **Target:** {Agent name}, {Environment name}
>
> **Goal:** {Latest authoring goal}
>
> **Outcome:** {Observed runtime outcome}

When a change or assistance is needed, render:

> **Topic debugging outcome**
>
> **Topic:** {Topic title}
>
> **Target:** {Agent name}, {Environment name}
>
> **Goal:** {Latest authoring goal}
>
> **Outcome:** {Current outcome and obstacle}
>
> **Recommendation:** {Concrete tweak or next action}

`{Current outcome and obstacle}` preserves completed work, unfinished or unobserved behavior and material uncertainty. `{Concrete tweak or next action}` addresses the actual obstacle: reconcile conflicting authoring constraints or eval intent, offer manual testing guidance for a tooling limitation, or identify a missing prerequisite or observation. These are applicable examples, not mandatory report categories. Do not hand back work that can still be performed safely within the existing authorization.

Render the selected block using its quoted wording, emphasis and paragraph breaks. Link actual available evidence after the complete outcome block; omit unavailable links. Preserve material evidence limitations without adding a mandatory test ledger, regression matrix or grading claim. For pause/stop, keep the fixed acknowledgement separate and report any completed work using the appropriate outcome block.

### Testing offers

Carry the selected topic forward. Creation stays inactive; updating preserves current state. Activate only after explicit Activate and test selection, confirm the result before testing, and do not publish. If state is unverified, resolve it or report the blocker; do not guess which state-dependent action applies.

When offering testing after authoring, use the question matching the topic's active state. Do not repeat the offer when testing has already been requested. Honor explicit requests to test without making changes.

For an active topic:

> **Test {Topic title} and fix any issues found?**
>
> **Test topic now** / **Not now**

For an inactive topic:

> **Activate {Topic title}, test it and fix any issues found?**
>
> **Activate and test** / **Not now**

When testing has already been requested but activation permission is missing:

> **Activate {Topic title} for testing?**
>
> **Activate and test** / **Not now**

Honor an explicit no-activation instruction and report the unresolved prerequisite using `{topic_test_results}`. A test-and-fix choice authorizes necessary fixes, pushes and retests within the selected scope, not unrelated changes or publication.

Test topic now continues into the testing owner with the selected topic and the authorized objective/editable scope. Activate and test performs the separately authorized activation continuation, then tests only after confirmed activation. An already-requested test does not waive missing activation permission. Honor explicit no-activation requests.

Not now uses the following outcome, then stops:

> **Testing deferred.**
>
> {Contextual trailer}

### Browser readiness and testing goal

Prepare or reuse the test browser, open the selected agent and resolve the browser connection internally. The maker opens the Test chat pane. Render the following readiness message in normal chat when confirmation is needed. Resolve `{Topic title}`, `{Agent name}` and `{Environment name}` from the selected context rather than asking for known values again. Omit the sign-in paragraph when the browser is already signed in with a test account. Reuse valid readiness confirmation instead of repeating this exchange. Use the test-and-fix goal below for an authorized test-and-fix request; preserve explicit test-only scope.

> **Test browser readiness**
>
> **Topic:** {Topic title}
>
> **Target:** {Agent name}, {Environment name}
>
> In the prepared test browser, sign in with a test account.
>
> Open the Test chat pane and leave its message box empty and idle.
>
> After you confirm readiness, I will test {Topic title} against its intended behavior, investigate and fix issues observed during execution, and retest the affected behavior.
>
> I will summarize the outcome and recommend any next action needed.

Render the readiness message using the quoted wording, emphasis and paragraph breaks. Start any additional scope context after a blank line following the readiness message.

Follow with this separate readiness-only control. Missing activation permission remains a separate requirement; this choice does not expand the testing/editing scope.

> **Is the test browser ready?**
>
> **Ready to test** / **Not ready, keep paused** / **Stop without sending**

For an explicit test-only request, describe that authorized scope without promising edits. An optional exact-response check remains one supported assertion, not a universal one-message or fixed-response-only testing policy.

### Pause, stop and resume

Apply the selected pause or stop immediately; no additional input is needed for either choice to take effect. Use the corresponding acknowledgement exactly. Preserve completed work and report it separately using `{topic_test_results}`.

For **Not ready, keep paused**:

> **Testing paused.**
>
> Let me know when the test browser is ready.

For **Stop without sending**:

> **Testing stopped.**

A pause waits for the maker's readiness or resume signal. A stop ends further testing until a later explicit request. On resumption, continue within the existing objective and scope, reusing valid context and permissions and resolving only missing or changed prerequisites. Completed activation, fixes or pushes remain completed; pausing or stopping does not roll them back.

### Unresolved prerequisites

Resolve session-owned preparation and connection work internally before handing an unresolved prerequisite back to the maker. Prepare or reuse the test browser and open the selected agent. Ask the maker only for a genuine human action, missing permission or scope decision.

Use the activation-only question when testing is already requested and only activation permission is missing. Honor explicit no-activation and test-only instructions. Use the browser-readiness message and separate readiness control when confirmation is needed, reusing valid readiness.

Preserve completed work and uncertain outcomes; do not blindly repeat an uncertain write. Report unresolved prerequisites using `{topic_test_results}`, identifying unfinished testing explicitly. Ask any genuinely required decision separately; use normal chat for free-text clarification. Omit genuinely empty sections and unavailable evidence links.
