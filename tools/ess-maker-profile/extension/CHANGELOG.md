# Changelog

## 0.4.24 (POC)

- **Auto-update nudge.** On VS Code startup, the extension now checks
  whether the local ESS ADK clone is behind `origin/main` (via
  `git ls-remote` vs the local `HEAD`) and, if so, shows a non-blocking
  notification: "A newer version of the ESS ADK is available."
  with **Update now**, **Later**, and **Don't ask again** actions.
  - **Update now** runs `git pull --ff-only` and offers a window reload.
  - Only fires when the clone is on `main` (developers on feature
    branches are never nagged), and degrades gracefully when offline,
    on a dirty tree, or on a diverged (non-fast-forward) clone.
  - Detects when the pulled repo ships a newer extension than the
    installed VSIX (a code pull doesn't refresh the extension) and
    prompts reinstall/reload instead.
  - **Don't ask again** persists per-user; a new `essMaker.autoUpdateCheck`
    setting (default `true`) lets IT disable the nudge on managed boxes.

## 0.4.22 (POC)

- **Tutorial is now a custom webview panel** — no checkboxes, no step
  indicators. All tutorial content renders as a single scrollable page
  with a table-of-contents nav bar.
- **Tutorial opens beside the chat** instead of replacing it. On first
  install the tutorial appears on the left with `/setup` chat on the
  right. The "View tutorial" button opens it next to whatever is
  currently focused.
- Removed VS Code walkthrough registration from `package.json`.

## 0.4.21 (POC)

- **Getting Started walkthrough + chat side-by-side on first install.**
  New users land on a split-editor layout: the Getting Started
  walkthrough ("Customize your ESS agent") on the left, and a `/setup`
  chat already running on the right. The walkthrough explains each
  stage (Connect → Create → Scan → FlightCheck → Push) with buttons
  that open the corresponding slash command. On subsequent VS Code
  launches, the extension skips the walkthrough and goes directly to
  the full-screen `/setup` chat as before.
- Bumps `APPLIED_KEY` to `v6` so existing installs see the walkthrough
  once on upgrade.

## 0.4.20 (POC)

- **The fix that finally worked.** The installer now launches `code .`
  (workspace only) instead of `code chat /setup` when this extension
  is installed, and the extension itself opens the chat in the editor
  area and submits /setup. This produces ONE full-width chat in the
  center editor area — no narrow aux-bar chat, no empty side-effect
  chat editor, no menu bar, no activity bar. Just Quick Actions on
  the left and a full-screen `/setup` chat in the middle.
- Implementation: after a 2s wait for VS Code to settle, the extension
  closes all editor tabs via the `tabGroups` API (the side-effect
  empty chat editor is a chat tab — `closeAllEditors` doesn't touch
  it, but `tabGroups.close(tabs)` does), then opens a fresh chat in
  the editor area, focuses its input, and injects `/setup` via
  clipboard paste (the most reliable way — `chat.open({query,
  location:'editor'})` silently drops the query and the `type`
  command isn't always honoured by the chat input). Aux bar is then
  hidden for cleanliness.
- Bumps `APPLIED_KEY` to `v4` so existing installs re-run the layout
  once.

## 0.4.8 (POC)

- Try the `type` command to inject `/setup` into a freshly-opened
  chat-in-editor. The various `chat.open` shapes with `{ query, location }`
  opened a chat editor but silently dropped the query — using the
  built-in `type` keystroke handler is the same path VS Code itself
  uses for "Run Selection in Terminal" and works on any focused input.
- Close the aux bar TWICE — before and after the chat-in-editor opens —
  because some VS Code builds reopen it when a new chat session is
  created.

## 0.4.7 (POC)

- New strategy: let the installer's `code chat /setup` create the chat
  session (this part has always worked — /setup gets pre-filled and
  submitted), and have the extension MOVE that session to the editor
  area instead of creating its own. Sequence: wait 600 ms for the chat
  to be wired up, focus the chat view, call
  `workbench.action.chat.openInEditor` (which moves the active chat to
  an editor tab), then close the aux bar. End result: one full-screen
  chat in the editor with /setup running.
- Reverts the 0.4.5 installer takeover (extension was opening a parallel
  empty chat) — installer keeps invoking `code chat /setup`.

## 0.4.6 (POC)

- Try `workbench.action.chat.open` with the documented
  `location: 'editor'` option first when opening the /setup chat — this
  is the public API path that reliably opens chat in the editor area
  with a pre-filled query. Falls through to several alternative shapes
  (mode='editor', open-then-move, clipboard paste) on older VS Code
  builds so we don't lose /setup if the public shape changes again.
- Reorder the layout-apply: close all editors -> open chat with /setup
  in editor -> close aux bar (so the stock GH Copilot Chat aux-bar view
  doesn't reappear after our chat is opened).

## 0.4.5 (POC)

- **Eliminate duplicate chat panels.** The one-shot installer now skips
  its own `code chat /setup` invocation when this extension is present,
  so the extension owns chat-opening end-to-end. Result: exactly one
  full-screen chat in the editor area with `/setup` pre-filled and
  submitted, instead of one chat from the CLI launch + one from the
  extension racing each other.

## 0.4.4 (POC)

- **Coalesce to ONE full-screen chat with /setup auto-running.** The
  previous build was non-destructive to avoid killing the chat from
  `code chat /setup`, but that left the user with two chats: the one
  from the launch (in the aux bar or chat editor depending on prefs)
  AND any other chat surfaces that VS Code restored. Now, on first
  apply, the extension closes the aux bar + all editors and opens
  exactly one chat in the editor area with `/setup` pre-filled and
  submitted. /setup just shows sign-in instructions so re-running it
  costs nothing.

## 0.4.3 (POC)

- **Stop killing the installer's `/setup` chat.** The previous layout-apply
  did `closeAuxiliaryBar` + `closeAllEditors` + `openChatInEditor` on
  every activation, which destroyed the chat that the one-shot installer
  opens via `code chat /setup` and replaced it with an empty chat. Made
  the layout-apply non-destructive: it now only applies the settings,
  collapses the explorer tree, and focuses the Quick Actions container
  — no editor / panel / sidebar closing.
- Dropped `workbench.action.resetViewLocations` from 0.4.2 — it was too
  aggressive (would reset every customized view location, not just ours)
  and didn't actually pull Quick Actions back to the aux bar reliably.
  Quick Actions now opens wherever the user last had it (default per
  package.json is the aux bar).

## 0.4.2 (POC)

- Force the Quick Actions view back to the **auxiliary bar** on every
  layout apply via `workbench.action.resetViewLocations`. It can drift
  into the primary sidebar (via user drag or cached layout-state
  restore), where it ends up stacked under Explorer + Outline + Timeline
  and the action buttons get cut off below the fold. With this fix,
  Quick Actions lives in a dedicated pane on the right, completely
  separate from the file explorer.
- Hardened the explorer-collapse fallback: focus the explorer view,
  yield 150 ms so VS Code finishes mounting it, then send both
  `workbench.files.action.collapseExplorerFolders` and
  `list.collapseAll`. Without the yield, the collapse command was
  firing before the tree existed and silently no-op'd.

## 0.4.1 (POC)

- Collapse the file explorer tree on layout apply so the workspace folder
  (e.g. `ess-maker-skills`) doesn't sit expanded with every top-level file
  taking sidebar space and pushing the Quick Actions buttons below the
  fold. Runs on first install AND every subsequent activation, so the
  collapse sticks across VS Code restarts even if VS Code restores the
  sidebar to its previous expanded state.

## 0.4.0 (POC)

- Quick Action buttons are now **state-aware**: only the next applicable
  step is enabled; later steps are greyed out with a "locked" badge and
  a tooltip explaining which prerequisites they're waiting on.
- Sequence: `Connect` → `Create` → (`Update`/`Scan`/`Flightcheck`/`Evaluate`) → `Push`.
- Completed actions get a green ✓ badge so the user can see where they
  are in the flow.
- State is inferred from the workspace (presence of topic yaml files or
  connection config files) plus what the user has clicked, persisted
  across sessions in globalState.
- New "Reset progress" secondary button to re-lock the steps.

## 0.3.1 (POC)

- Fix: clicking a Quick Action button now actually drives Copilot Chat.
  The previous build called `workbench.action.chat.openInEditor` with a
  `{query}` payload that some builds silently ignored. We now try a
  cascade: `chat.open` with `{query, isPartialQuery:false}` →
  `chat.open(query)` → editor variant → focus-then-open, and explicitly
  call `chat.submit` after. On total failure the slash command is
  copied to the clipboard with a *modal* warning so the failure is
  impossible to miss.

## 0.3.0 (POC)

- Apply chrome-hiding settings at **global (user) scope** instead of
  workspace so menu bar, custom title bar, and activity bar actually
  disappear after reload (workspace-scope was getting overridden by
  user defaults).
- Close the **auxiliary (right) side bar** on apply so Copilot's own
  side chat goes away — chat lives only in the editor center now.
- Re-apply the layout silently on every activation so VS Code's
  restored sidebars/panels get closed again after a reopen.
- Prompt the user to reload the window on first apply (required for
  the menu bar to vanish on Windows).
- Add `window.titleBarStyle: 'custom'` + zen-mode hide settings to the
  bundle for tighter chrome control.

## 0.2.0 (POC)

- Chat-only layout: chat opens in the editor area; explorer, menu bar,
  status bar, tabs, activity bar all hidden.
- New right-hand button rail (Webview view in the secondary side bar)
  with seven big buttons mapped to the ESS slash commands
  (`/setup`, `/create`, `/update`, `/scan`, `/flightcheck`,
  `/evaluate`, `/push`) plus quick "re-apply layout" and
  "switch to standard VS Code" controls.
- `ESS Maker: Start Chat-Only Layout` command to re-trigger the
  apply on demand.
- Walkthrough kept as a fallback; the button rail is the primary surface.

## 0.1.0 (POC)

- Initial proof-of-concept.
- Apply / restore maker layout (workspace scope).
- Welcome walkthrough with five big-button steps mapped to ESS slash commands.
- Auto-apply layout + open walkthrough on first activation.
