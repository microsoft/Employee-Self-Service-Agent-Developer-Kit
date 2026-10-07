# Repo-root Copilot instructions

## Discover Maker Kit operations

Establish the Maker Kit catalog location once per conversation:

1. Check whether `.github/prompts/` contains any `*.prompt.md` files and
   `src/skills/` exists in the same current folder.
2. When that pair is unavailable, check whether
   `solutions/ess-maker-skills/.github/prompts/` contains any `*.prompt.md`
   files and `solutions/ess-maker-skills/src/skills/` exists.

Classify the result:

- The qualifying paths in the current folder mean the Maker Kit catalog is
  available from the current folder.
- The qualifying paths under `solutions/ess-maker-skills/` mean the Maker Kit
  catalog is available from a nested solution folder.
- No qualifying catalog at either location means the Maker Kit operation
  catalog is unavailable.

When the catalog is available from the current folder, read and follow the
current folder's `.github/copilot-instructions.md`. That file owns setup-state
and operation routing for the conversation.

When the catalog is available from a nested solution folder:

- When the request begins with `/`, derive its prompt filename from the command
  name. For example, `/flightcheck` maps to `flightcheck.prompt.md`. Check that
  candidate directly in the nested catalog.
- For natural-language requests, or when the direct command candidate does not
  exist, list the prompt filenames in the nested catalog and use them to match
  the operation intent.
- When the filename match remains unclear, read the `description` frontmatter
  field from likely candidate prompts.
- When the request matches a discovered Maker Kit operation, provide the
  folder-selection guidance.

When the operation catalog is unavailable and the user explicitly names the ESS
Maker Kit, provide the folder-selection guidance.

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
