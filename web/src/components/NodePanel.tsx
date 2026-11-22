import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Collapse, Descriptions, Input, InputNumber, Select, Space, Switch, Tabs, Tag, Typography } from "antd";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError, api, describeError } from "../api/client";
import type { ApiEndpoint, AttrItem, DataType, Effect, EntityField, Link, ModelNode, Module, NodeDetail, Reference } from "../api/types";
import { cleanEffects, cleanPreconditions } from "./ActionRules";
import { cleanAttributes } from "./AttributesEditor";
import { DATA_TYPE_OPTIONS } from "./dataTypes";
import { fieldLabel } from "./EntityFields";
import { IoParamsTable } from "./IoParams";
import { CARD_LABEL, EFFECT_LABEL, OP_TEXT } from "./links";
import { blankEdge, blankField, blankLink, fieldBody, fillFromApis, linkBody, sameIds, toDraft, type EdgeDraft, type FieldDraft, type LinkDraft, type NodeDraft } from "./nodeDraft";
import { EditableTable } from "./panel/EditableTable";
import { SideDetailPanel } from "./panel/SideDetailPanel";
import { confirmDiscard, UnsavedNavigationGuard } from "./panel/UnsavedGuard";
import { EDGE_ROLE_EN, EDGE_ROLE_ZH } from "./graph/edgeLabel";
import { KIND_COLOR, KIND_LABEL } from "./StatusTags";

const EDGE_ROLES = [
  { value: "object", label: EDGE_ROLE_ZH.object, title: EDGE_ROLE_EN.object },
  { value: "ref", label: EDGE_ROLE_ZH.ref, title: EDGE_ROLE_EN.ref },
  { value: "actor", label: EDGE_ROLE_ZH.actor, title: EDGE_ROLE_EN.actor },
];
const REF_LABEL: Record<string, string> = { edge: "边", link: "关系", api: "API", requirement: "需求", case: "用例" };
const ATTR_GROUPS = [
  ["conditions", "条件"],
  ["states", "状态"],
  ["constraints", "约束"],
] as const;

export interface PanelGuard {
  dirty: boolean;
  discard: () => Promise<boolean>;
}

export interface PanelSeed {
  nonce: number;
  source: string;
  target: string;
  kind: "link" | "edge";
  role?: EdgeDraft["role"];
}

