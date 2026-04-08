# Make Your Employee Self-Service Agent Multilingual

This article explains **two supported ways** to enable multilingual experiences in the Employee Self-service (ESS) agent:

- **Browser based localization** (recommended for most customers)
- **Dynamic Language Switching** (advanced configuration)

Both approaches are supported today. The right choice depends on your rollout goals, complexity tolerance, and cost considerations.

## Supported Languages in Copilot Studio

Employee Self-Service is built on Copilot Studio, which means it inherits the same **language support and localization capabilities** available in Copilot Studio.

Copilot Studio currently supports **dozens of languages**, including many Tier 1 and Tier 2 languages commonly required for global deployments.

We recommend reviewing the official, up-to-date documentation: [**Copilot language support**](/microsoft-copilot-studio/authoring-language-support)

Because Employee Self-Service is a custom agent built on Copilot Studio, the languages listed in that article represent the **maximum language coverage Employee Self-Service can support**, subject to the configuration approach and known limitations described in this article.

## Option 1: Browser Based Localization (Recommended)

### What is Browser Based Localization?

The Employee Self-Service agent automatically responds in the **same language as the user’s browser**.

### How Browser Based Localization works

- The user’s browser language determines the response language.
- Employee Self-Service responds automatically in the user’s browser language **only if that language is configured as a supported secondary language** in Copilot Studio.
- If the user’s browser language is **not** included as a supported secondary language, Employee Self-Service defaults to **English**.
- Employee Self-Service UI surfaces are localized automatically.

### When to use this approach

This approach works best when:

- You’re okay with users setting or changing their browser language to their preferred language.
- You want the **simplest setup**.
- You’re supporting **large or global audiences**.

### How to configure

#### Add languages to an agent

1. Go to the **Settings** page for the agent and select **Languages**.
2. Select **Add languages**.
3. In the **Add languages** panel, select the languages you want to add to the agent, and select **Add**.
4. Review the list of languages and close the **Settings** page.
5. Publish the agent.

#### Translate agent strings into your agents’ secondary languages (optional)

In Copilot Studio, you perform all topic and content editing in the agent's primary language. This section explains how to [download strings from your agent and translate them into your agent's secondary languages](/microsoft-copilot-studio/multilingual#manage-localization-for-a-multilingual-agent). Once you upload the translated strings, you can [switch the language in the test panel](/microsoft-copilot-studio/multilingual#test-a-multilingual-agent) and verify that conversations in the secondary languages also flow as expected.

**_If you make changes to the primary language strings, you must also update the content in the secondary languages. This process includes both new content and modified content. Incremental changes aren't automatically translated._**

After you complete these steps and publish your agent, Employee Self-Service automatically responds in the user’s browser language.

## Option 2: Dynamic Language Switching

### What is Dynamic Language Switching

Dynamic Language Switching allows Employee Self-Service to respond in the **same language as the user’s input**, even if the user changes languages in mid-conversation.

### How Dynamic Language Switching works

- A **custom topic** is configured to detect the user’s language at runtime using AI.
- The detected language is used to guide how responses are generated for the remainder of the conversation or turn.
- Enables the agent to **switch languages mid-conversation**, independent of the user’s browser language.

### Important clarification

Dynamic Language Switching **does not work by default**. Makers must explicitly add all supported secondary languages to the agent and **configure the custom topic** for language detection for this behavior to occur.

If a user’s language isn't added as a secondary language, Employee Self-Service defaults to English, even if the custom topic detects that language.

⚠️ **Cost consideration**

Dynamic Language Switching relies on AI prompts to detect and route language. These prompts can incur usage charges for users who aren't licensed. Customers should factor these charges into their cost and scale planning when choosing this approach.

### When to use this functionality

This approach may be appropriate if:

- Users frequently switch languages mid-conversation.
- Browser language doesn't reliably reflect the user’s preferred language, or the browser-based setup doesn't work for your organization.
- Your users are mostly licensed, or you’re comfortable with the cost implications for unlicensed users.
- You’re okay with ongoing testing and maintenance for this setup.

### How to configure

[**Set up an agent for Dynamic Language Switching**](/microsoft-copilot-studio/multilingual)

## Quick Reference: Which Option Should I Choose?

| **Scenario** | **Recommended Approach** |
|--------------|--------------------------|
| Large global rollout | Browser based localization |
| Minimal setup and maintenance | Browser based localization |
| No custom topic management | Browser based localization |
| Users switch languages midchat | Dynamic Language Switching |
| Browser language is unreliable | Dynamic Language Switching |
| Fine-grained language control needed | Dynamic Language Switching |

## Known Limitations to Consider

| **Area** | **Limitation** | **Applies To** | **Help Article** |
|---------|---------------|---------------|------------------|
| Custom Content | In Copilot Studio, you perform all topic and content editing in the agent's primary language (English). To localize your content, you have to download your agents strings and translate them into your agent’s secondary languages. | Both | [Preparing localized content](/microsoft-copilot-studio/multilingual) |
| Adaptive cards | Localization files don't include mixed-typed strings from Adaptive Cards. If you need to localize an Adaptive Card where a string can include both static text and variables (dynamic content), use the following workaround. | Both | |
| Multi-agent | If using multi-agent, dynamic language topic must be configured at the parent and sub-agent level.| Dynamic Language Switching | [Set up an agent for Dynamic Language Switching](/microsoft-copilot-studio/multilingual) |
| Starter prompts | Starter prompts aren’t localized by default with these setups. Makers need to manually author them in each secondary language directly in the Copilot Studio authoring canvas. | Both | |
| Language quality variability | Some languages were tested to work reliably in Employee Self-Service, but you may observe response quality or formatting issues with **Chinese, Japanese, and Korean** due to underlying Large Language Model (LLM). We recommend validating these languages in a pilot before including them in a full rollout. | Both | |
| Costs | Language detection uses AI prompts and may incur usage costs for unlicensed users. | Dynamic Language Switching | [Set up an agent for Dynamic Language Switching](/microsoft-copilot-studio/multilingual) |
| Ongoing maintenance | Custom language topics must be maintained and tested over time. | Dynamic Language Switching | [Set up an agent for Dynamic Language Switching](/microsoft-copilot-studio/multilingual) |

## Recommendation

For most customers, **browser-based localization** provides the best balance of simplicity, scale, and reliability. Dynamic Language Switching should be reserved for advanced scenarios where browser language doesn't meet user needs.

If you’re unsure which approach is right for your deployment, start with browser based localization and validate with a pilot group before introducing more complexity.

## Next Steps

- Review your target user languages.
- Decide which localization approach aligns with your rollout goals.
