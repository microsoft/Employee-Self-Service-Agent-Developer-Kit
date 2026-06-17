# ESS Maker Profile — POC

A proof-of-concept VS Code experience that strips the editor down to a **chat-first, big-button** surface for the ESS HR/IT admin persona.

> **POC status.** This is an exploratory build to validate the UX direction. It is not productized, not signed, and not intended for customer distribution as-is.

## What it does (v0.4)

When the extension activates inside the ESS Maker workspace it:

1. **Hides every developer surface** — activity bar, status bar, editor tabs, minimap, breadcrumbs, layout controls, menu bar, command center, custom title bar, and bottom panel.
2. **Opens GitHub Copilot Chat in the editor area** — chat lives in the center of the window, not tucked into a side panel.
3. **Pins a "Quick actions" button rail in the primary sidebar** — a custom Webview view with big icon-labeled buttons:
   - **Connect** → `/setup`
   - **Create a topic** → `/create`
   - **Update a topic** → `/update`
   - **Scan for issues** → `/scan`
   - **Run a flightcheck** → `/flightcheck`
   - **Generate tests** → `/evaluate` (gated on flightcheck)
   - **Push to Copilot Studio** → `/push` (gated on flightcheck)
   - plus: *View tutorial*, *Switch to standard VS Code / lite mode*
4. **Routes every button click into Copilot Chat** with the slash command pre-filled.
5. **Provides a "View tutorial"** button that opens a custom webview panel beside chat explaining how each button works.

The customer never sees code, a file tree, or a menu. The whole window is: **chat in the center, big buttons on the left**.

## Layout

| Stock VS Code | ESS Maker (lite mode) |
|---|---|
| Menu bar, activity bar, file tree, editor tabs, status bar | Chat fills the editor area; "Quick actions" button rail on the left; everything else hidden |

## Try it

### Via the one-shot installer (recommended)

The lite mode installer installs VS Code + the Maker Profile extension:

**Windows** (PowerShell):
```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite.ps1)
```

**macOS** (Terminal):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite-mac.sh)"
```

The standard installer (`bootstrap.ps1` / `bootstrap-mac.sh`) does NOT install the Maker Profile — it uses stock VS Code with `code chat /setup`.

### From source (development)

Requires Node.js 18+ and VS Code 1.86+.

```pwsh
cd tools\ess-maker-profile\extension
npx @vscode/vsce package --no-dependencies
code --install-extension ess-maker-profile-*.vsix --force
```

Or press **F5** from `tools/ess-maker-profile/extension` for an Extension Development Host.

On first activation the maker layout auto-applies. To restore the standard workbench, click "Switch to standard mode" in Quick Actions or run **ESS Maker: Restore Standard Layout** from the command palette.

## What's in the box

```
tools/ess-maker-profile/
├── README.md                          this file
├── ess-maker.code-profile             standalone VS Code profile export
├── settings.json                      reference settings (also applied programmatically)
├── extension/
│   ├── package.json                   command + view container contributions
│   ├── extension.js                   activation, layout, tutorial, slash-command bridge
│   ├── CHANGELOG.md
│   ├── .vscodeignore
│   ├── ess-maker-profile-*.vsix       pre-built extension package
│   └── walkthrough/                   (legacy reference — not used by extension)
│       ├── overview.md
│       ├── connect.md
│       ├── create-topic.md
│       ├── flightcheck.md
│       ├── scan.md
│       └── push.md
└── test.sh                            POC validation
```

## Known POC gaps

- The native OS title bar still shows on Windows until a window reload.
- The Webview view header ("Quick actions") is rendered by VS Code and cannot be styled away.
- `Ctrl+Shift+P` still surfaces every VS Code command.
- On the very first launch (before reload), Quick Actions may flash briefly as VS Code routes the view.
