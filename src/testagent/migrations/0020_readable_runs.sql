-- readable pytest run reports and AI completion of hand-written cases.
-- case_execution.report: steps / requests / assertions written by the platform's pytest plugin.
-- test_case.ai_proposal: the latest AI completion proposal for a case; it changes nothing until
-- a person accepts it (C01), then it is cleared.
ALTER TABLE case_execution ADD COLUMN report jsonb;
ALTER TABLE test_case ADD COLUMN ai_proposal jsonb;
