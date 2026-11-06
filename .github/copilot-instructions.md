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

## Folder-selection recovery

When folder-selection guidance applies, do not execute the Maker Kit operation
in the repository-root chat. Preserve the user's original request without
adding, removing, or rewriting any text.

First provide this manual guidance:

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

Then send:

> **Want me to try?**
>
> I can attempt to open the Maker Kit in a new VS Code window and send your
> prompt to a fresh chat. This requires the new Maker Kit window to remain
> focused until the attempt finishes. Do not switch to another VS Code window
> during the attempt.
>
> This chat will remain available until you confirm that the prompt arrived.

After sending that message, call `ask_user` with this exact form shape:

```json
{
  "message": "",
  "requestedSchema": {
    "properties": {
      "recoveryAction": {
        "type": "string",
        "title": "ADK Maker Kit Recovery",
        "description": "Choose how to continue",
        "oneOf": [
          {
            "const": "attempt",
            "title": "Attempt to open the Maker Kit"
          },
          {
            "const": "manual",
            "title": "I’ll open it manually"
          }
        ]
      }
    }
  }
}
```

If the user chooses **I’ll open it manually**, declines, or skips the
confirmation, do not launch VS Code. The manual steps have already been
provided.

If the user chooses **Attempt to open the Maker Kit**:

1. Resolve `solutions/ess-maker-skills` to an absolute path from the active
   repository root. Verify the direct Maker Kit markers listed above exist at
   that path.
2. Show `Opening the Maker Kit workspace` while running
   `code --new-window "<absolute Maker Kit path>"`. Wait for that command to
   complete successfully, then wait for the newly opened Maker Kit window to
   finish loading. Do not run the two commands concurrently.
3. Show `Keep the new Maker Kit window focused`, then use the Maker Kit folder
   as the working directory and run
   `code chat --reuse-window "<original request>"` while showing
   `Sending your prompt to a fresh Maker Kit chat`. Pass the preserved request
   as one prompt argument with shell-appropriate escaping. Do not add guard
   text, setup instructions, or other framing to the prompt.
4. After the chat command succeeds, respond with only:

   > VS Code accepted your prompt. Check the new Maker Kit window.

5. Keep the current chat available and call `ask_user` with this exact form
   shape:

   ```json
   {
     "message": "",
     "requestedSchema": {
       "properties": {
         "promptResult": {
           "type": "string",
           "title": "Confirm prompt",
           "description": "Did your prompt appear in a fresh Maker Kit chat?",
           "oneOf": [
             {
               "const": "confirmed",
               "title": "Yes, continue there"
             },
             {
               "const": "retry",
               "title": "No, try again"
             },
             {
               "const": "manual",
               "title": "No, let me handle it manually"
             }
           ]
         }
       }
     }
   }
   ```

6. If the user chooses **Yes, continue there**, respond with only:

   > Continue in the Maker Kit window.

   Then stop processing the request in the current chat. The new Maker Kit chat
   owns setup gating, execution, recovery, and completion reporting.
7. If the user chooses **No, try again**, respond with:

   > I’ll repeat the attempt. Keep the newly opened Maker Kit window focused
   > until your prompt appears.

   Then repeat the complete attempt beginning with path validation. Each retry
   requires the user's explicit selection. Do not retry automatically.
8. If the user chooses **No, let me handle it manually**, respond with:

   > Use the manual steps above.

If path validation or either command fails, surface the failure, keep the
current chat available, and direct the user to the manual steps above. Do not
claim that the prompt appeared in the Maker Kit window.

Route every request not covered above as normal.
