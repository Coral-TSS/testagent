import { ListSection, ListTable } from "../components/ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Popconfirm, Progress, Space, Tag, Typography } from "antd";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import { streamEvents } from "../api/sse";
import type { RunExecution, TaskRun } from "../api/types";
import { EXECUTION_MODE_LABEL } from "../app/executionMode";
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
    success: "已请求取消：当前用例结束后不会再启动新的用例",
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
            执行 <Link to={`/tasks/${r.task_id}`}>{r.task_name}</Link> <TaskRunStatusTag status={r.status} />
            {r.trigger === "schedule" && <Tag color="purple">已调度</Tag>}
            {r.cancel_requested && !TERMINAL.has(r.status) && <Tag color="orange">正在取消</Tag>}
          </Space>
        }
        extra={
          <Space>
            {TERMINAL.has(r.status) && <CorrectionButton targetType="task_run" targetId={r.id} kind="omission" />}
            {r.report_id && (
              <Link to={`/reports/${r.report_id}`}>
                <Button type="primary">查看报告</Button>
              </Link>
            )}
            {!TERMINAL.has(r.status) && (
              <Popconfirm title="取消后不会再启动新的用例（正在执行的用例会跑完）。要继续吗？" onConfirm={() => cancel.mutate(undefined)}>
                <Button danger disabled={r.cancel_requested}>
                  取消执行
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
              跳过和手工用例不计为通过
            </span>
          )}
        </Space>
        {causeCounts(r.executions).length > 0 && (
          <Space wrap style={{ marginBottom: 8 }} data-testid="cause-counts">
            <Typography.Text type="secondary">按可疑原因分类的失败：</Typography.Text>
            {causeCounts(r.executions).map(([cause, n]) => (
              <Tag key={cause} color={CAUSE_TAG[cause][1]}>
                {CAUSE_TAG[cause][0]} {n}
              </Tag>
            ))}
          </Space>
        )}
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="执行方式">{EXECUTION_MODE_LABEL[r.executor] || EXECUTOR_LABEL[r.executor] || r.executor}</Descriptions.Item>
          <Descriptions.Item label="开始">{r.started_at ? fmtTime(r.started_at, { seconds: true }) : "排队中"}</Descriptions.Item>
          <Descriptions.Item label="结束">{fmtTime(r.ended_at, { seconds: true })}</Descriptions.Item>
        </Descriptions>
        {r.error && <Alert type="error" showIcon title={r.error} />}
        {r.status === "not_executed" && (
          <Alert
            type="warning"
            showIcon
            data-testid="not-executed"
            title="未执行：本批次结束时没有用例真正跑过。用例可能被跳过或正等待手工执行；详见下方。这既不是通过也不是失败，因此没有通过率。"
          />
        )}
        {r.not_ready.length > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8 }}
            title={`${r.not_ready.length} 条用例未设为就绪，因此未执行：${r.not_ready.map((n) => n.code).join("、")}`}
          />
        )}
        {(r.no_script?.length || 0) > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 8 }}
            data-testid="no-script"
            title={`未执行（无自动化脚本）：${r.no_script!.length} 条用例——这是测试准备缺口，不是失败`}
            description={
              <ListSection label="执行无脚本的用例" count={r.no_script!.length}>
              <Space wrap>
                {r.no_script!.map((n) => (
                  <Link key={n.case_id} to={`/cases/${n.case_id}`}>
                    {objLabel(n.title, n.code)}
                  </Link>
                ))}
                <Typography.Text type="secondary">生成脚本（AI 自动化），或把这些用例移到 Agent 任务。</Typography.Text>
              </Space>
              </ListSection>
            }
          />
        )}
      </Card>
      <Card size="small" title="用例结果">
        <ListTable<RunExecution>
          label="运行执行"
          size="small"
          rowKey="id"
          dataSource={r.executions}

          locale={{ emptyText: r.status === "queued" ? "正在等待工作进程启动" : "暂无执行" }}
          columns={[
            { title: "#", render: (_: unknown, e: RunExecution) => r.executions.indexOf(e) + 1, width: 50 },
            { title: "用例", render: (_: unknown, e) => <Link to={`/cases/${e.case_id}`}>{objLabel(e.case_title, e.case_code)}</Link> },
            { title: "结果", dataIndex: "status", render: (v: string) => <ExecutionStatusTag status={v} /> },
            { title: "执行器", dataIndex: "executor", render: (v: string) => EXECUTOR_LABEL[v] || v },
            {
              title: "原因",
              render: (_: unknown, e) =>
                e.failure_kind === "no_script" ? <Tag>无脚本</Tag> : e.status === "failed" || e.status === "error" ? <CauseTag cause={e.suspected_cause} /> : null,
            },
            {
              title: "描述",
              render: (_: unknown, e) => (
                <Typography.Text ellipsis style={{ maxWidth: 360 }}>
                  {e.status === "blocked" ? "等待手工执行" : e.summary?.headline || e.failed_assertion || e.error || ""}
                </Typography.Text>
              ),
            },
            { title: "", render: (_: unknown, e) => <Link to={`/executions/${e.id}`}>{e.status === "blocked" ? "记录结果" : "详情"}</Link> },
          ]}
        />
      </Card>
    </Space>
  );
}
