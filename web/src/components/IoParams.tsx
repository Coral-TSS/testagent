import { ListTable } from "./ListView";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Modal, Select, Space, Switch, Tag, Tooltip, Typography } from "antd";
import { useState } from "react";

import type { DataType, IoLocation, IoParam } from "../api/types";
import { DATA_TYPE_OPTIONS, LOCATION_LABEL, typeText } from "./dataTypes";

export interface FieldOption {
  value: string;
  label: string;
}

interface ParamForm {
  name: string;
  display_name?: string;
  data_type: DataType;
  required?: boolean;
  location?: IoLocation;
  format?: string;
  example?: string;
  enum_values?: string[];
  attribute_id?: string;
  description?: string;
}

/** Type cell: an enum shows its values. */
export function TypeTag({ p }: { p: { data_type: string; enum_values?: string[] | null } }) {
  return (
    <Space size={2} wrap>
      <Tag color="blue">{typeText(p.data_type)}</Tag>
      {p.data_type === "enum" && (p.enum_values || []).length > 0 && (
        <Typography.Text type="secondary">{(p.enum_values || []).join(" / ")}</Typography.Text>
      )}
    </Space>
  );
}

/**
 * Inputs / outputs as a readable table (name, type, required, location, format/example, mapped field, description).
 * With `onChange` it becomes an editor (add / edit / delete rows); usable as a Form.Item control.
 */
