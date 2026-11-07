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

Present non-routing advisories within Notes using the following structure. Repeat the advisory bullet as needed. Ordinary factual notes retain their existing form.

> **Notes**
>
> - {Advisory issue}. {Practical effect}.
>
>   **Suggested action:** {Concrete next action}.

`{Concrete next action}` is a specific, relevant recommended step to investigate or address the issue, identifying what to inspect, test or change and its purpose. `{Note}` in the summaries below represents an ordinary factual note. Include factual notes and advisory entries only when applicable.

### Routing Conflicts

Put instruction-routing conflicts in Routing Conflicts, separate from topic state and pending testing, rather than in Notes. Do not duplicate the conflict in both sections. Omit empty sections; ordinary factual notes and unrelated advisories retain their existing form.

> **Routing Conflicts**
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
>
>   **Suggested action:** {Concrete next action}.

`{Routing conflict}` identifies the observed instruction constraint and affected topic behavior. The execution-impact statement describes a likely consequence, not a confirmed conversation-test failure. Recommend a targeted instruction correction before testing.

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
> - {Advisory issue}. {Practical effect}.
>
>   **Suggested action:** {Concrete next action}.
>
> **Routing Conflicts**
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
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
> - {Advisory issue}. {Practical effect}.
>
>   **Suggested action:** {Concrete next action}.
>
> **Routing Conflicts**
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
>
>   **Suggested action:** {Concrete next action}.
>
> [Full draft]({Draft link})

Follow either summary with the initial routing-conflict decision below when an instruction-routing conflict is known. Otherwise use this separate short choice control:

> **Push topic to agent** / **Keep as draft**

Keep as draft leaves the draft local without a remote write. Do not offer a runnable remote test for a draft-only outcome.

### Initial routing-conflict decision

When the initial Create or Update review identifies an instruction-routing conflict, offer resolution before any topic or instruction push. Follow the completed summary with:

> **How would you like to continue with {Topic title}?**
>
> **Resolve the routing conflict in the Agent Instructions** / **Push topic anyway** / **Keep as draft**

Resolve the routing conflict in the Agent Instructions prepares the targeted correction below while the proposed topic changes remain local. This choice does not approve a topic push, instruction push, activation or testing. Do not draft an instruction correction merely because a topic is being authored unless the correction is already within an explicitly authorized scope.

Review the topic draft and targeted instruction correction together before saving either. Use the existing component-level or scoped batch Push review and consent for exactly those displayed changes; exclude unrelated pending edits. Do not repeat owner approval for unchanged operations covered by that consent. Save and verify a new topic before an instruction correction that depends on its existence; pause dependent work if the prerequisite result is failed or uncertain.

Push topic anyway approves only the displayed topic save and leaves the conflicting instructions unchanged. It does not authorize activation, testing or publication. Carry the declined routing correction as an explicit exclusion into any later authorized testing. Do not immediately offer the same resolution decision again after saving.

Keep as draft performs no remote save. Retain the proposed changes locally and do not offer runnable testing of unsaved topic changes. Reuse an existing unchanged scoped approval rather than repeating this decision.

### Authorization and recovery

Ordinary authoring requires separate topic and instruction approvals. A topic save does not implicitly approve an instruction save.

A displayed Push batch has the scoped consent described below; do not repeat independent approvals for its unchanged approved operations. Carry the exact target, selected changes and material consequences into each owner.

Ordinary update approval covers safe recovery that still achieves the same approved change and preserves unrelated content, subject to owner safety/concurrency guards. Re-show the change-focused summary and obtain fresh approval for a materially changed target, behavior, scope or treatment of conflicting edits. For a rejected conflicting save, retain the truthful outcome head, then render the Update summary with Title, Agent, the freshly read current wording versus the proposal, verified Unchanged facts, applicable advisories and Full draft. Follow it with the specific replacement or draft-only decision; the conflicting excerpts alone do not replace the summary.

