---
nav_exclude: true
search_exclude: false
---
# View direct reports' service anniversaries

This topic retrieves upcoming service anniversaries for your direct reports.
Try "What are the upcoming service anniversaries of my direct reports?" or
"Show my team's service anniversaries next month." The response is a table with
employee name, hire date, anniversary date and upcoming milestone.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic)
and [manager prerequisites](../), then [add this scenario](../../#add-a-scenario)
using [topic.yaml](./topic.yaml). Keep manager context and the existing manager-check
and common-execution topics configured.

You can customize trigger wording and table labels while retaining the `response`
binding and manager scope. Verify date filtering, empty results and non-manager
behavior in fresh conversations before publishing.
