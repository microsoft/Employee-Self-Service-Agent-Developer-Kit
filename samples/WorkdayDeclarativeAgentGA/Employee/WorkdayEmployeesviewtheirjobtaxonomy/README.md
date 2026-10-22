---
nav_exclude: true
search_exclude: false
---
# View your job taxonomy

This topic retrieves your own job function, family, profile and title information
from Workday. Try "What is my job profile?" or "What is my external title?"
It is not a general policy or organization-structure lookup.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic),
then [add this scenario](../../#add-a-scenario) using [topic.yaml](./topic.yaml).
Keep employee context and the existing Workday execution and access-check topics
configured. The topic returns `jobFunctionData` for the response.

You can customize trigger wording and the presentation of returned fields without
changing the scenario key or runtime bindings. Test your own records and an
out-of-scope request in fresh conversations before publishing.