The scoped debugging exception is not blanket permission attached to a command named `/test`. A test-only request must not silently authorize edits. Establish the debugging objective and editable scope from an explicit request or the state-aware test-and-fix offer below. Carry that authorization into delegated topic or instruction work; an owner does not ask again for necessary in-scope fixes and pushes.

Within that authorization, repeated necessary fixes, pushes and retests do not each need fresh approval. Ask again for expanded scope, changed intended behavior or additional consequential actions. Preserve concurrency safeguards, known outcomes and uncertainty; do not blindly repeat an uncertain operation. The exception does not itself authorize publication, unrelated changes or unsupported capabilities.

### Topic outcomes

The head catalog `{topic_outcome_heads}` covers at least these resulting outcomes:

- Confirmed remote push: **Topic pushed to agent.**
- Requested content verified already present without a new remote write: **Topic already up to date. No push needed.**
- Draft retained locally without a remote change: **Draft kept locally. Agent unchanged.**
- Blocked before saving, or confirmed rejection: **Topic was not pushed.**
- Remote outcome remains uncertain: **Topic push could not be confirmed.**
- Remote save confirmed, but a subsequent local write failed: **Topic pushed; workspace update incomplete.**

Select the head from the resulting known state after observation and appropriate session-led recovery. Add the flexible factual trailer. Preserve known remote success after a local failure; do not claim the agent is unchanged when its remote outcome is uncertain.

When authoritative verification succeeds with `writeAttempted: false` and `updatedComponents: 0`, use the already-up-to-date head, not a pushed head. Do not attribute the existing change to this operation. If local tracking fails afterward, retain the no-write head and disclose that local issue in the factual trailer. A zero update count alone does not establish verification.

The flexible trailer carries relevant identity, observed state, draft link, cause, pending work or next safe action. Render:

> **{Outcome head}**
>
> {Contextual trailer}

During composed Push, contribute these known facts to the single composed report instead of stacking owner reports.

Use the draft-only Agent unchanged head only when none of this operation's components were remotely changed. For partial saves, use the composed report with actual per-component outcomes rather than a global unchanged claim.

### Combined routing-conflict and testing follow-up

Use this combined decision only when a routing conflict is newly discovered or materially changed after Push. If the maker already chose Push topic anyway, or deliberately omitted the reviewed correction, honor that decision: retain the unresolved-conflict reminder and offer ordinary state-aware testing once, with the correction excluded. Do not repeat the resolution choice for the same conflict.

For a newly discovered or materially changed conflict after a confirmed topic push, present the saved result, verified topic state and pending testing separately from Routing Conflicts:

> **Topic pushed to agent.**
>
> Saved **{Topic title}** to **{Destination agent}**.
>
> {Verified topic state}. Conversation testing is pending.
>
> **Routing Conflicts**
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
>
>   **Suggested action:** {Concrete next action}.

For a verified no-write result or a confirmed save with a local issue, retain the corresponding truthful `{topic_outcome_heads}` head and factual trailer rather than claiming a new push. `{Verified topic state}` comes from observed native state, not the save itself.

Follow with one combined decision, not a routing-resolution offer followed by another testing offer. Check the installed testing capability before offering a runnable test; report an actual capability gap rather than advertising unavailable testing. Without a routing conflict, use the ordinary state-aware testing offer.

For an inactive topic:

> **How would you like to continue with {Topic title}?**
>
> **Resolve the routing conflict in the Agent Instructions** / **Not now, Activate and test anyway.**

For an active topic:

> **How would you like to continue with {Topic title}?**
>
> **Resolve the routing conflict in the Agent Instructions** / **Not now, Test anyway.**

Resolve the routing conflict in the Agent Instructions prepares the targeted preview below. This choice does not approve an instruction push, activation or testing.

