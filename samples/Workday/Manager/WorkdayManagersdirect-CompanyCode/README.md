---
nav_exclude: true
search_exclude: false
---
# View direct reports' company codes

This topic retrieves company codes and company names for your direct reports
and presents them as a nested list. Try "What are the company codes for my
direct reports?" It is not a lookup for peers or your own company code.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic)
and [manager prerequisites](../), then [add this scenario](../../#add-a-scenario)
using [topic.yaml](./topic.yaml). Keep manager status, manager organization and
the existing Workday manager-check and common-execution topics configured.

You can customize trigger wording and list labels while retaining the manager
scope, scenario key and `workdayResponseTable` binding. Validate manager and
non-manager behavior in fresh conversations before publishing.
