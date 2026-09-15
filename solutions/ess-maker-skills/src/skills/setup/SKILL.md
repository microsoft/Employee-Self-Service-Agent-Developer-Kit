<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Hybrid Workday Extension Setup

Hybrid Workday keeps its flows, connections, plugins, template
configurations, and environment configuration in a separately owned
Dataverse-backed extension while the agent itself uses the DA-GA platform.

The extension's installation, logical-action bridge, identity handoff, and
readiness contract are not implemented in this release.

**Message:**

Hybrid Workday extension setup is not available in this release. Your DA-GA
agent setup is unchanged, and no Dataverse environment, solution, connection,
or flow was modified.

If a hybrid Workday extension is already configured and its Dataverse endpoint
is recorded in this workspace, `/backup-template-configs` and
`/restore-template-configs` remain available for its reference-data
customisations.

**End message.**

Then stop. Do not run the retained Workday setup playbooks, foundation setup,
solution installation, connection binding, flow registration, or preferred
solution configuration.
