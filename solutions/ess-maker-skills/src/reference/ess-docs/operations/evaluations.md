# Response quality evaluations for the Employee Self-Service agent

Microsoft Copilot Studio has an evaluation tool that enables automated testing for agent response output quality. Unlike [testing in the chat pane](/microsoft-copilot-studio/authoring-test-bot), the agent evaluation tool runs repeatable, scenario-based test sets using different user profiles without requiring manual testing of each prompt. [Learn more about the evaluation tool](/microsoft-copilot-studio/analytics-agent-evaluation-intro).

How to get started:

- Start by learning about evaluations as a process and a skill set
- Next, learn more about how to create a custom evaluations strategy for your Employee Self-Service agent
- Then, get started using evaluation tooling, test sets, and learn how to think about measuring different pieces of the Employee Self-Service experience

> [!NOTE]
> - The evaluation tool can't review content inside of adaptive cards yet.
> - The evaluation tool doesn't measure latency, or how quickly the agent responds.
> - You need edit access to Copilot Studio to run tests. Test results can be shared with people who don't have access to Copilot Studio by exporting test results.

## Why invest in evaluations for your agent?

Agent evaluations, also called evals, are a new way to measure how a generative agent behaves and responds as it uses your organization's knowledge and data to answer employee questions. Stop guessing and start evaluating the quality of agent responses using the Copilot Studio evaluator tool to ensure they align with HR policies, respect user context like role and region, and keep the employee and the organization safe form misinformation. Build a clear evaluation strategy that includes golden queries, structured test sets, and a process to review results. Use what you learn from test results to improve response quality by refining agent instructions, adjusting topic triggers, and updating knowledge sources.

- Get a clearer picture on how your Employee Self-Service agent responds and handles certain scenarios.
- Deploy faster with less risk by validating changes before production.
- Improve accuracy and relevance using grounded, consistent quality scoring.
- Prevent regressions caused by prompt, model, or configuration changes.
- Save manual QA time through automated dataset generation and evaluation.
- Increase employee trust with more consistent, complete, and correct answers.
- Support governance and compliance with auditable, repeatable, objective evaluation practices.

**Evaluations help you answer:**
- Does this experience meet the needs of the employees?
- Does knowledge, data, and conversational qualities come together in a way that actually deflects tickets and improve the employee experience?
- Do the responses form the agent reflect the right level of accuracy, completeness, and relevance to build trust and encourage user adoption?

### How traditional quality assurance (QA) practices and LLM evaluations differ

Traditional QA asks: *Did the system work?* It checks whether software behaves exactly as programmed, finds bugs and crashes, and uses manual or scripted checks.

Evals ask: *Was the response good enough, safe enough, and useful enough?* Evals check whether an AI system behaves acceptably across many possible outcomes, test real user scenarios, and use automated reusable test sets.

- **QA** checks whether the agent responded
- **Evals** check whether the response was *helpful

#### Examples

Here are some examples that demonstrate the difference between QA and LLM evaluations.

| Approach | Focus |
|----------|-------|
| Traditional QA | System functionality |
| LLM Evaluations | Response quality and usefulness |

**Scenario:** An employee asks a common payroll question  

**User prompt:** "Why is my net pay lower this month?"

**Traditional QA example response:**

> "Your net pay is lower because of deductions. Please check your pay slip for more details."

From a traditional QA perspective, this response looks fine:
- The system didn't crash
- The response rendered correctly
- No errors were thrown
- The agent returned an answer
- Nothing violated a hard rule

The problem with a response like this one is it doesn't help prevent tickets from getting created and doesn't increase employee satisfaction.

**Higher-quality response:**

> "Your net pay is lower because deductions reset at the beginning of the calendar year. Get more details in Employee hub to check your last paystub."

This response:
- Answers the real question
- Helps the employee self-serve
- Reduces support tickets
- Aligns with payroll policy behavior

This response is much more useful and helps the user solve their problem. Evaluations help you measure the distance between the actual agent response and the ideal expected response for specific scenarios so you can make improvements to your agent to achieve certain business outcomes. Another example:

**User prompt:** "What’s my base salary?"

**Traditional QA example response:**

> “Your base salary can be found in Workday.”

**Higher-quality response:**

> “Your base salary is $155,000 USD. More payroll information can be found in the Employee Hub.”

