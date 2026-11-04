-- 2026-11-04: batch 2 "result trustworthiness" (design: batch2-result-trust-proposal.md).
-- 1) Executions carry a deterministic failure kind, a suspected cause and a readable summary.
ALTER TABLE case_execution
  ADD COLUMN failure_kind text CHECK (failure_kind IS NULL OR failure_kind IN
    ('assertion','locator','timeout','script_error','http_error','env_unreachable',
     'platform','agent_error','no_script','non_functional','unknown')),
  ADD COLUMN suspected_cause text CHECK (suspected_cause IS NULL OR suspected_cause IN
    ('sut','script','environment','platform','unknown')),
  ADD COLUMN summary jsonb;

-- Backfill (D6): history keeps its status; only the kind / cause are filled in so the UI can
-- show the right reason. Summaries of old rows stay empty (the UI falls back to the raw text).
UPDATE case_execution SET failure_kind = 'no_script', suspected_cause = 'platform'
  WHERE status = 'error' AND error LIKE 'A case in the automated task has no automation code yet%';
UPDATE case_execution SET failure_kind = 'env_unreachable', suspected_cause = 'environment'
  WHERE status = 'error' AND failure_kind IS NULL AND error LIKE 'ENV_UNREACHABLE%';
UPDATE case_execution SET failure_kind = 'platform', suspected_cause = 'platform'
  WHERE status = 'error' AND failure_kind IS NULL
    AND (error LIKE 'NO_ENVIRONMENT%' OR error LIKE 'CONFIG_MISSING%' OR error LIKE 'MODEL_UNAVAILABLE%');
UPDATE case_execution SET failure_kind = 'non_functional'
  WHERE status = 'skipped' AND failure_kind IS NULL;
UPDATE case_execution SET failure_kind = 'assertion', suspected_cause = 'unknown'
  WHERE status = 'failed' AND failure_kind IS NULL;

-- 2) A self-check that found the system behaving differently from the expected result.
ALTER TABLE test_case DROP CONSTRAINT IF EXISTS test_case_automation_status_check;
ALTER TABLE test_case ADD CONSTRAINT test_case_automation_status_check CHECK
  (automation_status IS NULL OR automation_status IN ('ok','needs_fix','env_unavailable','sut_mismatch'));
ALTER TABLE test_case ADD COLUMN automation_failure jsonb;

-- 3) Model suggestions say where they come from; AI guesses are never pre-selected.
ALTER TABLE model_suggestion
  ADD COLUMN source text NOT NULL DEFAULT 'ai_inferred'
    CHECK (source IN ('requirement','openapi','model_rule','ai_inferred')),
  ADD COLUMN evidence text;
UPDATE model_suggestion SET source = 'requirement' WHERE requirement_id IS NOT NULL;
UPDATE model_suggestion SET source = 'openapi'
  WHERE requirement_id IS NULL AND agent_run_id IS NULL AND kind = 'field';
UPDATE model_suggestion SET source = 'model_rule'
  WHERE requirement_id IS NULL AND agent_run_id IS NULL AND kind = 'link';
