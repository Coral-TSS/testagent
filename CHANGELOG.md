# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Accounts and sign-in: users with roles `admin` / `member`, argon2id passwords, server-side sessions in
  an HttpOnly cookie (12 h idle, 7 days at most), CSRF token for writes, per-address rate limit and a
  15-minute lock after 5 wrong passwords, change password, admin **Users** page (create, role, reset
  password, unlock, disable). First admin from `TESTAGENT_ADMIN_USER` / `TESTAGENT_ADMIN_PASSWORD`;
  `testagent user add|passwd|list|unlock|disable|enable` for the command line.
- Actions are recorded under the signed-in user name instead of `local-user`.
- Public HTTPS: optional `proxy` service (Caddy, compose profile `public`) on port 443 with a Let's Encrypt
  IP certificate (`TESTAGENT_TLS=acme`, TLS-ALPN-01) or Caddy's internal CA (`TESTAGENT_TLS=internal`).
- Only admins change the agent model settings and SUT environment start commands.

- Optional package mirrors for building the image: `PIP_INDEX_URL`, `NPM_REGISTRY`,
  `PLAYWRIGHT_DOWNLOAD_HOST` and `UV_IMAGE` (next to `DEBIAN_MIRROR`), passed from `.env` as build
  arguments. Empty by default (official sources); packages are still checked against the lock-file hashes.

### Changed

- `DEBIAN_MIRROR` defaults to empty (the image's own `deb.debian.org` sources are kept unchanged).
- Faster image builds: BuildKit cache mounts for apt, uv and npm downloads (a changed lock file only
  fetches the difference), the image is built once for `testagent` and reused by `demo`, and only
  Playwright's headless Chromium shell is installed (`PLAYWRIGHT_ONLY_SHELL=0` restores the full build).
  The image shrinks from about 1.8 GB to 1.1 GB. Base images are configurable (`PYTHON_IMAGE`,
  `NODE_IMAGE`). Building now requires BuildKit (`docker buildx`).

### Removed

- The shared access token (`TESTAGENT_ACCESS_TOKEN`, `#t=` sign-in links). The desktop launcher now
  opens the browser with a one-time sign-in ticket instead.

## [0.1.0] - 2026-11-02

Initial public release.

### Added

- Ontology model of the system under test: entities with typed fields, actions with inputs/outputs,
  preconditions and effects, links with readings, cardinality and foreign-key fields; graph and list
  views; read-only model review with Markdown export.
- API registry with OpenAPI import, field-alignment and link suggestions.
- Versions and requirements with AI structuring against the model, people per requirement
  (owner/developer/tester), confirm and freeze with model snapshots.
- AI test strategy and rule-based tasks; one-off and cron schedules.
- AI test case generation (normal/boundary/exception), coverage of requirements, actions, entities and
  fields, case library with revisions and export.
- Automation: the agent writes pytest/Playwright scripts into a local git test repo and binds them only
  after a passing self-check.
- Execution with pytest, an agent browser executor (screenshots, Playwright traces), an agent API
  executor and manual results.
- Defects from failed executions, AI cause analysis, attribution to people, task and version reports,
  severity-weighted people statistics.
- Corrections digested into memories and prompt versions; full agent run traces.
- Any OpenAI-compatible model; configurable agent output language (`TESTAGENT_AGENT_LANGUAGE`).
- Procurement approval demo SUT with three seeded bugs.
- Docker image and Compose stack (PostgreSQL 17, platform with Chromium, demo SUT).

[0.1.0]: https://github.com/Coral-TSS/testagent/releases/tag/v0.1.0
