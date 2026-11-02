import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Popconfirm, Progress, Space, Table, Tag, Typography } from "antd";
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

const TERMINAL = new Set(["passed", "failed", "error", "cancelled"]);

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
          status={r.status === "running" || r.status === "queued" ? "active" : r.status === "passed" ? "success" : "exception"}
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
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="Actor">{EXECUTOR_LABEL[r.executor] || r.executor}</Descriptions.Item>
          <Descriptions.Item label="Start">{r.started_at ? fmtTime(r.started_at, { seconds: true }) : "Queued"}</Descriptions.Item>
          <Descriptions.Item label="End">{fmtTime(r.ended_at, { seconds: true })}</Descriptions.Item>
        </Descriptions>
        {r.error && <Alert type="error" showIcon title={r.error} />}
        {r.not_ready.length > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8 }}
            title={`${r.not_ready.length} case(s) were not set ready and did not run: ${r.not_ready.map((n) => n.code).join(", ")}`}
          />
        )}
      </Card>
      <Card size="small" title="Case results">
        <Table<RunExecution>
          size="small"
          rowKey="id"
          dataSource={r.executions}
          pagination={false}
          locale={{ emptyText: r.status === "queued" ? "Waiting for the worker to start" : "No executions" }}
          columns={[
            { title: "#", render: (_: unknown, __: RunExecution, i: number) => i + 1, width: 50 },
            { title: "Case", render: (_: unknown, e) => <Link to={`/cases/${e.case_id}`}>{objLabel(e.case_title, e.case_code)}</Link> },
            { title: "Result", dataIndex: "status", render: (v: string) => <ExecutionStatusTag status={v} /> },
            { title: "Executor", dataIndex: "executor", render: (v: string) => EXECUTOR_LABEL[v] || v },
            {
              title: "description",
              render: (_: unknown, e) => (
                <Typography.Text ellipsis style={{ maxWidth: 360 }}>
                  {e.status === "blocked" ? "Waiting for manual execution" : e.failed_assertion || e.error || ""}
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
