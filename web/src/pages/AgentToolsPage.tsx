import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Form, Input, Modal, Row, Select, Space, Switch, Table, Tabs, Tag, Typography } from "antd";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AgentMemory, Correction, McpServer, PromptSummary, PromptVersion, SkillItem } from "../api/types";
import { AgentRunDrawer, PURPOSE } from "../components/AgentRunDrawer";
import { CorrectionStatusTag } from "../components/CorrectionButton";
import { fmtTime } from "../utils/time";

const promptLabel = (name: string) => (name === "system" ? "System prompt (all entries)" : `${PURPOSE[name] || name} (${name})`);
const byLabel = (by: string) => (by.startsWith("agent:") ? <Tag color="purple">AI processed</Tag> : by === "system" ? <Tag>Built-in</Tag> : <Tag color="blue">{by}</Tag>);
const TARGET_LABEL: Record<string, string> = {
  case: "Case",
  strategy: "Strategy",
  requirement: "Requirement",
  execution: "Execution",
  report: "Report",
  agent_run: "Agent run",
  task_run: "Run",
  version: "Version",
};
const TARGET_LINK: Record<string, (id: string) => string> = {
  case: (id) => `/cases/${id}`,
  execution: (id) => `/executions/${id}`,
  report: (id) => `/reports/${id}`,
  task_run: (id) => `/runs/${id}`,
  version: (id) => `/versions/${id}`,
};

