# Provision Checklist

- [x] **Environment bound** — Target env URL captured and reachable
- [x] **ESS base installed** — ESS HR or ESS IT persona pack installed via `pac application install`
- [x] **ISV imported** — Workday extension solution installed via `pac application install`
- [x] **Connections active** — Workday OAuthUser + Dataverse OAuth (signed-in user) both connected
- [x] **Connection refs bound** — Solution connection references PATCHed to point at the new connections
- [x] **Flow runtime connections wired** — ESS HR Workday + WorkdayRESTExecution flows connected via Copilot Studio (MANUAL)
- [x] **User Context Setup topic configured** — Redirect to WorkdaySystemGetUserContextV2 added
- [x] **Health check passed** — All provision tasks verified
