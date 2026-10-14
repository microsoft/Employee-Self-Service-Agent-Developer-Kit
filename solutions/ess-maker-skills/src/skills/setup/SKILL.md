<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Hybrid Workday Extension Setup

This file is only the boundary for an explicit request to configure the retired
hybrid Workday extension. It is **not** the entry point for `/connect workday`
or `/connect-workday`.

If this file is reached from either Workday connect command, immediately read
`src/skills/connect/SKILL.md` and follow its architecture-aware routing. Stop
processing this file; do not show the hybrid-unavailable message below.

Hybrid Workday keeps its flows, connections, plugins, template
configurations, and environment configuration in a separately owned
Dataverse-backed extension while the agent itself uses the DA-GA platform.

The extension's installation, logical-action bridge, identity handoff, and
readiness contract are not implemented in this release.

**Message:**

Hybrid Workday extension setup is not available in this release. Your DA-GA
agent setup is unchanged, and no Dataverse environment, solution, connection,
or flow was modified.

Use `/connect workday` to connect Workday to a supported ESS HR agent.

**End message.**

Then stop. Do not run the retained Workday setup playbooks, foundation setup,
solution installation, connection binding, flow registration, or preferred
solution configuration.