/** Model node editor docked beside the graph. Every change stays local until 保存. */
export function NodePanel(props: {
  sutId: string;
  readOnly?: boolean;
  nodeId: string;
  onClose: () => void;
  onOpenNode: (id: string) => void;
  modules: Module[];
  allNodes: ModelNode[];
  seed?: PanelSeed | null;
  onSeedConsumed?: () => void;
  onGuard?: (guard: PanelGuard) => void;
}) {
  const { sutId, nodeId } = props;
  const qc = useQueryClient();
  const { modal, message } = App.useApp();
  const [draft, setDraft] = useState<NodeDraft | null>(null);
  const [baseline, setBaseline] = useState("");
  const [tab, setTab] = useState("basic");
  const [saving, setSaving] = useState(false);
  const [seeded, setSeeded] = useState(0);

  const node = useQuery({ queryKey: ["node", nodeId], queryFn: () => api<NodeDetail>(`/nodes/${nodeId}`) });
  const refs = useQuery({ queryKey: ["node-refs", nodeId], queryFn: () => api<Reference[]>(`/nodes/${nodeId}/references`), enabled: Boolean(nodeId) });
  const apis = useQuery({ queryKey: ["apis", sutId], queryFn: () => api<ApiEndpoint[]>(`/suts/${sutId}/apis`), enabled: Boolean(nodeId) });
  const sutFields = useQuery({ queryKey: ["sut-fields", sutId], queryFn: () => api<EntityField[]>(`/suts/${sutId}/fields`), enabled: Boolean(nodeId) });
  const nodeFields = useQuery({ queryKey: ["node-fields", nodeId], queryFn: () => api<EntityField[]>(`/nodes/${nodeId}/fields`), enabled: Boolean(nodeId) });
  const links = useQuery({ queryKey: ["links", sutId], queryFn: () => api<Link[]>(`/suts/${sutId}/links`), enabled: Boolean(nodeId) });

  useEffect(() => {
    setDraft(null);
    setBaseline("");
    setTab("basic");
  }, [nodeId]);

  useEffect(() => {
    if (draft || !node.data) return;
    if (node.data.kind === "entity" && nodeFields.isLoading) return;
    const next = toDraft(node.data, nodeFields.data || node.data.fields || []);
    setDraft(next);
    setBaseline(JSON.stringify(next));
  }, [draft, node.data, nodeFields.data, nodeFields.isLoading]);

  const dirty = Boolean(draft && JSON.stringify(draft) !== baseline);
  const discard = () => confirmDiscard(modal);
  useEffect(() => {
    props.onGuard?.({ dirty, discard });
  }, [dirty]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (props.readOnly || !draft || !props.seed || props.seed.source !== nodeId || props.seed.nonce === seeded) return;
    setSeeded(props.seed.nonce);
    if (props.seed.kind === "link") {
      setDraft({ ...draft, links: [...draft.links, blankLink(props.seed.source, props.seed.target)] });
      setTab("relations");
    } else {
      setDraft({ ...draft, edges: [...draft.edges, blankEdge(props.seed.target, props.seed.role || "object")] });
      setTab("refs");
    }
    props.onSeedConsumed?.();
  }, [props.seed, draft, nodeId, seeded]); // eslint-disable-line react-hooks/exhaustive-deps

  const patch = (part: Partial<NodeDraft>) => {
    if (props.readOnly) return;
    setDraft((current) => (current ? { ...current, ...part } : current));
  };
  const n = node.data;
  const entities = props.allNodes.filter((item) => item.kind === "entity");
  const entityOptions = entities.map((item) => ({ value: item.id, label: item.name }));
  const fieldOptions = (sutFields.data || []).map((f) => ({ value: f.id, label: fieldLabel(f) }));

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["graph", sutId] });
    qc.invalidateQueries({ queryKey: ["node", nodeId] });
    qc.invalidateQueries({ queryKey: ["node-refs", nodeId] });
    qc.invalidateQueries({ queryKey: ["node-fields", nodeId] });
    qc.invalidateQueries({ queryKey: ["sut-fields", sutId] });
    qc.invalidateQueries({ queryKey: ["links", sutId] });
    qc.invalidateQueries({ queryKey: ["apis", sutId] });
  };

  const destroy = async (path: string) => {
    try {
      await api(path, { method: "DELETE" });
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFLICT") {
        const ok = await new Promise<boolean>((resolve) => {
          modal.confirm({
            title: "仍被引用",
            content: err.message,
            okText: "仍然删除",
            okButtonProps: { danger: true },
            cancelText: "取消",
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        });
        if (!ok) throw err;
        await api(path, { method: "DELETE", params: { confirm: true } });
        return;
      }
      throw err;
    }
  };

  const save = async () => {
    if (!draft || !n || !baseline) return;
    if (!draft.name.trim()) {
      message.error("请填写名称");
      setTab("basic");
      return;
    }
    const saved = JSON.parse(baseline) as NodeDraft;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        module_id: draft.module_id || null,
        code_ref: draft.code_ref.trim() || null,
        attributes: cleanAttributes(draft.attributes as never),
      };
      if (n.kind === "action") {
        body.preconditions = cleanPreconditions(draft.preconditions);
        body.effects = cleanEffects(draft.effects);
        body.inputs = draft.inputs.filter((row) => row.name.trim());
        body.outputs = draft.outputs.filter((row) => row.name.trim());
        body.input_format = draft.input_format.trim() || null;
        body.output_format = draft.output_format.trim() || null;
      }
      await api(`/nodes/${nodeId}`, { method: "PATCH", body });
      if (n.kind === "action" && !sameIds(draft.api_ids, saved.api_ids)) {
        await api(`/nodes/${nodeId}/apis`, { method: "PUT", body: { api_ids: draft.api_ids } });
      }
      if (n.kind === "entity") await saveFields(saved.fields, draft.fields);
      await saveLinks(saved.links, draft.links);
      await saveEdges(saved.edges, draft.edges);
      message.success("已保存");
      setDraft(null);
      refresh();
    } catch (err) {
      if (!(err instanceof ApiError && err.code === "CONFLICT")) message.error(describeError(err));
    } finally {
      setSaving(false);
    }
  };

  const saveFields = async (before: FieldDraft[], after: FieldDraft[]) => {
    const kept = new Set(after.filter((row) => row.id).map((row) => row.id));
    for (const row of before) {
      if (row.id && !kept.has(row.id)) await destroy(`/fields/${row.id}`);
    }
    for (const row of after) {
      const body = fieldBody(row);
      if (!body) continue;
      if (!row.id) await api(`/nodes/${nodeId}/fields`, { method: "POST", body });
      else if (JSON.stringify(body) !== JSON.stringify(fieldBody(before.find((item) => item.id === row.id)!))) {
        await api(`/fields/${row.id}`, { method: "PATCH", body });
      }
    }
  };

  const saveLinks = async (before: LinkDraft[], after: LinkDraft[]) => {
    for (const row of after) {
      const body = linkBody(row);
      if (!body) continue;
      if (!row.from_node_id || !row.to_node_id || !row.forward_name.trim() || !row.reverse_name.trim()) {
        throw new ApiError(400, { code: "VALIDATION", message: "关系需要源实体、目标实体和两个方向的名称" });
      }
    }
    const kept = new Set(after.filter((row) => row.id).map((row) => row.id));
    for (const row of before) {
      if (row.id && !kept.has(row.id)) await destroy(`/links/${row.id}`);
    }
    for (const row of after) {
      const body = linkBody(row);
      if (!body) continue;
      if (!row.id) await api(`/suts/${sutId}/links`, { method: "POST", body });
      else if (JSON.stringify(body) !== JSON.stringify(linkBody(before.find((item) => item.id === row.id)!))) {
        await api(`/links/${row.id}`, { method: "PATCH", body });
      }
    }
  };

  const saveEdges = async (before: EdgeDraft[], after: EdgeDraft[]) => {
    const kept = new Set(after.filter((row) => row.id).map((row) => row.id));
    for (const row of before) {
      if (row.id && !kept.has(row.id)) await api(`/edges/${row.id}`, { method: "DELETE" });
    }
    for (const row of after) {
      if (!row.target_id) continue;
      const changed = Boolean(row.id) && (row.role !== row.original_role || row.target_id !== row.original_target);
      if (row.id && !changed) continue;
      if (row.id && changed) await api(`/edges/${row.id}`, { method: "DELETE" });
      await api(`/suts/${sutId}/edges`, { method: "POST", body: { source_node_id: nodeId, target_node_id: row.target_id, role: row.role } });
    }
  };

  const removeNode = async (confirm: boolean) => {
    try {
      await api(`/nodes/${nodeId}`, { method: "DELETE", params: { confirm } });
      message.success("节点已删除（可在变更日志中追溯）");
      qc.invalidateQueries({ queryKey: ["graph", sutId] });
      props.onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFLICT" && !confirm) {
        modal.confirm({
          title: "节点仍被引用",
          content: err.message,
          okText: "仍然删除",
          okButtonProps: { danger: true },
          cancelText: "取消",
          onOk: () => removeNode(true),
        });
      } else message.error(describeError(err));
    }
  };

  const close = async () => {
    if (dirty && !(await discard())) return;
    props.onClose();
  };

  const fill = (replace: boolean) => {
    if (!draft) return;
    if (!draft.api_ids.length) {
      message.warning("请先在基本信息里选择要绑定的 API");
      return;
    }
    const result = fillFromApis(draft, apis.data || [], replace);
    if (!result.addedIn && !result.addedOut && !replace) message.info("绑定的 API 没有新的字段可填充");
    setDraft(result.draft);
  };

  const setAttr = (key: (typeof ATTR_GROUPS)[number][0], rows: AttrItem[]) => {
    if (!draft) return;
    patch({ attributes: { ...draft.attributes, [key]: rows } });
  };

  const others = props.allNodes.filter((item) => item.id !== nodeId).map((item) => ({ value: item.id, label: `${KIND_LABEL[item.kind]} · ${item.name}` }));

  return (
    <SideDetailPanel
      kind="node"
      title={
        n ? (
          <Space>
            <Tag color={KIND_COLOR[n.kind]}>{KIND_LABEL[n.kind]}</Tag>
            {draft?.name || n.name}
          </Space>
        ) : (
          "节点"
        )
      }
      extra={
        props.readOnly ? undefined : (
          <Button danger onClick={() => removeNode(false)}>
            删除
          </Button>
        )
      }
      saving={saving}
      onClose={() => void close()}
      onCancel={() => void close()}
      onSave={props.readOnly ? undefined : () => void save()}
      footer={props.readOnly ? null : undefined}
    >
      {props.readOnly && <Alert type="info" showIcon style={{ marginBottom: 12 }} title="该版本已封板，模型只读。" />}
      <UnsavedNavigationGuard when={dirty} />
      {draft && n && (
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={
            n.kind === "entity"
              ? [
                  { key: "basic", label: "基本信息", children: <Basics draft={draft} kind="entity" modules={props.modules} onChange={patch} schema={n.data_schema} /> },
                  { key: "fields", label: "字段", children: <Fields draft={draft} entities={entityOptions} onChange={(fields) => patch({ fields })} /> },
                  { key: "relations", label: "关系", children: <Relations draft={draft} entities={entityOptions} fields={sutFields.data || []} onChange={(links) => patch({ links })} /> },
                  { key: "rules", label: "条件与状态", children: <Attributes draft={draft} onChange={setAttr} /> },
                  { key: "refs", label: "被引用", children: <References draft={draft} refs={refs.data || []} others={others} onOpenNode={props.onOpenNode} onChange={(edges) => patch({ edges })} /> },
                ]
              : [
                  { key: "basic", label: "基本信息", children: <Basics draft={draft} kind="action" modules={props.modules} apis={apis.data || []} onChange={patch} schema={n.data_schema} /> },
                  {
                    key: "io",
                    label: "输入输出",
                    children: (
                      <>
                        <Space style={{ marginBottom: 8 }} wrap>
                          <Button size="small" onClick={() => fill(false)}>从已绑定 API 填充（合并）</Button>
                          <Button size="small" onClick={() => fill(true)}>根据 API 重建</Button>
                        </Space>
                        <Typography.Text type="secondary">输入格式</Typography.Text>
                        <Input style={{ margin: "4px 0 12px" }} value={draft.input_format} placeholder="例如：请求体 JSON 对象（application/json）" onChange={(e) => patch({ input_format: e.target.value })} />
                        <IoParamsTable label="输入参数" value={draft.inputs} onChange={(inputs) => patch({ inputs })} showLocation locations={["body", "path", "query", "header", "form", "ui"]} fieldOptions={fieldOptions} emptyText="还没有输入" />
                        <Typography.Text type="secondary">输出格式</Typography.Text>
                        <Input style={{ margin: "12px 0 4px" }} value={draft.output_format} placeholder="例如 HTTP 201，JSON 对象（application/json）" onChange={(e) => patch({ output_format: e.target.value })} />
                        <IoParamsTable label="输出参数" value={draft.outputs} onChange={(outputs) => patch({ outputs })} fieldOptions={fieldOptions} emptyText="还没有输出" />
                      </>
                    ),
                  },
                  { key: "rules", label: "前置条件与效果", children: <Rules draft={draft} fields={sutFields.data || []} entities={props.allNodes} links={links.data || []} onChange={patch} /> },
                  { key: "refs", label: "被引用", children: <References draft={draft} refs={refs.data || []} others={others} onOpenNode={props.onOpenNode} onChange={(edges) => patch({ edges })} /> },
                ]
          }
        />
      )}
    </SideDetailPanel>
  );
}

