# Repo-root Copilot instructions

## Determine the active workspace

At the beginning of each conversation, first check whether both of these direct
Maker Kit paths are available:

- `.github/prompts/` contains at least one `*.prompt.md` file.
- `src/skills/` exists.

When that direct pair is available, the Maker Kit is already the active
workspace. Do not apply the folder-selection guidance in this file. Continue
with the active workspace instructions instead.

Otherwise, check whether both of these nested Maker Kit paths are available:

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

## Folder-selection handoff

When folder-selection guidance applies, do not execute the Maker Kit operation
in the repository-root chat. Preserve the user's original request without
adding, removing, or rewriting any text.

Before launching VS Code, first send this standalone message:

> Your prompt needs the Maker Kit workspace so the correct prompts and skills
> are available.
>
> **Continue in a new Maker Kit chat?**
>
> I’ll open `solutions/ess-maker-skills` in a new VS Code window, start a fresh
> chat, and transfer your prompt unchanged. This chat will stop after the
> transfer.

After sending that message, call `ask_user` with this exact form shape. Keep
`message` empty so no smaller pre-text appears. Use the field title for the
single card heading, set a distinct field description for the inner prompt,
and use labeled options instead of a boolean prompt:

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "handoffAction": {
        "type": "string",
        "title": "ADK Maker Kit Recovery",
        "description": "Choose how to continue",
        "oneOf": [
          {
            "const": "open",
            "title": "Open the Maker Kit and continue"
          },
          {
            "const": "manual",
            "title": "Show manual steps instead"
          }
        ]
      }
    }
  }
}
```

If the user chooses **Open the Maker Kit and continue**:

1. Resolve `solutions/ess-maker-skills` to an absolute path from the active
   repository root. Verify the direct Maker Kit markers listed above exist at
   that path.
2. Show `Opening the Maker Kit workspace` while running
   `code --new-window "<absolute Maker Kit path>"`. Wait for that command to
   complete successfully, then wait for the newly opened Maker Kit window to
   finish loading. Do not run the two commands concurrently.
3. Use the Maker Kit folder as the working directory and run
   `code chat --reuse-window "<original request>"` while showing
   `Transferring your prompt to a fresh Maker Kit chat`. Pass the preserved
   request as one prompt argument with shell-appropriate escaping. Do not add
   guard text, setup instructions, or other framing to the prompt.
4. After the chat command succeeds, respond with only:

   > Your prompt was transferred to a fresh chat in the Maker Kit window.
   > Continue there.

   Then stop processing the request in the current chat. The new Maker Kit chat
   owns setup gating, execution, recovery, and completion reporting.

If the user chooses **Show manual steps instead**, declines, or skips the
confirmation, provide the manual guidance below without launching VS Code. If
path validation or either command fails, surface the failure and do not claim
that the request was transferred. Fall back to the same manual guidance:

> ESS Maker Kit agent operations are available from the
> `solutions/ess-maker-skills` workspace.
>
> **Open the Maker Kit workspace manually:**
>
> 1. In VS Code, select `File` → `Open Folder…` or press `Ctrl+K Ctrl+O`.
> 2. Select `solutions/ess-maker-skills`.
> 3. Click `Select Folder`.
> 4. After VS Code reopens, start a new Copilot chat and enter your prompt
>    again.

Route every request not covered above as normal.
