import { ListTable, listTitle } from "../components/ListView";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Form, Input, Modal, Select, Space, Tabs, Tag, Typography } from "antd";
import { useMemo, useState } from "react";
import { Link as RouterLink, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { EntityField, Graph, Link, Module, ModelNode, NodeDetail, Suggestion } from "../api/types";
import { typeText } from "../components/dataTypes";
import { GraphCanvas } from "../components/graph/GraphCanvas";
import { LinkEditor, LinksTable } from "../components/LinkEditor";
import { NodeDrawer } from "../components/NodeDrawer";
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
    success: "Link suggestions generated from foreign-key/reference fields",
  });
  const kindOptions = Object.entries(KIND_LABEL)
    .filter(([value]) => value !== "relation")
    .map(([value, label]) => ({ value, label }));
  const openLink = (id: string) => setLinkEdit({ link: (links.data || []).find((l) => l.id === id) || null });

  const create = useApiMutation((body: Record<string, unknown>) => api<NodeDetail>(`/suts/${sutId}/nodes`, { method: "POST", body }), {
    invalidate: [["graph", sutId]],
    success: "Node created",
    onSuccess: (node) => {
      setCreating(false);
      form.resetFields();
      setParam("node", node.id);
    },
  });
  const kind = Form.useWatch("kind", form);

  return (
    <>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Model
        </Typography.Title>
        <Space>
          <RouterLink to={`/suts/${sutId}/review`}>Model review (read-only, exportable)</RouterLink>
          <Select
            allowClear
            placeholder="All groups"
            style={{ width: 180 }}
            value={moduleId}
            onChange={(v) => setParam("module", v)}
            options={(modules.data || []).map((m) => ({ value: m.id, label: m.name }))}
          />
          <Button icon={<PlusOutlined />} onClick={() => setLinkEdit({ link: null })}>
            New link
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            New node
          </Button>
        </Space>
      </Space>
      <Tabs
        activeKey={tab}
        onChange={(k) => setParam("view", k === "graph" ? null : k)}
        items={[
          {
            key: "graph",
            label: "Graph",
            children: graph.data && (
              graph.data.nodes.length ? (
                <GraphCanvas
                  graph={graph.data}
                  selectedId={selected}
                  onSelect={(id) => setParam("node", id)}
                  onLinkClick={openLink}
                />
              ) : (
                <Typography.Text type="secondary">No nodes yet; click “New node” to start modelling.</Typography.Text>
              )
            ),
          },
          {
            key: "list",
            label: listTitle("List", graph.data?.nodes.length),
            children: (
              <>
                <Space style={{ marginBottom: 12 }}>
                  <Select
                    allowClear
                    placeholder="All types"
                    style={{ width: 120 }}
                    value={kindFilter}
                    onChange={setKindFilter}
                    options={kindOptions}
                  />
                  <Input.Search placeholder="Search by name" allowClear onChange={(e) => setSearch(e.target.value)} />
                </Space>
                <ListTable<ModelNode>
                  total={fullGraph.data?.nodes.length}
                  filtered={Boolean(moduleId || kindFilter || search)}
                  label="Model nodes"
                  error={graph.isError}
                  onRetry={() => graph.refetch()}
                  size="small"
                  rowKey="id"
                  loading={graph.isLoading}
                  dataSource={rows}
                  onRow={(row) => ({ onClick: () => setParam("node", row.id), style: { cursor: "pointer" } })}
                  columns={[
                    { title: "Name", dataIndex: "name" },
                    { title: "Type", dataIndex: "kind", width: 90, render: (k) => <Tag color={KIND_COLOR[k]}>{KIND_LABEL[k]}</Tag> },
                    { title: "Group", dataIndex: "module_id", render: (m) => (m ? moduleName.get(m) : "-") },
                    {
                      title: "Inputs / outputs · fields (type)",
                      render: (_, n) => {
                        if (n.kind === "action") {
                          const ins = n.inputs || [];
                          const outs = n.outputs || [];
                          if (!ins.length && !outs.length) return <Typography.Text type="secondary">No inputs/outputs yet</Typography.Text>;
                          const short = (ps: typeof ins) => ps.map((p) => `${p.name}:${typeText(p.data_type)}`).join(", ");
                          return (
                            <Space orientation="vertical" size={0}>
                              <span>Inputs: {short(ins) || "—"}</span>
                              <span>Outputs: {short(outs) || "—"}</span>
                            </Space>
                          );
                        }
                        if (n.kind === "entity") {
                          const fs = fieldsByNode.get(n.id) || [];
                          return fs.length ? (
                            fs.map((f) => `${f.name}:${typeText(f.data_type)}`).join(", ")
                          ) : (
                            <Typography.Text type="secondary">No fields registered</Typography.Text>
                          );
                        }
                        return "—";
                      },
                    },
                    {
                      title: "Attributes",
                      width: 170,
                      render: (_, n) =>
                        `conditions ${n.attributes.conditions?.length || 0} / states ${n.attributes.states?.length || 0} / constraints ${n.attributes.constraints?.length || 0}`,
                    },
                    { title: "Description / purpose", dataIndex: "description", ellipsis: true },
                  ]}
                />
              </>
            ),
          },
          {
            key: "links",
            label: listTitle("Links", links.data?.length),
            children: (
              <>
                <Typography.Paragraph type="secondary">
                  A link is an edge between entities with a reading in each direction (e.g. PurchaseOrder belongs to Supplier / Supplier supplies PurchaseOrder), plus cardinality and foreign-key field.
                  Foreign-key field names match the API/code fields (e.g. supplier_id, order_id).
                </Typography.Paragraph>
                <LinksTable links={links.data} loading={links.isLoading} error={links.isError} onRetry={() => links.refetch()} onOpen={(l) => setLinkEdit({ link: l })} />
                <Space style={{ margin: "16px 0 8px" }}>
                  <Typography.Text strong>Link suggestions to review ({pendingLinks.length})</Typography.Text>
                  <Button size="small" loading={suggest.isPending} onClick={() => suggest.mutate()}>
                    Suggest from foreign-key fields
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
      <NodeDrawer
        sutId={sutId}
        nodeId={selected}
        onClose={() => setParam("node", null)}
        onOpenNode={(id) => setParam("node", id)}
        modules={modules.data || []}
        allNodes={fullGraph.data?.nodes || []}
      />
      <Modal
        title="New node"
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
          <Form.Item name="kind" label="Type" rules={[{ required: true }]}>
            <Select options={kindOptions} />
          </Form.Item>
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          {kind === "entity" && (
            <Typography.Paragraph type="secondary">Add links between entities with “New link” (readings on both ends, cardinality, foreign key).</Typography.Paragraph>
          )}
          <Form.Item name="module_id" label="Group">
            <Select allowClear options={(modules.data || []).map((m) => ({ value: m.id, label: m.name }))} />
          </Form.Item>
          <Form.Item name="description" label="description">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
