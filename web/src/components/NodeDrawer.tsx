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
  { value: "actor", label: "Actor" },
  { value: "object", label: "object" },
  { value: "ref", label: "References" },
];
const ROLE_LABEL: Record<string, string> = { source: "Source", target: "Target", actor: "Actor", object: "object", ref: "References" };

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
    success: "Saved",
    onSuccess: refresh,
  });
  const addEdge = useApiMutation(
    (body: Record<string, unknown>) => api(`/suts/${sutId}/edges`, { method: "POST", body }),
    { success: "Connected", onSuccess: () => { setEdgeTarget(undefined); refresh(); } },
  );
  const removeEdge = useApiMutation((id: string) => api(`/edges/${id}`, { method: "DELETE" }), { onSuccess: refresh });
  const linkApis = useApiMutation(
    (ids: string[]) => api(`/nodes/${nodeId}/apis`, { method: "PUT", body: { api_ids: ids } }),
    { success: "API binding updated", onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["apis", sutId] }); } },
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
          `Filled from the bound API: inputs +${r.inputs_added}, outputs +${r.outputs_added}${r.purpose_filled ? ", and added the purpose" : ""}`,
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
        form.setFields([{ name: "data_schema", errors: ["is not valid JSON"] }]);
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
      message.success("Node deleted (traceable in the change log)");
      qc.invalidateQueries({ queryKey: ["graph", sutId] });
      props.onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFLICT" && !confirm) {
        modal.confirm({
          title: "Node still referenced",
          content: (
            <>
              <p>{err.message}</p>
              <ul>
                {err.related.map((r) => (
                  <li key={r}>{r.split(":").slice(2).join(":") || r}</li>
                ))}
              </ul>
              <p>Its edges and API bindings will stop working after deletion.</p>
            </>
          ),
          okText: "Delete anyway",
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
          "Node"
        )
      }
      extra={
        <Space>
          <Button danger onClick={() => remove(false)}>
            Delete
          </Button>
          <Button type="primary" loading={save.isPending} onClick={() => form.submit()}>
            Save
          </Button>
        </Space>
      }
    >
      {n && (
        <>
          <Form name="node-detail" form={form} layout="vertical" onFinish={onFinish}>
            <Form.Item name="name" label="Name" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="module_id" label="Group">
              <Select allowClear options={props.modules.map((m) => ({ value: m.id, label: m.name }))} />
            </Form.Item>
            <Form.Item
              name="description"
              label={n.kind === "action" ? "Purpose (what this action does)" : "description"}
            >
              <Input.TextArea autoSize={{ minRows: 2 }} placeholder={n.kind === "action" ? "e.g. The requester submits a purchase order and the system decides by amount whether approval is needed" : undefined} />
            </Form.Item>
            <Form.Item name="code_ref" label="Code location (link)">
              <Input placeholder="e.g. https://git.example/repo/blob/main/src/order.py#L10" />
            </Form.Item>
            {n.kind === "action" && (
              <>
                <Divider titlePlacement="start">Bound API</Divider>
                <Select
                  mode="multiple"
                  style={{ width: "100%" }}
                  placeholder="Choose the APIs this action calls (empty inputs/outputs are filled from the API fields automatically)"
                  value={n.apis.map((a) => a.id)}
                  loading={linkApis.isPending}
                  onChange={(ids) => linkApis.mutate(ids)}
                  options={(apis.data || []).map((a) => ({ value: a.id, label: `${a.method} ${a.path}${a.name ? ` · ${a.name}` : ""}` }))}
                />
                <Divider titlePlacement="start">Inputs / outputs</Divider>
                <Space style={{ marginBottom: 8 }}>
                  <Button
                    size="small"
                    disabled={!n.apis.length}
                    loading={fromApis.isPending}
                    onClick={() => fromApis.mutate(false)}
                  >
                    Fill from bound API (merge)
                  </Button>
                  <Popconfirm title="Rebuild inputs/outputs from the bound API fields? Manually added parameters will be replaced" onConfirm={() => fromApis.mutate(true)}>
                    <Button size="small" disabled={!n.apis.length}>
                      Rebuild from API
                    </Button>
                  </Popconfirm>
                  <Typography.Text type="secondary">Click “Save” at the top right after editing</Typography.Text>
                </Space>
                <Form.Item name="input_format" label="Input format">
                  <Input placeholder="e.g. Request body JSON object (application/json); parameters: path parameters" />
                </Form.Item>
                <Form.Item name="inputs" label="Type">
                  <IoParamsTable
                    label="Input parameters"
                    showLocation
                    locations={["body", "path", "query", "header", "form", "ui"]}
                    fieldOptions={fieldOptions}
                    emptyText="No inputs yet (can be filled from the bound API)"
                    addLabel="Add input"
                  />
                </Form.Item>
                <Form.Item name="output_format" label="Output format">
                  <Input placeholder="e.g. HTTP 201, JSON object (application/json)" />
                </Form.Item>
                <Form.Item name="outputs" label="Outputs">
                  <IoParamsTable
                    label="Output parameters"
                    fieldOptions={fieldOptions}
                    emptyText="No outputs yet (can be filled from the bound API)"
                    addLabel="Add output"
                  />
                </Form.Item>
                <Divider titlePlacement="start">Preconditions & effects</Divider>
                <ActionRulesEditor fields={sutFields.data || []} entities={props.allNodes} links={links.data || []} />
              </>
            )}
            {n.kind === "entity" && (
              <>
                <Divider titlePlacement="start">Fields (name · type · required · format)</Divider>
                <EntityFields nodeId={n.id} sutId={sutId} entities={props.allNodes} />
                <Divider titlePlacement="start">Links (both readings · cardinality · foreign key)</Divider>
                <ListSection label="Entity links" count={n.links?.length ?? 0}>
                <List
                  size="small"
                  dataSource={n.links || []}
                  locale={{ emptyText: "No links yet" }}
                  renderItem={(l) => {
                    const outgoing = l.from_node_id === n.id;
                    const viaOnly = l.via_node_id === n.id && !outgoing && l.to_node_id !== n.id;
                    const text = viaOnly
                      ? `As “${l.from_name} ${l.forward_name} ${l.to_name}”`
                      : outgoing
                        ? `${n.name} ${l.forward_name} ${l.to_name}`
                        : `${n.name} ${l.reverse_name} ${l.from_name}`;
                    return (
                      <List.Item actions={[<a key="e" onClick={() => setLinkEdit({ link: l })}>Edit</a>]}>
                        <Space>
                          <span>{text}</span>
                          <Tag color="purple">{CARD_SHORT[l.cardinality]}</Tag>
                          {l.fk_field && <Typography.Text type="secondary">foreign key {l.fk_field}</Typography.Text>}
                          {l.required && <Tag>Required</Tag>}
                        </Space>
                      </List.Item>
                    );
                  }}
                />
                </ListSection>
                <Button size="small" style={{ marginTop: 8 }} onClick={() => setLinkEdit({ from: n.id })}>
                  New link
                </Button>
                <Form.Item
                  name="data_schema"
                  label="Raw data schema JSON (old format, migrated to “Fields” above, may be empty)"
                  style={{ marginTop: 16 }}
                >
                  <Input.TextArea rows={3} style={{ fontFamily: "monospace" }} />
                </Form.Item>
              </>
            )}
            <Divider titlePlacement="start">Attributes</Divider>
            <AttributesEditor />
          </Form>

          <Divider titlePlacement="start">Edges</Divider>
          <ListSection label="Related edges" count={n.edges.filter((e) => e.role !== "source" && e.role !== "target").length}>
          <List
            size="small"
            dataSource={n.edges.filter((e) => e.role !== "source" && e.role !== "target")}
            locale={{ emptyText: "No edges" }}
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
                          <Popconfirm key="d" title="Delete this edge?" onConfirm={() => removeEdge.mutate(e.id)}>
                            <a>Delete</a>
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
              placeholder="Connect to node"
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
              Add edge
            </Button>
          </Space>

          <Divider titlePlacement="start">Referenced by</Divider>
          {refs.data?.length ? (
            <Descriptions column={1} size="small">
              {refs.data.map((r) => (
                <Descriptions.Item key={`${r.type}-${r.id}`} label={r.type}>
                  {r.label}
                </Descriptions.Item>
              ))}
            </Descriptions>
          ) : (
            <Typography.Text type="secondary">No references</Typography.Text>
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