## Think of agent evaluations as a program

As you start evaluating agent responses, treat testing as a program, not a one-time task. You need clear roles, defined responsibilities, and a repeatable lifecycle so the right people review results, approve changes, implement changes, and rerun tests over time. This structure helps you improve quality consistently, scale to new scenarios, and compare performance across LLM models without experiencing unintended consequences.

### Roles and responsibilities

#### Organizing principles
In enterprise deployments not everyone can edit the agent, many teams own policies, and risk, sensitive employee data is involved, and decisions must be auditable and defensible. Organize people in a way that: respects Copilot Studio access limits, enables many reviewers without many editors, creates clear accountability, supports audits and compliance reviews, and prevents unapproved changes to sensitive content.

**TLDR:** People closest to the policy review the results. People closest to the platform apply the changes.

#### Accountable teams

| Team | Responsibilities | Role in evals |
|---|---|---|
| **Agent owner** (Central IT, Digital Workplace, Copilot Studio makers) | Owns the ESS agent configuration. Runs evaluations and manages test execution. Applies approved changes. Maintains the evaluation cadence. | The only role with hands on the controls—acts as the execution arm. |
| **Evaluation program owner** (Product manager, platform lead) | Defines what good quality means. Sets evaluation goals. Decides scenario classifications. Owns the evaluation strategy over time. | Without this role, evaluations become tactical and inconsistent. |
| **Domain owners** (HR, payroll, IT service owners) | Review evaluation results for their domain. Validate correctness against real policies. Approve or reject changes. Flag gaps or unsafe responses. | Most ESS failures are domain-specific—central teams can't validate alone. |
| **Legal, privacy, and compliance reviewers** | Review Responsible AI and sensitive scenarios. Validate refusal patterns. Approve coverage for high-risk topics. Define escalation requirements. | Evaluations often surface policy risk around compensation and personal data. |
| **Security and data protection stakeholders** | Validate evaluations don't expose restricted data. Ensure environments follow data-handling rules. | ESS evaluations touch real enterprise data—safeguards must be explicit. |

### How roles work together

1. The evaluation program owner defines what should be tested
2. The agent owner runs evaluations and collects results
3. Domain owners review failures relevant to their areas
4. Legal / Privacy / Security specify high-risk scenarios and review test results
5. The agent owner applies approved changes to improve agent responses
6. Evaluations are rerun after edits are made

## The evaluations lifecycle - when to evaluate?

**Before deploying—Goal: Launch with confidence
- Validate that core scenarios work
- Catch missing knowledge, broken connectors, or unsafe responses early
- Establish a baseline quality bar
- Focus on: Core must-be-right scenarios, Must-not-answer and Responsible AI scenarios, role and region differences

**During customization and iteration—Goal: Improve quality as the agent evolves
- Measure the impact of changes to knowledge, topics, or workflows
- Validate that fixes actually improve responses
- Prevent regressions when new content is added
- Focus on: Variations and edge cases, new scenarios from customization, previously failing prompts

**After deployment—Goal: Maintain quality over time
- Evaluations become an early warning system instead of relying on user complaints
- Detect regressions after updates or policy changes
- Focus on: Known high-risk or high-volume scenarios, sensitive and Responsible AI prompts, KPI-tied scenarios

**Scaling and optimization—Goal: Prove value and guide investment
- Show where the agent performs well or needs investment
- Tie quality improvements to business outcomes
- Focus on: Coverage across scenarios and personas, quality gaps aligned to KPIs, long-tail, and emerging user needs

### The basic phases of the testing cycle

**1. Start by measuring what matters most.**

Begin with a small, intentional test set instead of trying to cover everything at once. Choose scenarios based on critical employee tasks, known problem areas, high-risk topics (such as pay, leave policies, and scenarios that require employee data), and areas tied to business outcomes.

**2. Run the test to establish a baseline.**

Assume the first run reveals gaps. You should get clear signals about where responses are weak, where safety boundaries are unclear, and where expectations don't match actual behavior. This baseline gives everyone a shared reference point instead of relying on opinions.

**3. Synthesize results, because not all failures are equal.**

This step is the most important step. Ask what the failures are telling you. Look for patterns: Is the agent consistently too vague? Is it over-answering sensitive questions? Are failures concentrated in one domain? Without synthesis, evaluations quickly lose credibility.

