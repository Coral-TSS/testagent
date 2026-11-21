import { ListTable } from "./ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Tag, Typography } from "antd";
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
    { success: "字段已保存", onSuccess: () => { setEditing(null); refresh(); } },
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
      message.success("字段已归档");
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === "CONFLICT" && !confirm) {
        modal.confirm({
          title: "字段仍被引用",
          content: err.message,
          okText: "仍然归档",
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
      <ListTable<EntityField>
        label="实体字段"
        error={fields.isError}
        onRetry={() => fields.refetch()}
        size="small"
        rowKey="id"

        loading={fields.isLoading}
        dataSource={fields.data}
        locale={{ emptyText: "还没有字段（例如 amount amount_minor）" }}
        columns={[
          {
            title: "字段",
            render: (_, f) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text code>{f.name}</Typography.Text>
                {f.display_name && <Typography.Text type="secondary">{f.display_name}</Typography.Text>}
                {f.storage_name && <Typography.Text type="secondary">数据库列：{f.storage_name}</Typography.Text>}
              </Space>
            ),
          },
          {
            title: "类型",
            width: 160,
            render: (_, f) => (
              <Space orientation="vertical" size={0}>
                <TypeTag p={f} />
                {f.data_type === "reference" && f.ref_node_name && (
                  <Typography.Text type="secondary">→ {f.ref_node_name}</Typography.Text>
                )}
                {f.unit && <Typography.Text type="secondary">单位：{f.unit}</Typography.Text>}
              </Space>
            ),
          },
          {
            title: "必填",
            width: 56,
            render: (_, f) => (f.required ? <Tag color="red">必填</Tag> : <Typography.Text type="secondary">否</Typography.Text>),
          },
          {
            title: "格式 / 约束",
            render: (_, f) => (
              <Space orientation="vertical" size={0}>
                {f.format && <span>{f.format}</span>}
                {f.example && <Typography.Text type="secondary">例如 {f.example}</Typography.Text>}
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
                <a onClick={() => open(f)}>编辑</a>
                <Popconfirm title="要归档该字段吗？" onConfirm={() => remove(f)}>
                  <a>归档</a>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Button size="small" style={{ marginTop: 8 }} onClick={() => open("new")}>
        添加字段
      </Button>
      <Modal
        open={editing !== null}
        title={editing === "new" ? "添加字段" : "编辑字段"}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        confirmLoading={save.isPending}
        forceRender
      >
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
          <Form.Item name="name" label="字段名（与 API 字段相同，例如 amount_minor）" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input placeholder="例如 Amount" />
          </Form.Item>
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="data_type" label="类型（必填）" rules={[{ required: true, message: "必须填写类型" }]}>
              <Select style={{ minWidth: 150 }} options={DATA_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="unit" label="单位">
              <Input placeholder="例如 cents、CNY" />
            </Form.Item>
            <Form.Item name="position" label="顺序">
              <InputNumber min={0} />
            </Form.Item>
            <Form.Item name="required" label="必填" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          {dataType === "enum" && (
            <Form.Item name="enum_values" label="枚举值（回车添加）" rules={[{ required: true, message: "枚举字段需要填写取值" }]}>
              <Select mode="tags" tokenSeparators={[",", ", "]} placeholder="例如 pending、approved、rejected" />
            </Form.Item>
          )}
          {dataType === "reference" && (
            <Form.Item name="ref_node_id" label="被引用实体" rules={[{ required: true, message: "选择被引用的实体" }]}>
              <Select showSearch optionFilterProp="label" options={entityOptions} />
            </Form.Item>
          )}
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="format" label="格式">
              <Input placeholder="例如：以分为单位的整数、YYYY-MM-DD、uuid" />
            </Form.Item>
            <Form.Item name="example" label="示例">
              <Input placeholder="例如 5000000" />
            </Form.Item>
            <Form.Item name="storage_name" label="数据库列名（如与字段名不同）">
              <Input placeholder="例如 amount" />
            </Form.Item>
          </Space>
          <Form.Item name="constraints_text" label="约束（每行一条）">
            <Input.TextArea rows={3} placeholder="例如至少为 0" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
