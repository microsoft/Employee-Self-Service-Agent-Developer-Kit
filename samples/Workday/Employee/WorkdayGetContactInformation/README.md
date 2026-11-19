---
nav_exclude: true
search_exclude: false
---
# View your contact information

This topic retrieves your own work and home phone numbers, email addresses and
addresses from Workday. Try "What is my work phone number?" or "Show my home email."
It returns `finalizedContactInformation` after the contact and address reads.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic),
then [add this scenario](../../#add-a-scenario) using [topic.yaml](./topic.yaml).
Keep employee context, access checks and the existing common-execution topic
configured. Work-contact and work-address templates are supplied by the OOB
configuration; the shared template-config setup topic supplies the home-contact
template.

All three reads run even for a single-field request. If a request fails, inspect
the failing call and local access-check input rather than assuming the requested
field itself is forbidden. You can customize trigger wording and output labels;
preserve the runtime keys and parsed response bindings. Test in a fresh
conversation before publishing.
