---
nav_exclude: true
search_exclude: false
---
# View your government IDs

This topic reads government-ID information from your own Workday profile.
Try "Show my government IDs." It is a personal-record lookup, not guidance about
applications, renewals or immigration policy.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic),
then [add this scenario](../../#add-a-scenario) using [topic.yaml](./topic.yaml).
Keep employee context, common execution and reference-data refresh configured.
The topic returns `finalizedResponseTableData`.

You can customize trigger wording and the displayed fields without changing
runtime keys or parser bindings. Use approved test records, respect your
organization's handling rules for sensitive identifiers, and verify empty-result
and access behavior in fresh conversations before publishing.
