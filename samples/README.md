---
title: Samples
nav_order: 9
has_children: true
has_toc: false
description: Employee Self-Service samples for Microsoft Copilot Studio
---
# Employee Self-Service Samples

Reference samples for the Microsoft Employee Self-Service (ESS) agent built on Microsoft Copilot Studio. Each folder contains topic YAMLs, integration configuration, and supporting documentation that you can import into your environment. Workday DA GA includes a shared template-config setup topic.

> Samples are peer to [`solutions/`](../solutions/) and are intended as reference content, not as a supported product. See [SUPPORT.md](../SUPPORT.md).

## Contents

| Folder | Description |
|--------|-------------|
| [Facilities/](./Facilities/) | Facilities management topics — facilities ticket creation, dining menu lookup, dining station search, guest invitations, and vehicle registration. |
| [ServiceNow/](./ServiceNow/) | ServiceNow integration samples — employee HRSD scenarios such as HR case status lookup. |
| [Workday/](./Workday/) | DA GA Workday employee and manager scenarios with a shared template-config setup topic. |

## Using these samples

1. Browse to the folder for the scenario you want to enable.
2. Follow the scenario's configuration instructions. For Workday DA GA, configure the [shared template-config setup topic](./Workday/#set-up-the-shared-configuration-topic) once, then copy the selected `topic.yaml` into your agent.
3. Update parameter bindings (employee ID, manager org ID, effective date, etc.) to match your runtime context.
4. Use the trigger queries inside each `topic.yaml` as seed prompts for validation.

## Contributing

See the repo-level [CONTRIBUTING.md](../CONTRIBUTING.md) for the contribution model, scope policy, and validation guide before submitting new samples.
