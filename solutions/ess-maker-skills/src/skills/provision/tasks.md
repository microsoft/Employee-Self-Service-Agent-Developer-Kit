# Provision Checklist

- [ ] **Environment bound** — Target env URL captured and reachable
- [ ] **ESS base installed** — ESS HR or ESS IT persona pack installed via `pac application install`
- [ ] **ISV imported** — Workday extension solution installed via `pac application install`
- [ ] **Connections active** — Workday OAuthUser + Dataverse OAuth (signed-in user) both connected
- [ ] **Connection refs bound** — Solution connection references PATCHed to point at the new connections
- [ ] **Flow runtime connections wired** — ESS HR Workday + WorkdayRESTExecution flows connected via Copilot Studio
- [ ] **User Context Setup topic configured** — Redirect to WorkdaySystemGetUserContextV2 added
- [ ] **Health check passed** — All provision tasks verified