Not now, Activate and test anyway. leaves the conflicting instructions unchanged and authorizes activation and testing of the selected inactive topic. Confirm authoritative Active state before sending a test message. Not now, Test anyway. continues directly into testing of the selected active topic without activation. Neither selection introduces another testing offer.

Carry forward the testing objective and authorized editable scope. These choices do not create blanket debugging consent. Carry the declined routing correction as an explicit exclusion into the testing owner; do not silently repair it during testing. Preserve browser-readiness checks, test-only/no-activation limits and pause/stop handling. None of these choices authorizes publication.

Resolve unverified topic state or report its blocker rather than guessing which choice applies. Preserve the existing scoped batch/debugging consent rules and do not repeat a decision already established by explicit authorization. Do not make instruction correction a prerequisite for a deliberate topic-only save.

### Targeted instruction-change preview and approval

#### Prepare the correction

Carry forward the selected agent, topic, identified conflict and actual topic-save state. Use current native instruction evidence to prepare the smallest targeted correction through the normal instruction owner.

Preserve unrelated live instructions and pending local edits. Isolate the correction without losing other drafts or including them in the proposed push.

If current instructions cannot be established or the correction cannot be isolated, explain the missing evidence or scope issue and offer the next safe action. Do not present a runnable Push choice.

If the desired correction is already authoritatively present, report **Agent instructions already up to date.** using the existing no-write outcome. Preserve the actual topic-save state; do not offer an unnecessary instruction push.

#### Show the preview

Use actual instruction text. Show the affected current wording, exact proposed wording, intended routing effect and verified preservation facts. Label lengthy excerpts and provide access to the full draft. Do not claim preservation that has not been checked.

> **Instruction change ready for review.**
>
> **Agent:** {agent_name}
>
> **Related topic:** {topic_title}
>
> **Routing conflict:** {routing_conflict}
>
> **Proposed change:** {proposed_change}
>
> **Current wording**
>
> > {current_affected_wording}
>
> **Proposed wording**
>
> > {proposed_affected_wording}
>
> **Unchanged:** {verified_preservation_facts}
>
> This instruction change has not been pushed. This preview does not authorize activation or testing.
>
> {topic_save_state}

`{topic_save_state}` describes the currently proposed topic content, covering at least these cases:

| State                   | What to communicate                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------ |
| New local draft         | The new topic remains local and has not been pushed.                                 |
| Local update            | The proposed changes remain local; distinguish them from the existing saved topic.   |
| Pushed                  | The proposed topic content was confirmed saved remotely.                             |
| Already current         | The proposed content was confirmed already saved; no new write was needed.           |
| Kept pending            | The selected changes were deliberately left unpushed.                                |
| Cancelled               | Remaining changes were left unattempted at the user's request.                       |
| Failed                  | A prerequisite prevented the write or non-save is confirmed. Explain which occurred. |
| Unconfirmed             | The remote save outcome cannot be established.                                       |
| Pushed with local issue | The remote save succeeded, but subsequent workspace recording remains incomplete.    |

Include concise factual detail and preserve earlier confirmed saves. Do not describe newer local changes as pushed merely because an earlier topic version exists remotely. Reuse established Push-result labels where applicable.

#### Review and approve the save

**When topic changes remain local:** review the topic and isolated instruction correction together using **Entry inventory and choices** in `src/skills/topics/experience-contract.md`. Render its applicable inventory entries and reuse its full four-item choice block verbatim: **Summarize each change**, **Push all listed changes**, **Choose what to push**, and **Cancel**. Include exactly those displayed changes, excluding unrelated pending edits.

**Only when the proposed topic content is already authoritatively saved:** use this two-item control for the instruction correction:

> **Push this instruction change to {agent_name}?**
>
> **Push instruction change** / **Keep as draft**

Reuse valid scoped consent for unchanged operations. During composed Push, reuse its component-level decision rather than adding another approval control.

Push instruction change authorizes only the displayed correction for the identified agent. It does not authorize activation, testing or publication.

#### Apply an approved change

