import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography } from "antd";
import { useState } from "react";

import { ApiError, api, describeError } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { DataType, EntityField, ModelNode } from "../api/types";
import { DATA_TYPE_LABEL, DATA_TYPE_OPTIONS } from "./dataTypes";
import { TypeTag } from "./IoParams";

export { DATA_TYPE_LABEL };

/** "PurchaseOrder.amount_minor (amount)" */
export function fieldLabel(f: { name: string; display_name?: string | null; node_name?: string }): string {
  const head = f.node_name ? `${f.node_name}.${f.name}` : f.name;
  return f.display_name ? `${head} (${f.display_name})` : head;
}

interface FieldForm {
  name: string;
  display_name?: string;
  data_type: DataType;
  unit?: string;
  constraints_text?: string;
  description?: string;
  position?: number;
  required?: boolean;
  format?: string;
  example?: string;
  enum_values?: string[];
  ref_node_id?: string;
  storage_name?: string;
}

/** Entity fields: structured field table (name, display name, type (required), required, unit, format, constraints); requirement items can reference Entity.field */
export function EntityFields(props: { nodeId: string; sutId: string; entities?: ModelNode[] }) {
  const { nodeId, sutId } = props;
  const qc = useQueryClient();
  const { modal, message } = App.useApp();
  const [editing, setEditing] = useState<EntityField | "new" | null>(null);
  const [form] = Form.useForm<FieldForm>();
  const dataType = Form.useWatch("data_type", form);
  const entityOptions = (props.entities || [])
    .filter((n) => n.kind === "entity" && n.id !== nodeId)
    .map((n) => ({ value: n.id, label: n.name }));
  const fields = useQuery({
    queryKey: ["node-fields", nodeId],
    queryFn: () => api<EntityField[]>(`/nodes/${nodeId}/fields`),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["node-fields", nodeId] });
    qc.invalidateQueries({ queryKey: ["sut-fields", sutId] });
    qc.invalidateQueries({ queryKey: ["node", nodeId] });
  };
  const save = useApiMutation(
    (v: FieldForm) => {
      const body = {
        name: v.name,
        display_name: v.display_name || null,
        data_type: v.data_type,
        unit: v.unit || null,
        description: v.description || null,
        constraints: (v.constraints_text || "")
          .split("\n")
          .map((t) => t.trim())
          .filter(Boolean)
          .map((text) => ({ text })),
        ...(v.position !== undefined && v.position !== null ? { position: v.position } : {}),
        required: Boolean(v.required),
        format: v.format || null,
        example: v.example || null,
        enum_values: v.data_type === "enum" ? v.enum_values || [] : [],
        ref_node_id: v.data_type === "reference" ? v.ref_node_id || null : null,
        storage_name: v.storage_name?.trim() || null,
      };
      return editing && editing !== "new"
        ? api(`/fields/${editing.id}`, { method: "PATCH", body })
        : api(`/nodes/${nodeId}/fields`, { method: "POST", body });
    },
    { success: "Field saved", onSuccess: () => { setEditing(null); refresh(); } },
  );

  const open = (f: EntityField | "new") => {
    setEditing(f);
    form.resetFields();
    form.setFieldsValue(
      f === "new"
        ? { name: "", data_type: "string", required: false, enum_values: [] }
        : {
            name: f.name,
            display_name: f.display_name || undefined,
            data_type: f.data_type,
            unit: f.unit || undefined,
            description: f.description || undefined,
            constraints_text: (f.constraints || []).map((c) => c.text).join("\n"),
            position: f.position,
            required: Boolean(f.required),
            format: f.format || undefined,
            example: f.example || undefined,
            enum_values: f.enum_values || [],
            ref_node_id: f.ref_node_id || undefined,
            storage_name: f.storage_name || undefined,
          },
    );
  };

  const remove = async (f: EntityField, confirm = false) => {
    try {
      await api(`/fields/${f.id}`, { method: "DELETE", params: { confirm } });
      message.success("Field archived");
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFLICT" && !confirm) {
        modal.confirm({
          title: "Field still referenced",
          content: err.message,
          okText: "Archive anyway",
          okButtonProps: { danger: true },
          onOk: () => remove(f, true),
        });
      } else {
        message.error(describeError(err));
      }
    }
  };

  return (
    <>
      <Table<EntityField>
        size="small"
        rowKey="id"
        pagination={false}
        loading={fields.isLoading}
        dataSource={fields.data || []}
        locale={{ emptyText: "No fields yet (e.g. amount amount_minor)" }}
        columns={[
          {
            title: "Field",
            render: (_, f) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text code>{f.name}</Typography.Text>
                {f.display_name && <Typography.Text type="secondary">{f.display_name}</Typography.Text>}
                {f.storage_name && <Typography.Text type="secondary">DB column: {f.storage_name}</Typography.Text>}
              </Space>
            ),
          },
          {
            title: "Type",
            width: 160,
            render: (_, f) => (
              <Space orientation="vertical" size={0}>
                <TypeTag p={f} />
                {f.data_type === "reference" && f.ref_node_name && (
                  <Typography.Text type="secondary">→ {f.ref_node_name}</Typography.Text>
                )}
                {f.unit && <Typography.Text type="secondary">Unit: {f.unit}</Typography.Text>}
              </Space>
            ),
          },
          {
            title: "Required",
            width: 56,
            render: (_, f) => (f.required ? <Tag color="red">Required</Tag> : <Typography.Text type="secondary">no</Typography.Text>),
          },
          {
            title: "Format / constraints",
            render: (_, f) => (
              <Space orientation="vertical" size={0}>
                {f.format && <span>{f.format}</span>}
                {f.example && <Typography.Text type="secondary">e.g. {f.example}</Typography.Text>}
                {(f.constraints || []).length > 0 && <span>{(f.constraints || []).map((c) => c.text).join("; ")}</span>}
                {!f.format && !f.example && !(f.constraints || []).length && "—"}
              </Space>
            ),
          },
          {
            title: "",
            width: 96,
            render: (_, f) => (
              <Space>
                <a onClick={() => open(f)}>Edit</a>
                <Popconfirm title="Archive this field?" onConfirm={() => remove(f)}>
                  <a>Archive</a>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Button size="small" style={{ marginTop: 8 }} onClick={() => open("new")}>
        Add field
      </Button>
      <Modal
        open={editing !== null}
        title={editing === "new" ? "Add field" : "Edit field"}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        confirmLoading={save.isPending}
        forceRender
      >
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
          <Form.Item name="name" label="Field name (same as the API field, e.g. amount_minor)" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="display_name" label="Display name">
            <Input placeholder="e.g. Amount" />
          </Form.Item>
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="data_type" label="Type (required)" rules={[{ required: true, message: "Type is required" }]}>
              <Select style={{ minWidth: 150 }} options={DATA_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="unit" label="Unit">
              <Input placeholder="e.g. cents, CNY" />
            </Form.Item>
            <Form.Item name="position" label="Order">
              <InputNumber min={0} />
            </Form.Item>
            <Form.Item name="required" label="Required" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          {dataType === "enum" && (
            <Form.Item name="enum_values" label="Enum values (Enter to add)" rules={[{ required: true, message: "An enum field needs its values" }]}>
              <Select mode="tags" tokenSeparators={[",", ", "]} placeholder="e.g. pending, approved, rejected" />
            </Form.Item>
          )}
          {dataType === "reference" && (
            <Form.Item name="ref_node_id" label="Referenced entity" rules={[{ required: true, message: "Choose the referenced entity" }]}>
              <Select showSearch optionFilterProp="label" options={entityOptions} />
            </Form.Item>
          )}
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="format" label="format">
              <Input placeholder="e.g. integer in cents, YYYY-MM-DD, uuid" />
            </Form.Item>
            <Form.Item name="example" label="Example">
              <Input placeholder="e.g. 5000000" />
            </Form.Item>
            <Form.Item name="storage_name" label="DB column name (if different from the field name)">
              <Input placeholder="e.g. amount" />
            </Form.Item>
          </Space>
          <Form.Item name="constraints_text" label="Constraints (one per line)">
            <Input.TextArea rows={3} placeholder="e.g. at least 0" />
          </Form.Item>
          <Form.Item name="description" label="description">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
