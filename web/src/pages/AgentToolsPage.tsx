import { ListTable, listTitle } from "../components/ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Form, Input, Modal, Row, Select, Space, Switch, Tabs, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AgentMemory, Correction, McpServer, PromptSummary, PromptVersion, SkillItem } from "../api/types";
import { AgentRunDrawer, PURPOSE } from "../components/AgentRunDrawer";
import { CorrectionStatusTag } from "../components/CorrectionButton";
import { fmtTime } from "../utils/time";

const promptLabel = (name: string) => (name === "system" ? "系统提示词（全部条目）" : `${PURPOSE[name] || name} (${name})`);
const byLabel = (by: string) => (by.startsWith("agent:") ? <Tag color="purple">AI 已处理</Tag> : by === "system" ? <Tag>内置</Tag> : <Tag color="blue">{by}</Tag>);
const TARGET_LABEL: Record<string, string> = {
  case: "用例",
  strategy: "策略",
  requirement: "需求",
  execution: "执行",
  report: "报告",
  agent_run: "Agent 运行",
  task_run: "执行",
  version: "版本",
};
const TARGET_LINK: Record<string, (id: string) => string> = {
  case: (id) => `/cases/${id}`,
  execution: (id) => `/executions/${id}`,
  report: (id) => `/reports/${id}`,
  task_run: (id) => `/runs/${id}`,
  version: (id) => `/versions/${id}`,
};

type CountSink = (count: number | undefined) => void;
function useTabCount(count: number | undefined, onCount?: CountSink) {
  useEffect(() => onCount?.(count), [count, onCount]);
}

