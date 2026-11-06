import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tooltip, Typography, Upload } from "antd";
import type { UploadFile } from "antd";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, describeError } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AutomateResult, CaseCode, CaseExecution, Environment, ExecutionRow, TestCase } from "../api/types";
import { EXECUTOR_LABEL, ExecutionStatusTag } from "./StatusTags";
import { fmtTime } from "../utils/time";
import { EnvironmentStatus } from "./EnvironmentStatus";
import { CauseTag, FailureSummary } from "./FailureSummary";

const EXECUTORS = [
  { value: "auto", label: "Auto (pytest when there is code; HTTP for API cases; otherwise browser)" },
  { value: "agent_browser", label: "Agent browser" },
  { value: "agent_api", label: "Agent API (HTTP requests)" },
  { value: "pytest", label: "pytest script" },
];

/** Read-only code viewer: the bound script or the needs_fix draft */
export function CodeViewer({ caseId, draft, open, onClose }: { caseId: string; draft: boolean; open: boolean; onClose: () => void }) {
  const code = useQuery({
    queryKey: ["case-code", caseId, draft],
    queryFn: () => api<CaseCode>(`/cases/${caseId}/code`, { params: { draft } }),
    enabled: open,
  });
  return (
    <Modal open={open} onCancel={onClose} footer={null} width={900} title={draft ? "Automation draft (needs fix, not bound)" : "Automation code (read-only)"}>
      {code.isError && <Alert type="error" showIcon title={describeError(code.error)} />}
      {code.data && (
        <>
          <Typography.Paragraph>
            <Typography.Text copyable={{ text: code.data.abs_path }} code>
              {code.data.abs_path}
            </Typography.Text>
            {code.data.commit && <Typography.Text type="secondary"> @ {code.data.commit.slice(0, 8)}</Typography.Text>}
          </Typography.Paragraph>
          <pre
            style={{ maxHeight: 520, overflow: "auto", background: "#f6f8fa", padding: 12, fontSize: 12, borderRadius: 6 }}
            aria-label="Code"
          >
            {code.data.content}
          </pre>
        </>
      )}
    </Modal>
  );
}

interface ManualValues {
  status: string;
  environment_id?: string;
  result?: string;
  failed_assertion?: string;
  actual_data?: string;
  blocked_reason?: string;
  duration_min?: number;
}

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** Builds the manual-result body; returns an error message for invalid JSON. */
export async function manualBody(v: ManualValues, files: UploadFile[]): Promise<{ body?: Record<string, unknown>; error?: string }> {
  let actual: unknown;
  if (v.actual_data?.trim()) {
    try {
      actual = JSON.parse(v.actual_data);
    } catch {
      return { error: "Actual data is not valid JSON" };
    }
    if (typeof actual !== "object" || actual === null || Array.isArray(actual)) return { error: "Actual data must be a JSON object" };
  }
  const attachments = await Promise.all(
    files.filter((f) => f.originFileObj).map(async (f) => ({ name: f.name, content_base64: await toBase64(f.originFileObj as File) })),
  );
  const body: Record<string, unknown> = { status: v.status, attachments };
  if (v.environment_id) body.environment_id = v.environment_id;
  if (v.result?.trim()) body.result = v.result.trim();
  if (v.failed_assertion?.trim()) body.failed_assertion = v.failed_assertion.trim();
  if (v.blocked_reason?.trim()) body.blocked_reason = v.blocked_reason.trim();
  if (actual !== undefined) body.actual_data = actual;
  if (v.duration_min) body.duration_ms = Math.round(v.duration_min * 60000);
  return { body };
}

/** What to do about a failed self-check, by failure kind (batch 2). */
export function fixHint(kind?: string | null): string {
  switch (kind) {
    case "locator":
      return "An element was not found: check the page selectors and the case steps, then run “AI automation” again.";
    case "timeout":
      return "It timed out: check that the environment responds in time, then run “AI automation” again.";
    case "script_error":
      return "The script itself failed: run “AI automation” again (fix the case steps or API schema first if they are unclear).";
    case "assertion":
      return "Assertion failed and it is unclear whether the script or the system is wrong: compare with the requirement before regenerating.";
    default:
      return "Fix the case steps/API schema and run “AI automation” again.";
  }
}

