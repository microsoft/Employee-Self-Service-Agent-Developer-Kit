# Usage analytics for the Employee Self-Service agent

Monitoring the usage analytics of the Employee Self-Service agent should be part of the operational governance so that the agent's health and quality can be optimized continuously for end-users.

There are two approaches in consuming analytics:

1. Service owners or makers systematically monitoring agent usage, effectiveness, quality, and satisfaction. [Learn more](/microsoft-copilot-studio/analytics-overview) about Copilot Studio analytics documentation.
1. Organization leaders review agent usage, satisfaction scores, and other metrics to assess the agent's return on investment. [Learn more](/viva/insights/org-team-insights/copilot-dashboard) about Copilot.

## Measure what matters

Employee Self-Service telemetry is designed to help organizations move beyond basic usage reporting and toward **operational clarity, trust, and continuous improvement**. While Employee Self-Service collects a single, consistent telemetry stream, **different stakeholders interpret that telemetry through different lenses**, depending on the decisions they're responsible for making.

This article explains how to interpret Employee Self-Service telemetry for each stakeholder in your organization, using the same storytelling model that Microsoft's product and engineering teams use internally. This information allows customers and product teams to align on what "good" looks like and what actions to take next.

## One Telemetry, Different lenses

Employee Self-Service telemetry follows a simple but powerful narrative framework:

**Intent > Behavior > Outcome > Action**

This model ensures telemetry is decision-oriented as well as descriptive. The same data answers different questions depending on who is looking at it.

|Story Element |What it means in Employee Self-Service       |
|--------------|---------------------------------------------|
|**Intent**    |What employees are trying to do.             |
|**Behavior**  |How the Employee Self-Service agent is used. |
|**Outcome**   |Business and experience impact.              |
|**Action**    |What should change as a result?              |

## Stakeholder-based interpretation guide

### 1. Executive & Business Leaders

**Primary question**

*Is the Employee Self-Service agent compounding value on scale, and where should we invest next?*
Executives should focus on **outcome-level telemetry**, not raw interaction counts.

**Recommended telemetry signals**

- Active usage and rollout progression	
- Conversion success rate
- Reduction in assisted support
- Trend alignment with business goals (for example, ticket deflection, time saved, productivity gain, employee satisfaction)

**How to interpret**
- Rising usage without corresponding success improvements may indicate trust gaps
- Stable success rates with expanding usage suggest the Employee Self-Service agent is scaling reliably
- Drops in success or spikes in assisted support, signals investment needs

**Typical actions**
- Prioritize funding towards friction areas surfaced by telemetry
- Align Employee Self-Service agent expansion to scenarios with measurable business value

**Common business goals**
- Ticket deflection across implemented business verticals to reduce operational cost
- Time saved / Assisted savings for employees by reducing manual support interactions
- Return on investment (ROI) from Employee Self-Service deployment and expansion
- Sustained adoption beyond pilot phases (trust and repeat usage)	
- Predictable scale without increasing support or incident load

**What to use when**