function Basics({ draft, kind, modules, apis, onChange, schema }: {
  draft: NodeDraft;
  kind: "entity" | "action";
  modules: Module[];
  apis?: ApiEndpoint[];
  onChange: (part: Partial<NodeDraft>) => void;
  schema?: Record<string, unknown> | null;
}) {
  return (
    <>
      <Labeled label="名称">
        <Input value={draft.name} onChange={(e) => onChange({ name: e.target.value })} />
      </Labeled>
      <Labeled label="分组">
        <Select allowClear style={{ width: "100%" }} value={draft.module_id || undefined} options={modules.map((m) => ({ value: m.id, label: m.name }))} onChange={(module_id) => onChange({ module_id: module_id || null })} />
      </Labeled>
      <Labeled label={kind === "action" ? "用途（该动作做什么）" : "描述"}>
        <Input.TextArea autoSize={{ minRows: 2 }} value={draft.description} placeholder={kind === "action" ? "例如：申请人提交采购订单，系统根据金额决定是否需要审批" : undefined} onChange={(e) => onChange({ description: e.target.value })} />
      </Labeled>
      <Labeled label="代码位置（链接）">
        <Input value={draft.code_ref} placeholder="例如 https://git.example/repo/blob/main/src/order.py#L10" onChange={(e) => onChange({ code_ref: e.target.value })} />
      </Labeled>
      {kind === "action" && (
        <Labeled label="绑定的 API">
          <Select
            mode="multiple"
            style={{ width: "100%" }}
            value={draft.api_ids}
            placeholder="选择该动作调用的 API"
            options={(apis || []).map((a) => ({ value: a.id, label: `${a.method} ${a.path}${a.name ? ` · ${a.name}` : ""}` }))}
            onChange={(api_ids) => onChange({ api_ids })}
          />
        </Labeled>
      )}
      {kind === "entity" && (
        <Collapse
          style={{ marginTop: 12 }}
          items={[{
            key: "advanced",
            label: "高级",
            children: (
              <>
                <Typography.Paragraph type="secondary">原始数据模式（只读，字段已迁移到「字段」页）。</Typography.Paragraph>
                <Input.TextArea readOnly rows={4} style={{ fontFamily: "monospace" }} value={schema ? JSON.stringify(schema, null, 2) : ""} />
              </>
            ),
          }]}
        />
      )}
    </>
  );
}

