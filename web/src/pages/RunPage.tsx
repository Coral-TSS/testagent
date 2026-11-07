import { ListSection, ListTable } from "../components/ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Popconfirm, Progress, Space, Tag, Typography } from "antd";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import { streamEvents } from "../api/sse";
import type { RunExecution, TaskRun } from "../api/types";
import { EXECUTOR_LABEL, ExecutionStatusTag, TaskRunStatusTag } from "../components/StatusTags";
import { fmtTime } from "../utils/time";
import { CorrectionButton } from "../components/CorrectionButton";
import { objLabel } from "../components/ObjLink";
import { CAUSE_TAG, CauseTag } from "../components/FailureSummary";
import type { SuspectedCause } from "../api/types";

/** Failed / errored cases of a run counted by suspected cause (batch 2). */
export function causeCounts(executions: RunExecution[]): [SuspectedCause, number][] {
  const out = new Map<SuspectedCause, number>();
  for (const e of executions) {
    if (e.status !== "failed" && e.status !== "error") continue;
    const cause = e.suspected_cause || "unknown";
    out.set(cause, (out.get(cause) || 0) + 1);
  }
  return [...out.entries()];
}

const TERMINAL = new Set(["passed", "failed", "error", "cancelled", "not_executed"]);

/** Task run: live progress (SSE), per-case results, cancel, report link */
export function RunPage() {
  const { runId = "" } = useParams();
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api<TaskRun>(`/runs/${runId}`) });
  const status = run.data?.status;
  const live = Boolean(status && !TERMINAL.has(status));

  useEffect(() => {
    if (!live) return;
    const controller = new AbortController();
    streamEvents(`/runs/${runId}/events`, () => qc.invalidateQueries({ queryKey: ["run", runId] }), controller.signal)
      .catch(() => undefined)
      .finally(() => {
        if (!controller.signal.aborted) qc.invalidateQueries({ queryKey: ["run", runId] });
      });
    return () => controller.abort();
  }, [live, runId, qc]);

  const cancel = useApiMutation(() => api<TaskRun>(`/runs/${runId}/cancel`, { method: "POST" }), {
    success: "Cancellation requested: no new case starts after the current one finishes",
    onSuccess: () => qc.invalidateQueries({ queryKey: ["run", runId] }),
  });

  const r = run.data;
  if (!r) return <Card loading />;
  const c = r.counts;
  const percent = c.total ? Math.round((c.done / c.total) * 100) : r.status === "queued" ? 0 : 100;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={16}>
      <Card
        title={
          <Space>
            Run <Link to={`/tasks/${r.task_id}`}>{r.task_name}</Link> <TaskRunStatusTag status={r.status} />
            {r.trigger === "schedule" && <Tag color="purple">Scheduled</Tag>}
            {r.cancel_requested && !TERMINAL.has(r.status) && <Tag color="orange">Cancelling</Tag>}
          </Space>
        }
        extra={
          <Space>
            {TERMINAL.has(r.status) && <CorrectionButton targetType="task_run" targetId={r.id} kind="omission" />}
            {r.report_id && (
              <Link to={`/reports/${r.report_id}`}>
                <Button type="primary">View report</Button>
              </Link>
            )}
            {!TERMINAL.has(r.status) && (
              <Popconfirm title="After cancelling no new case starts (the running case finishes). Continue?" onConfirm={() => cancel.mutate(undefined)}>
                <Button danger disabled={r.cancel_requested}>
                  Cancel run
                </Button>
              </Popconfirm>
            )}
          </Space>
        }
      >
        <Progress
          percent={percent}
          status={
            r.status === "running" || r.status === "queued" ? "active" : r.status === "passed" ? "success" : r.status === "not_executed" ? "normal" : "exception"
          }
          format={() => `${c.done}/${c.total}`}
        />
        <Space wrap style={{ margin: "8px 0" }}>
          <Tag color="green">Passed {c.passed}</Tag>
          <Tag color="red">failed {c.failed}</Tag>
          <Tag color="volcano">Error {c.error}</Tag>
          <Tag color="orange">Manual {c.blocked}</Tag>
          <Tag>Skipped {c.skipped}</Tag>
          {(c.skipped > 0 || c.blocked > 0) && (
            <span style={{ color: "#8c8c8c", fontSize: 12 }} data-testid="skip-note">
              Skipped and manual cases do not count as passed
            </span>
          )}
        </Space>
        {causeCounts(r.executions).length > 0 && (
          <Space wrap style={{ marginBottom: 8 }} data-testid="cause-counts">
            <Typography.Text type="secondary">Failures by suspected cause:</Typography.Text>
            {causeCounts(r.executions).map(([cause, n]) => (
              <Tag key={cause} color={CAUSE_TAG[cause][1]}>
                {CAUSE_TAG[cause][0]} {n}
              </Tag>
            ))}
          </Space>
        )}
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="Actor">{EXECUTOR_LABEL[r.executor] || r.executor}</Descriptions.Item>
          <Descriptions.Item label="Start">{r.started_at ? fmtTime(r.started_at, { seconds: true }) : "Queued"}</Descriptions.Item>
          <Descriptions.Item label="End">{fmtTime(r.ended_at, { seconds: true })}</Descriptions.Item>
        </Descriptions>
        {r.error && <Alert type="error" showIcon title={r.error} />}
        {r.status === "not_executed" && (
          <Alert
            type="warning"
            showIcon
            data-testid="not-executed"
            title="Not executed: no case ran when this batch finished. Cases may be skipped or waiting for manual execution; see the details below. This is neither a pass nor a failure; there is no pass rate."
          />
        )}
        {r.not_ready.length > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8 }}
            title={`${r.not_ready.length} case(s) were not set ready and did not run: ${r.not_ready.map((n) => n.code).join(", ")}`}
          />
        )}
        {(r.no_script?.length || 0) > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8 }}
            data-testid="no-script"
            title={`Not executed (no automation script): ${r.no_script!.length} case(s) — a test-setup gap, not a failure`}
            description={
              <ListSection label="Run cases without scripts" count={r.no_script!.length}>
              <Space wrap>
                {r.no_script!.map((n) => (
                  <Link key={n.case_id} to={`/cases/${n.case_id}`}>
                    {objLabel(n.title, n.code)}
                  </Link>
                ))}
                <Typography.Text type="secondary">Generate a script (AI automation) or move these cases to an agent task.</Typography.Text>
              </Space>
              </ListSection>
            }
          />
        )}
      </Card>
      <Card size="small" title="Case results">
        <ListTable<RunExecution>
          label="Run executions"
          size="small"
          rowKey="id"
          dataSource={r.executions}

          locale={{ emptyText: r.status === "queued" ? "Waiting for the worker to start" : "No executions" }}
          columns={[
            { title: "#", render: (_: unknown, e: RunExecution) => r.executions.indexOf(e) + 1, width: 50 },
            { title: "Case", render: (_: unknown, e) => <Link to={`/cases/${e.case_id}`}>{objLabel(e.case_title, e.case_code)}</Link> },
            { title: "Result", dataIndex: "status", render: (v: string) => <ExecutionStatusTag status={v} /> },
            { title: "Executor", dataIndex: "executor", render: (v: string) => EXECUTOR_LABEL[v] || v },
            {
              title: "Cause",
              render: (_: unknown, e) =>
                e.failure_kind === "no_script" ? <Tag>No script</Tag> : e.status === "failed" || e.status === "error" ? <CauseTag cause={e.suspected_cause} /> : null,
            },
            {
              title: "description",
              render: (_: unknown, e) => (
                <Typography.Text ellipsis style={{ maxWidth: 360 }}>
                  {e.status === "blocked" ? "Waiting for manual execution" : e.summary?.headline || e.failed_assertion || e.error || ""}
                </Typography.Text>
              ),
            },
            { title: "", render: (_: unknown, e) => <Link to={`/executions/${e.id}`}>{e.status === "blocked" ? "Record result" : "Detail"}</Link> },
          ]}
        />
      </Card>
    </Space>
  );
}
