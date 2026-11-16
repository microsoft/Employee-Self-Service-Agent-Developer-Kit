# Topic authoring experience

<!-- markdownlint-disable MD001 -->

Apply the [shared foundation](experience-contract.md). Use this reference for Create/Update review and outcomes. Load [Push experience](push-experience.md) for a composed review or result, and [Testing experience](testing-experience.md) only when reaching the testing continuation.

## Contents

- [Authoring status updates](#authoring-status-updates)
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

## Authoring status updates

For Create, Update and related instruction corrections, apply [Status update markers](experience-contract.md#status-update-markers) using the definitions below. Resolve `{Topic title}` and `{Agent name}` from the selected target. Load these definitions before preparation or an approved save; a delegated caller reuses the performing owner's update.

| Reporting point           | Completion condition                                                                                                                          | Completion message                                                  |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `draft-preparation`       | The requested local draft is saved or verified unchanged with the requested behavior and wording.                                             | ✅ Prepared the draft for **{Topic title}**.                        |
| `instruction-preparation` | The requested isolated correction is saved locally, unrelated content is preserved, and its non-writing preview is ready for review.          | ✅ Prepared the instruction change for **{Agent name}**.            |
| `topic-save`              | The approved topic save and authoritative readback both succeed, a new remote write is confirmed, and required local recording is complete.   | ✅ Pushed and verified **{Topic title}**.                           |
| `instruction-save`        | The approved instruction write and authoritative readback succeed, a new remote write is confirmed, and required local recording is complete. | ✅ Pushed and verified the instruction change for **{Agent name}**. |

For `draft-preparation`, describe a failed or incomplete local draft using the observed evidence and applicable next safe action. Draft readiness does not establish wording acceptance, instruction alignment, save readiness, a remote save or resolution of a routing conflict.

For `topic-save`, use [Topic outcomes](#topic-outcomes) to interpret an already-current no-write result, a rejected or unconfirmed save, or confirmed remote success with an incomplete workspace update. Compose the short status update from those known facts rather than using the completion message. A retained draft does not enter this reporting point.

For `instruction-preparation`, report missing evidence, an incomplete correction or an already-present correction without claiming a new draft is ready. Preparation does not authorize either save. For `instruction-save`, use [Instruction-push outcomes and testing](#instruction-push-outcomes-and-testing) to distinguish new writes, already-current content, rejection, uncertainty and local issues. Instruction readback does not establish topic execution or a topic save.

Keep the full Create or Update review and existing outcome report after the applicable update. Do not announce work that is starting or still running. Preserve existing approval, uncertainty and recovery boundaries. Revisions return to the affected preparation point and fresh review; earlier confirmed saves remain completed work. Do not prepopulate activation, testing or publication. If the maker selects testing, continue with [Testing status updates](testing-experience.md#testing-status-updates).

## Authoring summaries

Resolve `{Topic title}` and `{Destination agent}` from the selected topic and target. Describe Behavior, accepted parameters/collected information under Inputs, returned values and employee-visible behavior under Outputs, and triggering scope under Starts when. `{Draft link}` is the actual local draft. An advisory alone does not add an acknowledgement gate.

Apply [Advisory entries in Notes](#advisory-entries-in-notes) and [Routing Conflicts](#routing-conflicts) when those sections are relevant to either summary.

### Response wording and local drafts

Preserve wording supplied as the intended response, including links. Do not polish or paraphrase it unless requested. Distinguish intended response text from background material; clarify consequential ambiguity in normal chat. When wording is absent, suggest a response grounded in established facts. Ask for missing essential facts rather than inventing them.

Under Outputs, show supplied or explicitly accepted wording with this label and quotation:

> - {Output description}
>
>   ###### RESPONSE TEXT
>
>   > {Response text}

Show newly generated wording that has not been accepted with this label and quotation:

> - {Output description}
>
>   ###### SUGGESTED RESPONSE
>
>   > {Suggested response}

Bind each quotation to the actual local draft, identifying the relevant response ending when needed. For Update, distinguish current wording from the proposed wording and preserve accepted wording and links outside the authorized change. A change to wording requires a revised preview.

A draft is the `.mcs.yml` file saved locally in the selected agent's topic folder in the VS Code workspace, not just text in chat or an unsaved editor buffer. After writing the draft successfully, include this statement with the summary, before the decision control, when the proposed changes remain local:

> The proposed changes are saved locally in your VS Code workspace. They have not been pushed to the agent.

If the proposed content is already authoritatively saved, report that state instead. Preserve known remote outcomes and uncertainty rather than describing already-saved or unconfirmed content as local-only.

Keeping a draft locally does not accept a suggestion or authorize a remote save. Retain any explicit prior wording acceptance in session context without treating it as Push consent. If acceptance is unknown, show the wording for review before approval; do not infer acceptance from the file's presence or add persistent approval metadata.

### Advisory entries in Notes

Present non-routing advisories within Notes using the following structure. Repeat the advisory bullet as needed. Ordinary factual notes retain their existing form.

> ##### NOTES
>
> - {Advisory issue}. {Practical effect}.
>
> ##### SUGGESTED ACTION
>
> {Concrete next action}.

`{Concrete next action}` is a specific, relevant recommended step to investigate or address the issue, identifying what to inspect, test or change and its purpose. `{Note}` in the summaries below represents an ordinary factual note. Include factual notes and advisory entries only when applicable.

### Routing Conflicts

Put instruction-routing conflicts in Routing Conflicts, separate from topic state and pending testing, rather than in Notes. Do not duplicate the conflict in both sections. Omit empty sections; ordinary factual notes and unrelated advisories retain their existing form.

> ##### ROUTING CONFLICTS
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
>
>   ###### SUGGESTED ACTIONS
>   - {Concrete next action}.

List all applicable conflicts first, then include this single grouped action block. Repeat action bullets as needed, identifying which conflicts they address.

`{Routing conflict}` identifies the observed instruction constraint and affected topic behavior. The execution-impact statement describes a likely consequence, not a confirmed conversation-test failure. Recommend a targeted instruction correction before testing.

### Create summary

For Create, state that creation is inactive and unpublished; activation is a separate choice in the testing follow-up. Apply the shared heading treatment, including Suggested action labels in Notes outside list indentation. Preserve the response quotation and all applicable omission rules. Do not turn field content, outcome sentences or picker options into uppercase headings.

Under Outputs, render child labels, including Response text and Suggested response, as indented level-six headings in ALL CAPS within the corresponding output bullet. Nest the response quotation at the same content indentation. Use RESPONSE TEXT for supplied or explicitly accepted wording, as shown below; use SUGGESTED RESPONSE for newly generated wording that has not been accepted. Omit the response heading and quotation for outputs without literal response wording. Apply the same treatment in Update and component reviews.

List all applicable routing conflicts first, repeating the conflict bullet as needed. Follow the complete conflict list with exactly one indented level-six SUGGESTED ACTIONS block, even when there is only one action. Nest the heading and action bullets as shown below. Repeat the action bullet as needed, making clear which conflicts each action addresses. Do not repeat this block for each conflict.

Render:

> ##### TITLE
>
> {Topic title}
>
> ##### AGENT
>
> {Destination agent}
>
> ##### BEHAVIOR
>
> {Concise behavior description}
>
> ##### INPUTS
>
> - {Input}: {Input description}
>
> ##### OUTPUTS
>
> - {Output description}
>
>   ###### RESPONSE TEXT
>
>   > {Response text}
>
> ##### STARTS WHEN
>
> {Triggering scope}
>
> ##### NOTES
>
> - {Note}
> - {Advisory issue}. {Practical effect}.
>
> ##### SUGGESTED ACTION
>
> {Concrete next action}.
>
> ##### ROUTING CONFLICTS
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
>
>   ###### SUGGESTED ACTIONS
>   - {Concrete next action}.
>
> [Full draft]({Draft link})

### Update summary

For Update, include only affected fields, concise before/after details where useful, and important verified preservation points. Preserve the existing active state. Within an affected response output, show CURRENT RESPONSE and PROPOSED RESPONSE as indented H6 labels; use SUGGESTED RESPONSE for unaccepted generated wording. Quote the actual respective wording at that same indentation. Omit the literal-response children when inapplicable. Render:

> ##### TITLE
>
> {Topic title}
>
> ##### AGENT
>
> {Destination agent}
>
> ##### BEHAVIOR
>
> {Behavior change}
>
> ##### INPUTS
>
> {Input changes}
>
> ##### OUTPUTS
>
> - {Output changes}
>
>   ###### CURRENT RESPONSE
>
>   > {Current response}
>
>   ###### PROPOSED RESPONSE
>
>   > {Proposed response}
>
> ##### STARTS WHEN
>
> {Trigger changes}
>
> ##### UNCHANGED
>
> - {Preserved behavior}
>
> ##### NOTES
>
> - {Note}
> - {Advisory issue}. {Practical effect}.
>
> ##### SUGGESTED ACTION
>
> {Concrete next action}.
>
> ##### ROUTING CONFLICTS
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
>
>   ###### SUGGESTED ACTIONS
>   - {Concrete next action}.
>
> [Full draft]({Draft link})

### Topic save decision

Follow either summary with the [initial routing-conflict decision](#initial-routing-conflict-decision) when an instruction-routing conflict is known. Otherwise use the [suggested-response decision](#suggested-response-decision) for unaccepted suggested wording, or this separate short choice control for supplied or accepted wording:

For Create or Update without a routing conflict, explain the choices in normal chat immediately before that control:

> ##### YOUR CHOICES
>
> | Choice              | What happens                                                         |
> | ------------------- | -------------------------------------------------------------------- |
> | Push topic to agent | Save and verify the topic in Dev. Leave it inactive and unpublished. |
> | Keep as draft       | Keep the local draft without changing the agent.                     |

For Update, replace the Push explanation with `Save and verify the displayed topic changes in Dev. Preserve its active state; do not publish.` When suggested wording is unaccepted, the Push explanation also states that it accepts the displayed response. Add the applicable I want to update the response row, explaining that it revises the draft without pushing it. Retain the existing short picker labels; do not put these explanations in option labels or replace the separate decision control with the table.

For a conflicting-save re-review, use the same control after the complete Update summary. The Push explanation names the conflicting content that the reviewed proposal would replace and the unrelated content preserved. Keep as draft retains the proposal locally without replacing the saved content. Retain the owner's concurrency checks; a revised approval does not bypass them.

For every Create or Update topic-save decision, call `ask_user` with this JSON shape. Keep the top message empty, use the contextual panel title and fixed inner question below, and allow custom text. The shown `enum` applies to supplied or accepted wording without a routing conflict. For the suggested-response or initial routing-conflict branch, replace only `enum` with that branch's applicable choices, including any conditional response-revision choice. The JSON defines the control; do not print it in chat. Submit, keyboard hints and close/collapse controls belong to the host.

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Topic save",
        "description": "How would you like to continue?",
        "enum": ["Push topic to agent", "Keep as draft"]
      }
    }
  }
}
```

Keep as draft leaves the draft saved locally in the VS Code workspace without a remote write. Do not offer a runnable remote test for a draft-only outcome.

### Suggested-response decision

After displaying the suggested wording and completed summary, present the applicable control.

For Create and Update, use the [Topic save control](#topic-save-decision) with **Push topic to agent**, **I want to update the response** and **Keep as draft**, in that order, and its corresponding explanation rows.

Push topic to agent accepts the displayed suggested wording and approves the topic save together. Do not add a separate mandatory wording-approval step. Activation, testing and publication retain their separate permission requirements.

I want to update the response does not accept the suggestion or authorize a remote save. Continue in normal chat:

> What would you like to change? Describe the edits or paste the response you want.

Apply the requested revision to the local draft, preserving supplied replacement text. Obtain a fresh save preview and reassess any affected instruction alignment. Then show the revised summary and wording and return to the applicable decision control before any save. When the maker describes edits rather than supplies replacement text, label newly generated wording Suggested response until accepted.

Keep as draft retains the suggestion locally without accepting it. Use the draft-only result in [Topic outcomes](#topic-outcomes), including its fixed unaccepted-suggestion trailer.

### Initial routing-conflict decision

When the initial Create or Update review identifies an instruction-routing conflict, offer resolution before any topic or instruction push. Follow the completed summary with the applicable control.

For Create and Update, use the [Topic save control](#topic-save-decision) with **Resolve the routing conflict in the Agent Instructions**, **Push topic anyway** and **Keep as draft**, in that order. Explain these choices immediately before that control:

> ##### YOUR CHOICES
>
> | Choice                                                 | What happens                                                                         |
> | ------------------------------------------------------ | ------------------------------------------------------------------------------------ |
> | Resolve the routing conflict in the Agent Instructions | Prepare a targeted instruction correction for review. Push neither change yet.       |
> | Push topic anyway                                      | Save only the displayed topic changes. Leave the conflicting instructions unchanged. |
> | Keep as draft                                          | Keep the local topic draft without a remote save.                                    |

When suggested wording remains unaccepted, include **I want to update the response** before Keep as draft and use the response-revision continuation above. Explain before the control that Push topic anyway also accepts the displayed suggestion; resolving the instruction conflict alone does not accept it.

Resolve the routing conflict in the Agent Instructions prepares the targeted correction below while the proposed topic changes remain local. This choice does not approve a topic push, instruction push, activation or testing. Do not draft an instruction correction merely because a topic is being authored unless the correction is already within an explicitly authorized scope.

Review the topic draft and targeted instruction correction together before saving either. Use the existing component-level or scoped batch Push review and consent for exactly those displayed applicable changes. Exclude unrelated pending edits from save scope, but retain them in the inventory as named Not included entries with individual reasons. Do not repeat owner approval for unchanged operations covered by that consent. Save and verify a new topic before an instruction correction that depends on its existence; pause dependent work if the prerequisite result is failed or uncertain.

Push topic anyway approves only the displayed topic save and leaves the conflicting instructions unchanged. It does not authorize activation, testing or publication. Carry the declined routing correction as an explicit exclusion into any later authorized testing. Do not immediately offer the same resolution decision again after saving.

Keep as draft performs no remote save. Retain the proposed changes locally and do not offer runnable testing of unsaved topic changes. Reuse an existing unchanged scoped approval rather than repeating this decision.

### Topic outcomes

The head catalog `{topic_outcome_heads}` covers at least these resulting outcomes:

- Confirmed remote push: **TOPIC PUSHED TO AGENT**
- Requested content verified already present without a new remote write: **TOPIC ALREADY UP TO DATE NO PUSH NEEDED**
- Draft retained locally without a remote change: **DRAFT KEPT LOCALLY AGENT UNCHANGED**
- Blocked before saving, or confirmed rejection: **TOPIC WAS NOT PUSHED**
- Remote outcome remains uncertain: **TOPIC PUSH COULD NOT BE CONFIRMED**
- Remote save confirmed, but a subsequent local write failed: **TOPIC PUSHED WORKSPACE UPDATE INCOMPLETE**

Select the head from the resulting known state after observation and appropriate session-led recovery. Add the flexible factual trailer. Preserve known remote success after a local failure; do not claim the agent is unchanged when its remote outcome is uncertain.

For a retained draft, explicitly state that it is saved locally in the VS Code workspace. Distinguish local persistence, wording acceptance and remote save status; do not describe an unaccepted suggestion as approved.

When authoritative verification succeeds with `writeAttempted: false` and `updatedComponents: 0`, use the already-up-to-date head, not a pushed head. Do not attribute the existing change to this operation. If local tracking fails afterward, retain the no-write head and disclose that local issue in the factual trailer. A zero update count alone does not establish verification.

The flexible trailer carries relevant identity, observed state, draft link, cause, pending work or next safe action. Render:

> ##### {Outcome head}
>
> {Contextual trailer}

For a retained draft with unaccepted suggested wording, `{Contextual trailer}` begins with the following fixed block. Resolve `{Topic title}` from the selected draft; put additional factual context after a blank line.

> {Topic title} is saved locally in your VS Code workspace. The suggested response remains available for review or revision.

During composed Push, contribute these known facts to the single composed report instead of stacking owner reports.

Use the draft-only Agent unchanged head only when none of this operation's components were remotely changed. For partial saves, use the composed report with actual per-component outcomes rather than a global unchanged claim.

### Combined routing-conflict and testing follow-up

Use this combined decision only when a routing conflict is newly discovered or materially changed after Push. If the maker already chose Push topic anyway, or deliberately omitted the reviewed correction, honor that decision: retain the unresolved-conflict reminder and offer ordinary state-aware testing once, with the correction excluded. Do not repeat the resolution choice for the same conflict.

For a newly discovered or materially changed conflict after a confirmed topic push, present the saved result, verified topic state and pending testing separately from Routing Conflicts:

> ##### TOPIC PUSHED TO AGENT
>
> Saved **{Topic title}** to **{Destination agent}**.
>
> {Verified topic state}. Conversation testing is pending.
>
> ##### ROUTING CONFLICTS
>
> - {Routing conflict}. This routing conflict will likely block topic execution.
>
>   ###### SUGGESTED ACTIONS
>   - {Concrete next action}.

For a verified no-write result or a confirmed save with a local issue, retain the corresponding truthful `{topic_outcome_heads}` head and factual trailer rather than claiming a new push. `{Verified topic state}` comes from observed remote state, not the save itself.

Follow with one combined decision, not a routing-resolution offer followed by another testing offer. Check the installed testing capability before offering a runnable test; report an actual capability gap rather than advertising unavailable testing. Without a routing conflict, use the ordinary state-aware testing offer.

For an inactive topic, explain the following choices and use the JSON below:

> ##### YOUR CHOICES
>
> | Choice                                                 | What happens                                                                                                |
> | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
> | Resolve the routing conflict in the Agent Instructions | Prepare a targeted correction for review. Do not push it, activate or test yet.                             |
> | Not now, Activate and test anyway.                     | Leave the conflict unchanged; activate and test this saved topic within the existing scope. Do not publish. |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Routing conflict and testing",
        "description": "How would you like to continue?",
        "enum": [
          "Resolve the routing conflict in the Agent Instructions",
          "Not now, Activate and test anyway."
        ]
      }
    }
  }
}
```

For an active topic, replace the second `enum` entry and its explanation row with **Not now, Test anyway.** Explain that it leaves the conflict unchanged and tests the saved topic within the existing scope, without activation or publication. Keep the other control metadata unchanged.

Resolve the routing conflict in the Agent Instructions prepares the targeted preview below. This choice does not approve an instruction push, activation or testing.

Not now, Activate and test anyway. leaves the conflicting instructions unchanged and authorizes activation and testing of the selected inactive topic. Confirm authoritative Active state before sending a test message. Not now, Test anyway. continues directly into testing of the selected active topic without activation. Neither selection introduces another testing offer.

Carry forward the testing objective and authorized editable scope. These choices do not create blanket debugging consent. Carry the declined routing correction as an explicit exclusion into the testing owner; do not silently repair it during testing. Preserve browser-readiness checks, test-only/no-activation limits and pause/stop handling. None of these choices authorizes publication.

Resolve unverified topic state or report its blocker rather than guessing which choice applies. Preserve the existing scoped batch/debugging consent rules and do not repeat a decision already established by explicit authorization. Do not make instruction correction a prerequisite for a deliberate topic-only save.

### Targeted instruction-change preview and approval

For deletion-related routing corrections, reuse this preview and the instruction-only save control with the state, consent and outcome bindings in [Deletion-related instruction correction](deletion-experience.md#deletion-related-instruction-correction). That path does not use Create/Update's topic-save sequencing or testing continuation.

#### Prepare the correction

Carry forward the selected agent, topic, identified conflict and actual topic-save state. Use current saved instruction evidence to prepare the smallest targeted correction through the normal instruction owner.

Preserve unrelated live instructions and pending local edits. Isolate the correction without losing other drafts or including them in the proposed push.

If current instructions cannot be established or the correction cannot be isolated, explain the missing evidence or scope issue and offer the next safe action. Do not present a runnable Push choice.

If the desired correction is already authoritatively present, report **AGENT INSTRUCTIONS ALREADY UP TO DATE** using the existing no-write outcome. Preserve the actual topic-save state; do not offer an unnecessary instruction push.

#### Show the preview

Use actual instruction text. Show the affected current wording, exact proposed wording, intended routing effect and verified preservation facts. Label lengthy excerpts and provide access to the full draft. Do not claim preservation that has not been checked.

> **Instruction change ready for review.**
>
> ##### AGENT
>
> {agent_name}
>
> ##### RELATED TOPIC
>
> {topic_title}
>
> ##### ROUTING CONFLICT
>
> {routing_conflict}
>
> ##### PROPOSED CHANGE
>
> {proposed_change}
>
> ##### CURRENT WORDING
>
> > {current_affected_wording}
>
> ##### PROPOSED WORDING
>
> > {proposed_affected_wording}
>
> ##### UNCHANGED
>
> {verified_preservation_facts}
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

**When topic changes remain local:** review the topic and isolated instruction correction together using [Entry inventory and choices](push-experience.md#entry-inventory-and-choices). Render its applicable inventory entries and named Not included entries, then reuse its full four-item choice block verbatim: **Summarize each change**, **Push all listed changes**, **Choose what to push**, and **Cancel**. Approval includes exactly the displayed applicable changes; unrelated pending edits remain excluded, not omitted.

**Only when the proposed topic content is already authoritatively saved:** use this two-item control for the instruction correction:

> ##### YOUR CHOICES
>
> | Choice                  | What happens                                                                                   |
> | ----------------------- | ---------------------------------------------------------------------------------------------- |
> | Push instruction change | Save and verify only this correction for the selected agent. Do not activate, test or publish. |
> | Keep as draft           | Retain the instruction correction locally without pushing it.                                  |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Instruction save",
        "description": "How would you like to continue?",
        "enum": ["Push instruction change", "Keep as draft"]
      }
    }
  }
}
```

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

> ##### INSTRUCTION DRAFT KEPT LOCALLY
>
> No instruction change was pushed. {topic_save_state} The routing conflict remains unresolved.

If both changes remain local, explicitly report that neither was pushed. Preserve any earlier confirmed remote changes; do not describe the entire agent as unchanged after a confirmed write.

Do not offer runnable testing of unsaved topic changes. For already-saved topic content, honor the declined correction and obtain only any missing activation or testing permission.

### Instruction-push outcomes and testing

Report the actual instruction-save result and reassess the identified conflict using the saved wording. Report the actual topic-save state; preserve any earlier confirmed topic push as completed work, but do not assume one occurred. Do not repeat an unchanged valid Push approval or imply that an instruction update saves or activates the topic.

For composed Push, including a topic and routing correction approved together, use `{composed_push_report}` instead of separate topic and instruction outcome blocks. Put the complete `{Verified instruction-save result}` statement below in the instruction row's Details, with each component's actual status. Put the conflict assessment and verified testing readiness in the contextual trailer, then use the applicable testing offer once. Preserve failed, uncertain and partial results; a saved instruction does not establish a saved topic.

Outside composed Push, use the head matching the resulting known facts:

- Confirmed instruction write and authoritative readback: **INSTRUCTIONS PUSHED TO AGENT**
- Desired correction authoritatively verified without a write: **AGENT INSTRUCTIONS ALREADY UP TO DATE**
- Confirmed non-save: **INSTRUCTIONS WERE NOT PUSHED**
- Remote outcome remains uncertain: **INSTRUCTION PUSH COULD NOT BE CONFIRMED**
- Remote save confirmed but subsequent local recording remains incomplete: **INSTRUCTIONS PUSHED WORKSPACE UPDATE INCOMPLETE**

Outside composed Push, when the saved wording addresses the identified conflict, render:

> ##### {Instruction outcome head}
>
> {Verified instruction-save result}
>
> The saved wording addresses the identified routing conflict. Topic execution has not yet been verified.
>
> {topic_save_state}
>
> {Testing readiness}

`{Verified instruction-save result}` uses the applicable complete statement below, including the named correction, agent and related topic even when those identities also appear elsewhere. Preserve the standalone block's paragraph breaks. In a composed report, use the statement in Details without adding an instruction outcome head.

**Saved in this operation:** outside composed Push, use the **INSTRUCTIONS PUSHED TO AGENT** head.

> {Instruction correction} was saved in **{Agent name}** for **{Topic title}** and confirmed by instruction readback.

**Already present; no write:** outside composed Push, use the **AGENT INSTRUCTIONS ALREADY UP TO DATE** head.

> Instruction readback confirmed that {Instruction correction} was already present in **{Agent name}** for **{Topic title}**. No instruction write was needed.

For a confirmed save followed by a local recording issue, retain the confirmed-save statement and describe the unfinished local work. Use **Pushed with local issue** in a composed report or the **INSTRUCTIONS PUSHED WORKSPACE UPDATE INCOMPLETE** standalone head. Failed or uncertain instruction saves use their corresponding status or standalone head and do not use either confirmed-state statement.

`{Testing readiness}` gives the verified active or inactive state and pending testing only when the proposed topic content is authoritatively saved or verified already current. Otherwise state that topic Push is still pending and do not offer runnable conversation testing. For partial saves, report each component's actual result rather than claiming the whole agent is unchanged.

Omit the resolved Routing Conflicts advisory. For authoritatively saved topic content, reuse [Testing offers](testing-experience.md#testing-offers). Render the applicable choice explanations and native control, following their consent, continuation and deferral rules. Use [Scoped runtime correctness goal](testing-experience.md#scoped-runtime-correctness-goal) for the authorized testing, fixes and retesting. Reuse existing authorization rather than presenting another offer. Instruction-push approval does not supply topic-push, testing or activation consent.

For a failed or uncertain instruction push, or a remaining conflict after readback, preserve the actual result and uncertainty. Recover within the approved scope without blindly repeating an uncertain write. Do not claim resolution or enter the resolved-conflict testing path. If the maker explicitly requests testing despite the remaining conflict, require authoritatively saved topic content, obtain only missing testing or activation permission and carry the declined correction as an explicit exclusion. Do not automatically repeat resolution for the same conflict. No publication is authorized.
