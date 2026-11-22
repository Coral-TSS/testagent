import { MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Select, Space, Tag, Typography, type FormInstance } from "antd";
import { useEffect } from "react";

import type { EntityField, Link, ModelNode, Part, Structure } from "../api/types";
import { fieldLabel } from "./EntityFields";
import { linkText } from "./links";
import { KIND_LABEL } from "./StatusTags";

export const PARTS: [Part, string][] = [
  ["actor", "执行者"],
  ["condition", "前置条件"],
  ["action", "动作"],
  ["result", "预期结果"],
  ["constraint", "约束"],
];

export function cleanStructure(value: Structure | null | undefined): Structure {
  return Object.fromEntries(
    PARTS.map(([part]) => [part, (value?.[part] || []).filter((item) => item?.text?.trim()).map((item) => ({ text: item.text.trim(), node_id: item.node_id || null, attribute_id: item.attribute_id || null, link_id: item.link_id || null }))]),
  ) as Structure;
}

/** Five-part requirement structure; each item may link to a model node, an entity field and a relation. */
export function StructureEditor({
  value,
  nodes,
  fields = [],
  links = [],
  disabled,
  saving,
  onSave,
  form: external,
  showSave = true,
}: {
  value?: Structure | null;
  nodes: ModelNode[];
  fields?: EntityField[];
  links?: Link[];
  disabled?: boolean;
  saving?: boolean;
  onSave: (s: Structure) => void;
  form?: FormInstance;
  showSave?: boolean;
}) {
  const [own] = Form.useForm();
  const form = external || own;
  useEffect(() => {
    form.setFieldsValue(Object.fromEntries(PARTS.map(([p]) => [p, value?.[p] || []])));
  }, [value, form]);
  const linkOptions = links.map((l) => ({ value: l.id, label: linkText(l) }));
  const options = nodes.filter((n) => n.kind !== "relation").map((n) => ({ value: n.id, label: `${KIND_LABEL[n.kind]} · ${n.name}` }));
  const fieldOptions = fields.map((f) => ({ value: f.id, label: fieldLabel(f) }));
  return (
    <Form
      form={form}
      disabled={disabled}
      onFinish={(v: Structure) => onSave(cleanStructure(v))}
    >
      {PARTS.map(([part, label]) => (
        <Form.List key={part} name={part}>
          {(rows, { add, remove }) => (
            <div style={{ marginBottom: 8 }}>
              <div
                data-testid={`structure-section-${part}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                  marginTop: 4,
                  paddingTop: 8,
                  borderTop: "1px solid #f0f0f0",
                }}
              >
                <Typography.Text strong>{label}</Typography.Text>
                {!disabled && (
                  <Button
                    type="link"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => add({ text: "" })}
                    style={{ paddingInline: 4, height: "auto" }}
                  >
                    添加
                  </Button>
                )}
              </div>
              {rows.map((f) => (
                <Space key={f.key} align="baseline" style={{ display: "flex" }}>
                  <Form.Item name={[f.name, "text"]} rules={[{ required: true, message: "必填" }]} style={{ marginBottom: 6 }}>
                    <Input style={{ width: 200 }} />
                  </Form.Item>
                  <Form.Item name={[f.name, "node_id"]} style={{ marginBottom: 6 }}>
                    <Select allowClear showSearch optionFilterProp="label" placeholder="关联的模型节点" style={{ width: 200 }} options={options} />
                  </Form.Item>
                  {fieldOptions.length > 0 && (
                    <Form.Item name={[f.name, "attribute_id"]} style={{ marginBottom: 6 }}>
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder="关联字段"
                        style={{ width: 200 }}
                        options={fieldOptions}
                      />
                    </Form.Item>
                  )}
                  {linkOptions.length > 0 && (
                    <Form.Item name={[f.name, "link_id"]} style={{ marginBottom: 6 }}>
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder="关联关系"
                        style={{ width: 220 }}
                        options={linkOptions}
                      />
                    </Form.Item>
                  )}
                  <Form.Item noStyle shouldUpdate>
                    {() => (form.getFieldValue([part, f.name, "missing"]) ? <Tag color="orange">模型中缺失</Tag> : null)}
                  </Form.Item>
                  {!disabled && <MinusCircleOutlined onClick={() => remove(f.name)} />}
                </Space>
              ))}
            </div>
          )}
        </Form.List>
      ))}
      {!disabled && showSave && (
        <Button size="small" htmlType="submit" loading={saving}>
          保存结构
        </Button>
      )}
    </Form>
  );
}
