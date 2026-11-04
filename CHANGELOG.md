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
- Result trustworthiness (batch 2, migration `0023_result_trust`):
  - Every failed, errored or skipped execution carries a failure kind (assertion, element not found,
    timeout, script error, error response, system unreachable, platform/config, agent did not finish,
    no script, non-functional) and a suspected cause (system under test, script/case, environment,
    platform, unclear), plus a readable summary: one sentence, expected vs actual, the requirement and
    step, and the raw output folded away. Shown on the execution page, the case history, run pages and
    reports. History is backfilled for kind and cause only; statuses are unchanged.
  - AI automation self-check no longer "fixes" a script whose assertion disagrees with the system: when
    the expectation is backed by the case or requirement, the case is marked **suspected system issue**
    (`sut_mismatch`) and a person chooses: bind the script and record a failed execution (optionally
    creating a defect), only record the failure, or mark it a script issue. Batch automation skips these
    cases unless they are picked.
  - Automated tasks with ready cases that have no script: "Run now" / "Set ready" ask first (generate
    scripts, move the cases to an agent task, or run anyway). Such cases are skipped with kind
    `no_script` instead of counting as errors; scheduled runs skip them without asking. Tasks show how
    many cases lack a script.
  - **Run all runnable tasks** for a version (`GET /versions/{id}/runnable-tasks`,
    `POST /versions/{id}/run-tasks`): one dialog lists every task, ticks the runnable ones and says why
    the others cannot start; "Start testing" opens it (or only changes the status). The main-flow
    "Run tasks" step opens the same dialog.
  - Reports and run pages count failures by suspected cause and list cases skipped for a missing script
    (`skipped_no_script` in the summary); the pass-rate note says how many skipped cases had no script.
- Model suggestions show where they come from: **Requirement** (with the quoted text), **OpenAPI**
  (the API field), **Model rule** (the foreign-key field) or **AI inferred**. An AI completion only
  counts as from a requirement when the quote it gives really is in that requirement. **Accept
  selected** accepts many suggestions at once (`POST /suts/{id}/suggestions/accept-batch`); AI inferences
  and links are not pre-selected, and accepting an AI inference asks why it is right (kept in the change
  log). The model review shows how many pending suggestions are AI inferences.
- AI model completion no longer proposes duplicates: a new action for an API that an action is already
  bound to, the same node twice in one batch, a node similar to one already pending or one a person
  rejected, and actions without a description are left out, with the counts shown after the run. An
  action suggestion may name its API, which is bound when it is accepted; a suggestion close to an
  existing node is marked "possible duplicate".

### Changed

- `DEBIAN_MIRROR` defaults to empty (the image's own `deb.debian.org` sources are kept unchanged).
- Faster image builds: BuildKit cache mounts for apt, uv and npm downloads (a changed lock file only
  fetches the difference), the image is built once for `testagent` and reused by `demo`, and only
  Playwright's headless Chromium shell is installed (`PLAYWRIGHT_ONLY_SHELL=0` restores the full build).
  The image shrinks from about 1.8 GB to 1.1 GB. Base images are configurable (`PYTHON_IMAGE`,
  `NODE_IMAGE`). Building now requires BuildKit (`docker buildx`).
- A skipped case in an automated task that has no automation script is recorded as `skipped` (kind
  `no_script`) instead of `error`, so it no longer lowers the pass rate as an error.
- The needs-fix note of AI automation is now the readable one-line failure summary; the raw output is
  kept with the case (`automation_failure.raw`).
- Accepting a model suggestion inferred by the AI without a source needs a note (`note`, 5+ characters).
- A task run in which no case was executed because every case lacks an automation script now ends as
  **Not executed** (`not_executed`, migration `0024_run_not_executed`) instead of passed. Its report has
  no pass rate and says so; runs with any executed, awaiting-manual or other skipped case keep the
  previous rule. Runs already recorded that way since `0023` are updated; older runs are unchanged.

### Fixed

- Public HTTPS (`TESTAGENT_TLS=acme`): the Caddy issuer uses Let's Encrypt production explicitly, also
  for retries. Before, a failed first attempt was retried against the staging CA, which is often
  unreachable from mainland China, so the certificate was never issued.
- `DEBIAN_MIRROR` now also replaces `security.debian.org` and works with the classic `sources.list`
  format; apt retries with 30 s timeouts instead of hanging, and the build log prints the apt sources,
  npm registry and Python index actually used.
- Test results recorded with `check()` reported the test as passed in the parsed report when an
  earlier check had failed.
- `ops/export_openapi.py` failed with an unexpected argument.

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
