# Topic authoring experience

Apply the [shared foundation](experience-contract.md). Use this reference for Create/Update review and outcomes. Load [Push experience](push-experience.md) for a composed review or result, and [Testing experience](testing-experience.md) only when reaching the testing continuation.

## Contents

- [Authoring summaries](#authoring-summaries)
- [Response wording and local drafts](#response-wording-and-local-drafts)
- [Advisory entries in Notes](#advisory-entries-in-notes)
- [Routing Conflicts](#routing-conflicts)
- [Create summary](#create-summary)
- [Update summary](#update-summary)
- [Topic save decision](#topic-save-decision)
- [Suggested-response decision](#suggested-response-decision)
- [Initial routing-conflict decision](#initial-routing-conflict-decision)
- [Topic outcomes](#topic-outcomes)
- [Combined routing-conflict and testing follow-up](#combined-routing-conflict-and-testing-follow-up)
- [Targeted instruction-change preview and approval](#targeted-instruction-change-preview-and-approval)
- [Instruction-push outcomes and testing](#instruction-push-outcomes-and-testing)

## Authoring summaries

Resolve `{Topic title}` and `{Destination agent}` from the selected topic and target. Describe Behavior, accepted parameters/collected information under Inputs, returned values and employee-visible behavior under Outputs, and triggering scope under Starts when. `{Draft link}` is the actual local draft. An advisory alone does not add an acknowledgement gate.

Apply [Advisory entries in Notes](#advisory-entries-in-notes) and [Routing Conflicts](#routing-conflicts) when those sections are relevant to either summary.

### Response wording and local drafts

Preserve wording supplied as the intended response, including links. Do not polish or paraphrase it unless requested. Distinguish intended response text from background material; clarify consequential ambiguity in normal chat. When wording is absent, suggest a response grounded in established facts. Ask for missing essential facts rather than inventing them.

Under Outputs, show supplied or explicitly accepted wording with this label and quotation:

> **Response text**
>
> > {Response text}

Show newly generated wording that has not been accepted with this label and quotation:

> **Suggested response**
>
> > {Suggested response}

Bind each quotation to the actual local draft, identifying the relevant response ending when needed. For Update, distinguish current wording from the proposed wording and preserve accepted wording and links outside the authorized change. A change to wording requires a revised preview.

A draft is the `.mcs.yml` file saved locally in the selected agent's topic folder in the VS Code workspace, not just text in chat or an unsaved editor buffer. After writing the draft successfully, include this statement with the summary, before the decision control, when the proposed changes remain local:

> The proposed changes are saved locally in your VS Code workspace. They have not been pushed to the agent.

If the proposed content is already authoritatively saved, report that state instead. Preserve known remote outcomes and uncertainty rather than describing already-saved or unconfirmed content as local-only.

Keeping a draft locally does not accept a suggestion or authorize a remote save. Retain any explicit prior wording acceptance in session context without treating it as Push consent. If acceptance is unknown, show the wording for review before approval; do not infer acceptance from the file's presence or add persistent approval metadata.

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

### Create summary

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

### Update summary

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

### Topic save decision

Follow either summary with the [initial routing-conflict decision](#initial-routing-conflict-decision) when an instruction-routing conflict is known. Otherwise use the [suggested-response decision](#suggested-response-decision) for unaccepted suggested wording, or this separate short choice control for supplied or accepted wording:

> **Push topic to agent** / **Keep as draft**

Keep as draft leaves the draft saved locally in the VS Code workspace without a remote write. Do not offer a runnable remote test for a draft-only outcome.

### Suggested-response decision

After displaying the suggested wording and completed summary, use:

> **Use this suggested response and push {Topic title} to {Destination agent}?**
>
> **Push topic to agent** / **I want to update the response** / **Keep as draft**

Push topic to agent accepts the displayed suggested wording and approves the topic save together. Do not add a separate mandatory wording-approval step. Activation, testing and publication retain their separate permission requirements.

I want to update the response does not accept the suggestion or authorize a remote save. Continue in normal chat:

> What would you like to change? Describe the edits or paste the response you want.

Apply the requested revision to the local draft, preserving supplied replacement text. Obtain a fresh native preview and reassess any affected instruction alignment. Then show the revised summary and wording and return to the applicable decision control before any save. When the maker describes edits rather than supplies replacement text, label newly generated wording Suggested response until accepted.

Keep as draft retains the suggestion locally without accepting it. Use the truthful draft-only outcome, with a trailer that explicitly identifies the VS Code workspace. For an unaccepted suggestion, use:

> {Topic title} is saved locally in your VS Code workspace. The suggested response remains available for review or revision.

### Initial routing-conflict decision

When the initial Create or Update review identifies an instruction-routing conflict, offer resolution before any topic or instruction push. Follow the completed summary with:

> **How would you like to continue with {Topic title}?**
>
> **Resolve the routing conflict in the Agent Instructions** / **Push topic anyway** / **Keep as draft**

When suggested wording remains unaccepted, include **I want to update the response** before Keep as draft and use the response-revision continuation above. Explain before the control that Push topic anyway also accepts the displayed suggestion; resolving the instruction conflict alone does not accept it.

Resolve the routing conflict in the Agent Instructions prepares the targeted correction below while the proposed topic changes remain local. This choice does not approve a topic push, instruction push, activation or testing. Do not draft an instruction correction merely because a topic is being authored unless the correction is already within an explicitly authorized scope.

Review the topic draft and targeted instruction correction together before saving either. Use the existing component-level or scoped batch Push review and consent for exactly those displayed changes; exclude unrelated pending edits. Do not repeat owner approval for unchanged operations covered by that consent. Save and verify a new topic before an instruction correction that depends on its existence; pause dependent work if the prerequisite result is failed or uncertain.

Push topic anyway approves only the displayed topic save and leaves the conflicting instructions unchanged. It does not authorize activation, testing or publication. Carry the declined routing correction as an explicit exclusion into any later authorized testing. Do not immediately offer the same resolution decision again after saving.

Keep as draft performs no remote save. Retain the proposed changes locally and do not offer runnable testing of unsaved topic changes. Reuse an existing unchanged scoped approval rather than repeating this decision.

### Topic outcomes

The head catalog `{topic_outcome_heads}` covers at least these resulting outcomes:

- Confirmed remote push: **Topic pushed to agent.**
- Requested content verified already present without a new remote write: **Topic already up to date. No push needed.**
- Draft retained locally without a remote change: **Draft kept locally. Agent unchanged.**
- Blocked before saving, or confirmed rejection: **Topic was not pushed.**
- Remote outcome remains uncertain: **Topic push could not be confirmed.**
- Remote save confirmed, but a subsequent local write failed: **Topic pushed; workspace update incomplete.**

Select the head from the resulting known state after observation and appropriate session-led recovery. Add the flexible factual trailer. Preserve known remote success after a local failure; do not claim the agent is unchanged when its remote outcome is uncertain.

For a retained draft, explicitly state that it is saved locally in the VS Code workspace. Distinguish local persistence, wording acceptance and remote save status; do not describe an unaccepted suggestion as approved.

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

**When topic changes remain local:** review the topic and isolated instruction correction together using [Entry inventory and choices](push-experience.md#entry-inventory-and-choices). Render its applicable inventory entries and reuse its full four-item choice block verbatim: **Summarize each change**, **Push all listed changes**, **Choose what to push**, and **Cancel**. Include exactly those displayed changes, excluding unrelated pending edits.

**Only when the proposed topic content is already authoritatively saved:** use this two-item control for the instruction correction:

> **Push this instruction change to {agent_name}?**
>
> **Push instruction change** / **Keep as draft**

Reuse valid scoped consent for unchanged operations. During composed Push, reuse its component-level decision rather than adding another approval control.

Push instruction change authorizes only the displayed correction for the identified agent. It does not authorize activation, testing or publication.

#### Apply an approved change

- Follow [Push telemetry](push-experience.md#push-telemetry). Reuse an enclosing approved batch's lifecycle; otherwise own the standalone instruction-save batch.
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

Omit the resolved Routing Conflicts advisory. For authoritatively saved topic content, reuse [Testing offers](testing-experience.md#testing-offers). Render the applicable quoted control verbatim and follow its consent, continuation and deferral rules. Use [Scoped runtime correctness goal](testing-experience.md#scoped-runtime-correctness-goal) for the authorized testing, fixes and retesting. Reuse existing authorization rather than presenting another offer. Instruction-push approval does not supply topic-push, testing or activation consent.

For a failed or uncertain instruction push, or a remaining conflict after readback, preserve the actual result and uncertainty. Recover within the approved scope without blindly repeating an uncertain write. Do not claim resolution or enter the resolved-conflict testing path. If the maker explicitly requests testing despite the remaining conflict, require authoritatively saved topic content, obtain only missing testing or activation permission and carry the declined correction as an explicit exclusion. Do not automatically repeat resolution for the same conflict. No publication is authorized.