**4. Decide what actually needs to change.**

Most changes fall into three categories:
- **A. The agent needs to change—Results might show knowledge gaps, topics that don't trigger (or over-trigger), or missing user-context details like role and region. These issues usually require updates to knowledge sources, agent instructions, or topic design.
- **B. The expected response needs to change—The expected response might be too strict, might not reinforce the right behavior, or might create false failures from minor wording differences.
- **C. The test criteria need to change—The issue might be the test type, pass thresholds that don't reflect acceptable quality, or criteria that measure the wrong thing.

**5. Iterate through a few improvement cycles.**

Loop: Run -> Review -> Adjust -> Rerun. The agent improves, tests get more precise, and the team builds shared understanding of what good looks like.

**6. The test stabilizes.**

Expected responses stop shifting. Criteria feel fair. Failures become meaningful instead of noisy. The test becomes benchmark—passing, which it means the experience meets agreed-upon expectations and stakeholders trust the result.

**7. Use the stabilized test for regressions.**

Reuse the same test to: validate changes before rollout, catch regressions early, monitor quality over time, and check how quality varies between LLM models. The evaluation now acts as a safety rail.

## Process considerations for your evaluation strategy

Setting up an evaluation strategy isn't just about writing test cases, it's also about designing a process that fits the shape, structure, and governance model of your organization. Every enterprise has different ownership models, systems, policies, and review flows. These cross-functional realities determine how you structure your golden queries, who reviews the results, and how test sets should be organized.

The following section lists the most common patterns and considerations to help you define an evaluation strategy that works for your Employee Self-Service agent and your broader organization.

### Organizational structure and ownership model

Most organizations have multiple subdomains that own different topics, for example:
- HR: Benefits, compensation, mobility, leave, onboarding, employee relations
- IT: Identity & access, endpoint/device, software, networking, support operations

**Strategy impact:**

- Create separate test sets by domain (for example, Benefits, Leave, IT Access, Devices, and so on).
- Assign domain specific owners to review test results.
- Use tagging or separate CSV. files so test results can be routed to the right teams.
- Some teams require legal, HR operations, IT security, or compliance signoff.

### System complexity and integrations

HR and IT have multiple integrated systems (Workday, ServiceNow, tools for payroll, travel, identity, device management). Response quality often depends on accurate connector calls and correct system routing.

**Strategy impact:**

- Create system specific test sets (for example, Workday Profile Queries)
- Define expected responses that include correct tool triggers and parameters.
- Run regression tests every time a system's configuration or permissions change.

### Policy variation across regions and roles

Enterprises with global workforces commonly have different rules for holidays, leave, eligibility, VPN requirements, payroll systems, and device support.

**Strategy impact:**

- Include region specific golden queries (for example, "Am I eligible for parental leave in Germany?").
- Use user context variables (role, region) in testing to ensure responses adapt correctly.
- Consider evaluating "US-only scenarios," and so on, as separate test sets.

### Role-based differences in permissions and workflows

Managers, employees, contractors, and new hires often have different steps and entitlements, which can also vary by region.

**Strategy impact:**

- Create test sets that intentionally mix roles to expose gaps in personalization logic.
- Validate refusal patterns for restricted access ("As a contractor, you don't have access…").
- Include manager specific workflows (approvals, team level tasks).

### Governance, compliance, and risk tolerance

More regulated industries like healthcare, financial services, government, pharma, and so on, may have stricter thresholds for agent responses.

**Strategy impact:**

- Emphasize guardrail tests (RAI, sensitive topics, restricted data).
- Include tests that confirm correct refusal patterns for all high risk categories.
- Tighten expected responses to ensure no hallucinated policies or invented workflows.

### Content lifecycle and frequency of change

Benefits, payroll cycles, IT support standards, or troubleshooting instructions may update annually, or even quarterly.

**Strategy impact:**

- Build your eval plan around policy change cycles.
- Rerun test sets after every knowledge update or seasonal policy adjustment.
- Run and evaluate tests that are “policy-sensitive” so they're more closely monitored.

---

## Next steps

- Learn how to [create a custom evaluation strategy](evaluations-custom-strategy.md)
- Skip ahead: [Start running tests](evaluations-run-tests.md)
