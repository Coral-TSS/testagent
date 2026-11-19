import { ReadingDrawer } from "./ReadingDrawer";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListSection } from "./ListView";
import {
  App,
  Button,
  Descriptions,
  Divider,
  Form,
  Input,
  List,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import { ApiError, api, describeError } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { ApiEndpoint, EntityField, Link, Module, ModelNode, NodeDetail, Reference } from "../api/types";
import { ActionRulesEditor, cleanEffects, cleanPreconditions, preconditionRows } from "./ActionRules";
import { AttributesEditor, cleanAttributes } from "./AttributesEditor";
import { EntityFields, fieldLabel } from "./EntityFields";
import { IoParamsTable } from "./IoParams";
import { LinkEditor } from "./LinkEditor";
import { CARD_SHORT } from "./links";
import { KIND_COLOR, KIND_LABEL } from "./StatusTags";

const EDGE_ROLES = [
  { value: "actor", label: "执行者" },
  { value: "object", label: "对象" },
  { value: "ref", label: "引用" },
];
const ROLE_LABEL: Record<string, string> = { source: "来源", target: "目标", actor: "执行者", object: "对象", ref: "引用" };

/** P03 node detail: purpose, inputs/outputs (action), fields (entity), attributes, edges, API binding, references, delete */
export function NodeDrawer(props: {
  sutId: string;
  nodeId: string | null;
  onClose: () => void;
  onOpenNode: (id: string) => void;
  modules: Module[];
  allNodes: ModelNode[];
}) {
  const { sutId, nodeId } = props;
  const qc = useQueryClient();
  const { modal, message } = App.useApp();
  const [form] = Form.useForm();
  const [edgeTarget, setEdgeTarget] = useState<string>();
  const [edgeRole, setEdgeRole] = useState("object");
  const [linkEdit, setLinkEdit] = useState<{ link?: Link | null; from?: string } | null>(null);
  const linkFrom = linkEdit?.from;
  const linkDefaults = useMemo(() => (linkFrom ? { from_node_id: linkFrom } : undefined), [linkFrom]);

  const node = useQuery({
    queryKey: ["node", nodeId],
    queryFn: () => api<NodeDetail>(`/nodes/${nodeId}`),
    enabled: Boolean(nodeId),
  });
  const refs = useQuery({
    queryKey: ["node-refs", nodeId],
    queryFn: () => api<Reference[]>(`/nodes/${nodeId}/references`),
    enabled: Boolean(nodeId),
  });
  const apis = useQuery({
    queryKey: ["apis", sutId],
    queryFn: () => api<ApiEndpoint[]>(`/suts/${sutId}/apis`),
    enabled: Boolean(nodeId),
  });
  const sutFields = useQuery({
    queryKey: ["sut-fields", sutId],
    queryFn: () => api<EntityField[]>(`/suts/${sutId}/fields`),
    enabled: Boolean(nodeId),
  });
  const fieldOptions = (sutFields.data || []).map((f) => ({ value: f.id, label: fieldLabel(f) }));
  const links = useQuery({
    queryKey: ["links", sutId],
    queryFn: () => api<Link[]>(`/suts/${sutId}/links`),
    enabled: Boolean(nodeId),
  });

  useEffect(() => {
    if (!node.data) return;
    const n = node.data;
    form.setFieldsValue({
      name: n.name,
      description: n.description,
      module_id: n.module_id,
      code_ref: n.code_ref,
      data_schema: n.data_schema ? JSON.stringify(n.data_schema, null, 2) : "",
      attributes: n.attributes,
      preconditions: preconditionRows(n.preconditions),
      effects: n.effects || [],
      inputs: n.inputs || [],
      outputs: n.outputs || [],
      input_format: n.input_format || "",
      output_format: n.output_format || "",
    });
  }, [node.data, form]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["graph", sutId] });
    qc.invalidateQueries({ queryKey: ["node", nodeId] });
    qc.invalidateQueries({ queryKey: ["node-refs", nodeId] });
  };
  const save = useApiMutation((body: Record<string, unknown>) => api(`/nodes/${nodeId}`, { method: "PATCH", body }), {
    success: "已保存",
    onSuccess: refresh,
  });
  const addEdge = useApiMutation(
    (body: Record<string, unknown>) => api(`/suts/${sutId}/edges`, { method: "POST", body }),
    { success: "已连接", onSuccess: () => { setEdgeTarget(undefined); refresh(); } },
  );
  const removeEdge = useApiMutation((id: string) => api(`/edges/${id}`, { method: "DELETE" }), { onSuccess: refresh });
  const linkApis = useApiMutation(
    (ids: string[]) => api(`/nodes/${nodeId}/apis`, { method: "PUT", body: { api_ids: ids } }),
    { success: "API 绑定已更新", onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["apis", sutId] }); } },
  );
  const fromApis = useApiMutation(
    (replace: boolean) =>
      api<{ inputs_added: number; outputs_added: number; purpose_filled: boolean }>(`/nodes/${nodeId}/io/from-apis`, {
        method: "POST",
        body: { replace },
      }),
    {
      onSuccess: (r) => {
        message.success(
          `Filled from the bound API: inputs +${r.inputs_added}, outputs +${r.outputs_added}${r.purpose_filled ? "，并补充了用途" : ""}`,
        );
        refresh();
      },
    },
  );

  const onFinish = (v: Record<string, unknown>) => {
    let dataSchema: unknown = null;
    const raw = String(v.data_schema || "").trim();
    if (raw) {
      try {
        dataSchema = JSON.parse(raw);
      } catch {
        form.setFields([{ name: "data_schema", errors: ["不是合法 JSON"] }]);
        return;
      }
    }
    const body: Record<string, unknown> = {
      name: v.name,
      description: v.description || null,
      module_id: v.module_id || null,
      code_ref: v.code_ref || null,
      data_schema: dataSchema,
      attributes: cleanAttributes(v.attributes as never),
    };
    if (node.data?.kind === "action") {
      body.preconditions = cleanPreconditions(v.preconditions as never);
      body.effects = cleanEffects(v.effects as never);
      body.inputs = v.inputs || [];
      body.outputs = v.outputs || [];
      body.input_format = v.input_format || null;
      body.output_format = v.output_format || null;
    }
    save.mutate(body);
  };

  const remove = async (confirm: boolean) => {
    try {
      await api(`/nodes/${nodeId}`, { method: "DELETE", params: { confirm } });
      message.success("节点已删除（可在变更日志中追溯）");
      qc.invalidateQueries({ queryKey: ["graph", sutId] });
      props.onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFLICT" && !confirm) {
        modal.confirm({
          title: "节点仍被引用",
          content: (
            <>
              <p>{err.message}</p>
              <ul>
                {err.related.map((r) => (
                  <li key={r}>{r.split(":").slice(2).join(":") || r}</li>
                ))}
              </ul>
              <p>删除后，它的边和 API 绑定将失效。</p>
            </>
          ),
          okText: "仍然删除",
          okButtonProps: { danger: true },
          onOk: () => remove(true),
        });
      } else {
        message.error(describeError(err));
      }
    }
  };

  const n = node.data;
  const others = props.allNodes.filter((x) => x.id !== nodeId);

  return (
    <ReadingDrawer kind="node"
      open={Boolean(nodeId)}
      onClose={props.onClose}
      title={
        n ? (
          <Space>
            <Tag color={KIND_COLOR[n.kind]}>{KIND_LABEL[n.kind]}</Tag>
            {n.name}
          </Space>
        ) : (
          "节点"
        )
      }
      extra={
        <Space>
          <Button danger onClick={() => remove(false)}>
            删除
          </Button>
          <Button type="primary" loading={save.isPending} onClick={() => form.submit()}>
            保存
          </Button>
        </Space>
      }
    >
      {n && (
        <>
          <Form name="node-detail" form={form} layout="vertical" onFinish={onFinish}>
            <Form.Item name="name" label="名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="module_id" label="分组">
              <Select allowClear options={props.modules.map((m) => ({ value: m.id, label: m.name }))} />
            </Form.Item>
            <Form.Item
              name="description"
              label={n.kind === "action" ? "用途（该动作做什么）" : "description"}
            >
              <Input.TextArea autoSize={{ minRows: 2 }} placeholder={n.kind === "action" ? "例如：申请人提交采购订单，系统根据金额决定是否需要审批" : undefined} />
            </Form.Item>
            <Form.Item name="code_ref" label="代码位置（链接）">
              <Input placeholder="例如 https://git.example/repo/blob/main/src/order.py#L10" />
            </Form.Item>
            {n.kind === "action" && (
              <>
                <Divider titlePlacement="start">绑定的 API</Divider>
                <Select
                  mode="multiple"
                  style={{ width: "100%" }}
                  placeholder="选择该动作调用的 API（空白的输入/输出会自动按 API 字段填充）"
                  value={n.apis.map((a) => a.id)}
                  loading={linkApis.isPending}
                  onChange={(ids) => linkApis.mutate(ids)}
                  options={(apis.data || []).map((a) => ({ value: a.id, label: `${a.method} ${a.path}${a.name ? ` · ${a.name}` : ""}` }))}
                />
                <Divider titlePlacement="start">输入 / 输出</Divider>
                <Space style={{ marginBottom: 8 }}>
                  <Button
                    size="small"
                    disabled={!n.apis.length}
                    loading={fromApis.isPending}
                    onClick={() => fromApis.mutate(false)}
                  >
                    从已绑定 API 填充（合并）
                  </Button>
                  <Popconfirm title="要从绑定的 API 字段重建输入/输出吗？手工添加的参数将被替换" onConfirm={() => fromApis.mutate(true)}>
                    <Button size="small" disabled={!n.apis.length}>
                      根据 API 重建
                    </Button>
                  </Popconfirm>
                  <Typography.Text type="secondary">编辑后请点击右上角的“保存”</Typography.Text>
                </Space>
                <Form.Item name="input_format" label="输入格式">
                  <Input placeholder="例如：请求体 JSON 对象（application/json）；参数：路径参数" />
                </Form.Item>
                <Form.Item name="inputs" label="类型">
                  <IoParamsTable
                    label="输入参数"
                    showLocation
                    locations={["body", "path", "query", "header", "form", "ui"]}
                    fieldOptions={fieldOptions}
                    emptyText="还没有输入（可从绑定的 API 填充）"
                    addLabel="添加输入"
                  />
                </Form.Item>
                <Form.Item name="output_format" label="输出格式">
                  <Input placeholder="例如 HTTP 201，JSON 对象（application/json）" />
                </Form.Item>
                <Form.Item name="outputs" label="输出">
                  <IoParamsTable
                    label="输出参数"
                    fieldOptions={fieldOptions}
                    emptyText="还没有输出（可从绑定的 API 填充）"
                    addLabel="添加输出"
                  />
                </Form.Item>
                <Divider titlePlacement="start">前置条件与效果</Divider>
                <ActionRulesEditor fields={sutFields.data || []} entities={props.allNodes} links={links.data || []} />
              </>
            )}
            {n.kind === "entity" && (
              <>
                <Divider titlePlacement="start">字段（名称 · 类型 · 必填 · 格式）</Divider>
                <EntityFields nodeId={n.id} sutId={sutId} entities={props.allNodes} />
                <Divider titlePlacement="start">关系（双向读法 · 基数 · 外键）</Divider>
                <ListSection label="实体关系" count={n.links?.length ?? 0}>
                <List
                  size="small"
                  dataSource={n.links || []}
                  locale={{ emptyText: "暂无关系" }}
                  renderItem={(l) => {
                    const outgoing = l.from_node_id === n.id;
                    const viaOnly = l.via_node_id === n.id && !outgoing && l.to_node_id !== n.id;
                    const text = viaOnly
                      ? `As “${l.from_name} ${l.forward_name} ${l.to_name}”`
                      : outgoing
                        ? `${n.name} ${l.forward_name} ${l.to_name}`
                        : `${n.name} ${l.reverse_name} ${l.from_name}`;
                    return (
                      <List.Item actions={[<a key="e" onClick={() => setLinkEdit({ link: l })}>编辑</a>]}>
                        <Space>
                          <span>{text}</span>
                          <Tag color="purple">{CARD_SHORT[l.cardinality]}</Tag>
                          {l.fk_field && <Typography.Text type="secondary">foreign key {l.fk_field}</Typography.Text>}
                          {l.required && <Tag>必填</Tag>}
                        </Space>
                      </List.Item>
                    );
                  }}
                />
                </ListSection>
                <Button size="small" style={{ marginTop: 8 }} onClick={() => setLinkEdit({ from: n.id })}>
                  新建关系
                </Button>
                <Form.Item
                  name="data_schema"
                  label="原始数据模式 JSON（旧格式，已迁移到上方“字段”，可能为空）"
                  style={{ marginTop: 16 }}
                >
                  <Input.TextArea rows={3} style={{ fontFamily: "monospace" }} />
                </Form.Item>
              </>
            )}
            <Divider titlePlacement="start">属性</Divider>
            <AttributesEditor />
          </Form>

          <Divider titlePlacement="start">边</Divider>
          <ListSection label="相关边" count={n.edges.filter((e) => e.role !== "source" && e.role !== "target").length}>
          <List
            size="small"
            dataSource={n.edges.filter((e) => e.role !== "source" && e.role !== "target")}
            locale={{ emptyText: "没有边" }}
            renderItem={(e) => {
              const outgoing = e.source_node_id === n.id;
              const otherId = outgoing ? e.target_node_id : e.source_node_id;
              const otherName = outgoing ? e.target_name : e.source_name;
              return (
                <List.Item
                  actions={
                    e.role === "source" || e.role === "target"
                      ? []
                      : [
                          <Popconfirm key="d" title="要删除这条边吗？" onConfirm={() => removeEdge.mutate(e.id)}>
                            <a>删除</a>
                          </Popconfirm>,
                        ]
                  }
                >
                  {outgoing ? "→" : "←"} <Tag>{ROLE_LABEL[e.role] || e.role}</Tag>
                  <a onClick={() => props.onOpenNode(otherId)}>{otherName}</a>
                </List.Item>
              );
            }}
          />
          </ListSection>
          <Space style={{ marginTop: 8 }}>
            <Select value={edgeRole} onChange={setEdgeRole} options={EDGE_ROLES} style={{ width: 100 }} />
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="连接到节点"
              style={{ width: 260 }}
              value={edgeTarget}
              onChange={setEdgeTarget}
              options={others.map((x) => ({ value: x.id, label: `${KIND_LABEL[x.kind]} · ${x.name}` }))}
            />
            <Button
              disabled={!edgeTarget}
              loading={addEdge.isPending}
              onClick={() => addEdge.mutate({ source_node_id: n.id, target_node_id: edgeTarget, role: edgeRole })}
            >
              添加边
            </Button>
          </Space>

          <Divider titlePlacement="start">被引用</Divider>
          {refs.data?.length ? (
            <Descriptions column={1} size="small">
              {refs.data.map((r) => (
                <Descriptions.Item key={`${r.type}-${r.id}`} label={r.type}>
                  {r.label}
                </Descriptions.Item>
              ))}
            </Descriptions>
          ) : (
            <Typography.Text type="secondary">没有引用</Typography.Text>
          )}
        </>
      )}
      <LinkEditor
        sutId={sutId}
        open={Boolean(linkEdit)}
        link={linkEdit?.link}
        defaults={linkDefaults}
        entities={props.allNodes}
        fields={sutFields.data || []}
        onClose={() => {
          setLinkEdit(null);
          refresh();
        }}
      />
    </ReadingDrawer>
  );
}
