---
mode: agent
description: "Review or change your Maker Kit communication style"
---

# Profile

Route `/profile` and unambiguous requests to change, review, retake, or reset
the maker's communication style to `src/skills/user-profile/SKILL.md`.
The saved style applies only to maker-facing FlightCheck, Setup, and Connect
responses in this checkout. It is not an employee profile and does not change
the ESS agent.

Profile management is available before setup and does not require an agent,
environment, or authentication. Read the setup state as required by the
central instructions, then route this request before the setup-required stop.
Do not let this exception bypass admission gates for any other requested task.

This is a management request: do not count an eligible skill run, offer
automatic onboarding, or automatically present a learned-preference proposal.
Use the shared profile entry contract and keep all saved values local.
