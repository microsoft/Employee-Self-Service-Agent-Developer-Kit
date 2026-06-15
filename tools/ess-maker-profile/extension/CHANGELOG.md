# Changelog

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
