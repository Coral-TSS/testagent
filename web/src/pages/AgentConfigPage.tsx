import { useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, InputNumber, Space, Switch, Typography } from "antd";
import { useEffect, useState } from "react";

import { api, describeError } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AgentConfig } from "../api/types";

/** P14 agent model settings (OpenAI-compatible); the API key is write-only, the page shows only a mask */
export function AgentConfigPage() {
  const cfg = useQuery({ queryKey: ["agent-config"], queryFn: () => api<AgentConfig>("/agent/config") });
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const [testing, setTesting] = useState(false);
  useEffect(() => {
    if (cfg.data) form.setFieldsValue({ ...cfg.data, api_key: "" });
  }, [cfg.data, form]);
  const save = useApiMutation((body: Record<string, unknown>) => api<AgentConfig>("/agent/config", { method: "PUT", body }), {
    invalidate: [["agent-config"]],
    success: "Settings saved",
  });
  const onFinish = (v: Record<string, unknown>) => {
    const body = { ...v };
    if (!body.api_key) delete body.api_key; // empty = keep existing key
    save.mutate(body);
  };
  const test = async () => {
    setTesting(true);
    try {
      const r = await api<{ ok: boolean; reply: string }>("/agent/config/test", { method: "POST" });
      message.success(`Connected: ${r.reply}`);
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setTesting(false);
    }
  };
  return (
    <Card style={{ maxWidth: 720 }}>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Agent model settings
      </Typography.Title>
      {cfg.data && !cfg.data.configured && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} title="No model configured yet; AI structuring, completion and strategy generation are unavailable." />
      )}
      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Form.Item name="base_url" label="Base URL (OpenAI-compatible)" rules={[{ required: true }]}>
          <Input placeholder="https://api.example.com/v1" />
        </Form.Item>
        <Form.Item name="model" label="Model name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="api_key"
          label="API Key"
          extra={cfg.data?.api_key_masked ? `Current: ${cfg.data.api_key_masked} (leave empty to keep)` : "Not set"}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Space wrap>
          <Form.Item name="temperature" label="temperature">
            <InputNumber min={0} max={2} step={0.1} />
          </Form.Item>
          <Form.Item name="max_tokens" label="max_tokens">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="timeout_s" label="Timeout (seconds)">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="max_steps" label="Max steps">
            <InputNumber min={1} max={200} />
          </Form.Item>
        </Space>
        <Typography.Title level={5}>Case automation</Typography.Title>
        <Space wrap align="start">
          <Form.Item
            name="max_self_checks"
            label="Self-check attempts"
            extra="How many pytest self-checks to run at most after the AI writes a script; if the last one fails the script is not bound and the case is marked “Needs fix”"
          >
            <InputNumber min={1} max={20} />
          </Form.Item>
          <Form.Item
            name="auto_automate"
            label="Generate automation scripts after AI case generation"
            valuePropName="checked"
            extra="Generated and self-checked one by one in the background; progress is on the version page; can be switched off per generation"
          >
            <Switch />
          </Form.Item>
        </Space>
        <Space>
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            Save
          </Button>
          <Button onClick={test} loading={testing} disabled={!cfg.data?.configured}>
            Test connection
          </Button>
        </Space>
      </Form>
    </Card>
  );
}
