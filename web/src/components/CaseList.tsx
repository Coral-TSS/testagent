import { CodeOutlined, DownloadOutlined, PlusOutlined, RobotOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Dropdown, Form, Input, Modal, Popconfirm, Select, Space, Tag, Tooltip } from "antd";
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
import { ReadyTaskFeedback } from "./ReadyTaskFeedback";
import { ListTable } from "./ListView";

/** P09 case list: filters, manual create, AI generation (in a version), export, coverage report */
export function CaseList({ sutId, versionId, onOpenRun }: { sutId: string; versionId?: string; onOpenRun?: (id: string) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const [status, setStatus] = useState<string>();
  const [reqFilter, setReqFilter] = useState<string>();
  const [q, setQ] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
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
  // Share the unfiltered query key: the first view fetches once, and filters retain its scoped total.
  const allCases = useQuery({
    queryKey: ["cases", sutId, versionId || null, null, null, ""],
    queryFn: () => api<CaseRow[]>(`/suts/${sutId}/cases`, { params: { version_id: versionId } }),
  });
  const shownCases = cases.data?.filter((row) => !categories.length || categories.includes(row.category || "requirement"));
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
    success: "用例已创建",
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
            `已生成 ${out.cases?.length ?? 0} 条草稿用例；请评审并设为就绪${queued ? `；${queued} 个自动化脚本正在后台生成` : ""}`,
          );
        else message.warning(`生成未完成（${out.error_code || out.status}）；请查看追踪`);
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
        if (r.queued) message.success(`已排队 ${r.queued} 条用例；脚本将在后台逐条生成并自检`);
        else message.info("没有需要自动化的用例（只会排队未自动化、待修复或环境不可用的用例）");
      },
    },
  );
  const BATCH_LABEL: Record<string, string> = {
    ready: "设为就绪",
    draft: "设为草稿",
    deprecated: "废弃（归档）",
    automate: "AI 自动化",
    complete: "AI 补全",
    add_to_task: "加入任务",
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
        const head = `${label}：成功 ${r.ok.length}${r.queued ? `（已排队 ${r.queued} 个后台任务）` : ""}${r.skipped.length ? `，跳过 ${r.skipped.length}` : ""}${r.failed.length ? `，失败 ${r.failed.length}` : ""}`;
        if (r.failed.length || r.skipped.length || r.action === "ready") {
          const resultDialog = modal.info({
            title: head,
            width: r.action === "ready" ? 760 : 560,
            content: (
              <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
              {r.action === "ready" && [...r.ok, ...r.skipped].map((row) => (
                <div key={row.id} style={{ marginBottom: 12 }}>
                  {row.task_binding ? <ReadyTaskFeedback feedback={row.task_binding} onNavigate={(path) => { resultDialog.destroy(); navigate(path); }} /> : `${row.code}：无法显示任务关联详情；请打开该用例查看其关联。`}
                </div>
              ))}
              <ul style={{ paddingInlineStart: 18 }}>
                {r.failed.map((f) => (
                  <li key={f.id}>
                    <Tag color="red">失败</Tag>
                    {f.code || f.id}: {f.error}
                  </li>
                ))}
                {r.skipped.map((f) => (
                  <li key={f.id}>
                    <Tag>跳过</Tag>
                    {f.code}: {f.reason}
                  </li>
                ))}
              </ul>
              </div>
            ),
          });
        } else message.success(head);
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
          新建用例
        </Button>
        {versionId && (
          <>
            <Button icon={<RobotOutlined />} onClick={() => setGenerating(true)}>
              AI 生成用例
            </Button>
            <Tooltip title="在后台逐条为本版本尚未自动化的用例（草稿和就绪）以及待修复、环境不可用的用例生成并自检自动化脚本">
              <Button icon={<CodeOutlined />} loading={batch.isPending} onClick={() => batch.mutate(undefined)}>
                AI 自动化尚未自动化的用例
              </Button>
            </Tooltip>
            <Dropdown
              menu={{
                items: [
                  { key: "csv", label: "导出 CSV（Excel）" },
                  { key: "md", label: "导出 Markdown" },
                ],
                onClick: ({ key }) => exportAs(key as "csv" | "md"),
              }}
            >
              <Button icon={<DownloadOutlined />}>导出列表</Button>
            </Dropdown>
          </>
        )}
        <Select allowClear placeholder="全部状态" style={{ width: 120 }} value={status} onChange={setStatus} options={[
          { value: "draft", label: "草稿" },
          { value: "ready", label: "就绪" },
          { value: "deprecated", label: "已废弃" },
        ]} />
        {versionId && (
          <Select allowClear placeholder="全部需求" style={{ width: 220 }} value={reqFilter} onChange={setReqFilter} optionFilterProp="label" showSearch
            options={(reqs.data || []).map((r) => ({ value: r.id, label: `${r.code} ${r.title}` }))} />
        )}
        <Input.Search placeholder="编号/标题/测试点" allowClear onSearch={setQ} style={{ width: 220 }} />
      </Space>
      {selected.length > 0 && (
        <Space wrap data-testid="batch-bar" style={{ background: "#f6ffed", border: "1px solid #b7eb8f", borderRadius: 6, padding: "6px 12px" }}>
          <span>已选 {selected.length} 个用例：</span>
          <Popconfirm title={`将 ${selected.length} 个用例设为就绪？`} description="等同于评审后逐条批准；只有就绪用例会被任务执行。" onConfirm={() => runBatch.mutate({ action: "ready" })}>
            <Button size="small" type="primary" loading={runBatch.isPending}>
              设为就绪
            </Button>
          </Popconfirm>
          <Button size="small" onClick={() => runBatch.mutate({ action: "draft" })}>
            设为草稿
          </Button>
          <Tooltip title="脚本会在后台逐条生成并自检">
            <Button size="small" icon={<CodeOutlined />} onClick={() => runBatch.mutate({ action: "automate" })}>
              AI 自动化
            </Button>
          </Tooltip>
          <Tooltip title="补全建议（步骤 / 预期 / 测试数据 / 关联）会在后台逐条生成；请在用例页逐项接受">
            <Button size="small" icon={<RobotOutlined />} onClick={() => runBatch.mutate({ action: "complete" })}>
              AI 补全
            </Button>
          </Tooltip>
          {versionId && (
            <Button size="small" onClick={() => setPicking(true)}>
              加入任务
            </Button>
          )}
          <Popconfirm
            title={`废弃 ${selected.length} 个用例？`}
            description="已废弃的用例只读且不再执行（草稿必须先设为就绪才能废弃）；记录会保留，不会删除。"
            okButtonProps={{ danger: true }}
            onConfirm={() => runBatch.mutate({ action: "deprecated" })}
          >
            <Button size="small" danger>
              废弃（归档）
            </Button>
          </Popconfirm>
          <Button size="small" type="link" onClick={() => setSelected([])}>
            清除选择
          </Button>
        </Space>
      )}
      <ListTable<CaseRow>
        label="测试用例"
        total={allCases.data?.length}
        filtered={Boolean(status || reqFilter || q || categories.length)}
        error={cases.isError || allCases.isError}
        onRetry={() => { cases.refetch(); if (status || reqFilter || q) allCases.refetch(); }}
        size="small"
        rowKey="id"
        rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]) }}
        loading={cases.isLoading}
        dataSource={shownCases}
        onChange={(_, filters) => setCategories((filters.category || []).map(String))}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        locale={{
          emptyText:
            status || reqFilter || q ? (
              "没有符合筛选条件的用例"
            ) : (
              <EmptyState
                title="暂无测试用例"
                hint={
                  versionId
                    ? "用例从已确认的需求生成：点击“AI 生成用例”，让 AI 根据需求和模型起草（再由人评审并设为就绪），或手工创建。"
                    : "请在版本页的“测试用例与覆盖”下按需求生成用例，或在此手工创建。"
                }
                actionLabel={versionId ? "AI 生成用例" : "新建用例"}
                onAction={() => (versionId ? setGenerating(true) : setCreating(true))}
              />
            ),
        }}
        columns={[
          { title: "编号", dataIndex: "code", width: 90, render: (c, r) => <Link to={`/cases/${r.id}`}>{c}</Link> },
          { title: "标题", dataIndex: "title" },
          { title: "测试点", dataIndex: "test_point", ellipsis: true },
          { title: "需求", dataIndex: "requirement_codes", render: (codes: string[]) => codes.map((c) => <Tag key={c}>{c}</Tag>) },
          {
            title: "覆盖",
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
            title: "类别",
            dataIndex: "category",
            width: 100,
            filters: Object.entries(CATEGORY_LABEL).map(([value, text]) => ({ value, text })),
            filteredValue: categories,
            render: (cat: CaseRow["category"], r) => (
              <Space size={2} wrap>
                <Tag color={CATEGORY_COLOR[cat || "requirement"]}>{CATEGORY_LABEL[cat || "requirement"]}</Tag>
                {r.category_suggestion && (
                  <Tooltip title={`建议：${CATEGORY_LABEL[r.category_suggestion.category]}：${r.category_suggestion.reason || ""}（请在用例详情中确认）`}>
                    <Tag color="orange" data-testid={`suggest-${r.code}`}>
                      待确认
                    </Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          { title: "场景", dataIndex: "scenario", width: 70, render: (s) => <ScenarioTag value={s} /> },
          { title: "优先级", dataIndex: "priority", width: 60 },
          { title: "来源", dataIndex: "source", width: 70, render: (s) => (s === "agent" ? <Tag color="purple">AI</Tag> : "手工") },
          { title: "状态", dataIndex: "status", width: 80, render: (s) => <CaseStatusTag status={s} /> },
          {
            title: "已自动化",
            width: 110,
            render: (_, r) => <AutomationTag row={r} job={jobOf.get(r.id)} />,
          },
          { title: "修订", dataIndex: "revision", width: 60 },
        ]}
      />
      <Modal
        title="新建用例"
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
        title={`将 ${selected.length} 个用例加入任务`}
        open={picking}
        onCancel={() => setPicking(false)}
        okText="添加"
        okButtonProps={{ disabled: !taskPick }}
        confirmLoading={runBatch.isPending}
        onOk={() => taskPick && runBatch.mutate({ action: "add_to_task", task_id: taskPick })}
      >
        <p>将追加到任务末尾；已在任务中的用例会跳过，已废弃的用例不能添加。</p>
        <Select
          aria-label="选择任务"
          style={{ width: "100%" }}
          placeholder="选择该版本的任务"
          loading={tasks.isLoading}
          value={taskPick}
          onChange={setTaskPick}
          options={(tasks.data || []).filter((t) => !["running", "archived"].includes(t.status)).map((t) => ({ value: t.id, label: t.name }))}
        />
      </Modal>
      <Modal
        title="AI 生成用例"
        open={generating}
        onCancel={() => setGenerating(false)}
        onOk={() => generate.mutate()}
        confirmLoading={generate.isPending}
        okText="生成"
      >
        <p>每个需求至少生成 3 条用例（正常 / 边界 / 异常），并关联到需求、模型节点和字段；API 步骤会根据已登记的模式构造请求体。结果为草稿，设为就绪前需要人工评审。</p>
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder="留空表示该版本的全部需求"
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
            aria-label="自检环境"
            style={{ width: "100%", marginTop: 8 }}
            placeholder="自检环境（没有环境时只会生成草稿，并标记为待修复）"
            value={environment}
            onChange={setEnvId}
            options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} (${e.base_url})` }))}
          />
        )}
      </Modal>
    </Space>
  );
}
