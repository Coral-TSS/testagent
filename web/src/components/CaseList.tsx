import { CodeOutlined, DownloadOutlined, PlusOutlined, RobotOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Dropdown, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Tooltip } from "antd";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, describeError, download } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AgentConfig, AiOutcome, AutomationProgress as Progress_, BatchResult, CaseRow, Coverage, Environment, Requirement, Task, TestCase } from "../api/types";
import { AutomationProgress } from "./AutomationProgress";
import { AutomationTag } from "./AutomationTag";
import { EmptyState } from "./EmptyState";
import { EnvironmentStatus } from "./EnvironmentStatus";
import { CaseForm, formToBody, type CaseFormValues } from "./CaseForm";
import { CaseStatusTag, ScenarioTag } from "./CaseTags";
import { CoverageView } from "./CoverageView";
import { CaseCoverageTags, coverageSummary } from "./CoverageDetail";
import { CATEGORY_COLOR, CATEGORY_LABEL } from "../utils/categories";

/** P09 case list: filters, manual create, AI generation (in a version), export, coverage report */
export function CaseList({ sutId, versionId, onOpenRun }: { sutId: string; versionId?: string; onOpenRun?: (id: string) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const [status, setStatus] = useState<string>();
  const [reqFilter, setReqFilter] = useState<string>();
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genReqs, setGenReqs] = useState<string[]>([]);
  const [genAutomate, setGenAutomate] = useState<boolean | null>(null);
  const [envId, setEnvId] = useState<string>();
  const config = useQuery({ queryKey: ["agent-config"], queryFn: () => api<AgentConfig>("/agent/config"), enabled: Boolean(versionId) });
  const envs = useQuery({ queryKey: ["environments", sutId], queryFn: () => api<Environment[]>(`/suts/${sutId}/environments`) });
  const automateOn = genAutomate ?? config.data?.auto_automate ?? true;
  const environment = envId || envs.data?.[0]?.id;
  const progress = useQuery({
    queryKey: ["automation", versionId],
    queryFn: () => api<Progress_>(`/versions/${versionId}/automation`),
    enabled: Boolean(versionId),
  });
  // newest job per case: queued / generating
  const jobOf = new Map<string, string>();
  for (const j of progress.data?.jobs || []) if (j.case_id && !jobOf.has(j.case_id)) jobOf.set(j.case_id, j.status);
  const [form] = Form.useForm<CaseFormValues>();
  const [selected, setSelected] = useState<string[]>([]);
  const [taskPick, setTaskPick] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const tasks = useQuery({
    queryKey: ["tasks", versionId],
    queryFn: () => api<Task[]>(`/versions/${versionId}/tasks`),
    enabled: Boolean(versionId) && picking,
  });

  const cases = useQuery({
    queryKey: ["cases", sutId, versionId || null, status || null, reqFilter || null, q],
    queryFn: () => api<CaseRow[]>(`/suts/${sutId}/cases`, { params: { version_id: versionId, status, requirement_id: reqFilter, q } }),
  });
  const reqs = useQuery({
    queryKey: ["requirements", versionId],
    queryFn: () => api<Requirement[]>(`/versions/${versionId}/requirements`),
    enabled: Boolean(versionId),
  });
  const coverage = useQuery({
    queryKey: ["coverage", versionId],
    queryFn: () => api<Coverage>(`/versions/${versionId}/coverage`),
    enabled: Boolean(versionId),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["cases", sutId] });
    qc.invalidateQueries({ queryKey: ["coverage", versionId] });
  };

  const create = useApiMutation((body: Record<string, unknown>) => api<TestCase>(`/suts/${sutId}/cases`, { method: "POST", body }), {
    success: "Case created",
    onSuccess: (c) => {
      setCreating(false);
      form.resetFields();
      refresh();
      navigate(`/cases/${c.id}`);
    },
  });
  const generate = useApiMutation(
    () =>
      api<AiOutcome & { cases?: { id: string }[] }>(`/versions/${versionId}/cases/generate`, {
        method: "POST",
        body: {
          requirement_ids: genReqs.length ? genReqs : null,
          automate: automateOn,
          environment_id: environment || null,
        },
      }),
    {
      onSuccess: (out) => {
        setGenerating(false);
        refresh();
        qc.invalidateQueries({ queryKey: ["automation", versionId] });
        const queued = (out as { automation?: { queued: number } }).automation?.queued || 0;
        if (out.status === "succeeded")
          message.success(
            `Generated ${out.cases?.length ?? 0} draft case(s); review them and set them ready${queued ? `; ${queued} automation script(s) being generated in the background` : ""}`,
          );
        else message.warning(`Generation not finished (${out.error_code || out.status}); see the trace`);
        onOpenRun?.(out.agent_run_id);
      },
    },
  );
  const batch = useApiMutation(
    () =>
      api<{ queued: number }>(`/versions/${versionId}/automate`, {
        method: "POST",
        body: { environment_id: environment || null, include_drafts: true },
      }),
    {
      onSuccess: (r) => {
        qc.invalidateQueries({ queryKey: ["automation", versionId] });
        if (r.queued) message.success(`Queued ${r.queued} case(s); scripts are generated and self-checked one by one in the background`);
        else message.info("No cases need automation (only not-automated, needs-fix or env-unavailable cases are queued)");
      },
    },
  );
  const BATCH_LABEL: Record<string, string> = {
    ready: "Set ready",
    draft: "Set draft",
    deprecated: "Deprecate (archive)",
    automate: "AI automation",
    complete: "AI completion",
    add_to_task: "Add to task",
  };
  const runBatch = useApiMutation(
    (body: { action: string; task_id?: string }) =>
      api<BatchResult>("/cases/batch", {
        method: "POST",
        body: { case_ids: selected, environment_id: environment || null, ...body },
      }),
    {
      onSuccess: (r) => {
        refresh();
        qc.invalidateQueries({ queryKey: ["automation", versionId] });
        qc.invalidateQueries({ queryKey: ["tasks"] });
        setPicking(false);
        const label = BATCH_LABEL[r.action] || r.action;
        const head = `${label}: succeeded ${r.ok.length} ${r.queued ? ` (queued ${r.queued} background job(s))` : ""}${r.skipped.length ? `, skipped ${r.skipped.length} ` : ""}${r.failed.length ? `, failed ${r.failed.length} ` : ""}`;
        if (r.failed.length || r.skipped.length)
          modal.info({
            title: head,
            width: 560,
            content: (
              <ul style={{ paddingInlineStart: 18 }}>
                {r.failed.map((f) => (
                  <li key={f.id}>
                    <Tag color="red">failed</Tag>
                    {f.code || f.id}: {f.error}
                  </li>
                ))}
                {r.skipped.map((f) => (
                  <li key={f.id}>
                    <Tag>Skipped</Tag>
                    {f.code}: {f.reason}
                  </li>
                ))}
              </ul>
            ),
          });
        else message.success(head);
        if (!r.failed.length) setSelected([]);
      },
    },
  );
  const exportAs = async (format: "csv" | "md") => {
    try {
      await download(`/versions/${versionId}/cases/export`, { format }, `cases.${format}`);
    } catch (err) {
      message.error(describeError(err));
    }
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size={16}>
      {versionId && coverage.data && <CoverageView coverage={coverage.data} />}
      {versionId && <EnvironmentStatus env={envs.data?.find((e) => e.id === environment)} />}
      {versionId && <AutomationProgress versionId={versionId} onChanged={refresh} />}
      <Space wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
          New case
        </Button>
        {versionId && (
          <>
            <Button icon={<RobotOutlined />} onClick={() => setGenerating(true)}>
              AI generate cases
            </Button>
            <Tooltip title="In the background, generate and self-check automation scripts one by one for this version's cases that are not automated yet (draft and ready) and for needs-fix and env-unavailable cases">
              <Button icon={<CodeOutlined />} loading={batch.isPending} onClick={() => batch.mutate(undefined)}>
                AI automate unautomated cases
              </Button>
            </Tooltip>
            <Dropdown
              menu={{
                items: [
                  { key: "csv", label: "Export CSV (Excel)" },
                  { key: "md", label: "Export Markdown" },
                ],
                onClick: ({ key }) => exportAs(key as "csv" | "md"),
              }}
            >
              <Button icon={<DownloadOutlined />}>Export list</Button>
            </Dropdown>
          </>
        )}
        <Select allowClear placeholder="All states" style={{ width: 120 }} value={status} onChange={setStatus} options={[
          { value: "draft", label: "Draft" },
          { value: "ready", label: "Ready" },
          { value: "deprecated", label: "Deprecated" },
        ]} />
        {versionId && (
          <Select allowClear placeholder="All requirements" style={{ width: 220 }} value={reqFilter} onChange={setReqFilter} optionFilterProp="label" showSearch
            options={(reqs.data || []).map((r) => ({ value: r.id, label: `${r.code} ${r.title}` }))} />
        )}
        <Input.Search placeholder="Code/title/test point" allowClear onSearch={setQ} style={{ width: 220 }} />
      </Space>
      {selected.length > 0 && (
        <Space wrap data-testid="batch-bar" style={{ background: "#f6ffed", border: "1px solid #b7eb8f", borderRadius: 6, padding: "6px 12px" }}>
          <span>Selected {selected.length} case(s): </span>
          <Popconfirm title={`Set ${selected.length} case(s) ready?`} description="Same as approving each one after review; only ready cases are run by tasks." onConfirm={() => runBatch.mutate({ action: "ready" })}>
            <Button size="small" type="primary" loading={runBatch.isPending}>
              Set ready
            </Button>
          </Popconfirm>
          <Button size="small" onClick={() => runBatch.mutate({ action: "draft" })}>
            Set draft
          </Button>
          <Tooltip title="Scripts are generated and self-checked one by one in the background">
            <Button size="small" icon={<CodeOutlined />} onClick={() => runBatch.mutate({ action: "automate" })}>
              AI automation
            </Button>
          </Tooltip>
          <Tooltip title="Completion suggestions (steps / expected / test data / links) are generated one by one in the background; accept them item by item on the case page">
            <Button size="small" icon={<RobotOutlined />} onClick={() => runBatch.mutate({ action: "complete" })}>
              AI completion
            </Button>
          </Tooltip>
          {versionId && (
            <Button size="small" onClick={() => setPicking(true)}>
              Add to task
            </Button>
          )}
          <Popconfirm
            title={`Deprecate ${selected.length} case(s)?`}
            description="Deprecated cases are read-only and no longer run (a draft must be set ready before it can be deprecated); records are kept, never deleted."
            okButtonProps={{ danger: true }}
            onConfirm={() => runBatch.mutate({ action: "deprecated" })}
          >
            <Button size="small" danger>
              Deprecate (archive)
            </Button>
          </Popconfirm>
          <Button size="small" type="link" onClick={() => setSelected([])}>
            Clear selection
          </Button>
        </Space>
      )}
      <Table<CaseRow>
        size="small"
        rowKey="id"
        rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]) }}
        loading={cases.isLoading}
        dataSource={cases.data}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        locale={{
          emptyText:
            status || reqFilter || q ? (
              "No cases match the filters"
            ) : (
              <EmptyState
                title="No cases yet"
                hint={
                  versionId
                    ? "Cases are generated from confirmed requirements: click “AI generate cases” to let the AI draft them from the requirements and the model (then a person reviews them and sets them ready), or create one by hand."
                    : "Generate cases per requirement under “Test cases & coverage” on the version page, or create one by hand here."
                }
                actionLabel={versionId ? "AI generate cases" : "New case"}
                onAction={() => (versionId ? setGenerating(true) : setCreating(true))}
              />
            ),
        }}
        columns={[
          { title: "Code", dataIndex: "code", width: 90, render: (c, r) => <Link to={`/cases/${r.id}`}>{c}</Link> },
          { title: "Title", dataIndex: "title" },
          { title: "Test point", dataIndex: "test_point", ellipsis: true },
          { title: "Requirement", dataIndex: "requirement_codes", render: (codes: string[]) => codes.map((c) => <Tag key={c}>{c}</Tag>) },
          {
            title: "Coverage",
            width: 150,
            render: (_, r) => (
              <Tooltip
                color="white"
                styles={{ root: { maxWidth: 520 } }}
                title={r.coverage ? <CaseCoverageTags coverage={r.coverage} sutId={sutId} /> : null}
              >
                <span data-testid={`coverage-${r.code}`} style={{ cursor: "help", borderBottom: "1px dashed #bbb" }}>
                  {coverageSummary(r.coverage)}
                </span>
              </Tooltip>
            ),
          },
          {
            title: "category",
            dataIndex: "category",
            width: 100,
            filters: Object.entries(CATEGORY_LABEL).map(([value, text]) => ({ value, text })),
            onFilter: (v, r) => (r.category || "requirement") === v,
            render: (cat: CaseRow["category"], r) => (
              <Space size={2} wrap>
                <Tag color={CATEGORY_COLOR[cat || "requirement"]}>{CATEGORY_LABEL[cat || "requirement"]}</Tag>
                {r.category_suggestion && (
                  <Tooltip title={`Suggested: ${CATEGORY_LABEL[r.category_suggestion.category]}: ${r.category_suggestion.reason || ""} (confirm in the case detail)`}>
                    <Tag color="orange" data-testid={`suggest-${r.code}`}>
                      To confirm
                    </Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          { title: "Scenario", dataIndex: "scenario", width: 70, render: (s) => <ScenarioTag value={s} /> },
          { title: "Priority", dataIndex: "priority", width: 60 },
          { title: "Source", dataIndex: "source", width: 70, render: (s) => (s === "agent" ? <Tag color="purple">AI</Tag> : "Manual") },
          { title: "Status", dataIndex: "status", width: 80, render: (s) => <CaseStatusTag status={s} /> },
          {
            title: "Automated",
            width: 110,
            render: (_, r) => <AutomationTag row={r} job={jobOf.get(r.id)} />,
          },
          { title: "Rev", dataIndex: "revision", width: 60 },
        ]}
      />
      <Modal
        title="New case"
        open={creating}
        width={860}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        forceRender
      >
        <CaseForm
          form={form}
          sutId={sutId}
          versionId={versionId}
          onFinish={(v) => {
            const { body, error } = formToBody(v);
            if (error) return message.error(error);
            create.mutate({ ...body!, ...(versionId ? { origin_version_id: versionId } : {}) });
          }}
        />
      </Modal>
      <Modal
        title={`Add ${selected.length} case(s) to a task`}
        open={picking}
        onCancel={() => setPicking(false)}
        okText="Add"
        okButtonProps={{ disabled: !taskPick }}
        confirmLoading={runBatch.isPending}
        onOk={() => taskPick && runBatch.mutate({ action: "add_to_task", task_id: taskPick })}
      >
        <p>Appended to the end of the task; cases already in the task are skipped, deprecated cases cannot be added.</p>
        <Select
          aria-label="Choose task"
          style={{ width: "100%" }}
          placeholder="Choose a task of this version"
          loading={tasks.isLoading}
          value={taskPick}
          onChange={setTaskPick}
          options={(tasks.data || []).filter((t) => !["running", "archived"].includes(t.status)).map((t) => ({ value: t.id, label: t.name }))}
        />
      </Modal>
      <Modal
        title="AI generate cases"
        open={generating}
        onCancel={() => setGenerating(false)}
        onOk={() => generate.mutate()}
        confirmLoading={generate.isPending}
        okText="Generate"
      >
        <p>At least 3 cases are generated per requirement (normal / boundary / exception), linked to requirements, model nodes and fields; API steps build request bodies from the registered schema. Results are drafts and need human review before they are set ready.</p>
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder="Leave empty for all requirements of this version"
          value={genReqs}
          onChange={setGenReqs}
          optionFilterProp="label"
          options={(reqs.data || []).map((r) => ({ value: r.id, label: `${r.code} ${r.title}` }))}
        />
        <div style={{ marginTop: 12 }}>
          <Checkbox checked={automateOn} onChange={(e) => setGenAutomate(e.target.checked)}>
            Also generate an automation script for each case (in the background, with self-check)
          </Checkbox>
        </div>
        {automateOn && (
          <Select
            aria-label="Self-check environment"
            style={{ width: "100%", marginTop: 8 }}
            placeholder="Self-check environment (without one only drafts are generated, marked needs fix)"
            value={environment}
            onChange={setEnvId}
            options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} (${e.base_url})` }))}
          />
        )}
      </Modal>
    </Space>
  );
}
