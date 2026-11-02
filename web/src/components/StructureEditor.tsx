import { MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Select, Space, Tag, Typography } from "antd";
import { useEffect } from "react";

import type { EntityField, Link, ModelNode, Part, Structure } from "../api/types";
import { fieldLabel } from "./EntityFields";
import { linkText } from "./links";
import { KIND_LABEL } from "./StatusTags";

export const PARTS: [Part, string][] = [
  ["actor", "Actor"],
  ["condition", "Preconditions"],
  ["action", "Actions"],
  ["result", "Expected result"],
  ["constraint", "Constraints"],
];

/** Five-part requirement structure; each item may link to a model node, an entity field and a relation. */
export function StructureEditor({
  value,
  nodes,
  fields = [],
  links = [],
  disabled,
  saving,
  onSave,
}: {
  value?: Structure | null;
  nodes: ModelNode[];
  fields?: EntityField[];
  links?: Link[];
  disabled?: boolean;
  saving?: boolean;
  onSave: (s: Structure) => void;
}) {
  const [form] = Form.useForm();
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
      onFinish={(v: Structure) =>
        onSave(
          Object.fromEntries(
            PARTS.map(([p]) => [p, (v[p] || []).filter((i) => i?.text?.trim()).map((i) => ({ text: i.text.trim(), node_id: i.node_id || null, attribute_id: i.attribute_id || null, link_id: i.link_id || null }))]),
          ),
        )
      }
    >
      {PARTS.map(([part, label]) => (
        <div key={part} style={{ marginBottom: 8 }}>
          <Typography.Text strong>{label}</Typography.Text>
          <Form.List name={part}>
            {(fields, { add, remove }) => (
              <>
                {fields.map((f) => (
                  <Space key={f.key} align="baseline" style={{ display: "flex" }}>
                    <Form.Item name={[f.name, "text"]} rules={[{ required: true, message: "Required" }]} style={{ marginBottom: 6 }}>
                      <Input style={{ width: 200 }} />
                    </Form.Item>
                    <Form.Item name={[f.name, "node_id"]} style={{ marginBottom: 6 }}>
                      <Select allowClear showSearch optionFilterProp="label" placeholder="Linked model nodes" style={{ width: 200 }} options={options} />
                    </Form.Item>
                    {fieldOptions.length > 0 && (
                      <Form.Item name={[f.name, "attribute_id"]} style={{ marginBottom: 6 }}>
                        <Select
                          allowClear
                          showSearch
                          optionFilterProp="label"
                          placeholder="Linked fields"
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
                          placeholder="Linked links"
                          style={{ width: 220 }}
                          options={linkOptions}
                        />
                      </Form.Item>
                    )}
                    <Form.Item noStyle shouldUpdate>
                      {() => (form.getFieldValue([part, f.name, "missing"]) ? <Tag color="orange">Missing in model</Tag> : null)}
                    </Form.Item>
                    {!disabled && <MinusCircleOutlined onClick={() => remove(f.name)} />}
                  </Space>
                ))}
                {!disabled && (
                  <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={() => add({ text: "" })}>
                    Add
                  </Button>
                )}
              </>
            )}
          </Form.List>
        </div>
      ))}
      {!disabled && (
        <Button size="small" htmlType="submit" loading={saving}>
          Save structure
        </Button>
      )}
    </Form>
  );
}