// ------------------------------------------------------------------ prompts
function PromptsTab({ onOpenRun, onCount }: { onOpenRun: (id: string) => void; onCount?: CountSink }) {
  const qc = useQueryClient();
  const { modal } = App.useApp();
  const [selected, setSelected] = useState("system");
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const list = useQuery({ queryKey: ["prompts"], queryFn: () => api<PromptSummary[]>("/agent/prompts") });
  useTabCount(list.data?.length, onCount);
  const versions = useQuery({ queryKey: ["prompt", selected], queryFn: () => api<PromptVersion[]>(`/agent/prompts/${selected}`) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["prompts"] });
    qc.invalidateQueries({ queryKey: ["prompt", selected] });
  };
  const activate = useApiMutation((v: number) => api(`/agent/prompts/${selected}/versions/${v}/activate`, { method: "POST" }), { success: "已切换活动版本", onSuccess: refresh });
  const create = useApiMutation(() => api(`/agent/prompts/${selected}/versions`, { method: "POST", body: { content: editing, note: note || null } }), {
    success: "已另存为新版本并启用",
    onSuccess: () => {
      setEditing(null);
      setNote("");
      refresh();
    },
  });
  const current = list.data?.find((p) => p.name === selected);
  return (
    <Row gutter={16}>
      <Col span={8}>
        <ListTable<PromptSummary>
          label="提示词"
          error={list.isError}
          onRetry={() => list.refetch()}
          size="small"
          rowKey="name"

          loading={list.isLoading}
          dataSource={list.data}
          onRow={(p) => ({ onClick: () => setSelected(p.name), style: { cursor: "pointer", background: p.name === selected ? "#e6f4ff" : undefined } })}
          columns={[
            { title: "提示词", dataIndex: "name", render: (v: string) => promptLabel(v) },
            { title: "当前版本", dataIndex: "active_version", width: 90, render: (v: number | null, p) => (p.is_default ? <Tag>内置默认</Tag> : `v${v}`) },
          ]}
        />
      </Col>
      <Col span={16}>
        <Card
          size="small"
          title={promptLabel(selected)}
          extra={
            <Button onClick={() => setEditing(current?.content ?? "")} disabled={!current}>
              编辑为新版本
            </Button>
          }
        >
          <Typography.Paragraph type="secondary">
            Assembly order: system prompt → entry description → extra guidance for this entry → enabled memories → context. Patches from corrections create a new version that takes effect immediately; you can switch back to any older version at any time (roll back).
          </Typography.Paragraph>
          <ListTable<PromptVersion>
            label="提示词版本"
            error={versions.isError}
            onRetry={() => versions.refetch()}
            size="small"
            rowKey="id"
            loading={versions.isLoading}
            dataSource={versions.data}
            locale={{ emptyText: "尚无版本：正在使用内置默认" }}
            expandable={{ expandedRowRender: (v) => <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{v.content || "（空：没有额外指引）"}</pre> }}
            columns={[
              { title: "版本", dataIndex: "version", width: 70, render: (v: number, r) => <Space>v{v}{r.active && <Tag color="green">正常</Tag>}</Space> },
              { title: "来源", dataIndex: "created_by", width: 100, render: byLabel },
              { title: "description", dataIndex: "note", render: (v: string | null, r) => <Space>{v || "-"}{r.source_correction_ids.length > 0 && <Tag>From {r.source_correction_ids.length} correction(s)</Tag>}</Space> },
              { title: "时间", dataIndex: "created_at", width: 140, render: (v: string) => fmtTime(v) },
              {
                title: "",
                key: "ops",
                width: 170,
                render: (_: unknown, r) => (
                  <Space>
                    {r.agent_run_id && <Button size="small" type="link" onClick={() => onOpenRun(r.agent_run_id!)}>追踪</Button>}
                    {!r.active && (
                      <Button
                        size="small"
                        onClick={() => modal.confirm({ title: `Switch to v${r.version}? `, content: "后续 Agent 运行将使用此版本。", onOk: () => activate.mutateAsync(r.version) })}
                      >
                        回滚到此版本
                      </Button>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      </Col>
      <Modal title={`Edit ${promptLabel(selected)}`} open={editing !== null} onCancel={() => setEditing(null)} onOk={() => create.mutate()} okText="另存为新版本" confirmLoading={create.isPending} width={720}>
        <Input.TextArea aria-label="提示词内容" rows={14} value={editing ?? ""} onChange={(e) => setEditing(e.target.value)} />
        <Input aria-label="版本说明" style={{ marginTop: 8 }} placeholder="版本说明（可选）" value={note} onChange={(e) => setNote(e.target.value)} />
      </Modal>
    </Row>
  );
}

// ------------------------------------------------------------------ memories
function MemoriesTab({ onOpenRun, onCount }: { onOpenRun: (id: string) => void; onCount?: CountSink }) {
  const [enabled, setEnabled] = useState<string>();
  const q = useQuery({ queryKey: ["memories", enabled], queryFn: () => api<AgentMemory[]>("/agent/memories", { params: { enabled } }) });
  useTabCount(q.data?.length, onCount);
  const toggle = useApiMutation((v: { id: string; enabled: boolean }) => api(`/agent/memories/${v.id}`, { method: "PATCH", body: { enabled: v.enabled } }), {
    invalidate: [["memories"]],
    success: "已更新",
  });
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="全部状态" style={{ width: 120 }} value={enabled} onChange={setEnabled} options={[{ value: "true", label: "启用" }, { value: "false", label: "已停用" }]} />
        <Typography.Text type="secondary">已启用的记忆会在后续匹配的 Agent 运行中注入（全局 + 当前系统，最多 20 条）；已停用的不再注入。</Typography.Text>
      </Space>
      <ListTable<AgentMemory>
        label="记忆"
        error={q.isError}
        onRetry={() => q.refetch()}
        recordLimit={500}
        size="small"
        rowKey="id"
        loading={q.isLoading}
        dataSource={q.data}
        locale={{ emptyText: "还没有记忆：提交纠正后，Agent 会自动创建" }}
        columns={[
          { title: "内容", dataIndex: "content", render: (v: string) => <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{v}</Typography.Paragraph> },
          { title: "范围", dataIndex: "scope", width: 110, render: (v: string, m) => (v === "global" ? <Tag>全局</Tag> : <Tag color="blue">{m.sut_code || "系统"}</Tag>) },
          { title: "条目", dataIndex: "tags", width: 160, render: (v: string[]) => (v.length ? v.map((t) => <Tag key={t}>{PURPOSE[t] || t}</Tag>) : "全部") },
          {
            title: "来源",
            key: "src",
            width: 150,
            render: (_: unknown, m) => (
              <Space>
                {byLabel(m.created_by)}
                {m.source_correction_ids.length > 0 && <Link to={`/agent/tools?tab=corrections&id=${m.source_correction_ids[0]}`}>纠正</Link>}
                {m.agent_run_id && <Button size="small" type="link" onClick={() => onOpenRun(m.agent_run_id!)}>追踪</Button>}
              </Space>
            ),
          },
          { title: "时间", dataIndex: "created_at", width: 130, render: (v: string) => fmtTime(v) },
          {
            title: "启用",
            dataIndex: "enabled",
            width: 70,
            render: (v: boolean, m) => <Switch aria-label={`Enable memory ${m.content.slice(0, 10)}`} size="small" checked={v} onChange={(checked) => toggle.mutate({ id: m.id, enabled: checked })} />,
          },
        ]}
      />
    </>
  );
}

// ------------------------------------------------------------------ corrections
function CorrectionsTab({ onOpenRun, highlight, onCount }: { onOpenRun: (id: string) => void; highlight?: string | null; onCount?: CountSink }) {
  const [status, setStatus] = useState<string>();
  const [kind, setKind] = useState<string>();
  const q = useQuery({
    queryKey: ["corrections", "all", status, kind],
    queryFn: () => api<Correction[]>("/corrections", { params: { status, kind } }),
    refetchInterval: (query) => (query.state.data?.some((c) => c.status === "pending" || c.status === "processing") ? 3000 : false),
  });
  useTabCount(q.data?.length, onCount);
  const reprocess = useApiMutation((id: string) => api(`/corrections/${id}/reprocess`, { method: "POST" }), { invalidate: [["corrections"]], success: "已重新提交处理" });
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="全部状态" style={{ width: 120 }} value={status} onChange={setStatus} options={["pending", "processing", "processed", "failed"].map((v) => ({ value: v, label: <CorrectionStatusTag status={v} /> }))} />
        <Select allowClear placeholder="全部类型" style={{ width: 120 }} value={kind} onChange={setKind} options={[{ value: "correction", label: "纠正" }, { value: "omission", label: "漏测" }]} />
      </Space>
      <ListTable<Correction>
        label="纠正"
        error={q.isError}
        onRetry={() => q.refetch()}
        recordLimit={200}
        size="small"
        rowKey="id"
        loading={q.isLoading}
        dataSource={q.data}
        rowClassName={(c) => (c.id === highlight ? "ant-table-row-selected" : "")}
        locale={{ emptyText: "还没有纠正：请在用例、策略、执行或报告页点击“纠正”，或在执行页点击“报告漏测”" }}
        columns={[
          { title: "原文", dataIndex: "content", render: (v: string) => <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{v}</Typography.Paragraph> },
          {
            title: "对象",
            key: "target",
            width: 220,
            render: (_: unknown, c) => {
              const text = c.target_label || TARGET_LABEL[c.target_type] || c.target_type;
              const link = TARGET_LINK[c.target_type]?.(c.target_id);
              return (
                <Space direction="vertical" size={0}>
                  <Space size={4}>
                    {c.kind === "omission" && <Tag color="orange">漏测</Tag>}
                    {link ? <Link to={link}>{text}</Link> : text}
                  </Space>
                  {c.sut_code && <Typography.Text type="secondary">{c.sut_code}</Typography.Text>}
                </Space>
              );
            },
          },
          {
            title: "处理中",
            key: "status",
            width: 220,
            render: (_: unknown, c) => (
              <Space direction="vertical" size={2}>
                <Space>
                  <CorrectionStatusTag status={c.status} />
                  {c.attempts > 1 && <Typography.Text type="secondary">v {c.attempts} time(s)</Typography.Text>}
                </Space>
                {c.status === "processed" && (
                  <Typography.Text type="secondary">
                    {(c.outputs.memory_ids?.length || 0) > 0 && `记忆 ${c.outputs.memory_ids!.length} 项 `}
                    {(c.outputs.prompt_versions || []).map((p) => `${p.name} v${p.version}`).join(", ")}
                  </Typography.Text>
                )}
                {c.status === "failed" && <Typography.Text type="danger">{c.error}</Typography.Text>}
              </Space>
            ),
          },
          { title: "提交", dataIndex: "created_at", width: 130, render: (v: string, c) => `${fmtTime(v)} ${c.author}` },
          {
            title: "",
            key: "ops",
            width: 150,
            render: (_: unknown, c) => (
              <Space>
                {c.agent_run_id && <Button size="small" type="link" onClick={() => onOpenRun(c.agent_run_id!)}>追踪</Button>}
                {c.status !== "processing" && (
                  <Button size="small" onClick={() => reprocess.mutate(c.id)}>
                    再次处理
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
    </>
  );
}

// ------------------------------------------------------------------ skills / MCP
function RegistryTab<T extends SkillItem | McpServer>({ path, kind, onCount }: { path: string; kind: "skill" | "mcp"; onCount?: CountSink }) {
  const [form] = Form.useForm();
  const [open, setOpen] = useState(false);
  const key = ["registry", path];
  const q = useQuery({ queryKey: key, queryFn: () => api<T[]>(path) });
  useTabCount(q.data?.length, onCount);
  const create = useApiMutation((body: Record<string, unknown>) => api(path, { method: "POST", body }), {
    invalidate: [key],
    success: "已登记",
    onSuccess: () => {
      setOpen(false);
      form.resetFields();
    },
  });
  const toggle = useApiMutation((v: { id: string; enabled: boolean }) => api(`${path}/${v.id}`, { method: "PATCH", body: { enabled: v.enabled } }), { invalidate: [key] });
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message={`This version only registers and disables ${kind === "skill" ? "skills" : " 个 MCP 服务器"}; they are never loaded or executed (C07). The agent'的浏览器能力来自平台's built-in Playwright tools.`} />
      <Button type="primary" style={{ marginBottom: 12 }} onClick={() => setOpen(true)}>
        {kind === "skill" ? "登记技能" : "登记 MCP 服务器"}
      </Button>
      <ListTable<T>
        label={kind === "skill" ? "技能" : "MCP 服务器"}
        error={q.isError}
        onRetry={() => q.refetch()}
        size="small"
        rowKey="id"
        loading={q.isLoading}
        dataSource={q.data}
        locale={{ emptyText: "尚未登记" }}
        columns={[
          { title: "名称", dataIndex: "name" },
          ...(kind === "mcp"
            ? [
                { title: "传输", dataIndex: "transport", width: 80 },
                { title: "命令 / URL", key: "cmd", render: (_: unknown, r: T) => (r as McpServer).command || (r as McpServer).url || "-" },
              ]
            : [{ title: "来源", dataIndex: "source", render: (v: string | null) => v || "-" }]),
          { title: "description", dataIndex: "description", render: (v: string | null) => v || "-" },
          { title: "启用", dataIndex: "enabled", width: 70, render: (v: boolean, r: T) => <Switch size="small" checked={v} onChange={(checked) => toggle.mutate({ id: r.id, enabled: checked })} /> },
        ]}
      />
      <Modal title={kind === "skill" ? "登记技能" : "登记 MCP 服务器"} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={create.isPending}>
        <Form form={form} layout="vertical" initialValues={kind === "mcp" ? { transport: "stdio" } : {}} onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input />
          </Form.Item>
          {kind === "mcp" ? (
            <>
              <Form.Item name="transport" label="传输">
                <Select options={[{ value: "stdio", label: "stdio" }, { value: "http", label: "http" }]} />
              </Form.Item>
              <Form.Item name="command" label="命令（stdio）">
                <Input />
              </Form.Item>
              <Form.Item name="url" label="URL（http）">
                <Input />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="source" label="来源（路径或链接）">
              <Input />
            </Form.Item>
          )}
          <Form.Item name="description" label="description">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

/** P15 agent tools: prompts (versions/rollback), memories (view/disable), corrections, skill and MCP registry, trace entry */
export function AgentToolsPage() {
  const [params, setParams] = useSearchParams();
  const [runId, setRunId] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number | undefined>>({});
  const countSinks = useMemo(() => Object.fromEntries(["prompts", "memories", "corrections", "skills", "mcp"].map((key) => [key, (count: number | undefined) => setCounts((old) => old[key] === count ? old : { ...old, [key]: count })])) as Record<string, CountSink>, []);
  const tab = params.get("tab") || "prompts";
  return (
    <Card title="Agent 工具" extra={<Link to="/agent/runs">全部运行追踪</Link>}>
      <Tabs
        activeKey={tab}
        onChange={(k) => setParams(k === "prompts" ? {} : { tab: k }, { replace: true })}
        items={[
          { key: "prompts", label: listTitle("提示词", counts.prompts), children: <PromptsTab onOpenRun={setRunId} onCount={countSinks.prompts} /> },
          { key: "memories", label: listTitle("记忆", counts.memories), children: <MemoriesTab onOpenRun={setRunId} onCount={countSinks.memories} /> },
          { key: "corrections", label: listTitle("纠正", counts.corrections), children: <CorrectionsTab onOpenRun={setRunId} highlight={params.get("id")} onCount={countSinks.corrections} /> },
          { key: "skills", label: listTitle("技能（注册表）", counts.skills), children: <RegistryTab<SkillItem> path="/agent/skills" kind="skill" onCount={countSinks.skills} /> },
          { key: "mcp", label: listTitle("MCP（注册表）", counts.mcp), children: <RegistryTab<McpServer> path="/agent/mcp-servers" kind="mcp" onCount={countSinks.mcp} /> },
        ]}
      />
      <AgentRunDrawer runId={runId} onClose={() => setRunId(null)} />
    </Card>
  );
}
