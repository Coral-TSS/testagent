import { MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Select, Space, Typography } from "antd";

import type { Effect, EntityField, Link, ModelNode, Precondition, Scalar } from "../api/types";
import { EFFECT_LABEL, OP_TEXT, forwardText } from "./links";

/** Form values of one row; `attribute_id` selects Entity.field. */
type PreRow = Precondition & { value_list?: string[] };
type EffRow = Effect;

const OPS = Object.entries(OP_TEXT).map(([value, label]) => ({ value, label }));
const EFFECT_KINDS = Object.entries(EFFECT_LABEL).map(([value, label]) => ({ value, label }));

function enumOptions(field?: EntityField) {
  return (field?.enum_values || []).map((v) => ({ value: v, label: v }));
}

/** Form value → API body (drops empty rows, splits single/multi values). */
export function cleanPreconditions(rows: PreRow[] | undefined): Precondition[] {
  return (rows || [])
    .filter((r) => r && (r.attribute_id || r.text?.trim()))
    .map((r) => {
      if (!r.attribute_id) return { text: r.text?.trim(), message: r.message || null };
      const op = r.op || "eq";
      let value: Scalar | Scalar[] | null = null;
      if (op === "in" || op === "not_in") value = r.value_list || [];
      else if (op !== "is_null" && op !== "not_null") value = (r.value as Scalar) ?? "";
      return { attribute_id: r.attribute_id, op, value, message: r.message || null, text: r.text || null };
    });
}

export function cleanEffects(rows: EffRow[] | undefined): Effect[] {
  return (rows || [])
    .filter((r) => r && r.kind)
    .map((r) => {
      const base = { kind: r.kind, when: r.when || null, text: r.text || null };
      if (r.kind === "set_field") return { ...base, attribute_id: r.attribute_id, values: r.values || [] };
      if (r.kind === "create_object" || r.kind === "delete_object") return { ...base, node_id: r.node_id };
      return { ...base, link_id: r.link_id };
    });
}

/** API value → form rows (lists live in value_list for in / not_in). */
export function preconditionRows(items: Precondition[] | undefined): PreRow[] {
  return (items || []).map((p) => (Array.isArray(p.value) ? { ...p, value: null, value_list: p.value.map(String) } : p));
}

