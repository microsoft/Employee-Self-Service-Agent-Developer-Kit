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

Show the changed paths and agree the exact requested scope. Preserve unrelated pending changes. Read current remote state through the selected operation's owner before proposing a save.

## Compose the supported operations

Use these existing owners:

| Selected change | Owner |
| --- | --- |
| New topic draft | `src/skills/topics/create/SKILL.md`, using `topic_authoring.py create --draft` |
| Existing mapped topic | `src/skills/topics/update/SKILL.md`, using its fresh read and `topic_authoring.py update --draft` |
| Instructions in `agent.mcs.yml` | `agent_instructions.py read`, then `agent_instructions.py update --draft` against that read snapshot |
| Evaluation sets | The selected-set evaluation deployment flow above, retaining its review state and separate consent |

For mixed scope, apply that evaluation flow to the selected evaluation portion and continue the other approved operations. Run its analytics reminder only after verified evaluation deployment.

Topic creation uses ordinary YAML and separate creation metadata. Existing topics use their mapped identities. Follow the normal topic owner's overlap and instruction-alignment assessment without repeating still-current warnings.

For instructions, read current native instructions and preview only the instruction-section change. Preserve unrelated draft fields. Obtain separate instruction approval even when a topic save is also requested.

Show each selected operation's exact preview and obtain its required approval before using its noninteractive `--yes`. A general push request or "push anyway" does not combine topic, instruction, and evaluation approvals. It may override disclosed advisory review/alignment concerns, not unsupported scope or failed/uncertain operations.

Workflows, template configurations, deployed deletions, and non-instruction agent metadata are outside this general save path. Explain the boundary and leave those local changes pending. Direct Power Automate authoring, deployment, registration, and repair outside ADK. Preserve separately authorized product-extension setup and explicit activation operations; do not invoke them to make a topic save or test runnable.

## Report each outcome

Report topic, instruction, and evaluation results separately, including known remote outcomes and any subsequent local output or bookkeeping failure. Each owner acknowledges only its captured submitted content. Later disk edits and unsupported changes remain pending.

If a request failed or its outcome is uncertain, preserve the causal evidence and let the session select the next read or recovery action. Do not replay a create/save merely to repair output, refresh setup automatically, or reset the whole baseline.

Offer supported conversation testing for a plain save request; run it when already requested and available, carrying the selected topic. If `scripts/native_topic_test.py` is absent, report conversation acceptance as pending. Saving does not activate or publish. Preserve local review/catalog evidence; a save alone does not refresh review coverage or resolve findings.