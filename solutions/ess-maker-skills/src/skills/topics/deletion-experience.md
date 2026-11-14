# Topic deletion experience

<!-- markdownlint-disable MD001 -->

Apply the [shared foundation](experience-contract.md). Use this reference before reviewing deletion, staging it locally or discarding a draft. The [delete owner](delete/SKILL.md) owns execution; a remote deletion also uses [Push telemetry](push-experience.md#push-telemetry).

## Contents

- [Deletion status updates](#deletion-status-updates)
- [Topic deletion](#topic-deletion)
- [Deletion summary: `{delete_summary}`](#deletion-summary-delete_summary)
- [Deletion decision](#deletion-decision)
- [Routing-conflict decision](#routing-conflict-decision)
- [Deletion-related instruction correction](#deletion-related-instruction-correction)
- [Routing cleanup after deletion](#routing-cleanup-after-deletion)
- [Local-only variations](#local-only-variations)
- [Deletion outcomes: `{delete_outcome_heads}`](#deletion-outcomes-delete_outcome_heads)

## Deletion status updates

Apply [Status update markers](experience-contract.md#status-update-markers) before the delete owner's work. Bind `{Topic title}` to the exact selected topic. The delete owner emits these updates even when called by Push or cleanup; the caller does not repeat them.

| Reporting point       | Completion condition                                                                                                                                 | Completion message                                          |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `deletion-review`     | The exact target, removal scope, protection checks and required impact evidence are established for the applicable deletion or draft-discard review. | ✅ Checked the removal scope for **{Topic title}**.         |
| `deletion-checkpoint` | The checkpoint operation confirms a saved snapshot of the reviewed working files before any removal.                                                 | ✅ Saved a checkpoint before removing **{Topic title}**.    |
| `local-removal`       | Only the approved working files were newly removed, required baseline/mapping records are preserved, and no remote write occurred.                   | ✅ Removed **{Topic title}** from your local working files. |
| `topic-deletion`      | A new approved remote deletion returned HTTP success and required local reconciliation completed.                                                    | ✅ Deleted **{Topic title}** from the agent.                |

Use [Deletion outcomes](#deletion-outcomes-delete_outcome_heads) and [Local-only variations](#local-only-variations) for incomplete, rejected, already-absent, partial or uncertain results. A failed checkpoint leaves removal unstarted. Unverified impact remains unverified even when a review can proceed with that disclosure. Local removal does not establish remote deletion; remote absence without a new write does not qualify for the new-deletion completion message. Report partial local removal accurately.

## Topic deletion

The delete owner uses this section for direct requests, cleanup and selected Push deletions. Resolve the exact topic and selected editable Dev agent, then apply **Authoring policy for this release** to the topic and any contained topics. Selection is not deletion approval. Deletion does not author replacement behavior or authorize changes to referencing topics, instructions, evaluations or external resources.

For composed Push, combine overlapping parent and contained deletions into one reviewed operation. Show every affected topic, but do not dispatch a contained deletion again after its parent. Resolve conflicting updates or exclusions within that deletion scope before requesting approval.

Use **Push** for applying the deletion to the agent. Reserve **Publish** for the separate Copilot Studio operation. Do not describe a pushed deletion as merely local or as published.

### Deletion summary: `{delete_summary}`

Bind the topic, agent and behavior to current evidence. Also removed lists contained content and affected local files beyond the selected topic. References needing attention identifies other topic references, evaluation dependencies and their practical consequences. Put known instruction-routing references in Routing Conflicts instead, without duplicating them in References needing attention. Inspect relevant current topics and agent instructions; local files alone do not prove there are no remote references. Omit genuinely empty sections and identify unresolved impact explicitly.

Use the Create/Update heading treatment and one grouped SUGGESTED ACTIONS block after all routing conflicts. `{Deletion routing impact}` describes the dangling routing that deletion would leave, not a claim that the deleted topic should execute. Suggest the smallest instruction correction for review; do not promise to change instructions before that correction is selected and approved.

> ##### DELETE TOPIC
>
> ##### TOPIC
>
> {Topic title}
>
> ##### AGENT
>
> {Destination agent}
>
> ##### BEHAVIOR BEING REMOVED
>
> {Concise behavior description}
>
> ##### ALSO REMOVED
>
> - {Contained content or additional local file}
>
> ##### REFERENCES NEEDING ATTENTION
>
> - {Other reference and practical effect}
>
> ##### ROUTING CONFLICTS
>
> - {Routing conflict}. {Deletion routing impact}.
>
>   ###### SUGGESTED ACTIONS
>   - {Concrete next action}.
>
> Pushing this deletion removes the topic from the agent and your local workspace.

### Deletion decision

When a known instruction-routing conflict applies, use the [routing-conflict decision](#routing-conflict-decision) instead of the default choices below. Without a known conflict, show the completed deletion summary and these explanations before the separate native control. Unavailable instruction evidence is unverified alignment, not an established conflict or proof that no references exist.

Local staging alone leaves the upstream topic available. When the request is explicitly local-only, follow that variation without adding a remote routing-cleanup decision unless instruction work was independently requested.

> ##### YOUR CHOICES
>
> | Choice                 | What happens                                                                                           |
> | ---------------------- | ------------------------------------------------------------------------------------------------------ |
> | Push deletion to agent | Delete the displayed topic and contained content from the agent, then update the approved local files. |
> | Keep deletion locally  | Remove only the displayed working files. Keep the saved topic and tracking for a later reviewed Push.  |
> | Not now                | Leave the current local and remote state unchanged.                                                    |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Topic deletion",
        "description": "How would you like to continue?",
        "enum": ["Push deletion to agent", "Keep deletion locally", "Not now"]
      }
    }
  }
}
```

Push deletion to agent authorizes only the displayed deletion and local reconciliation. Reuse unchanged scoped Push consent only when it explicitly includes this destructive operation and its consequences. Refresh the review and obtain new approval when identity, contained content or material effects change.

Keep deletion locally authorizes removing the displayed working files only. Retain their baseline and component mapping so a later Push can discover the pending deletion. The agent remains unchanged, and this choice does not approve a later remote deletion. Not now leaves the current state unchanged; do not restore an already-missing file automatically.

### Routing-conflict decision

For deletion with a known instruction-routing conflict, use the same resolution label and first-choice positioning as Create/Update. Show the completed deletion summary, including Routing Conflicts, then these explanations and the native control:

> ##### YOUR CHOICES
>
> | Choice                                                 | What happens                                                                                                                               |
> | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
> | Resolve the routing conflict in the Agent Instructions | Prepare a targeted instruction correction for review. Push neither change yet.                                                             |
> | Push deletion anyway                                   | Delete only the displayed topic and contained content, then update the approved local files. Leave the conflicting instructions unchanged. |
> | Keep deletion locally                                  | Remove only the displayed working files. Leave the saved topic and instructions unchanged.                                                 |
> | Not now                                                | Leave the current local and remote state unchanged.                                                                                        |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Topic deletion",
        "description": "How would you like to continue?",
        "enum": [
          "Resolve the routing conflict in the Agent Instructions",
          "Push deletion anyway",
          "Keep deletion locally",
          "Not now"
        ]
      }
    }
  }
}
```

Resolve the routing conflict in the Agent Instructions authorizes preparing the [targeted correction](#deletion-related-instruction-correction), not deleting local files, deleting the saved topic or pushing instructions. Do not prepare it merely because deletion was requested unless the correction is already explicitly authorized.

Push deletion anyway approves only the displayed deletion and its local reconciliation. Keep the declined instruction correction as an explicit exclusion. Do not immediately offer the same resolution decision again after deletion or silently include it in a later Push.

Keep deletion locally retains live routing to the still-saved topic. Any already-prepared instruction correction stays local and unpushed. Not now performs no remaining changes; preserve earlier completed changes and do not imply that they were undone. Neither choice authorizes an instruction save.

An unchanged approved Push batch can supply consent for the exact displayed deletion and instruction correction. Reuse it rather than repeating this control. A newly discovered or materially changed routing consequence requires a revised review; a deliberately excluded unchanged correction does not.

### Deletion-related instruction correction

Use [Targeted instruction-change preview and approval](authoring-experience.md#targeted-instruction-change-preview-and-approval) for current instruction evidence, isolation, exact current/proposed wording and preservation facts. Apply these deletion-specific state and consent bindings instead of its topic-save and testing continuations.

Remove only routing made obsolete by the reviewed deletion. Preserve other topics in shared routing rules, unrelated instructions and pending local edits. When removing an entire instruction excerpt, explicitly show that it will be removed; do not invent replacement routing. Clarify intended replacement behavior if removal alone cannot establish the requested result. Other topic references, evaluations and external resources retain their own scope and approval.

If current instructions are unavailable or the correction cannot be isolated, explain the missing evidence and leave it unpushed. Do not present a runnable instruction Push choice. Return to the deletion decision only when the maker wants to continue with deletion alone and its prerequisites hold. If the desired correction is already authoritatively present, use the existing instruction no-write outcome and continue from the actual deletion state.

Bind the shared preview's `{topic_save_state}` to the actual deletion state:

| State                     | What to communicate                                                                       |
| ------------------------- | ----------------------------------------------------------------------------------------- |
| Deletion proposed         | The topic remains in the agent; no deletion has been pushed.                              |
| Deletion kept locally     | Approved working files were removed; the saved topic remains in the agent.                |
| Deleted                   | The remote deletion returned HTTP success; report the actual local reconciliation result. |
| Already absent            | Current inspection established absence; no new remote deletion was needed.                |
| Kept pending or cancelled | Unattempted changes remain pending; preserve any earlier confirmed effects.               |
| Failed                    | State whether deletion was unattempted or authoritatively rejected, with its cause.       |
| Unconfirmed               | The remote deletion outcome cannot be established.                                        |
| Deleted with local issue  | Remote deletion succeeded, but workspace reconciliation remains incomplete.               |

The correction preview does not authorize topic deletion. Preparation leaves topic files in their current state, including any previously staged removal.

While deletion remains pending, review the deletion and isolated instruction correction together through [Entry inventory and choices](push-experience.md#entry-inventory-and-choices). Include the reviewed deletion as a proposed change without removing working files merely to populate the inventory. Reuse **Summarize each change**, **Push all listed changes**, **Choose what to push**, and **Cancel**. Exclude unrelated pending edits. If only one change is selected, disclose the consequence of leaving the other pending before approval; selection of a type or resolution option alone is not write consent.

When deletion already succeeded or absence is established, use the shared **Push instruction change** / **Keep as draft** control for instruction-only cleanup. Keep as draft retains only the proposed correction; it does not restore or stage a topic deletion.

For joint execution, establish the order from the reviewed routing effect and disclose material intermediate consequences before approval. Do not copy Create's new-topic-before-routing rule into deletion. If removing routing first would change access to a still-existing topic, disclose that; if deleting first would temporarily leave a dangling reference, disclose that. Pause dependent work after a failed or uncertain prerequisite. If only one change completes, preserve it and report the other accurately; do not replay, roll back or recreate the topic automatically.

Use the shared instruction preparation/save status definitions and instruction outcome heads. Instruction saves retain their own concurrency and readback safeguards. For a joint result, use one composed Push report with separate topic-deletion and instruction rows, including the complete instruction-save statement. For instruction-only cleanup, retain that statement and the actual deletion state. Do not use the Create/Update topic-execution or testing trailer, and do not offer activation or testing of the deleted topic. A successful instruction save does not establish successful deletion.

### Routing cleanup after deletion

If a routing conflict is newly discovered or materially changed after deletion, report the actual deletion outcome first, then Routing Conflicts with the same grouped Suggested actions treatment. Describe the existing dangling reference rather than a future deletion consequence. Do not re-offer a correction already declined for the same unchanged conflict.

Offer instruction-only cleanup with these explanations and the separate control:

> ##### YOUR CHOICES
>
> | Choice                                                 | What happens                                                                 |
> | ------------------------------------------------------ | ---------------------------------------------------------------------------- |
> | Resolve the routing conflict in the Agent Instructions | Prepare a targeted correction for review. Do not push it or repeat deletion. |
> | Not now                                                | Leave the instructions unchanged. Keep the existing deletion outcome.        |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Routing conflict",
        "description": "How would you like to continue?",
        "enum": [
          "Resolve the routing conflict in the Agent Instructions",
          "Not now"
        ]
      }
    }
  }
}
```

Use the same path for a known topic already established absent. Carry its exact identity and agent without requiring a current local topic file or issuing another deletion. An uncertain deletion outcome is not established absence: reconcile that uncertainty before treating the correction as post-deletion cleanup.

### Local-only variations

For an existing topic with deletion deferred to a later Push, use:

> ##### DELETION KEPT LOCALLY AGENT UNCHANGED
>
> {Topic title} is removed from your VS Code working files. Its deletion has not been pushed to {Destination agent}.

A missing working file is a pending change, not proof of intent or permission to delete the topic from the agent. A later Push requires fresh state, impact review and scoped destructive approval.

For a draft established as never pushed, distinguish discarding that draft from staging deletion of an existing topic. An absent mapping alone does not establish that it was never pushed. If its remote status is unknown, resolve that uncertainty first. Render:

> ##### DISCARD LOCAL TOPIC DRAFT
>
> ##### TOPIC
>
> {Topic title}
>
> This removes the unsaved draft from your VS Code workspace. It does not push a deletion to the agent.

Follow with these explanations and the native control:

> ##### YOUR CHOICES
>
> | Choice              | What happens                                                                                        |
> | ------------------- | --------------------------------------------------------------------------------------------------- |
> | Discard local draft | Remove only this established never-pushed draft. No remote deletion or pending deletion is created. |
> | Keep draft          | Retain the local draft unchanged.                                                                   |

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "action": {
        "type": "string",
        "title": "Local draft",
        "description": "How would you like to continue?",
        "enum": ["Discard local draft", "Keep draft"]
      }
    }
  }
}
```

After approved removal of only that draft, use:

> ##### LOCAL DRAFT DISCARDED AGENT UNCHANGED
>
> {Topic title} was removed from your VS Code workspace. No agent deletion is pending.

### Deletion outcomes: `{delete_outcome_heads}`

Use at least these headings, followed by factual details naming the topic and agent, actual local and remote state, and any remaining action. Do not present this catalog to the maker.

| Established outcome                                                        | Heading                                           |
| -------------------------------------------------------------------------- | ------------------------------------------------- |
| Deletion and local reconciliation confirmed                                | `##### TOPIC DELETED FROM AGENT`                  |
| Cancelled before execution                                                 | `##### DELETION CANCELLED`                        |
| Template protection or another safety check blocks action                  | `##### TOPIC DELETION NOT STARTED`                |
| No write attempted, or deletion authoritatively rejected                   | `##### TOPIC WAS NOT DELETED`                     |
| Remote effect remains uncertain                                            | `##### TOPIC DELETION COULD NOT BE CONFIRMED`     |
| Deletion succeeded or absence established, local reconciliation incomplete | `##### TOPIC DELETED WORKSPACE UPDATE INCOMPLETE` |
| Topic already absent on inspection                                         | `##### TOPIC ALREADY ABSENT FROM AGENT`           |

For confirmed deletion and local reconciliation, render:

> ##### TOPIC DELETED FROM AGENT
>
> ##### TOPIC
>
> {Topic title}
>
> ##### AGENT
>
> {Destination agent}
>
> The deletion was pushed to the agent, and your local workspace is updated.

Do not use the pushed-success statement when absence was already established without a write. Report that no new remote deletion was needed. Preserve uncertain outcomes, even after an unsuccessful HTTP response. Do not retry blindly, treat a local checkpoint restore as restoring the agent, or count disappearance from a local scan as confirmed remote deletion.

For composed Push, use the [Push experience](push-experience.md) report and statuses instead of a separate owner report: Pushed for HTTP-successful deletion, Pushed with local issue for unfinished reconciliation, and Unconfirmed when the effect is unknown. Put deletion and no-write facts in Details. Do not offer activation or testing of a deleted topic. Relevant remaining references or evaluation changes retain their own explicit scope and approval.