export function IoParamsTable(props: {
  label?: string;
  value?: IoParam[];
  onChange?: (next: IoParam[]) => void;
  showLocation?: boolean;
  locations?: IoLocation[];
  fieldOptions?: FieldOption[];
  emptyText?: string;
  addLabel?: string;
}) {
  const params = props.value || [];
  const editable = Boolean(props.onChange);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [form] = Form.useForm<ParamForm>();
  const dataType = Form.useWatch("data_type", form);
  const fieldLabel = new Map((props.fieldOptions || []).map((f) => [f.value, f.label]));

  const open = (index: number | "new") => {
    setEditing(index);
    const p = index === "new" ? undefined : params[index];
    form.resetFields();
    form.setFieldsValue(
      p
        ? {
            name: p.name,
            display_name: p.display_name || undefined,
            data_type: p.data_type,
            required: Boolean(p.required),
            location: p.location || undefined,
            format: p.format || undefined,
            example: p.example || undefined,
            enum_values: p.enum_values || [],
            attribute_id: p.attribute_id || undefined,
            description: p.description || undefined,
          }
        : { data_type: "string", required: false, location: props.locations?.[0] },
    );
  };
  const save = (v: ParamForm) => {
    const next: IoParam = {
      name: v.name.trim(),
      data_type: v.data_type,
      required: Boolean(v.required),
      ...(v.display_name ? { display_name: v.display_name } : {}),
      ...(v.location ? { location: v.location } : {}),
      ...(v.format ? { format: v.format } : {}),
      ...(v.example ? { example: v.example } : {}),
      ...(v.data_type === "enum" && v.enum_values?.length ? { enum_values: v.enum_values } : {}),
      ...(v.attribute_id ? { attribute_id: v.attribute_id, field: (fieldLabel.get(v.attribute_id) || "").split(" (")[0] } : {}),
      ...(v.description ? { description: v.description } : {}),
    };
    const list = [...params];
    if (editing === "new" || editing === null) list.push(next);
    else list[editing] = next;
    props.onChange?.(list);
    setEditing(null);
  };

  return (
    <>
      <ListTable<IoParam & { _i: number }>
        label={props.label || "参数"}
        size="small"
        rowKey="_i"

        dataSource={params.map((p, i) => ({ ...p, _i: i }))}
        locale={{ emptyText: props.emptyText || "未填写" }}
        columns={[
          {
            title: "名称",
            width: 170,
            render: (_, p) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text code style={{ whiteSpace: "nowrap" }}>
                  {p.name}
                </Typography.Text>
                {p.display_name && <Typography.Text type="secondary">{p.display_name}</Typography.Text>}
              </Space>
            ),
          },
          { title: "类型", width: 150, render: (_, p) => <TypeTag p={p} /> },
          {
            title: "必填",
            width: 56,
            render: (_, p) => (p.required ? <Tag color="red">必填</Tag> : <Typography.Text type="secondary">否</Typography.Text>),
          },
          ...(props.showLocation
            ? [
                {
                  title: "位置",
                  width: 84,
                  render: (_: unknown, p: IoParam) => (p.location ? LOCATION_LABEL[p.location] || p.location : "—"),
                },
              ]
            : []),
          {
            title: "格式 / 示例",
            width: 130,
            render: (_, p) => (
              <Space orientation="vertical" size={0}>
                {p.format && <span>{p.format}</span>}
                {p.example && <Typography.Text type="secondary">例如 {p.example}</Typography.Text>}
                {!p.format && !p.example && "—"}
              </Space>
            ),
          },
          {
            title: "映射字段",
            width: 130,
            render: (_, p) => (p.field ? <Tag color="purple">{p.field}</Tag> : "—"),
          },
          { title: "描述", dataIndex: "description", render: (d) => d || "—" },
          ...(editable
            ? [
                {
                  title: "",
                  width: 64,
                  render: (_: unknown, p: IoParam & { _i: number }) => (
                    <Space size={4}>
                      <Tooltip title="编辑">
                        <a aria-label={`编辑 ${p.name}`} onClick={() => open(p._i)}>
                          <EditOutlined />
                        </a>
                      </Tooltip>
                      <Tooltip title="删除">
                        <a aria-label={`删除 ${p.name}`} onClick={() => props.onChange?.(params.filter((_, i) => i !== p._i))}>
                          <DeleteOutlined />
                        </a>
                      </Tooltip>
                    </Space>
                  ),
                },
              ]
            : []),
        ]}
      />
      {editable && (
        <Button size="small" type="dashed" icon={<PlusOutlined />} style={{ marginTop: 6 }} onClick={() => open("new")}>
          {props.addLabel || "添加参数"}
        </Button>
      )}
      <Modal
        open={editing !== null}
        title={editing === "new" ? props.addLabel || "添加参数" : "编辑参数"}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        forceRender
      >
        <Form form={form} layout="vertical" onFinish={save}>
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="name" label="名称（与 API 字段相同）" rules={[{ required: true, whitespace: true }]}>
              <Input placeholder="例如 amount_minor" />
            </Form.Item>
            <Form.Item name="display_name" label="显示名">
              <Input placeholder="例如 Amount" />
            </Form.Item>
          </Space>
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="data_type" label="类型" rules={[{ required: true, message: "必须填写类型" }]}>
              <Select options={DATA_TYPE_OPTIONS} />
            </Form.Item>
            {props.showLocation && (
              <Form.Item name="location" label="位置">
                <Select
                  allowClear
                  options={(props.locations || (Object.keys(LOCATION_LABEL) as IoLocation[])).map((l) => ({
                    value: l,
                    label: LOCATION_LABEL[l],
                  }))}
                />
              </Form.Item>
            )}
            <Form.Item name="required" label="必填" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          {dataType === "enum" && (
            <Form.Item name="enum_values" label="枚举值（回车添加）" rules={[{ required: true, message: "枚举字段需要填写取值" }]}>
              <Select mode="tags" tokenSeparators={[",", ", "]} placeholder="例如 pending、approved" />
            </Form.Item>
          )}
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="format" label="格式">
              <Input placeholder="例如：以分为单位的整数、YYYY-MM-DD、uuid" />
            </Form.Item>
            <Form.Item name="example" label="示例">
              <Input placeholder="例如 5000000" />
            </Form.Item>
          </Space>
          {props.fieldOptions && (
            <Form.Item name="attribute_id" label="映射的实体字段（实体.字段）">
              <Select allowClear showSearch optionFilterProp="label" options={props.fieldOptions} placeholder="例如 PurchaseOrder.amount_minor" />
            </Form.Item>
          )}
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
