import { ListTable } from "./ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Tooltip, Typography, Upload } from "antd";
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
  { value: "auto", label: "自动（有代码时用 pytest；API 用例用 HTTP；否则用浏览器）" },
  { value: "agent_browser", label: "Agent 浏览器" },
  { value: "agent_api", label: "Agent API（HTTP 请求）" },
  { value: "pytest", label: "pytest 脚本" },
];

/** Read-only code viewer: the bound script or the needs_fix draft */
export function CodeViewer({ caseId, draft, open, onClose }: { caseId: string; draft: boolean; open: boolean; onClose: () => void }) {
  const code = useQuery({
    queryKey: ["case-code", caseId, draft],
    queryFn: () => api<CaseCode>(`/cases/${caseId}/code`, { params: { draft } }),
    enabled: open,
  });
  return (
    <Modal open={open} onCancel={onClose} footer={null} width={900} title={draft ? "自动化草稿（待修复，未绑定）" : "自动化代码（只读）"}>
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
            aria-label="编号"
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
      return { error: "实际数据不是合法 JSON" };
    }
    if (typeof actual !== "object" || actual === null || Array.isArray(actual)) return { error: "实际数据必须是 JSON 对象" };
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
      return "未找到元素：请检查页面选择器和用例步骤，然后再次运行“AI 自动化”。";
    case "timeout":
      return "超时：请确认环境能及时响应，然后再次运行“AI 自动化”。";
    case "script_error":
      return "脚本本身失败：请再次运行“AI 自动化”（如果用例步骤或 API 模式不清楚，请先修正）。";
    case "assertion":
      return "断言失败，且尚不清楚是脚本问题还是系统问题：重新生成前请先对照需求。";
    default:
      return "请修正用例步骤/API 模式，然后再次运行“AI 自动化”。";
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
    success: "已记录执行结果",
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
        if (r.status === "succeeded") message.success(`已生成并提交 ${r.code_path}@${(r.code_commit || "").slice(0, 8)}`);
        else if (r.status === "env_unavailable")
          modal.warning({ title: "被测系统环境不可达；未生成脚本", content: `${r.reason || ""}（未进行自检；请启动环境后重试）` });
        else if (r.status === "sut_mismatch")
          modal.warning({
            title: "疑似系统问题：系统表现与预期结果不符",
            content: `${r.reason || ""} 脚本未绑定。不要靠改断言让它通过；请查看下方结果。`,
          });
        else if (r.status === "needs_fix")
          modal.warning({
            title: "自检失败，未绑定（待修复）",
            content: r.reason || "上次自检失败",
            okText: "查看 AI 追踪",
            onOk: () => onAgentRun(r.agent_run_id),
          });
        else
          modal.warning({
            title: "自动化未完成",
            content: `${r.error_code || r.status}：打开 AI 追踪查看原因`,
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
        message.success(r.defect ? "已记录为失败执行，并创建了缺陷" : "已记录为失败执行");
        if (r.defect) navigate(`/defects/${r.defect.id}`);
      },
    },
  );
  const markScript = useApiMutation(() => api(`/cases/${tc.id}/automation/mark-script-issue`, { method: "POST" }), {
    success: "已标记为脚本 / 用例问题",
    onSuccess: refresh,
  });
  const bind = useApiMutation((body: { code_path: string }) => api(`/cases/${tc.id}/bind-code`, { method: "POST", body }), {
    success: "已绑定代码",
    onSuccess: () => {
      setBindOpen(false);
      refresh();
    },
  });

  return (
    <Card size="small" title="执行与自动化" style={{ marginTop: 16 }}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          aria-label="环境"
          style={{ width: 200 }}
          placeholder="选择环境"
          value={environment}
          onChange={setEnvId}
          options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} (${e.base_url})` }))}
        />
        <Select aria-label="执行器" style={{ width: 300 }} value={executor} onChange={setExecutor} options={EXECUTORS} />
        <Tooltip title={environment ? "立即在选定环境中执行一次（不属于任何任务）" : "请先为被测系统添加环境"}>
          <Button type="primary" disabled={!environment || deprecated} loading={debug.isPending} onClick={() => debug.mutate(undefined)}>
            调试执行
          </Button>
        </Tooltip>
        <Button disabled={deprecated} onClick={() => setManualOpen(true)}>
          记录手工执行
        </Button>
        <Tooltip title="Agent 会生成 pytest 脚本并在选定环境中自检；通过后写入该系统的本地测试仓库并绑定；自检失败则只留下草稿">
          <Button disabled={deprecated} loading={automate.isPending} onClick={() => automate.mutate(undefined)}>
            AI 自动化
          </Button>
        </Tooltip>
        <Button disabled={deprecated} onClick={() => setBindOpen(true)}>
          绑定已有代码
        </Button>
      </Space>
      {tc.code_path && (<>
        <Typography.Paragraph>
          <Typography.Text type="secondary">自动化代码： </Typography.Text>
          <Typography.Text code copyable={{ text: tc.code_abs_path || tc.code_path }}>
            {tc.code_abs_path || tc.code_path}
          </Typography.Text>
          {tc.code_commit && <Typography.Text type="secondary"> @ {tc.code_commit.slice(0, 8)} </Typography.Text>}
          <Button size="small" type="link" onClick={() => setViewer("code")}>
            查看代码
          </Button>
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          {tc.code_commit
            ? "将运行已绑定的 Git 版本（含其中的夹具和辅助代码）。要跑更新的版本，请先提交本地更改并重新绑定代码。"
            : "尚未绑定 Git 版本。执行会使用仓库开始时的已提交版本；重新执行前请先提交并绑定更改。"}
        </Typography.Paragraph>
      </>)}
      <EnvironmentStatus env={envs.data?.find((e) => e.id === environment)} />
      {tc.automation_status === "env_unavailable" && (
        <Alert
          type="warning"
          showIcon
          style={{ margin: "12px 0" }}
          title="上次 AI 自动化时被测系统环境不可达（不是脚本问题）"
          description={`${tc.automation_note || ""}；请启动环境后再次点击“AI 自动化”。`}
        />
      )}
      {tc.automation_status === "sut_mismatch" && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          data-testid="sut-mismatch"
          title="自检发现系统表现与预期结果不符（疑似系统问题）；脚本未绑定"
          description={
            <Space orientation="vertical" size={6} style={{ width: "100%" }}>
              {tc.automation_failure ? (
                <FailureSummary summary={tc.automation_failure} versionId={tc.origin_version_id} />
              ) : (
                <span>原因：{tc.automation_note || "未知"}</span>
              )}
              <Typography.Text type="secondary">
                不要靠改断言让测试通过。如果预期是对的，请先记录：绑定脚本后，在系统修复前再次执行仍会失败。
              </Typography.Text>
              <Space wrap>
                <Button
                  type="primary"
                  loading={confirmSut.isPending}
                  onClick={() => confirmSut.mutate({ action: "bind_and_record", create_defect: false })}
                >
                  绑定脚本并记录失败
                </Button>
                <Button loading={confirmSut.isPending} onClick={() => confirmSut.mutate({ action: "bind_and_record", create_defect: true })}>
                  绑定、记录并创建缺陷
                </Button>
                <Button loading={confirmSut.isPending} onClick={() => confirmSut.mutate({ action: "record_only", create_defect: false })}>
                  仅记录失败
                </Button>
                {tc.draft_abs_path && (
                  <Button type="link" onClick={() => setViewer("draft")}>
                    查看草稿
                  </Button>
                )}
                <Button type="link" danger loading={markScript.isPending} onClick={() => markScript.mutate(undefined)}>
                  这是脚本问题
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
          title="自动化待修复：上次自检失败，脚本未绑定到用例"
          description={
            <Space orientation="vertical" size={2}>
              {tc.automation_failure ? (
                <FailureSummary summary={tc.automation_failure} versionId={tc.origin_version_id} />
              ) : (
                <span>原因：{tc.automation_note || "未知"}</span>
              )}
              <span>{fixHint(tc.automation_failure?.kind)}</span>
              {tc.draft_abs_path && (
                <span>
                  草稿： 
                  <Typography.Text code copyable={{ text: tc.draft_abs_path }}>
                    {tc.draft_abs_path}
                  </Typography.Text>
                  <Button size="small" type="link" onClick={() => setViewer("draft")}>
                    查看草稿
                  </Button>
                </span>
              )}
              <span>或手工修正草稿并使用“绑定已有代码”。</span>
            </Space>
          }
        />
      )}
      {(debug.isPending || automate.isPending) && (
        <Typography.Paragraph type="secondary">正在运行；浏览器操作可能需要一两分钟…</Typography.Paragraph>
      )}
      <ListTable<ExecutionRow>
        label="用例执行历史"
        error={history.isError}
        onRetry={() => history.refetch()}
        recordLimit={100}
        size="small"
        rowKey="id"
        loading={history.isLoading}
        dataSource={history.data}
        pagination={{ pageSize: 10, hideOnSinglePage: true }}
        locale={{ emptyText: "暂无执行记录" }}
        columns={[
          { title: "时间", dataIndex: "created_at", render: (v: string, r) => <Link to={`/executions/${r.id}`}>{fmtTime(v, { seconds: true })}</Link> },
          { title: "结果", dataIndex: "status", render: (v: string) => <ExecutionStatusTag status={v} /> },
          { title: "执行器", dataIndex: "executor", render: (v: string) => EXECUTOR_LABEL[v] || v },
          { title: "环境", dataIndex: "environment_name", render: (v?: string) => v || "-" },
          { title: "来源", dataIndex: "task_run_id", render: (v?: string) => (v ? "测试任务" : "Debug/manual") },
          { title: "原因", dataIndex: "suspected_cause", render: (v?: ExecutionRow["suspected_cause"]) => <CauseTag cause={v} /> },
          {
            title: "description",
            render: (_: unknown, r) => (
              <Typography.Text ellipsis style={{ maxWidth: 260 }}>{r.summary?.headline || r.failed_assertion || r.error || ""}</Typography.Text>
            ),
          },
        ]}
      />
      <Modal
        title="记录手工执行结果"
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
          <Form.Item name="status" label="结果" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "passed", label: "通过" },
                { value: "failed", label: "失败" },
                { value: "blocked", label: "阻塞" },
                { value: "skipped", label: "跳过" },
              ]}
            />
          </Form.Item>
          <Form.Item name="environment_id" label="环境">
            <Select allowClear options={(envs.data || []).map((e) => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Form.Item name="result" label="实际结果">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.status !== b.status}>
            {({ getFieldValue }) =>
              getFieldValue("status") === "failed" ? (
                <Form.Item name="failed_assertion" label="未满足的预期" rules={[{ required: true, message: "失败时说明哪条预期未满足" }]}>
                  <Input.TextArea rows={2} />
                </Form.Item>
              ) : getFieldValue("status") === "blocked" ? (
                <Form.Item name="blocked_reason" label="阻塞原因" rules={[{ required: true, message: "请填写阻塞原因" }]}>
                  <Input />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item name="actual_data" label="实际使用的测试数据（JSON，可选）">
            <Input.TextArea rows={2} placeholder='{"amount": 0}' />
          </Form.Item>
          <Form.Item name="duration_min" label="耗时（分钟）">
            <InputNumber min={0} step={0.5} />
          </Form.Item>
          <Form.Item label="附件（截图、日志）">
            <Upload multiple fileList={files} beforeUpload={() => false} onChange={({ fileList }) => setFiles(fileList)}>
              <Button>选择文件</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>
      <CodeViewer caseId={tc.id} draft={viewer === "draft"} open={viewer !== null} onClose={() => setViewer(null)} />
      <Modal
        title="绑定已有自动化代码"
        open={bindOpen}
        onCancel={() => setBindOpen(false)}
        onOk={() => bindForm.submit()}
        confirmLoading={bind.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">请输入测试仓库中已提交文件的路径（位于 tests/ 下）；会固定到当前提交。</Typography.Paragraph>
        <Form form={bindForm} layout="vertical" initialValues={{ code_path: tc.code_path || "" }} onFinish={(v) => bind.mutate(v)}>
          <Form.Item name="code_path" label="代码路径" rules={[{ required: true, pattern: /^tests\/.+\.py$/, message: "必须是 tests/ 下的 .py 文件" }]}>
            <Input placeholder="tests/REQ-001/test_TC-001.py" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
