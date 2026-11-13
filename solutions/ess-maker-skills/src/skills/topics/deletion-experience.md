# Topic deletion experience

<!-- markdownlint-disable MD001 -->

Apply the [shared foundation](experience-contract.md). Use this reference before reviewing deletion, staging it locally or discarding a draft. The [delete owner](delete/SKILL.md) owns execution; a remote deletion also uses [Push telemetry](push-experience.md#push-telemetry).

## Contents

- [Deletion status updates](#deletion-status-updates)
- [Topic deletion](#topic-deletion)
- [Deletion summary: `{delete_summary}`](#deletion-summary-delete_summary)
- [Local-only variations](#local-only-variations)
- [Deletion outcomes: `{delete_outcome_heads}`](#deletion-outcomes-delete_outcome_heads)

## Deletion status updates

Apply [Status update markers](experience-contract.md#status-update-markers) before the delete owner's work. Bind `{Topic title}` to the exact selected topic. The delete owner emits these updates even when called by Push or cleanup; the caller does not repeat them.

| Reporting point       | Completion condition                                                                                                                                 | Completion message                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `deletion-review`     | The exact target, removal scope, protection checks and required impact evidence are established for the applicable deletion or draft-discard review. | ✅ Checked the removal scope for **{Topic title}**.                   |
| `deletion-checkpoint` | The checkpoint operation confirms a saved snapshot of the reviewed working files before any removal.                                                 | ✅ Saved a checkpoint before removing **{Topic title}**.              |
| `local-removal`       | Only the approved working files were newly removed, required baseline/mapping records are preserved, and no remote write occurred.                   | ✅ Removed **{Topic title}** from your local working files.           |
| `topic-deletion`      | A new approved remote deletion, authoritative absence and required local reconciliation are all confirmed.                                           | ✅ Deleted **{Topic title}** and verified its removal from the agent. |

Use [Deletion outcomes](#deletion-outcomes-delete_outcome_heads) and [Local-only variations](#local-only-variations) for incomplete, rejected, already-absent, partial or uncertain results. A failed checkpoint leaves removal unstarted. Unverified impact remains unverified even when a review can proceed with that disclosure. Local removal does not establish remote deletion; remote absence without a new write does not qualify for the new-deletion completion message. Report partial local removal accurately.

## Topic deletion

The delete owner uses this section for direct requests, cleanup and selected Push deletions. Resolve the exact topic and selected editable Dev agent, then apply **Authoring policy for this release** to the topic and any contained topics. Selection is not deletion approval. Deletion does not author replacement behavior or authorize changes to referencing topics, instructions, evaluations or external resources.

For composed Push, combine overlapping parent and contained deletions into one reviewed operation. Show every affected topic, but do not dispatch a contained deletion again after its parent. Resolve conflicting updates or exclusions within that deletion scope before requesting approval.

Use **Push** for applying the deletion to the agent. Reserve **Publish** for the separate Copilot Studio operation. Do not describe a pushed deletion as merely local or as published.

### Deletion summary: `{delete_summary}`

Bind the topic, agent and behavior to current evidence. Also removed lists contained content and affected local files beyond the selected topic. References needing attention identifies actual references and their practical consequences. Inspect relevant current topics and agent instructions; local files alone do not prove there are no remote references. Omit genuinely empty sections and identify unresolved impact explicitly.

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
> - {Referencing topic or instruction and practical effect}
>
> Pushing this deletion removes the topic from the agent and your local workspace.

Show this summary and these explanations before the separate native control:

> ##### YOUR CHOICES
>
> | Choice                 | What happens                                                                                                             |
> | ---------------------- | ------------------------------------------------------------------------------------------------------------------------ |
> | Push deletion to agent | Delete the displayed topic and contained content from the agent, verify absence, and reconcile the approved local files. |
> | Keep deletion locally  | Remove only the displayed working files. Keep the saved topic and tracking for a later reviewed Push.                    |
> | Not now                | Leave the current local and remote state unchanged.                                                                      |

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

| Established outcome                                       | Heading                                           |
| --------------------------------------------------------- | ------------------------------------------------- |
| Deletion and local reconciliation confirmed               | `##### TOPIC DELETED FROM AGENT`                  |
| Cancelled before execution                                | `##### DELETION CANCELLED`                        |
| Template protection or another safety check blocks action | `##### TOPIC DELETION NOT STARTED`                |
| No write attempted, or deletion authoritatively rejected  | `##### TOPIC WAS NOT DELETED`                     |
| Remote effect remains uncertain                           | `##### TOPIC DELETION COULD NOT BE CONFIRMED`     |
| Remote absence confirmed, local reconciliation incomplete | `##### TOPIC DELETED WORKSPACE UPDATE INCOMPLETE` |
| Topic already absent on inspection                        | `##### TOPIC ALREADY ABSENT FROM AGENT`           |

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

For composed Push, use the [Push experience](push-experience.md) report and statuses instead of a separate owner report: Pushed for verified deletion, Pushed with local issue for unfinished reconciliation, and Unconfirmed when the effect is unknown. Put deletion and no-write facts in Details. Do not offer activation or testing of a deleted topic. Relevant remaining references or evaluation changes retain their own explicit scope and approval.