// ------------------------------------------------------------------ prompts
function PromptsTab({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  const qc = useQueryClient();
  const { modal } = App.useApp();
  const [selected, setSelected] = useState("system");
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const list = useQuery({ queryKey: ["prompts"], queryFn: () => api<PromptSummary[]>("/agent/prompts") });
  const versions = useQuery({ queryKey: ["prompt", selected], queryFn: () => api<PromptVersion[]>(`/agent/prompts/${selected}`) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["prompts"] });
    qc.invalidateQueries({ queryKey: ["prompt", selected] });
  };
  const activate = useApiMutation((v: number) => api(`/agent/prompts/${selected}/versions/${v}/activate`, { method: "POST" }), { success: "Active version switched", onSuccess: refresh });
  const create = useApiMutation(() => api(`/agent/prompts/${selected}/versions`, { method: "POST", body: { content: editing, note: note || null } }), {
    success: "Saved as a new version and activated",
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
        <Table<PromptSummary>
          size="small"
          rowKey="name"
          pagination={false}
          loading={list.isLoading}
          dataSource={list.data || []}
          onRow={(p) => ({ onClick: () => setSelected(p.name), style: { cursor: "pointer", background: p.name === selected ? "#e6f4ff" : undefined } })}
          columns={[
            { title: "Prompt", dataIndex: "name", render: (v: string) => promptLabel(v) },
            { title: "Active version", dataIndex: "active_version", width: 90, render: (v: number | null, p) => (p.is_default ? <Tag>Built-in default</Tag> : `v${v}`) },
          ]}
        />
      </Col>
      <Col span={16}>
        <Card
          size="small"
          title={promptLabel(selected)}
          extra={
            <Button onClick={() => setEditing(current?.content ?? "")} disabled={!current}>
              Edit as new version
            </Button>
          }
        >
          <Typography.Paragraph type="secondary">
            Assembly order: system prompt → entry description → extra guidance for this entry → enabled memories → context. Patches from corrections create a new version that takes effect immediately; you can switch back to any older version at any time (roll back).
          </Typography.Paragraph>
          <Table<PromptVersion>
            size="small"
            rowKey="id"
            loading={versions.isLoading}
            dataSource={versions.data || []}
            locale={{ emptyText: "No versions yet: using the built-in default" }}
            expandable={{ expandedRowRender: (v) => <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{v.content || "(empty: no extra guidance)"}</pre> }}
            columns={[
              { title: "Version", dataIndex: "version", width: 70, render: (v: number, r) => <Space>v{v}{r.active && <Tag color="green">Active</Tag>}</Space> },
              { title: "Source", dataIndex: "created_by", width: 100, render: byLabel },
              { title: "description", dataIndex: "note", render: (v: string | null, r) => <Space>{v || "-"}{r.source_correction_ids.length > 0 && <Tag>From {r.source_correction_ids.length} correction(s)</Tag>}</Space> },
              { title: "Time", dataIndex: "created_at", width: 140, render: (v: string) => fmtTime(v) },
              {
                title: "",
                key: "ops",
                width: 170,
                render: (_: unknown, r) => (
                  <Space>
                    {r.agent_run_id && <Button size="small" type="link" onClick={() => onOpenRun(r.agent_run_id!)}>Trace</Button>}
                    {!r.active && (
                      <Button
                        size="small"
                        onClick={() => modal.confirm({ title: `Switch to v${r.version}? `, content: "Later agent runs will use this version.", onOk: () => activate.mutateAsync(r.version) })}
                      >
                        Roll back to this version
                      </Button>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      </Col>
      <Modal title={`Edit ${promptLabel(selected)}`} open={editing !== null} onCancel={() => setEditing(null)} onOk={() => create.mutate()} okText="Save as new version" confirmLoading={create.isPending} width={720}>
        <Input.TextArea aria-label="Prompt content" rows={14} value={editing ?? ""} onChange={(e) => setEditing(e.target.value)} />
        <Input aria-label="Version note" style={{ marginTop: 8 }} placeholder="Version note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      </Modal>
    </Row>
  );
}

// ------------------------------------------------------------------ memories
function MemoriesTab({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  const [enabled, setEnabled] = useState<string>();
  const q = useQuery({ queryKey: ["memories", enabled], queryFn: () => api<AgentMemory[]>("/agent/memories", { params: { enabled } }) });
  const toggle = useApiMutation((v: { id: string; enabled: boolean }) => api(`/agent/memories/${v.id}`, { method: "PATCH", body: { enabled: v.enabled } }), {
    invalidate: [["memories"]],
    success: "Updated",
  });
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="All states" style={{ width: 120 }} value={enabled} onChange={setEnabled} options={[{ value: "true", label: "Enable" }, { value: "false", label: "Disabled" }]} />
        <Typography.Text type="secondary">Enabled memories are injected into later agent runs for the matching entries (global + current system, at most 20); disabled ones are no longer injected.</Typography.Text>
      </Space>
      <Table<AgentMemory>
        size="small"
        rowKey="id"
        loading={q.isLoading}
        dataSource={q.data || []}
        locale={{ emptyText: "No memories yet: the agent creates them automatically after you submit corrections" }}
        columns={[
          { title: "Content", dataIndex: "content", render: (v: string) => <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{v}</Typography.Paragraph> },
          { title: "Scope", dataIndex: "scope", width: 110, render: (v: string, m) => (v === "global" ? <Tag>Global</Tag> : <Tag color="blue">{m.sut_code || "System"}</Tag>) },
          { title: "Entries", dataIndex: "tags", width: 160, render: (v: string[]) => (v.length ? v.map((t) => <Tag key={t}>{PURPOSE[t] || t}</Tag>) : "All") },
          {
            title: "Source",
            key: "src",
            width: 150,
            render: (_: unknown, m) => (
              <Space>
                {byLabel(m.created_by)}
                {m.source_correction_ids.length > 0 && <Link to={`/agent/tools?tab=corrections&id=${m.source_correction_ids[0]}`}>Correct</Link>}
                {m.agent_run_id && <Button size="small" type="link" onClick={() => onOpenRun(m.agent_run_id!)}>Trace</Button>}
              </Space>
            ),
          },
          { title: "Time", dataIndex: "created_at", width: 130, render: (v: string) => fmtTime(v) },
          {
            title: "Enable",
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
function CorrectionsTab({ onOpenRun, highlight }: { onOpenRun: (id: string) => void; highlight?: string | null }) {
  const [status, setStatus] = useState<string>();
  const [kind, setKind] = useState<string>();
  const q = useQuery({
    queryKey: ["corrections", "all", status, kind],
    queryFn: () => api<Correction[]>("/corrections", { params: { status, kind } }),
    refetchInterval: (query) => (query.state.data?.some((c) => c.status === "pending" || c.status === "processing") ? 3000 : false),
  });
  const reprocess = useApiMutation((id: string) => api(`/corrections/${id}/reprocess`, { method: "POST" }), { invalidate: [["corrections"]], success: "Resubmitted for processing" });
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="All states" style={{ width: 120 }} value={status} onChange={setStatus} options={["pending", "processing", "processed", "failed"].map((v) => ({ value: v, label: <CorrectionStatusTag status={v} /> }))} />
        <Select allowClear placeholder="All types" style={{ width: 120 }} value={kind} onChange={setKind} options={[{ value: "correction", label: "Correct" }, { value: "omission", label: "Missed test" }]} />
      </Space>
      <Table<Correction>
        size="small"
        rowKey="id"
        loading={q.isLoading}
        dataSource={q.data || []}
        rowClassName={(c) => (c.id === highlight ? "ant-table-row-selected" : "")}
        locale={{ emptyText: "No corrections yet: click “Correct” on a case, strategy, execution or report page, or “Report missed test” on a run page" }}
        columns={[
          { title: "Original text", dataIndex: "content", render: (v: string) => <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{v}</Typography.Paragraph> },
          {
            title: "object",
            key: "target",
            width: 220,
            render: (_: unknown, c) => {
              const text = c.target_label || TARGET_LABEL[c.target_type] || c.target_type;
              const link = TARGET_LINK[c.target_type]?.(c.target_id);
              return (
                <Space direction="vertical" size={0}>
                  <Space size={4}>
                    {c.kind === "omission" && <Tag color="orange">Missed test</Tag>}
                    {link ? <Link to={link}>{text}</Link> : text}
                  </Space>
                  {c.sut_code && <Typography.Text type="secondary">{c.sut_code}</Typography.Text>}
                </Space>
              );
            },
          },
          {
            title: "Processing",
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
                    {(c.outputs.memory_ids?.length || 0) > 0 && `Memory ${c.outputs.memory_ids!.length} item(s) `}
                    {(c.outputs.prompt_versions || []).map((p) => `${p.name} v${p.version}`).join(", ")}
                  </Typography.Text>
                )}
                {c.status === "failed" && <Typography.Text type="danger">{c.error}</Typography.Text>}
              </Space>
            ),
          },
          { title: "Submit", dataIndex: "created_at", width: 130, render: (v: string, c) => `${fmtTime(v)} ${c.author}` },
          {
            title: "",
            key: "ops",
            width: 150,
            render: (_: unknown, c) => (
              <Space>
                {c.agent_run_id && <Button size="small" type="link" onClick={() => onOpenRun(c.agent_run_id!)}>Trace</Button>}
                {c.status !== "processing" && (
                  <Button size="small" onClick={() => reprocess.mutate(c.id)}>
                    Process again
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
function RegistryTab<T extends SkillItem | McpServer>({ path, kind }: { path: string; kind: "skill" | "mcp" }) {
  const [form] = Form.useForm();
  const [open, setOpen] = useState(false);
  const key = ["registry", path];
  const q = useQuery({ queryKey: key, queryFn: () => api<T[]>(path) });
  const create = useApiMutation((body: Record<string, unknown>) => api(path, { method: "POST", body }), {
    invalidate: [key],
    success: "Registered",
    onSuccess: () => {
      setOpen(false);
      form.resetFields();
    },
  });
  const toggle = useApiMutation((v: { id: string; enabled: boolean }) => api(`${path}/${v.id}`, { method: "PATCH", body: { enabled: v.enabled } }), { invalidate: [key] });
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message={`This version only registers and disables ${kind === "skill" ? "skills" : " MCP servers"}; they are never loaded or executed (C07). The agent's browser abilities come from the platform's built-in Playwright tools.`} />
      <Button type="primary" style={{ marginBottom: 12 }} onClick={() => setOpen(true)}>
        {kind === "skill" ? "Register skill" : "Register MCP server"}
      </Button>
      <Table<T>
        size="small"
        rowKey="id"
        loading={q.isLoading}
        dataSource={q.data || []}
        locale={{ emptyText: "Nothing registered" }}
        columns={[
          { title: "Name", dataIndex: "name" },
          ...(kind === "mcp"
            ? [
                { title: "Transport", dataIndex: "transport", width: 80 },
                { title: "Command / URL", key: "cmd", render: (_: unknown, r: T) => (r as McpServer).command || (r as McpServer).url || "-" },
              ]
            : [{ title: "Source", dataIndex: "source", render: (v: string | null) => v || "-" }]),
          { title: "description", dataIndex: "description", render: (v: string | null) => v || "-" },
          { title: "Enable", dataIndex: "enabled", width: 70, render: (v: boolean, r: T) => <Switch size="small" checked={v} onChange={(checked) => toggle.mutate({ id: r.id, enabled: checked })} /> },
        ]}
      />
      <Modal title={kind === "skill" ? "Register skill" : "Register MCP server"} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={create.isPending}>
        <Form form={form} layout="vertical" initialValues={kind === "mcp" ? { transport: "stdio" } : {}} onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="Name" rules={[{ required: true, message: "Please enter a name" }]}>
            <Input />
          </Form.Item>
          {kind === "mcp" ? (
            <>
              <Form.Item name="transport" label="Transport">
                <Select options={[{ value: "stdio", label: "stdio" }, { value: "http", label: "http" }]} />
              </Form.Item>
              <Form.Item name="command" label="Command (stdio)">
                <Input />
              </Form.Item>
              <Form.Item name="url" label="URL (http)">
                <Input />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="source" label="Source (path or link)">
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
  const tab = params.get("tab") || "prompts";
  return (
    <Card title="Agent tools" extra={<Link to="/agent/runs">All run traces</Link>}>
      <Tabs
        activeKey={tab}
        onChange={(k) => setParams(k === "prompts" ? {} : { tab: k }, { replace: true })}
        items={[
          { key: "prompts", label: "Prompt", children: <PromptsTab onOpenRun={setRunId} /> },
          { key: "memories", label: "Memories", children: <MemoriesTab onOpenRun={setRunId} /> },
          { key: "corrections", label: "Corrections", children: <CorrectionsTab onOpenRun={setRunId} highlight={params.get("id")} /> },
          { key: "skills", label: "Skills (registry)", children: <RegistryTab<SkillItem> path="/agent/skills" kind="skill" /> },
          { key: "mcp", label: "MCP (registry)", children: <RegistryTab<McpServer> path="/agent/mcp-servers" kind="mcp" /> },
        ]}
      />
      <AgentRunDrawer runId={runId} onClose={() => setRunId(null)} />
    </Card>
  );
}
