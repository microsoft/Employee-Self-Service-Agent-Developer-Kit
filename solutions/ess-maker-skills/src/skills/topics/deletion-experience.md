# Topic deletion experience

Apply the [shared foundation](experience-contract.md). Use this reference before reviewing deletion, staging it locally or discarding a draft. The [delete owner](delete/SKILL.md) owns execution; a remote deletion also uses [Push telemetry](push-experience.md#push-telemetry).

## Contents

- [Topic deletion](#topic-deletion)
- [Deletion summary: `{delete_summary}`](#deletion-summary-delete_summary)
- [Local-only variations](#local-only-variations)
- [Deletion outcomes: `{delete_outcome_heads}`](#deletion-outcomes-delete_outcome_heads)

## Topic deletion

The delete owner uses this section for direct requests, cleanup and selected Push deletions. Resolve the exact topic and selected editable Dev agent, then apply **Authoring policy for this release** to the topic and any contained topics. Selection is not deletion approval. Deletion does not author replacement behavior or authorize changes to referencing topics, instructions, evaluations or external resources.

For composed Push, combine overlapping parent and contained deletions into one reviewed operation. Show every affected topic, but do not dispatch a contained deletion again after its parent. Resolve conflicting updates or exclusions within that deletion scope before requesting approval.

Use **Push** for applying the deletion to the agent. Reserve **Publish** for the separate Copilot Studio operation. Do not describe a pushed deletion as merely local or as published.

### Deletion summary: `{delete_summary}`

Bind the topic, agent and behavior to current evidence. Also removed lists contained content and affected local files beyond the selected topic. References needing attention identifies actual references and their practical consequences. Inspect relevant current topics and agent instructions; local files alone do not prove there are no remote references. Omit genuinely empty sections and identify unresolved impact explicitly.

> **Delete topic**
>
> **Topic:** {Topic title}
>
> **Agent:** {Destination agent}
>
> **Behavior being removed:** {Concise behavior description}
>
> **Also removed**
>
> - {Contained content or additional local file}
>
> **References needing attention**
>
> - {Referencing topic or instruction and practical effect}
>
> Pushing this deletion removes the topic from the agent and your local workspace.

Show this summary before the separate choice:

> **Push deletion to agent** / **Keep deletion locally** / **Not now**

Push deletion to agent authorizes only the displayed deletion and local reconciliation. Reuse unchanged scoped Push consent only when it explicitly includes this destructive operation and its consequences. Refresh the review and obtain new approval when identity, contained content or material effects change.

Keep deletion locally authorizes removing the displayed working files only. Retain their baseline and component mapping so a later Push can discover the pending deletion. The agent remains unchanged, and this choice does not approve a later remote deletion. Not now leaves the current state unchanged; do not restore an already-missing file automatically.

### Local-only variations

For an existing topic with deletion deferred to a later Push, use:

> **Deletion kept locally. Agent unchanged.**
>
> {Topic title} is removed from your VS Code working files. Its deletion has not been pushed to {Destination agent}.

A missing working file is a pending change, not proof of intent or permission to delete the topic from the agent. A later Push requires fresh state, impact review and scoped destructive approval.

For a draft established as never pushed, distinguish discarding that draft from staging deletion of an existing topic. An absent mapping alone does not establish that it was never pushed. If its remote status is unknown, resolve that uncertainty first. Render:

> **Discard local topic draft**
>
> **Topic:** {Topic title}
>
> This removes the unsaved draft from your VS Code workspace. It does not push a deletion to the agent.

Follow with:

> **Discard local draft** / **Keep draft**

After approved removal of only that draft, use:

> **Local draft discarded. Agent unchanged.**
>
> {Topic title} was removed from your VS Code workspace. No agent deletion is pending.

### Deletion outcomes: `{delete_outcome_heads}`

Use at least these headings, followed by factual details naming the topic and agent, actual local and remote state, and any remaining action. Do not present this catalog to the maker.

| Established outcome                                       | Heading                                         |
| --------------------------------------------------------- | ----------------------------------------------- |
| Deletion and local reconciliation confirmed               | **Topic deleted from agent.**                   |
| Cancelled before execution                                | **Deletion cancelled.**                         |
| Protection or unresolved ownership prevents proceeding    | **Topic deletion not started.**                 |
| No write attempted, or deletion authoritatively rejected  | **Topic was not deleted.**                      |
| Remote effect remains uncertain                           | **Topic deletion could not be confirmed.**      |
| Remote absence confirmed, local reconciliation incomplete | **Topic deleted; workspace update incomplete.** |
| Topic already absent on inspection                        | **Topic already absent from agent.**            |

For confirmed deletion and local reconciliation, render:

> **Topic deleted from agent.**
>
> **Topic:** {Topic title}
>
> **Agent:** {Destination agent}
>
> The deletion was pushed to the agent, and your local workspace is updated.

Do not use the pushed-success statement when absence was already established without a write. Report that no new remote deletion was needed. Preserve uncertain outcomes, even after an unsuccessful HTTP response. Do not retry blindly, treat a local checkpoint restore as restoring the agent, or count disappearance from a local scan as confirmed remote deletion.

For composed Push, use the [Push experience](push-experience.md) report and statuses instead of a separate owner report: Pushed for verified deletion, Pushed with local issue for unfinished reconciliation, and Unconfirmed when the effect is unknown. Put deletion and no-write facts in Details. Do not offer activation or testing of a deleted topic. Relevant remaining references or evaluation changes retain their own explicit scope and approval.
