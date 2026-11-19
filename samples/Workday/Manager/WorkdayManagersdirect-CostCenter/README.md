---
nav_exclude: true
search_exclude: false
---
# View direct reports' cost centers

This topic retrieves cost-center information for your direct reports and
presents it as a nested list. Try "Show cost centers for my direct reports."
It does not handle requests about unrelated employees.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic)
and [manager prerequisites](../), then [add this scenario](../../#add-a-scenario)
using [topic.yaml](./topic.yaml). Keep manager status, manager organization and
the existing Workday manager-check and common-execution topics configured.

You can customize trigger wording and output labels; preserve the manager
scope, scenario key and `workdayResponseTable` binding. Verify the template's
case-sensitive cost-center extraction against your tenant response, and test
manager/non-manager behavior in fresh conversations before publishing.