function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

function Fields({ draft, entities, onChange }: { draft: NodeDraft; entities: { value: string; label: string }[]; onChange: (rows: FieldDraft[]) => void }) {
  const update = (index: number, part: Partial<FieldDraft>) => onChange(draft.fields.map((row, i) => (i === index ? { ...row, ...part } : row)));
  return (
    <EditableTable<FieldDraft>
      label="实体字段"
      rows={draft.fields}
      rowKey={(row) => row.key}
      emptyText="还没有字段"
      onAdd={() => onChange([...draft.fields, blankField()])}
      onRemove={(index) => onChange(draft.fields.filter((_, i) => i !== index))}
      removeLabel={(row) => `删除 ${row.name || "字段"}`}
      columns={[
        { title: "名称", render: (row, index) => <Input value={row.name} placeholder="amount_minor" onChange={(e) => update(index, { name: e.target.value })} /> },
        { title: "类型", width: 150, render: (row, index) => <Select style={{ width: "100%" }} value={row.data_type} options={DATA_TYPE_OPTIONS} onChange={(data_type: DataType) => update(index, { data_type })} /> },
        { title: "必填", width: 64, render: (row, index) => <Switch checked={row.required} onChange={(required) => update(index, { required })} /> },
      ]}
      extra={(row, index) => (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Labeled label="显示名"><Input value={row.display_name} placeholder="例如 Amount" onChange={(e) => update(index, { display_name: e.target.value })} /></Labeled>
          <Space>
            <Labeled label="单位"><Input value={row.unit} placeholder="例如 cents" onChange={(e) => update(index, { unit: e.target.value })} /></Labeled>
            <Labeled label="顺序"><InputNumber min={0} value={row.position === "" ? null : Number(row.position)} onChange={(value) => update(index, { position: value === null ? "" : String(value) })} /></Labeled>
          </Space>
          <Labeled label="格式"><Input value={row.format} onChange={(e) => update(index, { format: e.target.value })} /></Labeled>
          <Labeled label="示例"><Input value={row.example} onChange={(e) => update(index, { example: e.target.value })} /></Labeled>
          <Labeled label="数据库列名"><Input value={row.storage_name} placeholder="与字段名不同时填写" onChange={(e) => update(index, { storage_name: e.target.value })} /></Labeled>
          {row.data_type === "enum" && <Labeled label="枚举值"><Select mode="tags" style={{ width: "100%" }} value={row.enum_values} onChange={(enum_values) => update(index, { enum_values })} /></Labeled>}
          {row.data_type === "reference" && <Labeled label="被引用实体"><Select showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.ref_node_id} options={entities} onChange={(ref_node_id) => update(index, { ref_node_id })} /></Labeled>}
          <Labeled label="约束（每行一条）"><Input.TextArea value={row.constraints_text} autoSize={{ minRows: 2 }} placeholder="例如至少为 0" onChange={(e) => update(index, { constraints_text: e.target.value })} /></Labeled>
          <Labeled label="描述"><Input.TextArea value={row.description} autoSize={{ minRows: 1 }} onChange={(e) => update(index, { description: e.target.value })} /></Labeled>
        </Space>
      )}
    />
  );
}

