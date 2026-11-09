# Documentation maintenance — 2026-11-09

Reviewed product baseline: f8eb3618acfcbed4f54915e03e43db01bbd3e2a8 (develop, matched origin before this documentation change).

The tracked [specification set](../../specs/test-agent-platform/README.md) now contains the maintained spec, plan, tasks, architecture, detailed design, test design and evidence review. The old workspace specs directory remains an identical local reference mirror. Historical proposal bodies are explicitly labelled and retained.

This change corrects stale repository paths, relation-node modelling, shared-token authentication, Agent/module layout, result and script-version semantics, and task completion claims. It distinguishes implemented behaviour, recorded tests, real-model results and deployment status. All 81 original M1 task IDs remain traceable; remaining work has dependencies and observable acceptance conditions.

Validation is documentation-only: relative Markdown links, evidence paths, original task ID coverage, document mirror hashes, secret-pattern scan and git diff --check. No product code, database migrations, runtime configuration or historical test results were changed. Product tests were not rerun; the 2026-11-07 results are cited as historical evidence.