- Use the owning operations and preserve their concurrency and readback safeguards.
- Save and verify a new topic before an instruction correction that depends on its existence.
- Pause dependent work after a failed or uncertain prerequisite.
- Obtain fresh approval if the target, scope, intended behavior or material consequences change.

Report each component's actual result. An instruction save does not establish that the topic was saved, activated or successfully tested.

#### Keep changes as drafts

Keep as draft retains the correction locally without an instruction push, activation or testing.

> **Instruction draft kept locally.**
>
> No instruction change was pushed. {topic_save_state} The routing conflict remains unresolved.

If both changes remain local, explicitly report that neither was pushed. Preserve any earlier confirmed remote changes; do not describe the entire agent as unchanged after a confirmed write.

Do not offer runnable testing of unsaved topic changes. For already-saved topic content, honor the declined correction and obtain only any missing activation or testing permission.

### Instruction-push outcomes and testing

Report the actual instruction-save result and reassess the identified conflict using the saved wording. Report the actual topic-save state; preserve any earlier confirmed topic push as completed work, but do not assume one occurred. Do not repeat an unchanged valid Push approval or imply that an instruction update saves or activates the topic.

For composed Push, including a topic and routing correction approved together, use `{composed_push_report}` instead of separate topic and instruction outcome blocks. Put the complete `{Verified instruction-save result}` statement below in the instruction row's Details, with each component's actual status. Put the conflict assessment and verified testing readiness in the contextual trailer, then use the applicable testing offer once. Preserve failed, uncertain and partial results; a saved instruction does not establish a saved topic.

Outside composed Push, use the head matching the resulting known facts:

- Confirmed instruction write and authoritative readback: **Instructions pushed to agent.**
- Desired correction authoritatively verified without a write: **Agent instructions already up to date.**
- Confirmed non-save: **Instructions were not pushed.**
- Remote outcome remains uncertain: **Instruction push could not be confirmed.**
- Remote save confirmed but subsequent local recording remains incomplete: **Instructions pushed; workspace update incomplete.**

Outside composed Push, when the saved wording addresses the identified conflict, render:

> **{Instruction outcome head}**
>
> {Verified instruction-save result}
>
> The saved wording addresses the identified routing conflict. Topic execution has not yet been verified.
>
> {topic_save_state}
>
> {Testing readiness}

`{Verified instruction-save result}` uses the applicable complete statement below, including the named correction, agent and related topic even when those identities also appear elsewhere. Preserve the standalone block's paragraph breaks. In a composed report, use the statement in Details without adding an instruction outcome head.

**Saved in this operation:** outside composed Push, use the **Instructions pushed to agent.** head.

> {Instruction correction} was saved in **{Agent name}** for **{Topic title}** and confirmed by instruction readback.

**Already present; no write:** outside composed Push, use the **Agent instructions already up to date.** head.

> Instruction readback confirmed that {Instruction correction} was already present in **{Agent name}** for **{Topic title}**. No instruction write was needed.

For a confirmed save followed by a local recording issue, retain the confirmed-save statement and describe the unfinished local work. Use **Pushed with local issue** in a composed report or the **Instructions pushed; workspace update incomplete.** standalone head. Failed or uncertain instruction saves use their corresponding status or standalone head and do not use either confirmed-state statement.

`{Testing readiness}` gives the verified active or inactive state and pending testing only when the proposed topic content is authoritatively saved or verified already current. Otherwise state that topic Push is still pending and do not offer runnable conversation testing. For partial saves, report each component's actual result rather than claiming the whole agent is unchanged.

Omit the resolved Routing Conflicts advisory. For authoritatively saved topic content, reuse **Testing offers** in `src/skills/topics/experience-contract.md`. Render the applicable quoted control verbatim and follow its consent, continuation and deferral rules. Use **Scoped runtime correctness goal** for the authorized testing, fixes and retesting. Reuse existing authorization rather than presenting another offer. Instruction-push approval does not supply topic-push, testing or activation consent.

