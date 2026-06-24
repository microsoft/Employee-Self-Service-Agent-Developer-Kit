# ESS Maker — VS Code extension

Proof-of-concept VS Code extension that delivers a chat-first, low-chrome experience for customizing the Microsoft Employee Self-Service (ESS) agent.

See `../README.md` for the full context. To try it locally:

```pwsh
npm install
code --extensionDevelopmentPath=. ..\..\..
```

Or open this folder in VS Code and press **F5**.

## Commands

| Command | What it does |
|---|---|
| `ESS Maker: Apply Maker Layout` | Hide developer chrome (workspace scope). |
| `ESS Maker: Restore Standard Layout` | Revert. |
| `ESS Maker: Open Welcome Walkthrough` | Re-open the welcome page. |
| `ESS Maker: Connect to environment` | Opens Copilot Chat with `/setup`. |
| `ESS Maker: Create a topic` | Opens Copilot Chat with `/create`. |
| `ESS Maker: Scan for issues` | Opens Copilot Chat with `/scan`. |
| `ESS Maker: Validate readiness (FlightCheck)` | Opens Copilot Chat with `/flightcheck`. |
| `ESS Maker: Push to Copilot Studio` | Opens Copilot Chat with `/push`. |