function Relations({ draft, entities, fields, onChange }: { draft: NodeDraft; entities: { value: string; label: string }[]; fields: EntityField[]; onChange: (rows: LinkDraft[]) => void }) {
  const update = (index: number, part: Partial<LinkDraft>) => onChange(draft.links.map((row, i) => (i === index ? { ...row, ...part } : row)));
  const name = (id?: string) => entities.find((item) => item.value === id)?.label || "…";
  return (
    <EditableTable<LinkDraft>
      label="实体关系"
      rows={draft.links}
      rowKey={(row) => row.key}
      emptyText="还没有关系"
      onAdd={() => onChange([...draft.links, blankLink()])}
      onRemove={(index) => onChange(draft.links.filter((_, i) => i !== index))}
      removeLabel={() => "删除关系"}
      columns={[
        { title: "源实体", width: 130, render: (row, index) => <Select showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.from_node_id || undefined} options={entities} onChange={(from_node_id) => update(index, { from_node_id })} /> },
        { title: "关系", render: (row, index) => <Input value={row.forward_name} placeholder="belongs to" onChange={(e) => update(index, { forward_name: e.target.value })} /> },
        { title: "目标实体", width: 130, render: (row, index) => <Select showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.to_node_id || undefined} options={entities} onChange={(to_node_id) => update(index, { to_node_id })} /> },
        { title: "基数", width: 88, render: (row, index) => <Select style={{ width: "100%" }} value={row.cardinality} options={Object.entries(CARD_LABEL).map(([value, label]) => ({ value, label: label.split("（")[0] }))} onChange={(cardinality) => update(index, { cardinality })} /> },
      ]}
      extra={(row, index) => {
        const owners = row.cardinality === "one_to_many" ? [row.to_node_id] : row.cardinality === "many_to_one" ? [row.from_node_id] : [row.from_node_id, row.to_node_id];
        const fkOptions = fields.filter((f) => owners.includes(f.node_id)).map((f) => ({ value: f.id, label: fieldLabel(f) }));
        return (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text>{name(row.from_node_id)} {row.forward_name || "…"} {name(row.to_node_id)}</Typography.Text>
            <Labeled label="反向名称"><Input value={row.reverse_name} placeholder="例如 supplies" onChange={(e) => update(index, { reverse_name: e.target.value })} /></Labeled>
            <Labeled label="正向 API 名称"><Input value={row.forward_api_name} onChange={(e) => update(index, { forward_api_name: e.target.value })} /></Labeled>
            <Labeled label="反向 API 名称"><Input value={row.reverse_api_name} onChange={(e) => update(index, { reverse_api_name: e.target.value })} /></Labeled>
            <Labeled label="外键字段"><Select allowClear showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.fk_attribute_id} options={fkOptions} onChange={(fk_attribute_id) => update(index, { fk_attribute_id })} /></Labeled>
            <Labeled label="必填"><Switch checked={row.required} onChange={(required) => update(index, { required })} /></Labeled>
            <Labeled label="描述"><Input.TextArea value={row.description} autoSize={{ minRows: 1 }} onChange={(e) => update(index, { description: e.target.value })} /></Labeled>
          </Space>
        );
      }}
    />
  );
}

