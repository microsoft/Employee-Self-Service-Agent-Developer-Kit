---
mode: agent
description: "Install Workday OSS topics through an authenticated Copilot Studio browser session"
---

# Import Workday OSS topics

Read `.local/setup/config.json` and `.local/config.json`. If canonical state
does not have `schema_version: 4` and an `agents` entry matching the active
workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/import-oss`, type `/setup` to set up your environment.

and STOP.

Read `src/skills/topics/import-oss/SKILL.md` and follow it exactly. This command
may create only missing Workday OSS `DialogComponent` topics through the
authenticated CDP browser/MinimalBot path. It must not use Computer Use, raw
YAML POSTs, a cached MSAL token, Dataverse mutation, overwrite, delete, publish,
or runtime-test behavior.
