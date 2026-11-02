import { MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Space, Typography } from "antd";

const GROUPS = [
  ["conditions", "Conditions"],
  ["states", "Status"],
  ["constraints", "Constraints"],
] as const;

/** Edits attributes.{conditions,states,constraints}: lists of {text, expr?}. Use inside a Form. */
export function AttributesEditor() {
  return (
    <>
      {GROUPS.map(([key, label]) => (
        <div key={key} style={{ marginBottom: 8 }}>
          <Typography.Text strong>{label}</Typography.Text>
          <Form.List name={["attributes", key]}>
            {(fields, { add, remove }) => (
              <>
                {fields.map((field) => (
                  <Space key={field.key} align="baseline" style={{ display: "flex" }}>
                    <Form.Item name={[field.name, "text"]} rules={[{ required: true, message: "Required" }]} style={{ marginBottom: 6 }}>
                      <Input placeholder={`${label}Description`} style={{ width: 240 }} />
                    </Form.Item>
                    <Form.Item name={[field.name, "expr"]} style={{ marginBottom: 6 }}>
                      <Input placeholder="Expression (optional)" style={{ width: 170 }} />
                    </Form.Item>
                    <MinusCircleOutlined onClick={() => remove(field.name)} />
                  </Space>
                ))}
                <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={() => add({ text: "" })}>
                  Add{label}
                </Button>
              </>
            )}
          </Form.List>
        </div>
      ))}
    </>
  );
}

/** Drops empty optional exprs so the backend's strict schema accepts the payload. */
export function cleanAttributes(raw: Record<string, { text: string; expr?: string | null }[] | undefined> | undefined) {
  const out: Record<string, { text: string; expr?: string }[]> = {};
  for (const [key] of GROUPS) {
    out[key] = (raw?.[key] || [])
      .filter((i) => i && i.text && i.text.trim())
      .map((i) => (i.expr && i.expr.trim() ? { text: i.text.trim(), expr: i.expr.trim() } : { text: i.text.trim() }));
  }
  return out;
}
