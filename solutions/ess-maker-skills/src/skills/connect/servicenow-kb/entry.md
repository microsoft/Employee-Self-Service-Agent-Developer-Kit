# Connect ServiceNow Knowledge

This provider is separate from the unavailable transactional `servicenow`
provider. It supports native ESS **HR or IT, Development only**, with Federated
Auth and either Simple or Advanced permissions. It does not install a Power
Platform solution, create flows, execute ServiceNow scripts, provision gallery
connections through Graph, publish or promote agents.

The generic Connect router owns capability telemetry and provider selection.
Preserve `servicenow-kb` through any prerequisite handoff; do not emit a second
Connect-start event.

1. Run `python scripts\servicenow_kb_connect.py preflight` from the maker
   workspace root. This validates **local canonical workspace metadata**, not
   the current deployed target. Do not read `.env` files or credential caches.
2. If workspace preparation is absent/incomplete, preserve the original request
   and follow `src/skills/foundation-setup/SKILL.md`, using **Prepare the
   workspace for an integration**. Return here automatically after verified
   preparation; do not require `connect_ready: true`, ask the maker to repeat
   Connect, or loop through preparation between milestones. Unsupported
   products, unknown realms, Test/Production and conflicting target metadata
   are blockers, not permission to retarget or change environments.
3. Follow [the guided lifecycle](SKILL.md). An existing gallery connection uses
   the same guided configuration checks; administrators inspect healthy existing
   configuration rather than recreating it.
