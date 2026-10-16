# Repo-root Copilot instructions

## Workspace boundary

Apply this boundary before discovering operations or showing folder-selection
guidance. This file can be inherited while the Maker Kit workspace is open;
reading it does not prove that the repository root is the active workspace.

- Prefer the active VS Code workspace-folder information over a shell session's
  working directory or the Git repository root.
- If the Maker Kit folder or one of its descendants is the active workspace,
  do not redirect. Follow that workspace's local Copilot instructions and
  prompt catalog, resolving operation paths from the Maker Kit folder.
- If a multi-root workspace includes the Maker Kit folder, do not redirect.
  Use that folder for Maker Kit operations.
- If the user confirms that the Maker Kit workspace is already open, do not
  repeat folder-selection guidance. If workspace evidence conflicts or is
  unavailable, investigate the mismatch rather than assuming the wrong folder.
- The presence of `solutions/ess-maker-skills` under the Git repository root
  is not evidence that the user opened the wrong workspace.

Only show folder-selection guidance when the active workspace is positively
identified as the repository root and no Maker Kit workspace folder is active.
Otherwise, skip the repo-root routing below and handle the request normally.
Reports about incorrect redirects and requests to inspect or edit skill source
are development requests, not Maker Kit operation invocations.

## Discover Maker Kit operations

Only after the workspace boundary permits repo-root routing, check whether
both of these paths are available relative to the active repository-root
workspace, not by searching from the Git root of a different active workspace:

- `solutions/ess-maker-skills/.github/prompts/` contains at least one
  `*.prompt.md` file.
- `solutions/ess-maker-skills/src/skills/` exists.

When that pair is unavailable, do not apply the Maker Kit folder-routing
instructions below. Route the request as normal.

When that pair is available:

- When the request begins with `/`, derive its prompt filename from the command
  name. For example, `/flightcheck` maps to `flightcheck.prompt.md`. Check that
  candidate directly in the nested prompt catalog.
- For natural-language requests, or when the direct command candidate does not
  exist, list the prompt filenames in the nested catalog and use them to match
  the operation intent.
- When the filename match remains unclear, read the `description` frontmatter
  field from likely candidate prompts.
- Provide the folder-selection guidance when the request matches a discovered
  Maker Kit operation.
- Also provide the folder-selection guidance when the user explicitly asks to
  use, open, or run the ESS Maker Kit as a maker experience.

## Folder-selection guidance

When folder-selection guidance applies, respond with only:

> ESS Maker Kit agent operations are available from the
> `solutions/ess-maker-skills` workspace.
>
> **Open the Maker Kit workspace:**
>
> 1. In VS Code, select `File` → `Open Folder…` or press `Ctrl+K Ctrl+O`.
> 2. Select `solutions/ess-maker-skills`.
> 3. Click `Select Folder`.
> 4. After VS Code reopens, enter the request again.

Route every request not covered above as normal.