[Copilot Analytics introduction](/viva/insights/copilot-analytics-introduction#which-tool-should-i-use-when)

### 2. Product/Service Owners

**Primary question**

*What should we fix or improve next to move outcomes – not just metrics?*

Product/service stakeholders focused on each business domain/verticals such as HR, IT, Facilities, etc. should interpret telemetry as **signals of friction**, not performance grades.

**Recommended telemetry signals**

- Scenario-level success and failure patterns
- Drop-off and retry behaviors
- Error and failback indicators
- Evaluation (Eval) regression trends

**How to interpret**
- Concentrated failures often indicate missing configuration, connector gaps, or unclear responses
- Repeated retries imply intent is understood but fulfillment is failing
- Regression after changes indicates quality or performance tradeoffs

**Typical actions**
- Created targeted backlog items (operational guidance, evaluations, fixes)
- Expand evaluation coverage for high-risk scenarios
- Adjust prompts, orchestration, or data sources

**Common business goals**
- Improve conversation success rate for high-volume scenarios
- Reduce deployment and adoption friction detected in telemetry
- Prevent regressions such as prompts, knowledge, or integrations change
- Focus investment on highest-impact scenarios, not vanity metrics

**What to use When**

[Copilot Analytics introduction](/viva/insights/copilot-analytics-introduction#which-tool-should-i-use-when)

[Copilot Studio - Analytics](/microsoft-copilot-studio/analytics-overview)

#### Interpreting Telemetry by verticals
This section is designed to help you operationalize the Employee Self-Service telemetry across your organization by anchoring analytics to real scenarios, clear stakeholder questions, and concrete actions.

***Human Resources (HR)***
**Typical scenarios**
- "How many vacation days do I have left?"
- "When is my next payroll date?"
- "What benefits am I eligible for?"
- "How do I apply for parental leave?"
- "Can I add a dependent to my benefits?"

**HR stakeholders and questions**

|Stakeholder                |Key question                                                   |
|---------------------------|---------------------------------------------------------------|
|**HR Business Owner**      |Are employees getting accurate answers without HR tickets?     |
| **HR Operations**         |Which topics still require manual follow-up?                   |
|**Change & Adoption lead** |Are employees trusting Employee Self-Service for HR questions? |

**Telemetry signals to review for HR**
- Conversation success rate (HR intents).
- Assisted support rate for HR topics.
- Repeated queries or retries on the same HR topic.
- Evaluation (Eval) pass/fail trends for HR scenarios.

**How to interpret HR telemetry**
- **High usage + high success** = The Employee Self-Service agent is deflecting HR tickets effectively.
- **High usage + low success** = Knowledge gaps or response clarity issues.
- **Repeated retries** = Policy ambiguity or missing personalization (user context).
- **Eval regressions** = Risk of inconsistent answers.

**Recommended actions for HR**
- Prioritize Eval coverage for high-volume HR scenarios.
- Improve response specificity for policy-driven questions.
- Align HR telemetry reviews with specific organizational event cadence such as payroll/benefit cycles.
- Track success trends before expanding the Employee Self-Service agent to new HR domains.

***Information Technology (IT)***

**Typical IT scenarios**
- "Reset my password"
- "Unlock my account"
- "Request access to an application"
- "Install approved software"
- "Check my device compliance status"

**IT Stakeholders & Questions**

|**Stakeholder**      |**Key Question**                                                                |
|---------------------|--------------------------------------------------------------------------------|
|**IT Service Owner** |Is the Employee Self-Service agent reducing ticket volume for common IT issues? |
|**IT Operations**    |Are failures due to configuration or platform issues?                           |
|**Security**         |Are requests handled securely and consistently?                                 |

**Telemetry signals to review for IT**
- Ticket deflection indicators
- Error and fallback rates
- Connector and dependency health
- Latency and timeout signals for IT actions

**How to interpret IT Telemetry**
- **Low assisted support + high completion** = Effective IT self-service
- **Errors clustered by scenarios** = Configuration or connector issues
- **Latency spikes** = Throttling, dependency, or orchestration bottlenecks
- **Security-related fallbacks** = policy misalignment

**Recommended actions for IT**
- Focus telemetry reviews on top ticket-deflecting scenarios
- Use diagnostics to distinguish config issues vs. product gaps
- Validate performance telemetry before scaling rollout
- Pair telemetry with readiness and Application Lifecycle Management (ALM) checks for production moves

***Facilities & Workplace services***
**Typical Workplace scenarios**
- "Report a facilities issue"
- "Request building access"
- "Find office policies or amenities"
- "Book a workspace or room"
- "Check office hours or closures"

**Facilities Stakeholders & Questions**

|**Stakeholder**          |**Key Question**                                                         |
|-------------------------|-------------------------------------------------------------------------|
|**Workplace Operations** |Are facilities requests resolved without manual triage?                  |
|**Facilities Managers**  |Which requests still require human intervention?                         |
|**Employee Experience**  |Is the Employee Self-Service agent improving day to day workplace trust? |

**Telemetry signals to review for facilities**
- Scenario completion vs. handoff rates
- Repeated questions about the same facility topic
- Time-to-resolution proxies
- Satisfaction indicators (thumps up/down, sentiment)

**How to interpret facilities telemetry**
- **High completion + low retries** = Clear guidance and fulfillment
- **Repeated queries** = Outdated or unclear facilities content
- **Frequent handoffs** = Integration or workflow gaps
- **Negative sentiment** = Experience or clarity issues

**Recommended actions for facilities**
- Improve knowledge freshness and clarity
- Identify top "must-be-right" facilities scenarios for evals
- Use telemetry to justify integration investments
- Track sentiment trends as a proxy for workplace trust

### 3. IT Administrators & Makers ###
**Primary question**

*Is the Employee Self-Service agent configured correctly, stable, and ready to scale?*
Administrators and Makers should interpret telemetry as **health and readiness indicators**, not adoption metrics

**Recommended telemetry signals**
- Error rates and configuration warnings
- Connector and dependency health
- Performance and latency indicators
- ALM and environment readiness signals

**How to interpret**

- Persistent errors usually indicate misconfiguration or environment issues
- Latency spikes suggest throttling, dependency, or orchestration issues
- Clean telemetry during pilots increases confidence to expand rollout

**Typical actions**

- Address configuration or dependency gaps
- Validates environments before promoting to production
- Coordinate changes using ALM and readiness checks

**What to use When**

[Copilot Studio - Analytics](/microsoft-copilot-studio/analytics-overview)

[Capture telemetry with Application Insights](/microsoft-copilot-studio/advanced-bot-framework-composer-capture-telemetry)

## Employee Self-Service analytics and evaluations: A unified playbook to accelerate time-to-value (TTV)

### Why combine telemetry and evaluations?

Telemetry and evaluations solve different (but complementary) problems:
- Telemetry tells you what is happening in real usage - what employees are trying to do, what they do, and what outcomes are being produced.
- Evaluations (evals) tell you whether the agent behaves the way you expect – accurately, consistently, and safely, using repeatable, automated test cases that help validate improvements and catch regressions.

When used together, they create a practical loop:

- Telemetry identifies where to focus > Evaluations verify quality and prevent regressions > Telemetry confirm impact at scale > repeat.

This loop is what accelerates TTV: you don't "*look at dashboards*" or "*run tests*," you continuously turning signals into actions.

The shared operating model:

**'Intent ➡️ Behavior ➡️ Outcome ➡️ Action'**

Evals plug into the same model by providing repeatable evidence about whether the agent can reliably deliver the intended outcomes before you expose the change to broad employee usage.

[Learn more](/microsoft-copilot-studio/analytics-overview)
