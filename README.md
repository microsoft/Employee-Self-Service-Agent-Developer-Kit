# Employee Self-Service Agent Developer Kit

A monorepo of solutions, samples, and tooling for the Microsoft Employee Self-Service (ESS) agent built on Microsoft Copilot Studio.

> **This repo is intended as an example or learning tool.** It is not a Microsoft product or a supported service. See [SUPPORT.md](SUPPORT.md) for the support model and [SECURITY.md](SECURITY.md) for reporting security issues.

## Solutions

| Solution | Description |
|----------|-------------|
| [`solutions/ess-maker-skills/`](solutions/ess-maker-skills/) | VS Code workspace toolkit. Customize and deploy your ESS agent using GitHub Copilot — no deep platform knowledge required. |

Additional solutions (FlightCheck standalone, evaluation harnesses, etc.) will be added under `solutions/` over time.

## Samples

Reference content used directly by customers — topic YAMLs, template-config XMLs, evaluation test sets, and integration walkthroughs — lives at the root under [`samples/`](samples/), peer to `solutions/`. Samples are first-class reference resources, not implementation details of any single solution.

## Repository structure

```
.github/                Repo-level CI, CodeQL, Dependabot, issue templates, labels
solutions/
  ess-maker-skills/     VS Code workspace toolkit (scripts, prompts, MCP servers)
samples/                Reference topics, template configs, evaluation test sets (peer to solutions/)
LICENSE                 MIT
SECURITY.md             Microsoft MSRC reporting path
CODE_OF_CONDUCT.md      Microsoft Open Source Code of Conduct
CONTRIBUTING.md         Contribution guide, maintenance, privacy posture, validation
SUPPORT.md              Support model
```

## Contributing

This project welcomes contributions and suggestions. Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit https://cla.microsoft.com.

Please read our [Contributing Guide](CONTRIBUTING.md) for the full contribution model, security maintenance commitments, scope management policy, privacy posture, and validation guide.

## License

This project is licensed under the [MIT License](LICENSE).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos are subject to those third-party's policies.
