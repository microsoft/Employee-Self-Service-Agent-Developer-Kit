---
mode: agent
description: "Preview selected local changes and save supported topics, instructions, or evaluations"
---

# Push

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`.
If canonical state does not have `schema_version: 4` and an `agents` entry
matching the active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/push`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

Read `src/skills/topics/experience-contract.md` before presenting inventory,
comparisons, decisions or results. Use its literal copy and scoped consent
rules. Keep previews in normal chat and decision controls short.

## Explicit evaluation push

If the request explicitly targets only evaluation test sets, route before the
general-component instructions below. Discover/select the exact workspace or
current-agent set using `src/skills/evaluations/update/SKILL.md`, then follow
`src/skills/evaluations/deployment-flow.md` with helper action `push`.
Preserve existing review state; do not create a review request, mark review
complete, or start a run.
Use the existing backend APIs. Explain native `new_copy`/`reuse` behavior before
consent; a new copy gets a new deployed ID and retains the old remote copy.
Native review sidecars remain local, not shared review metadata. Follow the
shared guide's `reviewMetadataPersisted`/`reviewWarning` outcome rules rather
than adding an in-place-update or remote-review prerequisite.

This branch supports standalone evaluation push. Method admission, target checks, selected-set scope,
dry-run visibility, and required destructive approval remain mandatory.
Use noninteractive execution only after the shared flow obtains chat approval;
its authorized `--yes` does not bypass that consent. Never launch an
interactive evaluation push waiting for unattended stdin.
If evaluation scope is ambiguous, ask rather than pushing all components.
Return after this branch; do not also execute the general push below.

After the shared deployment flow reports a verified successful deployment,
run the one-time DA post-deployment analytics reminder:

```powershell
python scripts/analytics_pointer.py --post-deploy
```

Show any command output verbatim. The command is silent after the reminder has
already been completed for the current environment/agent association. Run it
only after deployment verification; do not show an analytics link after a
preview, cancellation, or failed deployment. If the resolver cannot build the
link, do not substitute the Copilot Studio home page.

## Inspect pending changes

For a general push request, inspect the selected agent's local changes:

```powershell
python scripts/push.py --dry-run
```

This operation only compares working files with `.baseline`. It does not authenticate, save, activate, publish, or verify remote state. The baseline records acknowledged submitted content, not a remote mirror or concurrency token.

Build one `{component_inventory}` in session context from the discovered
changes. Use the evaluation owner's selected-set discovery for applicable
changed evaluation sets not represented by the agent baseline. Preserve each
entry's type, name, exact identity, proposed change and applicability. An
`agent.mcs.yml` change is not necessarily an instruction change: compare its
parsed instruction section with the baseline separately from metadata. Keep
unchanged instructions out of pending and excluded changes. Classify an actual
rename as Display name, retaining the proposed value and save limitation.

For a Create/Update routing-correction handoff, scope this inventory to the
carried topic draft and isolated instruction correction. Leave unrelated
pending edits outside that displayed scope; do not include them implicitly.

Read current remote state and obtain the exact non-mutating previews through
the selected owners before asking for Push approval. Include material
evaluation-copy/reuse, local-replacement and review-state consequences in the
displayed scope. Inventory inspection alone is not remote validation.

Use the shared inventory outcomes after appropriate observation and recovery:
**No changes to push.** only after successful empty inspection, or **Could not
inspect local changes.** with the cause and an offer of the next safe action
when inspection remains unavailable. Do not equate failed inspection with no
changes or show runnable Push choices for it.

For available changes, render the shared bulleted entry inventory and offer
**Summarize each change**, **Push all listed changes**, **Choose what to push**
or **Cancel**. Reuse this same inventory throughout; do not rediscover a
different implicit scope after approval.

Choose what to push selects component types, initially none. Each type includes
all its displayed changes. Follow selection with **Summarize selected
changes**, **Push selected changes** or **Cancel**. Empty selection never means
all changes.

Summarize each change and Summarize selected changes review one component-level
operation at a time: one topic, one agent instruction-section update, or one
evaluation test-set deployment. Use the relevant owner summary, or the shared
`{compact_change_comparison}` for a previously deferred edit, in normal chat.
Current comes from the fresh saved state. Do not add a draft-link line to that
comparison. Include its Not included block for the current selected scope,
with labeled types and individual name/reason bullets even when previously
listed; do not replace it with a collective pending-changes sentence.
Then offer **Push this change**, **Keep pending** or **Cancel
remaining push**. Preserve completed pushes when remaining work is cancelled.

