import { useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Collapse, Descriptions, Empty, Form, Input, Radio, Row, Space, Tag, Timeline, Typography } from "antd";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, describeError, fetchBlob, saveBlob } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AnalyzeResult, CaseExecution, Defect, ExecutionStep } from "../api/types";
import { CAUSE_LABEL } from "../components/DefectTags";
import { AgentRunDrawer } from "../components/AgentRunDrawer";
import { ArtifactImage } from "../components/ArtifactImage";
import { EXECUTOR_LABEL, ExecutionStatusTag } from "../components/StatusTags";
import { fmtTime } from "../utils/time";
import { CorrectionButton } from "../components/CorrectionButton";
import { objLabel } from "../components/ObjLink";
import { RunReport, summarizeRawOutput } from "../components/RunReport";
import { FailureSummary } from "../components/FailureSummary";

const ACTION_LABEL: Record<string, string> = {
  goto: "打开",
  click: "点击",
  fill: "填写",
  select: "选择",
  press: "按键",
  read: "读取",
  assert: "断言",
  request: "请求",
};

/** Step values may be strings (browser) or JSON (API requests, receipts). */
export function asText(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : JSON.stringify(v);
}

export function describeTarget(target?: Record<string, string> | string | null): string {
  if (!target) return "";
  if (typeof target === "string") return target;
  if (target.role) return target.name ? `${target.role} “${target.name}”` : target.role;
  if (target.label) return `label “${target.label}”`;
  if (target.text) return `text “${target.text}”`;
  return target.selector || "";
}

function StepItem({ step }: { step: ExecutionStep }) {
  const target = describeTarget(step.target);
  return (
    <div>
      <Space wrap>
        <Typography.Text strong>
          {step.seq}. {ACTION_LABEL[step.action] || step.action}
        </Typography.Text>
        {target && <Typography.Text code>{target}</Typography.Text>}
        {step.value != null && step.value !== "" && <Typography.Text type="secondary">Value: {asText(step.value)}</Typography.Text>}
        {step.ms != null && <Typography.Text type="secondary">{step.ms} ms</Typography.Text>}
      </Space>
      {step.result != null && step.result !== "" && (
        <div>
          <Typography.Text type={step.status === "ok" ? undefined : "danger"}>{asText(step.result)}</Typography.Text>
        </div>
      )}
      {step.screenshot_sha && (
        <div style={{ marginTop: 4 }}>
          <ArtifactImage sha={step.screenshot_sha} alt={`Step ${step.seq} screenshot`} />
        </div>
      )}
    </div>
  );
}

/** Create a defect from a failed execution (requirements, node and API filled in automatically) or let the AI analyse the cause */
function DefectActions({ executionId, onAgentRun }: { executionId: string; onAgentRun: (id: string) => void }) {
  const navigate = useNavigate();
  const { modal } = App.useApp();
  const create = useApiMutation(() => api<Defect>(`/executions/${executionId}/defect`, { method: "POST", body: {} }), {
    onSuccess: (d) => navigate(`/defects/${d.id}`),
  });
  const analyze = useApiMutation(() => api<AnalyzeResult>(`/executions/${executionId}/analyze`, { method: "POST" }), {
    onSuccess: (r) => {
      if (r.defect) return navigate(`/defects/${r.defect.id}`);
      modal.info({
        title: r.status === "succeeded" ? `AI 建议原因：${CAUSE_LABEL[r.suggested_cause || "unknown"]}（不是产品问题，未创建缺陷）` : `AI 分析未完成（${r.error_code || r.status}）`,
        content: r.analysis || "打开 AI 追踪查看原因",
        onOk: () => onAgentRun(r.agent_run_id),
        okText: "查看追踪",
      });
    },
  });
  return (
    <>
      <Button loading={analyze.isPending} onClick={() => analyze.mutate(undefined)}>
        AI 分析原因
      </Button>
      <Button type="primary" danger loading={create.isPending} onClick={() => create.mutate(undefined)}>
        创建缺陷
      </Button>
    </>
  );
}

