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
  goto: "Open",
  click: "Click",
  fill: "Fill",
  select: "Select",
  press: "Press",
  read: "Read",
  assert: "Assertion",
  request: "Request",
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
        title: r.status === "succeeded" ? `AI suggested cause: ${CAUSE_LABEL[r.suggested_cause || "unknown"]} (not a product problem, no defect created)` : `AI analysis not finished (${r.error_code || r.status})`,
        content: r.analysis || "Open the AI trace to see why",
        onOk: () => onAgentRun(r.agent_run_id),
        okText: "View trace",
      });
    },
  });
  return (
    <>
      <Button loading={analyze.isPending} onClick={() => analyze.mutate(undefined)}>
        AI analyse cause
      </Button>
      <Button type="primary" danger loading={create.isPending} onClick={() => create.mutate(undefined)}>
        Create defect
      </Button>
    </>
  );
}

/** “Manual” executions left by a task run: a person records the result (C11) */
function CompleteBlocked({ executionId, onDone }: { executionId: string; onDone: () => void }) {
  const [form] = Form.useForm<{ status: string; result?: string; failed_assertion?: string }>();
  const done = useApiMutation((body: Record<string, unknown>) => api(`/executions/${executionId}/complete`, { method: "POST", body }), {
    success: "Result recorded",
    onSuccess: onDone,
  });
  return (
    <Card size="small" type="inner" title="Waiting for manual execution: follow the case steps, then record the result" style={{ marginBottom: 12 }}>
      <Form form={form} layout="vertical" initialValues={{ status: "passed" }} onFinish={(v) => done.mutate(Object.fromEntries(Object.entries(v).filter(([, x]) => x)))}>
        <Form.Item name="status" label="Result">
          <Radio.Group
            options={[
              { value: "passed", label: "Passed" },
              { value: "failed", label: "failed" },
              { value: "skipped", label: "Skipped" },
            ]}
          />
        </Form.Item>
        <Form.Item name="result" label="Actual result">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(a, b) => a.status !== b.status}>
          {({ getFieldValue }) =>
            getFieldValue("status") === "failed" ? (
              <Form.Item name="failed_assertion" label="Unmet expectation" rules={[{ required: true, message: "Say which expectation was not met" }]}>
                <Input.TextArea rows={2} />
              </Form.Item>
            ) : null
          }
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={done.isPending}>
          Save result
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
        <Typography.Text strong>pytest: </Typography.Text>
        {summary || "See raw output"}
        <Typography.Text type="secondary"> (this execution predates step reports; run a debug execution again to see step-by-step records)</Typography.Text>
      </Typography.Paragraph>
      <Collapse size="small" items={[{ key: "raw", label: "Raw output (pytest)", children: <pre style={{ margin: 0, maxHeight: 360, overflow: "auto", fontSize: 12, whiteSpace: "pre-wrap" }}>{body}</pre> }]} />
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
              Execution detail <ExecutionStatusTag status={ex.status} />
              <Link to={`/cases/${ex.case_id}`}>
                {objLabel(ex.case_title, ex.case_code)}
              </Link>
            </Space>
          }
          extra={
            <Space>
              {ex.agent_run_id && <Button onClick={() => setRunId(ex.agent_run_id!)}>View AI trace</Button>}
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
              title={ex.status === "skipped" ? "Not executed" : "Why it failed"}
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
                <Alert type="error" showIcon style={{ marginBottom: 12 }} title="Unmet assertions" description={<span style={{ whiteSpace: "pre-wrap" }}>{ex.failed_assertion}</span>} />
              )}
              {ex.error && !explained && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title="Execution error" description={<pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{ex.error}</pre>} />}
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
            <Empty description="No step records" />
          )}
        </Card>
      </Col>
      <Col span={8}>
        <Card size="small" title="Summary" style={{ marginBottom: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Executor">{EXECUTOR_LABEL[ex.executor] || ex.executor}</Descriptions.Item>
            <Descriptions.Item label="Source">{ex.task_run_id ? <Link to={`/runs/${ex.task_run_id}`}>Task run</Link> : ex.executor === "manual" ? "Manual record" : "Single-case debug"}</Descriptions.Item>
            <Descriptions.Item label="Environment">{ex.environment_name ? `${ex.environment_name} (${ex.base_url})` : "-"}</Descriptions.Item>
            <Descriptions.Item label="Executed by">{ex.executed_by ? (ex.executed_by.startsWith("agent") ? "AI" : ex.executed_by) : "-"}</Descriptions.Item>
            <Descriptions.Item label="Code version">{ex.code_commit ? <code>{ex.code_commit.slice(0, 8)}</code> : "-"}</Descriptions.Item>
            <Descriptions.Item label="Duration">{ex.duration_ms != null ? `${(ex.duration_ms / 1000).toFixed(1)} s` : "-"}</Descriptions.Item>
            <Descriptions.Item label="Time">{fmtTime(ex.ended_at || ex.created_at, { seconds: true })}</Descriptions.Item>
          </Descriptions>
        </Card>
        <Card size="small" title="Test data" style={{ marginBottom: 16 }}>
          {ex.test_data && Object.keys(ex.test_data).length ? (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(ex.test_data, null, 2)}</pre>
          ) : (
            <Typography.Text type="secondary">None</Typography.Text>
          )}
        </Card>
        <Card size="small" title="Attachment">
          {files.length ? (
            <Space orientation="vertical">
              {files.map((a) => (
                <Space key={a.sha256 + a.name}>
                  <Tag>{a.kind === "trace" ? "Trace" : a.kind === "screenshot" ? " screenshot" : a.kind === "video" ? "Video" : "Attachment"}</Tag>
                  <Button type="link" size="small" onClick={() => save(a.sha256, a.name)}>
                    Download {a.name}
                  </Button>
                </Space>
              ))}
              {files.some((a) => a.kind === "trace") && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Trace available <code>uv run playwright show-trace file.zip</code> Open
                </Typography.Text>
              )}
            </Space>
          ) : (
            <Typography.Text type="secondary">None</Typography.Text>
          )}
        </Card>
      </Col>
      <AgentRunDrawer runId={runId} onClose={() => setRunId(null)} />
    </Row>
  );
}
