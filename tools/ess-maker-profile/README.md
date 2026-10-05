# ESS Maker Profile — POC

A proof-of-concept VS Code experience that provides a **guided, plain-English** surface for the ESS HR/IT admin persona.

> **POC status.** This is an exploratory build to validate the UX direction. It is not productized, not signed, and not intended for customer distribution as-is.

## What it does (v0.4)

In Maker mode, the extension opens the **Agent Developer Kit** rail on the left, a native getting-started walkthrough in the center, and Copilot Chat on the right. The activity bar stays visible, and menus, tabs, and other developer surfaces retain the user's settings.

| Rail panel | Contents |
|---|---|
| **Quick start** | **Tutorial** opens the walkthrough; **Start setup** sends `/setup` and shows connected-agent information after setup completes. |
| **Customization** | The actions below, in display order. Every action is clickable; complete setup before customizing the agent. |
| **Help** | **Documentation** opens the repository documentation. |

| Customization action | Copilot Chat command |
|---|---|
| Create a topic | `/create` |
| Update a topic | `/update` |
| Scan for issues | `/scan` |
| Run a flightcheck | `/flightcheck` |
| Generate tests | `/evaluate` |
| Push to Copilot Studio | `/push` |
| Customize landing page | `/landing-page` |

The walkthrough has **What ADK does** and **Getting started** steps. Setup is user-driven in both modes: select **Start setup**, type `/setup`, or ask Copilot for setup help.

## Layout

| Mode | Layout |
|---|---|
| Maker | Agent Developer Kit rail, native walkthrough, and Copilot Chat; normal VS Code chrome remains available. |
| Developer | Default VS Code layout with a rendered workspace README preview. Revealing the Agent Developer Kit rail opens the guided walkthrough. |

The installer selects the mode in the terminal and writes `essMaker.mode`. The extension reads that setting on each activation. The accepted values are `maker` and `developer`, with `lite` and `standard` supported as compatibility aliases.

## Try it

### Via the one-shot installer (recommended)

These Maker-mode shortcuts install VS Code and the Maker Profile extension:

**Windows** (PowerShell):
```powershell
iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite.ps1)
```

**macOS** (Terminal):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite-mac.sh)"
```

The shared installer (`bootstrap.ps1`/`bootstrap-mac.sh`) supports Maker and Developer modes and installs the extension for both. See the [installation guide](../../setup/README.md) for mode selection and unattended options.

### From source (development)

Requires Node.js 18+ and VS Code 1.86+.

Every extension behavior change must include a version increment in `extension/package.json`, an entry in `extension/CHANGELOG.md`, and a rebuilt `extension/ess-maker-profile-<version>.vsix` in the same PR. Run the extension checks, package the current source, and confirm the archive's manifest version and `extension.js` match the working tree. Remove the superseded VSIX so the installers select the current package. Build each mirrored branch's VSIX from that branch's source to preserve its setup behavior.

```pwsh
cd tools\ess-maker-profile\extension
npm test
npm run validate
npx @vscode/vsce package --no-dependencies
code --install-extension ess-maker-profile-*.vsix --force
```

Or press **F5** from `tools/ess-maker-profile/extension` for an Extension Development Host.

On first activation in Maker mode, the guided layout applies automatically. Run **ESS Maker: Restore Developer Layout** to restore the saved settings, or **Agent Developer Kit: Open guided setup view** to open the guided layout. Set `essMaker.mode` to choose the layout used on subsequent activations.

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
│   └── walkthrough/                   native walkthrough content and topic references
│       ├── overview.md
│       ├── getting-started.md
│       ├── connect.md
│       ├── create-topic.md
│       ├── flightcheck.md
│       ├── scan.md
│       └── push.md
└── test.sh                            POC validation
```

## Known POC gaps

- Layout placement depends on the user's VS Code view positions and restored window state.
- Native tree-view headers and row styling are controlled by VS Code.
- `Ctrl+Shift+P` exposes every VS Code command.