/** “Manual” executions left by a task run: a person records the result (C11) */
function CompleteBlocked({ executionId, onDone }: { executionId: string; onDone: () => void }) {
  const [form] = Form.useForm<{ status: string; result?: string; failed_assertion?: string }>();
  const done = useApiMutation((body: Record<string, unknown>) => api(`/executions/${executionId}/complete`, { method: "POST", body }), {
    success: "已记录结果",
    onSuccess: onDone,
  });
  return (
    <Card size="small" type="inner" title="等待手工执行：请按用例步骤操作，然后记录结果" style={{ marginBottom: 12 }}>
      <Form form={form} layout="vertical" initialValues={{ status: "passed" }} onFinish={(v) => done.mutate(Object.fromEntries(Object.entries(v).filter(([, x]) => x)))}>
        <Form.Item name="status" label="结果">
          <Radio.Group
            options={[
              { value: "passed", label: "通过" },
              { value: "failed", label: "失败" },
              { value: "skipped", label: "跳过" },
            ]}
          />
        </Form.Item>
        <Form.Item name="result" label="实际结果">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(a, b) => a.status !== b.status}>
          {({ getFieldValue }) =>
            getFieldValue("status") === "failed" ? (
              <Form.Item name="failed_assertion" label="未满足的预期" rules={[{ required: true, message: "说明哪条预期未满足" }]}>
                <Input.TextArea rows={2} />
              </Form.Item>
            ) : null
          }
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={done.isPending}>
          保存结果
        </Button>
      </Form>
    </Card>
  );
}

const STEP_COLOR: Record<string, string> = { ok: "green", failed: "red", error: "red" };

/** pytest executions recorded from older versions (no report): summary line + collapsible output */
function RawPytest({ raw }: { raw: string }) {
  const { summary, body } = summarizeRawOutput(raw);
  return (
    <>
      <Typography.Paragraph>
        <Typography.Text strong>pytest： </Typography.Text>
        {summary || "查看原始输出"}
        <Typography.Text type="secondary"> （这次执行早于步骤报告；请再做一次调试执行以查看逐步记录）</Typography.Text>
      </Typography.Paragraph>
      <Collapse size="small" items={[{ key: "raw", label: "原始输出（pytest）", children: <pre style={{ margin: 0, maxHeight: 360, overflow: "auto", fontSize: 12, whiteSpace: "pre-wrap" }}>{body}</pre> }]} />
    </>
  );
}

