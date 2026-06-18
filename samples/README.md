---
title: Samples
nav_order: 9
has_children: true
has_toc: false
description: Employee Self-Service samples for Microsoft Copilot Studio
---
# Employee Self-Service Samples

Reference samples for the Microsoft Employee Self-Service (ESS) agent built on Microsoft Copilot Studio. Each folder contains ready-to-use assets — Copilot Studio topic YAMLs, ESS Template Configuration XMLs, and supporting documentation — that customers can import directly into their environment to extend or customize their ESS agent.

> Samples are peer to [`solutions/`](../solutions/) and are intended as reference content, not as a supported product. See [SUPPORT.md](../SUPPORT.md).

## Contents

| Folder | Description |
|--------|-------------|
| [Facilities/](./Facilities/) | Facilities management topics — facilities ticket creation, dining menu lookup, dining station search, guest invitations, and vehicle registration. |
| [ServiceNow/](./ServiceNow/) | ServiceNow integration samples — employee HRSD scenarios such as HR case status lookup. |
| [WorkdayCustomEngineAgent/](./WorkdayCustomEngineAgent/) | Workday HR integration topics for a Custom Engine Agent (CEA) — employee and manager scenarios such as vacation balance, time-off requests, job taxonomy, contact info, education, government IDs, and direct-report views. |
| [WorkdayDeclarativeAgent/](./WorkdayDeclarativeAgent/) | Workday HR integration scenarios packaged for a Declarative Agent (DA) — employee and manager scenarios authored declaratively for Copilot Studio. |

## Using these samples

1. Browse to the folder for the scenario you want to enable.
2. Copy the `topic.yaml` into your Copilot Studio topic catalog and add the accompanying Template Configuration XML to your ESS Template Configuration.
3. Update parameter bindings (employee ID, manager org ID, effective date, etc.) to match your runtime context.
4. Use the trigger queries inside each `topic.yaml` as seed prompts for validation.

## Contributing

See the repo-level [CONTRIBUTING.md](../CONTRIBUTING.md) for the contribution model, scope policy, and validation guide before submitting new samples.
