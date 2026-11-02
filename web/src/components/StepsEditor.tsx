import { ArrowDownOutlined, ArrowUpOutlined, MinusCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Form, Input, Space } from "antd";

/** Ordered case steps {action, data?, expected?}; use inside a Form under name "steps". */
export function StepsEditor({ disabled }: { disabled?: boolean }) {
  return (
    <Form.List name="steps">
      {(fields, { add, remove, move }) => (
        <>
          {fields.map((f, i) => (
            <Space key={f.key} align="baseline" style={{ display: "flex" }} wrap={false}>
              <span style={{ width: 20 }}>{i + 1}.</span>
              <Form.Item name={[f.name, "action"]} rules={[{ required: true, message: "Required" }]} style={{ marginBottom: 6 }}>
                <Input placeholder="Action" style={{ width: 260 }} />
              </Form.Item>
              <Form.Item name={[f.name, "data"]} style={{ marginBottom: 6 }}>
                <Input placeholder="Data (optional)" style={{ width: 150 }} />
              </Form.Item>
              <Form.Item name={[f.name, "expected"]} style={{ marginBottom: 6 }}>
                <Input placeholder="Expected for this step (optional)" style={{ width: 200 }} />
              </Form.Item>
              {!disabled && (
                <>
                  <ArrowUpOutlined onClick={() => i > 0 && move(i, i - 1)} />
                  <ArrowDownOutlined onClick={() => i < fields.length - 1 && move(i, i + 1)} />
                  <MinusCircleOutlined onClick={() => remove(f.name)} />
                </>
              )}
            </Space>
          ))}
          {!disabled && (
            <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={() => add({ action: "" })}>
              Add step
            </Button>
          )}
        </>
      )}
    </Form.List>
  );
}
