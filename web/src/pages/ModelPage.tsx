import { ExpandableDescription } from "../components/ExpandableDescription";
import { ListTable, listTitle } from "../components/ListView";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Form, Input, Select, Space, Tabs, Tag, Typography } from "antd";
import { useMemo, useRef, useState } from "react";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { EntityField, Graph, Link, Module, ModelNode, NodeDetail, Suggestion } from "../api/types";
import { typeText } from "../components/dataTypes";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { LinkEditor, LinksTable } from "../components/LinkEditor";
import { NodePanel, type PanelGuard, type PanelSeed } from "../components/NodePanel";
import { AppModal } from "../components/panel/AppModal";
import { SuggestionList } from "../components/SuggestionList";
import { KIND_COLOR, KIND_LABEL } from "../components/StatusTags";

/** P02 model (graph/list share one graph query) + P03 node drawer */
export function ModelPage() {
  const { sutId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const moduleId = params.get("module") || undefined;
  const selected = params.get("node");
  const tab = params.get("view") || "graph";
  const [kindFilter, setKindFilter] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();
  const [linkEdit, setLinkEdit] = useState<{ link?: Link | null } | null>(null);
  const [seed, setSeed] = useState<PanelSeed | null>(null);
  const guard = useRef<PanelGuard>({ dirty: false, discard: async () => true });

  const setParam = (key: string, value?: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const modules = useQuery({ queryKey: ["modules", sutId], queryFn: () => api<Module[]>(`/suts/${sutId}/modules`) });
  const graph = useQuery({
    queryKey: ["graph", sutId, moduleId || null],
    queryFn: () => api<Graph>(`/suts/${sutId}/graph`, { params: { module: moduleId } }),
  });
  const fullGraph = useQuery({
    queryKey: ["graph", sutId, null],
    queryFn: () => api<Graph>(`/suts/${sutId}/graph`),
  });
  const fields = useQuery({
    queryKey: ["sut-fields", sutId],
    queryFn: () => api<EntityField[]>(`/suts/${sutId}/fields`),
  });
  const fieldsByNode = useMemo(() => {
    const out = new Map<string, EntityField[]>();
    for (const f of fields.data || []) out.set(f.node_id, [...(out.get(f.node_id) || []), f]);
    return out;
  }, [fields.data]);
  const moduleName = useMemo(() => new Map((modules.data || []).map((m) => [m.id, m.name])), [modules.data]);

  const rows = graph.data?.nodes.filter(
    (n) => (!kindFilter || n.kind === kindFilter) && (!search || n.name.includes(search)),
  );
  const links = useQuery({ queryKey: ["links", sutId], queryFn: () => api<Link[]>(`/suts/${sutId}/links`) });
  const linkSuggestions = useQuery({
    queryKey: ["suggestions", sutId, "pending"],
    queryFn: () => api<Suggestion[]>(`/suts/${sutId}/suggestions`, { params: { status: "pending" } }),
  });
  const pendingLinks = (linkSuggestions.data || []).filter((s) => s.kind === "link");
  const suggest = useApiMutation(() => api<{ created: number }>(`/suts/${sutId}/links/suggest`, { method: "POST" }), {
    invalidate: [["suggestions", sutId]],
    success: "已根据外键/引用字段生成关系建议",
  });
  const kindOptions = Object.entries(KIND_LABEL)
    .filter(([value]) => value !== "relation")
    .map(([value, label]) => ({ value, label }));
  const openLink = (id: string) => setLinkEdit({ link: (links.data || []).find((l) => l.id === id) || null });

  const create = useApiMutation((body: Record<string, unknown>) => api<NodeDetail>(`/suts/${sutId}/nodes`, { method: "POST", body }), {
    invalidate: [["graph", sutId]],
    success: "节点已创建",
    onSuccess: (node) => {
      setCreating(false);
      form.resetFields();
      setParam("node", node.id);
    },
  });
  const kind = Form.useWatch("kind", form);
  const openNode = async (id: string | null) => {
    if (selected && id !== selected && guard.current.dirty && !(await guard.current.discard())) return false;
    setParam("node", id);
    return true;
  };
  const connectNodes = async (source: string, target: string) => {
    const sourceNode = (fullGraph.data?.nodes || []).find((item) => item.id === source);
    const targetNode = (fullGraph.data?.nodes || []).find((item) => item.id === target);
    if (!sourceNode || !targetNode) return;
    if (!(await openNode(source))) return;
    const bothEntities = sourceNode.kind === "entity" && targetNode.kind === "entity";
    setSeed({
      nonce: Date.now(),
      source,
      target,
      kind: bothEntities ? "link" : "edge",
      role: targetNode.kind === "action" ? "actor" : "object",
    });
  };

  return (
    <div className={tab === "graph" ? "model-stage" : "model-stage model-stage-auto"}>
      <div className="model-stage-main">
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          模型
        </Typography.Title>
        <Space>
          <RouterLink to={`/suts/${sutId}/review`}>模型评审（只读，可导出）</RouterLink>
          <Select
            allowClear
            placeholder="全部分组"
            style={{ width: 180 }}
            value={moduleId}
            onChange={(v) => setParam("module", v)}
            options={(modules.data || []).map((m) => ({ value: m.id, label: m.name }))}
          />
          <Button icon={<PlusOutlined />} onClick={() => {
            const current = (fullGraph.data?.nodes || []).find((item) => item.id === selected);
            if (current?.kind === "entity") setSeed({ nonce: Date.now(), source: current.id, target: "", kind: "link" });
            else setLinkEdit({ link: null });
          }}>
            新建关系
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            新建节点
          </Button>
        </Space>
      </Space>
      <Tabs
        activeKey={tab}
        onChange={(k) => setParam("view", k === "graph" ? null : k)}
        items={[
          {
            key: "graph",
            label: "图谱",
            children: graph.data && (
              graph.data.nodes.length ? (
                <div className="graph-fill">
                <GraphCanvas
                  graph={graph.data}
                  selectedId={selected}
                  onSelect={(id) => void openNode(id)}
                  onLinkClick={openLink}
                  onConnect={(source, target) => void connectNodes(source, target)}
                  height="fill"
                />
                </div>
              ) : (
                <Typography.Text type="secondary">还没有节点；请点击“新建节点”开始建模。</Typography.Text>
              )
            ),
          },
          {
            key: "list",
            label: listTitle("列表", graph.data?.nodes.length),
            children: (
              <>
                <Space style={{ marginBottom: 12 }}>
                  <Select
                    allowClear
                    placeholder="全部类型"
                    style={{ width: 120 }}
                    value={kindFilter}
                    onChange={setKindFilter}
                    options={kindOptions}
                  />
                  <Input.Search placeholder="按名称搜索" allowClear onChange={(e) => setSearch(e.target.value)} />
                </Space>
                <ListTable<ModelNode>
                  className="model-nodes-table"
                  total={fullGraph.data?.nodes.length}
                  filtered={Boolean(moduleId || kindFilter || search)}
                  label="模型节点"
                  error={graph.isError}
                  onRetry={() => graph.refetch()}
                  size="small"
                  rowKey="id"
                  loading={graph.isLoading}
                  dataSource={rows}
                  onRow={(row) => ({ onClick: () => void openNode(row.id), style: { cursor: "pointer" } })}
                  columns={[
                    { title: "名称", dataIndex: "name" },
                    { title: "类型", dataIndex: "kind", width: 90, render: (k) => <Tag color={KIND_COLOR[k]}>{KIND_LABEL[k]}</Tag> },
                    { title: "分组", dataIndex: "module_id", render: (m) => (m ? moduleName.get(m) : "-") },
                    {
                      title: "输入 / 输出 · 字段（类型）",
                      render: (_, n) => {
                        if (n.kind === "action") {
                          const ins = n.inputs || [];
                          const outs = n.outputs || [];
                          if (!ins.length && !outs.length) return <Typography.Text type="secondary">还没有输入/输出</Typography.Text>;
                          const short = (ps: typeof ins) => ps.map((p) => `${p.name}:${typeText(p.data_type)}`).join(", ");
                          return (
                            <Space orientation="vertical" size={0}>
                              <span>输入：{short(ins) || "—"}</span>
                              <span>输出：{short(outs) || "—"}</span>
                            </Space>
                          );
                        }
                        if (n.kind === "entity") {
                          const fs = fieldsByNode.get(n.id) || [];
                          return fs.length ? (
                            fs.map((f) => `${f.name}:${typeText(f.data_type)}`).join(", ")
                          ) : (
                            <Typography.Text type="secondary">尚未登记字段</Typography.Text>
                          );
                        }
                        return "—";
                      },
                    },
                    {
                      title: "属性",
                      width: 170,
                      render: (_, n) =>
                        `条件 ${n.attributes.conditions?.length || 0} / 状态 ${n.attributes.states?.length || 0} / 约束 ${n.attributes.constraints?.length || 0}`,
                    },
                    { title: "描述 / 用途", dataIndex: "description", width: 320, render: (text: string | null, n) => <ExpandableDescription text={text} name={n.name} /> },
                  ]}
                />
              </>
            ),
          },
          {
            key: "links",
            label: listTitle("关系", links.data?.length),
            children: (
              <>
                <Typography.Paragraph type="secondary">
                  关系是实体之间的一条边，两个方向各有一种读法（例如 PurchaseOrder belongs to Supplier / Supplier supplies PurchaseOrder），并包含基数和外键字段。
                  外键字段名与 API/代码字段一致（例如 supplier_id、order_id）。
                </Typography.Paragraph>
                <LinksTable links={links.data} loading={links.isLoading} error={links.isError} onRetry={() => links.refetch()} onOpen={(l) => setLinkEdit({ link: l })} />
                <Space style={{ margin: "16px 0 8px" }}>
                  <Typography.Text strong>待评审的关系建议（{pendingLinks.length}）</Typography.Text>
                  <Button size="small" loading={suggest.isPending} onClick={() => suggest.mutate()}>
                    根据外键字段建议
                  </Button>
                </Space>
                <SuggestionList
                  loading={linkSuggestions.isLoading}
                  error={linkSuggestions.isError}
                  onRetry={() => linkSuggestions.refetch()}
                  sutId={sutId}
                  items={pendingLinks}
                  onChanged={() => {
                    linkSuggestions.refetch();
                    links.refetch();
                    fullGraph.refetch();
                    graph.refetch();
                  }}
                />
              </>
            ),
          },
        ]}
      />
      <LinkEditor
        sutId={sutId}
        open={Boolean(linkEdit)}
        link={linkEdit?.link}
        entities={fullGraph.data?.nodes || []}
        fields={fields.data || []}
        onClose={() => setLinkEdit(null)}
      />
      <AppModal
        title="新建节点"
        help="先写下名称。字段、关系或输入输出可以在右侧面板里继续补。"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        forceRender
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ kind: "entity", module_id: moduleId }}
          onFinish={(v) => create.mutate(v)}
        >
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
            <Select options={kindOptions} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          {kind === "entity" && (
            <Typography.Paragraph type="secondary">使用“新建关系”在实体之间添加关系（两端读法、基数、外键）。</Typography.Paragraph>
          )}
          <Form.Item name="module_id" label="分组">
            <Select allowClear options={(modules.data || []).map((m) => ({ value: m.id, label: m.name }))} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </AppModal>
      </div>
      {selected && (
        <NodePanel
          sutId={sutId}
          nodeId={selected}
          onClose={() => setParam("node", null)}
          onOpenNode={(id) => void openNode(id)}
          modules={modules.data || []}
          allNodes={fullGraph.data?.nodes || []}
          seed={seed}
          onSeedConsumed={() => setSeed(null)}
          onGuard={(next) => { guard.current = next; }}
        />
      )}
    </div>
  );
}
