---
nav_exclude: true
search_exclude: false
---
# Give peer feedback

This topic asks for a colleague's employee ID and your feedback text, then
submits the feedback through the existing Workday common-execution topic.
Try "Give feedback about a colleague."

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic),
then [add this scenario](../../#add-a-scenario) using [topic.yaml](./topic.yaml).
Keep authenticated employee context and the existing Workday integration
configured.

You can customize the questions and trigger wording while preserving the
sender/recipient parameter bindings. The sample submits after collecting the
feedback; it does not add a separate confirmation step. Use only an approved
test recipient and feedback when validating submission behavior before publishing.