function Attributes({ draft, onChange }: { draft: NodeDraft; onChange: (key: (typeof ATTR_GROUPS)[number][0], rows: AttrItem[]) => void }) {
  return (
    <>
      {ATTR_GROUPS.map(([key, label]) => {
        const rows = draft.attributes[key] || [];
        return (
          <div key={key} style={{ marginBottom: 16 }}>
            <Typography.Text strong>{label}</Typography.Text>
            <EditableTable<AttrItem>
              label={label}
              rows={rows}
              rowKey={(_, index) => `${key}-${index}`}
              emptyText={`还没有${label}`}
              onAdd={() => onChange(key, [...rows, { text: "" }])}
              onRemove={(index) => onChange(key, rows.filter((_, i) => i !== index))}
              removeLabel={() => `删除${label}`}
              columns={[
                { title: "说明", render: (row, index) => <Input value={row.text} placeholder={`${label}说明`} onChange={(e) => onChange(key, rows.map((item, i) => (i === index ? { ...item, text: e.target.value } : item)))} /> },
                { title: "表达式", render: (row, index) => <Input value={row.expr || ""} placeholder="可选" onChange={(e) => onChange(key, rows.map((item, i) => (i === index ? { ...item, expr: e.target.value } : item)))} /> },
              ]}
            />
          </div>
        );
      })}
    </>
  );
}