/** P10 execution detail: result, unmet assertions, step records and screenshots, test data, attachments and trace */
export function ExecutionPage() {
  const { executionId = "" } = useParams();
  const { message } = App.useApp();
  const [runId, setRunId] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["execution", executionId], queryFn: () => api<CaseExecution>(`/executions/${executionId}`) });
  const ex = q.data;
  if (q.error) return <Alert type="error" showIcon title={describeError(q.error)} />;
  if (!ex) return <Card loading />;

  const save = async (sha: string, name: string) => {
    try {
      saveBlob(await fetchBlob(`/artifacts/${sha}`), name);
    } catch (err) {
      message.error(describeError(err));
    }
  };
  const explained = Boolean(ex.report?.tests.some((t) => t.failure?.explain));
  const files = ex.artifacts.filter((a) => a.kind !== "screenshot" || ex.executor !== "agent_browser");
  return (
    <Row gutter={16}>
      <Col span={16}>
        <Card
          title={
            <Space>
              执行详情 <ExecutionStatusTag status={ex.status} />
              <Link to={`/cases/${ex.case_id}`}>
                {objLabel(ex.case_title, ex.case_code)}
              </Link>
            </Space>
          }
          extra={
            <Space>
              {ex.agent_run_id && <Button onClick={() => setRunId(ex.agent_run_id!)}>查看 AI 追踪</Button>}
              <CorrectionButton targetType="execution" targetId={ex.id} />
              {(ex.status === "failed" || ex.status === "error") && ex.suspected_cause !== "platform" && <DefectActions executionId={ex.id} onAgentRun={setRunId} />}
            </Space>
          }
        >
          {ex.defects && ex.defects.length > 0 && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              title={
                <Space wrap>
                  Linked defects: 
                  {ex.defects.map((d) => (
                    <Link key={d.id} to={`/defects/${d.id}`}>{objLabel(d.title, d.code)}</Link>
                  ))}
                </Space>
              }
            />
          )}
          {ex.summary && (ex.status === "failed" || ex.status === "error" || ex.status === "skipped") ? (
            <Alert
              type={ex.status === "skipped" ? "info" : ex.suspected_cause === "sut" ? "error" : "warning"}
              showIcon
              style={{ marginBottom: 12 }}
              title={ex.status === "skipped" ? "未执行" : "失败原因"}
              description={
                <>
                  <FailureSummary summary={ex.summary} raw={[ex.failed_assertion, ex.error].filter(Boolean).join("\n\n") || null} />
                  {ex.suspected_cause === "platform" && (
                    <Typography.Paragraph type="secondary" style={{ margin: "6px 0 0" }}>
                      A platform or configuration problem is not a defect of the system under test: fix the setup (environment, test repo, script, model) and run again.
                    </Typography.Paragraph>
                  )}
                </>
              }
            />
          ) : (
            <>
              {ex.failed_assertion && !explained && (
                <Alert type="error" showIcon style={{ marginBottom: 12 }} title="未满足的断言" description={<span style={{ whiteSpace: "pre-wrap" }}>{ex.failed_assertion}</span>} />
              )}
              {ex.error && !explained && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title="执行错误" description={<pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{ex.error}</pre>} />}
            </>
          )}
          {ex.status === "blocked" ? (
            <CompleteBlocked executionId={ex.id} onDone={() => q.refetch()} />
          ) : (
            ex.blocked_reason && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title={`Blocked: ${ex.blocked_reason}`} />
          )}
          {ex.executor === "pytest" && ex.report ? (
            <RunReport report={ex.report} testData={ex.test_data} raw={ex.result} />
          ) : ex.executor === "pytest" && ex.result ? (
            <RawPytest raw={ex.result} />
          ) : (
            ex.result && <Typography.Paragraph>{ex.result}</Typography.Paragraph>
          )}
          {ex.executor === "pytest" ? null : ex.steps_recorded.length ? (
            <Timeline items={ex.steps_recorded.map((s) => ({ key: s.seq, color: STEP_COLOR[s.status] || "gray", content: <StepItem step={s} /> }))} />
          ) : (
            <Empty description="没有步骤记录" />
          )}
        </Card>
      </Col>
      <Col span={8}>
        <Card size="small" title="摘要" style={{ marginBottom: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="执行器">{EXECUTOR_LABEL[ex.executor] || ex.executor}</Descriptions.Item>
            <Descriptions.Item label="来源">{ex.task_run_id ? <Link to={`/runs/${ex.task_run_id}`}>任务执行</Link> : ex.executor === "manual" ? "手工记录" : "单用例调试"}</Descriptions.Item>
            <Descriptions.Item label="环境">{ex.environment_name ? `${ex.environment_name} (${ex.base_url})` : "-"}</Descriptions.Item>
            <Descriptions.Item label="执行人">{ex.executed_by ? (ex.executed_by.startsWith("agent") ? "AI" : ex.executed_by) : "-"}</Descriptions.Item>
            <Descriptions.Item label="代码版本">{ex.code_commit ? <code>{ex.code_commit.slice(0, 8)}</code> : "-"}</Descriptions.Item>
            <Descriptions.Item label="耗时">{ex.duration_ms != null ? `${(ex.duration_ms / 1000).toFixed(1)} s` : "-"}</Descriptions.Item>
            <Descriptions.Item label="时间">{fmtTime(ex.ended_at || ex.created_at, { seconds: true })}</Descriptions.Item>
          </Descriptions>
        </Card>
        <Card size="small" title="测试数据" style={{ marginBottom: 16 }}>
          {ex.test_data && Object.keys(ex.test_data).length ? (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(ex.test_data, null, 2)}</pre>
          ) : (
            <Typography.Text type="secondary">无</Typography.Text>
          )}
        </Card>
        <Card size="small" title="附件">
          {files.length ? (
            <Space orientation="vertical">
              {files.map((a) => (
                <Space key={a.sha256 + a.name}>
                  <Tag>{a.kind === "trace" ? "追踪" : a.kind === "screenshot" ? " 截图" : a.kind === "video" ? "视频" : "附件"}</Tag>
                  <Button type="link" size="small" onClick={() => save(a.sha256, a.name)}>
                    下载 {a.name}
                  </Button>
                </Space>
              ))}
              {files.some((a) => a.kind === "trace") && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  可用追踪，可用 <code>uv run playwright show-trace file.zip</code> 打开
                </Typography.Text>
              )}
            </Space>
          ) : (
            <Typography.Text type="secondary">无</Typography.Text>
          )}
        </Card>
      </Col>
      <AgentRunDrawer runId={runId} onClose={() => setRunId(null)} />
    </Row>
  );
}
