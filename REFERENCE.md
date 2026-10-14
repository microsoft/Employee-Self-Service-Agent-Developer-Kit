# Reference

Additional detail about this repo that isn't needed to get started. For installation and the quick start, see the [README](README.md).

## Samples

Reference content used directly by customers — topic YAMLs, template-config XMLs, evaluation test sets, and integration walkthroughs — lives at the root under [`samples/`](samples/), peer to `solutions/`. Samples are first-class reference resources, not implementation details of any single solution.

## Repository structure

```
.github/                Repo-level CI, CodeQL, Dependabot, issue templates, labels
solutions/
  ess-maker-skills/     Maker kit — customize your ESS agent in VS Code with Copilot
  ess-flightcheck/      (planned) Standalone deployment-readiness validator
samples/                Reference topics, template configs, evaluation test sets (peer to solutions/)
LICENSE                 MIT
SECURITY.md             Microsoft MSRC reporting path
CODE_OF_CONDUCT.md      Microsoft Open Source Code of Conduct
CONTRIBUTING.md         Contribution guide, maintenance, privacy posture, validation
SUPPORT.md              Support model
```

## Telemetry

The ESS Maker Skills CLI collects pseudonymous usage telemetry (enabled by
default) to help improve the product. No developer identity, agent content, or
personal data is collected.

**To opt out**, run either of the following (both are persistent and take effect immediately):

```bash
# 1. From the solutions/ess-maker-skills directory:
python scripts/adk_telemetry.py off

# 2. Or set the ESS_ADK_TELEMETRY environment variable to off (any shell / CI).
#    Syntax varies by shell — set it before running any ADK command.
```

Setting `ESS_ADK_TELEMETRY=off` inline before a command works in bash / zsh
(`ESS_ADK_TELEMETRY=off python scripts/...`). To persist it, add it to your
shell profile:

```bash
# bash / zsh (~/.bashrc, ~/.zshrc):
export ESS_ADK_TELEMETRY=off
```

```powershell
# PowerShell ($PROFILE) — persistent:
$env:ESS_ADK_TELEMETRY = "off"
# ...or for the current session only, run the same line at the prompt.
```

```cmd
:: cmd.exe — current session only:
set ESS_ADK_TELEMETRY=off
:: For persistence use setx ESS_ADK_TELEMETRY off (takes effect in new shells).
```

The env var overrides the config-file setting.

Re-enable later with `python scripts/adk_telemetry.py on` or by unsetting the
env var. See
[Telemetry & Privacy](solutions/ess-maker-skills/README.md#telemetry--privacy)
for the full data model and event catalog.