function Rules({ draft, fields, entities, links, onChange }: {
  draft: NodeDraft;
  fields: EntityField[];
  entities: ModelNode[];
  links: Link[];
  onChange: (part: Partial<NodeDraft>) => void;
}) {
  const fieldOptions = fields.map((f) => ({ value: f.id, label: `${f.node_name}.${f.name}` }));
  const entityOptions = entities.filter((item) => item.kind === "entity").map((item) => ({ value: item.id, label: item.name }));
  const linkOptions = links.map((item) => ({ value: item.id, label: `${item.from_name} ${item.forward_name} ${item.to_name}` }));
  const pre = draft.preconditions;
  const effects = draft.effects;
  return (
    <>
      <Typography.Text strong>前置条件</Typography.Text>
      <EditableTable<(typeof pre)[number]>
        label="前置条件"
        rows={pre}
        rowKey={(_, index) => `pre-${index}`}
        emptyText="还没有前置条件"
        onAdd={() => onChange({ preconditions: [...pre, { op: "eq" }] })}
        onRemove={(index) => onChange({ preconditions: pre.filter((_, i) => i !== index) })}
        removeLabel={() => "删除前置条件"}
        columns={[
          { title: "字段", render: (row, index) => <Select allowClear showSearch optionFilterProp="label" style={{ width: "100%" }} placeholder="实体.字段" value={row.attribute_id || undefined} options={fieldOptions} onChange={(attribute_id) => onChange({ preconditions: pre.map((item, i) => (i === index ? { ...item, attribute_id } : item)) })} /> },
          { title: "比较", width: 90, render: (row, index) => <Select style={{ width: "100%" }} value={row.op || "eq"} options={Object.entries(OP_TEXT).map(([value, label]) => ({ value, label }))} onChange={(op) => onChange({ preconditions: pre.map((item, i) => (i === index ? { ...item, op } : item)) })} /> },
          { title: "取值", render: (row, index) => <Input value={Array.isArray(row.value) ? row.value.join("|") : String(row.value ?? row.value_list?.join("|") ?? "")} onChange={(e) => onChange({ preconditions: pre.map((item, i) => (i === index ? { ...item, value: e.target.value } : item)) })} /> },
        ]}
        extra={(row, index) => (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Labeled label="不满足时的提示"><Input value={row.message || ""} onChange={(e) => onChange({ preconditions: pre.map((item, i) => (i === index ? { ...item, message: e.target.value } : item)) })} /></Labeled>
            <Labeled label="自由文本（不选字段时使用）"><Input value={row.text || ""} onChange={(e) => onChange({ preconditions: pre.map((item, i) => (i === index ? { ...item, text: e.target.value } : item)) })} /></Labeled>
          </Space>
        )}
      />
      <Typography.Text strong>效果</Typography.Text>
      <EditableTable<Effect>
        label="效果"
        rows={effects}
        rowKey={(_, index) => `eff-${index}`}
        emptyText="还没有效果"
        onAdd={() => onChange({ effects: [...effects, { kind: "set_field" }] })}
        onRemove={(index) => onChange({ effects: effects.filter((_, i) => i !== index) })}
        removeLabel={() => "删除效果"}
        columns={[
          { title: "类型", width: 120, render: (row, index) => <Select style={{ width: "100%" }} value={row.kind} options={Object.entries(EFFECT_LABEL).map(([value, label]) => ({ value, label }))} onChange={(kind: Effect["kind"]) => onChange({ effects: effects.map((item, i) => (i === index ? { ...item, kind } : item)) })} /> },
          {
            title: "对象",
            render: (row, index) => row.kind === "set_field" ? (
              <Select allowClear showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.attribute_id || undefined} options={fieldOptions} onChange={(attribute_id) => onChange({ effects: effects.map((item, i) => (i === index ? { ...item, attribute_id } : item)) })} />
            ) : row.kind === "create_object" || row.kind === "delete_object" ? (
              <Select allowClear showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.node_id || undefined} options={entityOptions} onChange={(node_id) => onChange({ effects: effects.map((item, i) => (i === index ? { ...item, node_id } : item)) })} />
            ) : (
              <Select allowClear showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.link_id || undefined} options={linkOptions} onChange={(link_id) => onChange({ effects: effects.map((item, i) => (i === index ? { ...item, link_id } : item)) })} />
            ),
          },
          { title: "新取值", render: (row, index) => row.kind === "set_field" ? <Select mode="tags" style={{ width: "100%" }} value={(row.values || []).map(String)} onChange={(values) => onChange({ effects: effects.map((item, i) => (i === index ? { ...item, values } : item)) })} /> : "—" },
        ]}
        extra={(row, index) => (
          <Labeled label="何时">
            <Input value={row.when || ""} onChange={(e) => onChange({ effects: effects.map((item, i) => (i === index ? { ...item, when: e.target.value } : item)) })} />
          </Labeled>
        )}
      />
    </>
  );
}