/** Preconditions and effects of an action, edited inside the node form. */
export function ActionRulesEditor({
  fields,
  entities,
  links,
}: {
  fields: EntityField[];
  entities: ModelNode[];
  links: Link[];
}) {
  const form = Form.useFormInstance();
  const fieldOptions = fields.map((f) => ({ value: f.id, label: `${f.node_name}.${f.name}` }));
  const byId = new Map(fields.map((f) => [f.id, f]));
  const entityOptions = entities.filter((e) => e.kind === "entity").map((e) => ({ value: e.id, label: e.name }));
  const linkOptions = links.map((l) => ({ value: l.id, label: forwardText(l) }));
  return (
    <>
      <Typography.Text strong>前置条件（执行前必须成立，例如 PurchaseOrder.state == pending）</Typography.Text>
      <Form.List name="preconditions">
        {(rows, { add, remove }) => (
          <div data-testid="preconditions">
            {rows.map((row) => (
              <Form.Item key={row.key} noStyle shouldUpdate>
                {() => {
                  const r: PreRow = form.getFieldValue(["preconditions", row.name]) || {};
                  const field = r.attribute_id ? byId.get(r.attribute_id) : undefined;
                  const op = r.op || "eq";
                  const opts = enumOptions(field);
                  return (
                    <Space align="baseline" style={{ display: "flex", flexWrap: "wrap" }}>
                      <Form.Item name={[row.name, "attribute_id"]} style={{ marginBottom: 6 }}>
                        <Select allowClear showSearch optionFilterProp="label" placeholder="实体.字段" style={{ width: 190 }} options={fieldOptions} />
                      </Form.Item>
                      {r.attribute_id ? (
                        <>
                          <Form.Item name={[row.name, "op"]} initialValue="eq" style={{ marginBottom: 6 }}>
                            <Select style={{ width: 90 }} options={OPS} />
                          </Form.Item>
                          {op === "in" || op === "not_in" ? (
                            <Form.Item name={[row.name, "value_list"]} style={{ marginBottom: 6 }} rules={[{ required: true, message: "输入取值" }]}>
                              <Select mode="tags" style={{ width: 200 }} options={opts} placeholder="取值（可多个）" />
                            </Form.Item>
                          ) : op === "is_null" || op === "not_null" ? null : (
                            <Form.Item name={[row.name, "value"]} style={{ marginBottom: 6 }} rules={[{ required: true, message: "输入取值" }]}>
                              {opts.length ? (
                                <Select style={{ width: 160 }} options={opts} placeholder="取值" />
                              ) : (
                                <Input style={{ width: 160 }} placeholder="取值" />
                              )}
                            </Form.Item>
                          )}
                        </>
                      ) : (
                        <Form.Item name={[row.name, "text"]} style={{ marginBottom: 6 }}>
                          <Input style={{ width: 290 }} placeholder="或一条文本条件，例如：审批人不能是提交人" />
                        </Form.Item>
                      )}
                      <Form.Item name={[row.name, "message"]} style={{ marginBottom: 6 }}>
                        <Input style={{ width: 200 }} placeholder="不满足时的提示（可选）" />
                      </Form.Item>
                      <MinusCircleOutlined onClick={() => remove(row.name)} />
                    </Space>
                  );
                }}
              </Form.Item>
            ))}
            <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={() => add({ op: "eq" })} style={{ marginBottom: 12 }}>
              添加前置条件
            </Button>
          </div>
        )}
      </Form.List>
      <div />
      <Typography.Text strong>效果（执行后会发生什么，例如 PurchaseOrder.state → approved | rejected）</Typography.Text>
      <Form.List name="effects">
        {(rows, { add, remove }) => (
          <div data-testid="effects">
            {rows.map((row) => (
              <Form.Item key={row.key} noStyle shouldUpdate>
                {() => {
                  const r: EffRow = form.getFieldValue(["effects", row.name]) || { kind: "set_field" };
                  const field = r.attribute_id ? byId.get(r.attribute_id) : undefined;
                  return (
                    <Space align="baseline" style={{ display: "flex", flexWrap: "wrap" }}>
                      <Form.Item name={[row.name, "kind"]} initialValue="set_field" style={{ marginBottom: 6 }}>
                        <Select style={{ width: 110 }} options={EFFECT_KINDS} />
                      </Form.Item>
                      {r.kind === "set_field" || !r.kind ? (
                        <>
                          <Form.Item name={[row.name, "attribute_id"]} style={{ marginBottom: 6 }} rules={[{ required: true, message: "选择字段" }]}>
                            <Select showSearch optionFilterProp="label" placeholder="实体.字段" style={{ width: 190 }} options={fieldOptions} />
                          </Form.Item>
                          <Form.Item name={[row.name, "values"]} style={{ marginBottom: 6 }}>
                            <Select mode="tags" style={{ width: 220 }} options={enumOptions(field)} placeholder="新取值（可多个）" />
                          </Form.Item>
                        </>
                      ) : r.kind === "create_object" || r.kind === "delete_object" ? (
                        <Form.Item name={[row.name, "node_id"]} style={{ marginBottom: 6 }} rules={[{ required: true, message: "选择实体" }]}>
                          <Select showSearch optionFilterProp="label" placeholder="实体" style={{ width: 190 }} options={entityOptions} />
                        </Form.Item>
                      ) : (
                        <Form.Item name={[row.name, "link_id"]} style={{ marginBottom: 6 }} rules={[{ required: true, message: "选择关系" }]}>
                          <Select showSearch optionFilterProp="label" placeholder="关系" style={{ width: 240 }} options={linkOptions} />
                        </Form.Item>
                      )}
                      <Form.Item name={[row.name, "when"]} style={{ marginBottom: 6 }}>
                        <Input style={{ width: 200 }} placeholder="何时（可选，例如 approved=true）" />
                      </Form.Item>
                      <MinusCircleOutlined onClick={() => remove(row.name)} />
                    </Space>
                  );
                }}
              </Form.Item>
            ))}
            <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={() => add({ kind: "set_field" })}>
              添加效果
            </Button>
          </div>
        )}
      </Form.List>
    </>
  );
}
