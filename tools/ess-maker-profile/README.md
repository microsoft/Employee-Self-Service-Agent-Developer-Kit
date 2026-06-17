# ESS Maker Profile — POC

A proof-of-concept VS Code experience that strips the editor down to a **chat-first, big-button** surface for the ESS HR/IT admin persona. This is the implementation of **Option A** from [`docs/proposals/ess-maker-streamlined-experience.md`](../../docs/proposals/ess-maker-streamlined-experience.md).

> **POC status.** This is an exploratory build to validate the UX direction. It is not productized, not signed, and not intended for customer distribution as-is.

## What it does (v0.2 — chat-only)

When the extension activates inside the ESS Maker workspace it:

1. **Hides every developer surface we can** — activity bar, status bar, editor tabs, minimap, breadcrumbs, layout controls, panel buttons, **menu bar, command center, custom title bar, sidebar, and bottom panel**. The file explorer and code editor are never visible.
2. **Opens GitHub Copilot Chat in the editor area** — chat lives in the center of the window, not tucked into a side panel.
3. **Pins a "Quick actions" button rail in the secondary side bar** — a custom Webview view with big icon-labeled buttons for every common ESS task:
   - **Connect** → `/setup`
   - **Create a topic** → `/create`
   - **Add a knowledge source** → `/scan`
   - **Validate readiness** → `/flightcheck`
   - **Push to Copilot Studio** → `/push`
   - plus secondary controls: *Re-apply chat-only layout*, *Switch to standard VS Code*
4. **Routes every button click into Copilot Chat** with the slash command pre-filled, so the user lands in the conversation immediately.

The customer never sees code, a file tree, or a menu. The whole window is: **chat in the center, big buttons on the right**.

## Layout (before / after)

| Stock VS Code | ESS Maker POC (v0.2) |
|---|---|
| Menu bar, activity bar, file tree, editor tabs, status bar, problems panel; chat tucked in a side panel | Chat fills the center of the editor area; "Quick actions" button rail on the right; everything else hidden |

## Try it

### Via the one-shot installer (recommended)

The easiest way to get the Maker Profile is to use the lite mode installer:

**Windows** (PowerShell):
```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite.ps1)
```

**macOS** (Terminal):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite-mac.sh)"
```

### From source (development)

Requires Node.js 18+ and VS Code 1.86+.

```pwsh
cd tools\ess-maker-profile\extension
npm install
# Launch a new Extension Development Host:
code --extensionDevelopmentPath=. ..\..\..
```

Or from inside VS Code: open `tools/ess-maker-profile/extension` and press **F5**.

On first activation in any workspace the maker layout auto-applies. To restore the standard workbench, run the command **ESS Maker: Restore Standard Layout** from the command palette (`Ctrl+Shift+P`).

## What's in the box

```
tools/ess-maker-profile/
├── README.md                          this file
├── ess-maker.code-profile             standalone VS Code profile export
├── settings.json                      reference settings (also applied programmatically)
├── extension/
│   ├── package.json                   walkthrough + command contributions
│   ├── extension.js                   activation, layout apply/restore, slash-command bridge
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── .vscodeignore
│   └── walkthrough/
│       ├── overview.md
│       ├── connect.md
│       ├── create-topic.md
│       ├── flightcheck.md
│       ├── scan.md
│       └── push.md
└── test.sh                            POC validation
```

## What it intentionally does NOT do

- Does not bundle or modify the Copilot Chat extension. It just invokes `workbench.action.chat.open` with a pre-filled query.
- Does not ship the ESS skill content (topic templates, MCP configs). The POC assumes the maker workspace already has them.
- Does not handle Marketplace publishing, signing, telemetry, or settings sync.
- Does not replace the proposal in `docs/proposals/` — that doc captures the full strategy; this is one step of the recommended sequencing.

## Known POC gaps

- The native OS title bar still shows on Windows. Truly removing it requires a custom workbench (Option E in the proposal) or running VS Code with `--no-title-bar` style switches not exposed in stable.
- The Webview view header ("Quick actions") is rendered by VS Code and cannot be styled away without forking.
- Auto-applied layout is **workspace-scoped**, so the user reverts to their normal layout when they open a non-ESS folder. Good for the POC; production should consider a dedicated profile.
- `Ctrl+Shift+P` still surfaces every VS Code command. Hiding it requires building a custom workbench (Option E).
- The button rail uses Copilot Chat's `{query}` pre-fill behavior. On VS Code builds where that payload isn't honored, the slash command is copied to the clipboard as a fallback and the user pastes into chat.

## Next steps if we pursue this

1. Demo to ESS leads + a friendly customer to validate the UX direction.
2. Add the walkthrough icons and screenshots (placeholders today).
3. Wire up the standalone `ess-maker.code-profile` import path in the existing bootstrap script.
4. Telemetry: which buttons get clicked, where users drop off in the walkthrough.
5. Decide whether to invest in Option E based on what we learn.
