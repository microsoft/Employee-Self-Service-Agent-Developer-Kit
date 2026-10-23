---
nav_exclude: true
search_exclude: false
---
# View direct reports' job taxonomy

This topic reads job-function, family, profile and title information for your
direct reports. Try "Show my direct reports' job titles and job profiles."
It presents `workdayResponseTable` as a nested list and does not authorize a
lookup for an unrelated employee.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic)
and [manager prerequisites](../), then [add this scenario](../../#add-a-scenario)
using [topic.yaml](./topic.yaml). Keep manager context, manager checks, reference
data and common execution configured.

You can customize trigger wording and field labels without changing the manager
scope or runtime bindings. Verify reference-data resolution and manager/non-manager
behavior in fresh conversations before publishing.