## Compose the supported operations

Use these existing owners:

| Selected change                 | Owner                                                                                                       |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| New topic draft                 | `src/skills/topics/create/SKILL.md`, using `topic_authoring.py create --draft`                              |
| Existing mapped topic           | `src/skills/topics/update/SKILL.md`, using its fresh read and `topic_authoring.py update --draft`           |
| Instructions in `agent.mcs.yml` | `agent_instructions.py read`, then `agent_instructions.py update --draft` against that read snapshot        |
| Evaluation sets                 | The selected-set evaluation deployment flow above, retaining its review state and applicable scoped consent |

For mixed scope, apply that evaluation flow to the selected evaluation portion and continue the other approved operations. Run its analytics reminder only after verified evaluation deployment.

Topic creation uses ordinary YAML and separate creation metadata. Existing topics use their mapped identities. Follow the normal topic owner's overlap and instruction-alignment assessment without repeating still-current warnings.

For instructions, read current native instructions and preview only the
instruction-section change. Preserve unrelated draft fields. Ordinary
authoring has separate approvals; the shared Push consent below covers an
unchanged displayed batch without another owner approval.

**Push all listed changes** approves every displayed applicable change for the
identified agent; **Push selected changes** approves only the displayed
selection. **Push this change** approves the current component-level item.
Carry this exact consent into the owners and their noninteractive `--yes`
operations, including evaluation deployment. Do not ask for independent owner
approval again for that unchanged authorized scope. A general request to push,
before these scoped choices, is not itself batch consent.

A material change to the authorized scope, intent or consequences requires a
revised summary and fresh approval. Keep native concurrency checks,
confirmation tokens, method admission and destructive/replacement approvals;
scoped batch consent is not a bypass for these safeguards. Do not treat an
advisory override as permission for unsupported operations or blind replay.

Render actual discovered exclusions using the shared Not included heading,
component-type sections and individual component-name/reason bullets. Retain
the inventory's readable names in comparisons and results and leave excluded
changes pending.
Do not advertise retired workflow/template-config deployment or deployed
deletion as choices. Preserve separately authorized product-extension setup
and explicit testing activation, without invoking them as save side effects.

## Recover, compose results and continue

Observe each outcome and attempt appropriate in-scope recovery. Continue
independently safe approved changes; pause dependent work when an unresolved
result affects its correctness or safety. Independence follows the requested
outcome, not merely different types or files. Cancellation stops remaining
work and preserves completed saves.

Use one `{composed_push_report}` with **Push results**, the Component / Outcome /
Details table and any actual **Not included** entries, all drawn from
`{component_inventory}`. Use the shared Pushed / Kept pending / Cancelled /
Failed / Unconfirmed / Pushed with local issue labels. A known prerequisite
failure uses Failed with its cause and states that no write was attempted;
there is no separate Blocked Push status.

For a topic and routing correction approved together, retain the complete
instruction-save statement in the instruction row's Details, with conflict
assessment and testing readiness in the trailer, not separate owner outcome
blocks. Preserve known remote results, uncertainty, subsequent local
output/bookkeeping failures, actual evaluation-copy/review facts and required links/reminders.
Each owner acknowledges only captured submitted content. Later disk edits
remain pending. Do not concatenate owner reports or menus, blindly replay an
uncertain write, refresh setup automatically or reset the whole baseline.

Honor the initial routing-conflict decision and exact approved scope. Use the
shared combined routing-conflict/testing decision and targeted instruction
preview/approval only for a newly discovered or materially changed conflict
after Push. After Push topic anyway, retain a concise conflict reminder and
offer ordinary state-aware testing once unless already requested. Carry any
declined instruction correction as an explicit exclusion into later authorized
testing; topic-only Push does not authorize testing. Do not offer runnable
testing of topic changes left local. Preserve per-component results when topic
and instruction outcomes differ.
If `scripts/native_topic_test.py` is absent, report conversation
acceptance as pending. Saving does not activate or publish; activation requires
the separate explicit testing choice. A save does not refresh review coverage,
resolve findings or authorize evaluation execution. Finish without a generic
What next form when no follow-up applies.
