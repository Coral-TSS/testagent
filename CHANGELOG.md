# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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