/** Execution area of the P09 case detail: single-case debug run, manual record, automation (written to the test repo), history */
export function CaseExecutionPanel({ tc, onAgentRun }: { tc: TestCase; onAgentRun: (id: string) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const [envId, setEnvId] = useState<string>();
  const [executor, setExecutor] = useState("auto");
  const [manualOpen, setManualOpen] = useState(false);
  const [bindOpen, setBindOpen] = useState(false);
  const [viewer, setViewer] = useState<"code" | "draft" | null>(null);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [manualForm] = Form.useForm<ManualValues>();
  const [bindForm] = Form.useForm<{ code_path: string }>();
  const envs = useQuery({ queryKey: ["environments", tc.sut_id], queryFn: () => api<Environment[]>(`/suts/${tc.sut_id}/environments`) });
  const history = useQuery({ queryKey: ["case-executions", tc.id], queryFn: () => api<ExecutionRow[]>(`/cases/${tc.id}/executions`) });
  const environment = envId || envs.data?.[0]?.id;
  const deprecated = tc.status === "deprecated";

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["case-executions", tc.id] });
    qc.invalidateQueries({ queryKey: ["case", tc.id] });
  };
  const debug = useApiMutation(
    () => api<CaseExecution>(`/cases/${tc.id}/debug`, { method: "POST", body: { environment_id: environment, executor } }),
    {
      onSuccess: (ex) => {
        refresh();
        navigate(`/executions/${ex.id}`);
      },
    },
  );
  const manual = useApiMutation((body: Record<string, unknown>) => api<CaseExecution>(`/cases/${tc.id}/executions/manual`, { method: "POST", body }), {
    success: "Execution result recorded",
    onSuccess: () => {
      setManualOpen(false);
      setFiles([]);
      manualForm.resetFields();
      refresh();
    },
  });
  const automate = useApiMutation(
    () => api<AutomateResult>(`/cases/${tc.id}/automate`, { method: "POST", body: environment ? { environment_id: environment } : {} }),
    {
      onSuccess: (r) => {
        refresh();
        if (r.status === "succeeded") message.success(`Generated and committed ${r.code_path}@${(r.code_commit || "").slice(0, 8)}`);
        else if (r.status === "env_unavailable")
          modal.warning({ title: "SUT environment unreachable; no script generated", content: `${r.reason || ""} (no self-check attempt used; retry after starting it)` });
        else if (r.status === "sut_mismatch")
          modal.warning({
            title: "Suspected system issue: the system behaved differently from the expected result",
            content: `${r.reason || ""} The script was not bound. Do not change the assertion to make it pass; review the result below.`,
          });
        else if (r.status === "needs_fix")
          modal.warning({
            title: "Self-check failed, not bound (needs fix)",
            content: r.reason || "The last self-check failed",
            okText: "View AI trace",
            onOk: () => onAgentRun(r.agent_run_id),
          });
        else
          modal.warning({
            title: "Automation not finished",
            content: `${r.error_code || r.status}: open the AI trace to see why`,
            onOk: () => onAgentRun(r.agent_run_id),
          });
      },
    },
  );
  const confirmSut = useApiMutation(
    (body: { action: "bind_and_record" | "record_only"; create_defect: boolean }) =>
      api<{ execution: CaseExecution; defect?: { id: string } | null }>(`/cases/${tc.id}/automation/confirm-sut-issue`, { method: "POST", body }),
    {
      onSuccess: (r) => {
        refresh();
        message.success(r.defect ? "Recorded as a failed execution and a defect was created" : "Recorded as a failed execution");
        if (r.defect) navigate(`/defects/${r.defect.id}`);
      },
    },
  );
  const markScript = useApiMutation(() => api(`/cases/${tc.id}/automation/mark-script-issue`, { method: "POST" }), {
    success: "Marked as a script / case issue",
    onSuccess: refresh,
  });
  const bind = useApiMutation((body: { code_path: string }) => api(`/cases/${tc.id}/bind-code`, { method: "POST", body }), {
    success: "Bound code",
    onSuccess: () => {
      setBindOpen(false);
      refresh();
    },
  });

  return (
    <Card size="small" title="Execution & automation" style={{ marginTop: 16 }}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          aria-label="Environment"
          style={{ width: 200 }}
          placeholder="Choose environment"
          value={environment}
          onChange={setEnvId}
          options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} (${e.base_url})` }))}
        />
        <Select aria-label="Executor" style={{ width: 300 }} value={executor} onChange={setExecutor} options={EXECUTORS} />
        <Tooltip title={environment ? "Run once now in the chosen environment (not part of any task)" : "Add an environment to the SUT first"}>
          <Button type="primary" disabled={!environment || deprecated} loading={debug.isPending} onClick={() => debug.mutate(undefined)}>
            Debug run
          </Button>
        </Tooltip>
        <Button disabled={deprecated} onClick={() => setManualOpen(true)}>
          Record manual execution
        </Button>
        <Tooltip title="The agent generates a pytest script and self-checks it in the chosen environment; when it passes it is written to this system's local test repo and bound; a failed self-check only leaves a draft">
          <Button disabled={deprecated} loading={automate.isPending} onClick={() => automate.mutate(undefined)}>
            AI automation
          </Button>
        </Tooltip>
        <Button disabled={deprecated} onClick={() => setBindOpen(true)}>
          Bind existing code
        </Button>
      </Space>
      {tc.code_path && (<>
        <Typography.Paragraph>
          <Typography.Text type="secondary">Automation code: </Typography.Text>
          <Typography.Text code copyable={{ text: tc.code_abs_path || tc.code_path }}>
            {tc.code_abs_path || tc.code_path}
          </Typography.Text>
          {tc.code_commit && <Typography.Text type="secondary"> @ {tc.code_commit.slice(0, 8)} </Typography.Text>}
          <Button size="small" type="link" onClick={() => setViewer("code")}>
            View code
          </Button>
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          {tc.code_commit
            ? "Runs the bound Git version, including its fixtures and helpers. Commit local changes and bind the code again to run a newer version."
            : "No Git version is bound yet. Runs use the repository's committed version at the start; commit and bind changes before rerunning."}
        </Typography.Paragraph>
      </>)}
      <EnvironmentStatus env={envs.data?.find((e) => e.id === environment)} />
      {tc.automation_status === "env_unavailable" && (
        <Alert
          type="warning"
          showIcon
          style={{ margin: "12px 0" }}
          title="The SUT environment was unreachable during the last AI automation (not a script problem)"
          description={`${tc.automation_note || ""}; start the environment and click “AI automation” again.`}
        />
      )}
      {tc.automation_status === "sut_mismatch" && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          data-testid="sut-mismatch"
          title="The self-check found the system behaving differently from the expected result (suspected system issue); the script was not bound"
          description={
            <Space orientation="vertical" size={6} style={{ width: "100%" }}>
              {tc.automation_failure ? (
                <FailureSummary summary={tc.automation_failure} versionId={tc.origin_version_id} />
              ) : (
                <span>Reason: {tc.automation_note || "unknown"}</span>
              )}
              <Typography.Text type="secondary">
                Do not change the assertion to make the test pass. If the expectation is right, record it: binding keeps the script so later runs fail until the system is fixed.
              </Typography.Text>
              <Space wrap>
                <Button
                  type="primary"
                  loading={confirmSut.isPending}
                  onClick={() => confirmSut.mutate({ action: "bind_and_record", create_defect: false })}
                >
                  Bind script and record failure
                </Button>
                <Button loading={confirmSut.isPending} onClick={() => confirmSut.mutate({ action: "bind_and_record", create_defect: true })}>
                  Bind, record and create defect
                </Button>
                <Button loading={confirmSut.isPending} onClick={() => confirmSut.mutate({ action: "record_only", create_defect: false })}>
                  Only record failure
                </Button>
                {tc.draft_abs_path && (
                  <Button type="link" onClick={() => setViewer("draft")}>
                    View draft
                  </Button>
                )}
                <Button type="link" danger loading={markScript.isPending} onClick={() => markScript.mutate(undefined)}>
                  It is a script issue
                </Button>
              </Space>
            </Space>
          }
        />
      )}
      {tc.automation_status === "needs_fix" && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title="Automation needs fix: the last self-check failed and the script was not bound to the case"
          description={
            <Space orientation="vertical" size={2}>
              {tc.automation_failure ? (
                <FailureSummary summary={tc.automation_failure} versionId={tc.origin_version_id} />
              ) : (
                <span>Reason: {tc.automation_note || "unknown"}</span>
              )}
              <span>{fixHint(tc.automation_failure?.kind)}</span>
              {tc.draft_abs_path && (
                <span>
                  Draft: 
                  <Typography.Text code copyable={{ text: tc.draft_abs_path }}>
                    {tc.draft_abs_path}
                  </Typography.Text>
                  <Button size="small" type="link" onClick={() => setViewer("draft")}>
                    View draft
                  </Button>
                </span>
              )}
              <span>Or fix the draft by hand and use “Bind existing code”.</span>
            </Space>
          }
        />
      )}
      {(debug.isPending || automate.isPending) && (
        <Typography.Paragraph type="secondary">Running; browser actions may take a minute or two…</Typography.Paragraph>
      )}
      <Table<ExecutionRow>
        size="small"
        rowKey="id"
        loading={history.isLoading}
        dataSource={history.data || []}
        pagination={{ pageSize: 10, hideOnSinglePage: true }}
        locale={{ emptyText: "No executions yet" }}
        columns={[
          { title: "Time", dataIndex: "created_at", render: (v: string, r) => <Link to={`/executions/${r.id}`}>{fmtTime(v, { seconds: true })}</Link> },
          { title: "Result", dataIndex: "status", render: (v: string) => <ExecutionStatusTag status={v} /> },
          { title: "Executor", dataIndex: "executor", render: (v: string) => EXECUTOR_LABEL[v] || v },
          { title: "Environment", dataIndex: "environment_name", render: (v?: string) => v || "-" },
          { title: "Source", dataIndex: "task_run_id", render: (v?: string) => (v ? "Task" : "Debug/manual") },
          { title: "Cause", dataIndex: "suspected_cause", render: (v?: ExecutionRow["suspected_cause"]) => <CauseTag cause={v} /> },
          {
            title: "description",
            render: (_: unknown, r) => (
              <Typography.Text ellipsis style={{ maxWidth: 260 }}>{r.summary?.headline || r.failed_assertion || r.error || ""}</Typography.Text>
            ),
          },
        ]}
      />
      <Modal
        title="Record manual execution result"
        open={manualOpen}
        onCancel={() => setManualOpen(false)}
        onOk={() => manualForm.submit()}
        confirmLoading={manual.isPending}
        destroyOnHidden
      >
        <Form<ManualValues>
          form={manualForm}
          layout="vertical"
          initialValues={{ status: "passed", environment_id: environment }}
          onFinish={async (v) => {
            const { body, error } = await manualBody(v, files);
            if (error) return message.error(error);
            manual.mutate(body!);
          }}
        >
          <Form.Item name="status" label="Result" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "passed", label: "Passed" },
                { value: "failed", label: "failed" },
                { value: "blocked", label: "Blocked" },
                { value: "skipped", label: "Skipped" },
              ]}
            />
          </Form.Item>
          <Form.Item name="environment_id" label="Environment">
            <Select allowClear options={(envs.data || []).map((e) => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Form.Item name="result" label="Actual result">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.status !== b.status}>
            {({ getFieldValue }) =>
              getFieldValue("status") === "failed" ? (
                <Form.Item name="failed_assertion" label="Unmet expectation" rules={[{ required: true, message: "On failure, say which expectation was not met" }]}>
                  <Input.TextArea rows={2} />
                </Form.Item>
              ) : getFieldValue("status") === "blocked" ? (
                <Form.Item name="blocked_reason" label="Blocking reason" rules={[{ required: true, message: "Please give the blocking reason" }]}>
                  <Input />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item name="actual_data" label="Test data actually used (JSON, optional)">
            <Input.TextArea rows={2} placeholder='{"amount": 0}' />
          </Form.Item>
          <Form.Item name="duration_min" label="Duration (minutes)">
            <InputNumber min={0} step={0.5} />
          </Form.Item>
          <Form.Item label="Attachments (screenshots, logs)">
            <Upload multiple fileList={files} beforeUpload={() => false} onChange={({ fileList }) => setFiles(fileList)}>
              <Button>Choose files</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>
      <CodeViewer caseId={tc.id} draft={viewer === "draft"} open={viewer !== null} onClose={() => setViewer(null)} />
      <Modal
        title="Bind existing automation code"
        open={bindOpen}
        onCancel={() => setBindOpen(false)}
        onOk={() => bindForm.submit()}
        confirmLoading={bind.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">Enter the path of a committed file in the test repo (under tests/); the current commit is pinned.</Typography.Paragraph>
        <Form form={bindForm} layout="vertical" initialValues={{ code_path: tc.code_path || "" }} onFinish={(v) => bind.mutate(v)}>
          <Form.Item name="code_path" label="Code path" rules={[{ required: true, pattern: /^tests\/.+\.py$/, message: "Must be a .py file under tests/" }]}>
            <Input placeholder="tests/REQ-001/test_TC-001.py" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