function References({ draft, refs, others, onOpenNode, onChange }: {
  draft: NodeDraft;
  refs: Reference[];
  others: { value: string; label: string }[];
  onOpenNode: (id: string) => void;
  onChange: (rows: EdgeDraft[]) => void;
}) {
  const update = (index: number, part: Partial<EdgeDraft>) => onChange(draft.edges.map((row, i) => (i === index ? { ...row, ...part } : row)));
  return (
    <>
      <Typography.Text strong>相关边</Typography.Text>
      <EditableTable<EdgeDraft>
        label="相关边"
        rows={draft.edges}
        rowKey={(row) => row.key}
        emptyText="没有边"
        onAdd={() => onChange([...draft.edges, blankEdge()])}
        onRemove={(index) => onChange(draft.edges.filter((_, i) => i !== index))}
        removeLabel={() => "删除边"}
        columns={[
          { title: "角色", width: 200, render: (row, index) => <Select style={{ width: "100%" }} value={row.role} options={EDGE_ROLES} onChange={(role) => update(index, { role })} /> },
          { title: "节点", render: (row, index) => <Select showSearch optionFilterProp="label" style={{ width: "100%" }} value={row.target_id || undefined} options={others} onChange={(target_id) => update(index, { target_id })} /> },
        ]}
      />
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        角色：{EDGE_ROLE_ZH.object} / {EDGE_ROLE_ZH.ref} / {EDGE_ROLE_ZH.actor}。图谱上这些边从动作指向实体，箭头在实体一端。效果里明确新建该实体时线上写「新建」，明确删除时写「删除」，否则写「修改」。
      </Typography.Paragraph>
      <Typography.Text strong>被引用</Typography.Text>
      {refs.length ? (
        <Descriptions column={1} size="small" style={{ marginTop: 8 }}>
          {refs.map((item) => (
            <Descriptions.Item key={`${item.type}-${item.id}`} label={REF_LABEL[item.type] || item.type}>
              {item.type === "edge" || item.type === "link" ? <a onClick={() => item.id && onOpenNode(item.id)}>{item.label}</a> : item.label}
            </Descriptions.Item>
          ))}
        </Descriptions>
      ) : (
        <Typography.Paragraph type="secondary">没有引用</Typography.Paragraph>
      )}
    </>
  );
}