For a failed or uncertain instruction push, or a remaining conflict after readback, preserve the actual result and uncertainty. Recover within the approved scope without blindly repeating an uncertain write. Do not claim resolution or enter the resolved-conflict testing path. If the maker explicitly requests testing despite the remaining conflict, require authoritatively saved topic content, obtain only missing testing or activation permission and carry the declined correction as an explicit exclusion. Do not automatically repeat resolution for the same conflict. No publication is authorized.

## Component inventory: `{component_inventory}`

Discover the component inventory for the selected agent. Preserve each entry's component type, name, exact identity, proposed change and applicability to this push.

Classify changes by their actual content, not their containing filename or YAML formatting. For `agent.mcs.yml`, compare the instruction section with its acknowledged baseline separately from other fields. List an unchanged instruction section as neither pending nor excluded. Represent a changed display name as **Display name**, naming the proposed value and its actual save limitation; do not relabel metadata as instruction changes.

Account for at least these component types:

- **Topics:** new or updated topic drafts.
- **Agent instructions:** instruction-section changes, not unrelated agent metadata.
- **Evaluation test sets:** changed sets; pushing does not imply running them.

The list is semi-fixed, not exhaustive. Include other discovered types when applicable, but offer push only where an owning operation actually supports it. Do not invent types or infer support from a name.

Use `{component_inventory}` for the entry list, type selector, component-level review, results table and Not included section. Derive displayed names, types and counts from its applicable entries.

Not included is a filtered view of `{component_inventory}`: discovered components outside this push's scope or support boundary. Reuse their component types and human-readable names throughout entry review, compact comparison and results. Keep the **Not included** heading, labeled component-type sections and one named bullet with its reason per component. Do not collapse exclusions into prose, combine several component names in one bullet, or substitute filename stems for discovered display titles. Do not duplicate entries already represented in the results table.

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

- **Pushed:** remote save confirmed.
- **Kept pending:** deliberately left unpushed.
- **Cancelled:** left unattempted because the user stopped the remaining push.
- **Failed:** the push could not be completed and the cause is established; distinguish a pre-write prerequisite problem from an attempted-write failure in Details.
- **Unconfirmed:** the remote outcome cannot yet be established.
- **Pushed with local issue:** remote save confirmed, but subsequent local recording or bookkeeping failed.

Use Pushed with local issue rather than plain Pushed when that local failure remains. Choose the resulting status after appropriate recovery. Preserve causal details and remaining uncertainty in the Details cell or flexible trailer.

For an authoritatively verified already-satisfied topic, use Pushed with explicit Details that the requested content already existed and no new remote write was needed. Retain the same no-write disclosure with Pushed with local issue if local tracking failed. Do not attribute the existing change to this operation.

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

After `{composed_push_report}`, continue already-requested next steps within their authorization rather than asking again. For confirmed pushed topics, honor the initial routing-conflict decision. Only for a newly discovered or materially changed conflict, use the combined routing-conflict/testing decision above, not a second testing offer. Otherwise offer relevant testing once using the continuation below, carrying any deliberately declined correction as an exclusion. Do not offer runnable testing of topic changes left local. Carry or infer the topic and use selection only when the target remains ambiguous.

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

After authoring, honor the initial routing-conflict decision. Use the combined routing-conflict/testing decision only for a newly discovered or materially changed conflict after Push. A selected test-anyway continuation enters testing directly with the declined instruction correction excluded; do not repeat the ordinary testing offer or silently fix that conflict. After Push topic anyway, use the ordinary question matching the saved topic's active state, carrying the declined correction as an explicit exclusion and retaining a concise conflict reminder. The topic-only Push did not authorize testing. Without a conflict, or after a verified instruction correction, use the same ordinary question. Do not offer runnable testing of topic changes left local or repeat an offer when testing has already been requested. Honor explicit requests to test without making changes.

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
