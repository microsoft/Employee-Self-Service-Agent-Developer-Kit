# ESS Maker — VS Code extension

Proof-of-concept VS Code extension that delivers a guided rail, native walkthrough, and Copilot Chat experience for customizing the Microsoft Employee Self-Service (ESS) agent.

See `../README.md` for the full context. To try it locally:

```pwsh
npm install
code --extensionDevelopmentPath=. ..\..\..\solutions\ess-maker-skills
```

The development host must open `solutions\ess-maker-skills` as its workspace
root so the kit prompts and instructions are active.

## Commands

| Command | What it does |
|---|---|
| `Agent Developer Kit: Open guided setup view` | Open the Agent Developer Kit rail, walkthrough, and Copilot Chat. |
| `ESS Maker: Restore Developer Layout` | Restore the saved VS Code layout settings. |
| `ESS Maker: View Tutorial` | Open the native getting-started walkthrough. |
| `ESS Maker: Connect to environment` | Opens Copilot Chat with `/setup`. |
| `ESS Maker: Create a topic` | Opens Copilot Chat to draft, preview, and approve a topic save. |
| `Agent Developer Kit: Modify a topic` | Opens Copilot Chat to read, preview, and approve a mapped topic update. |
| `ESS Maker: Scan for issues` | Opens Copilot Chat with `/scan`. |
| `ESS Maker: Validate readiness (FlightCheck)` | Opens Copilot Chat with `/flightcheck`. |
| `ESS Maker: Push to Copilot Studio` | Opens Copilot Chat with `/push`. |

In the **Customization** tree, **Customize landing page** appears immediately after **Push to Copilot Studio** and opens `/landing-page`. All Customization actions are clickable; complete setup before customizing the agent. Setup is user-driven in both Maker and Developer modes.

Topic authoring uses ordinary local YAML drafts followed by separately approved saves to the selected editable Dev agent. Creation saves one inactive topic; updates preserve the selected identity, active state, and unrelated behavior. Matching instruction changes have separate previews and approvals. Neither operation activates or publishes. Power Automate authoring remains outside ADK; conversation testing depends on the installed bounded capability and topic readiness.
