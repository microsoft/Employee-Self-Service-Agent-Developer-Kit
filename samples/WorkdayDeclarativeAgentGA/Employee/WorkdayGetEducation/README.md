---
nav_exclude: true
search_exclude: false
---
# View your education

This topic reads your own education history from Workday, including school,
degree and field of study. Try "Show my education details" or "What was my field
of study?" It does not answer tuition-reimbursement or training-policy questions.

Configure the [shared template-config setup topic](../../#set-up-the-shared-configuration-topic),
then [add this scenario](../../#add-a-scenario) using [topic.yaml](./topic.yaml).
Keep employee context, common execution and reference-data refresh configured.
The topic resolves reference values and returns `FinalizedEducationData`.

You can customize trigger wording and displayed labels; retain the template key
and response schema. Check populated and empty education records in fresh
conversations before publishing.
