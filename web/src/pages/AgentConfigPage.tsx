import { useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, InputNumber, Space, Switch, Typography } from "antd";
import { useEffect, useState } from "react";

import { api, describeError } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AgentConfig } from "../api/types";
import { useAuth } from "../app/AuthGate";

/** P14 agent model settings (OpenAI-compatible); the API key is write-only, the page shows only a mask */
export function AgentConfigPage() {
  const cfg = useQuery({ queryKey: ["agent-config"], queryFn: () => api<AgentConfig>("/agent/config") });
  const { me } = useAuth();
  const readOnly = me?.role === "member"; // model endpoint and API key are admin-only
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const [testing, setTesting] = useState(false);
  useEffect(() => {
    if (cfg.data) form.setFieldsValue({ ...cfg.data, api_key: "" });
  }, [cfg.data, form]);
  const save = useApiMutation((body: Record<string, unknown>) => api<AgentConfig>("/agent/config", { method: "PUT", body }), {
    invalidate: [["agent-config"]],
    success: "设置已保存",
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
      message.success(`已连接：${r.reply}`);
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setTesting(false);
    }
  };
  return (
    <Card style={{ maxWidth: 720 }}>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Agent 模型设置
      </Typography.Title>
      {cfg.data && !cfg.data.configured && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} title="尚未配置模型；AI 结构化、补全和策略生成不可用。" />
      )}
      {readOnly && <Alert type="info" showIcon style={{ marginBottom: 16 }} title="只有管理员可以更改模型设置。" />}
      <Form form={form} layout="vertical" onFinish={onFinish} disabled={readOnly}>
        <Form.Item name="base_url" label="Base URL（兼容 OpenAI）" rules={[{ required: true }]}>
          <Input placeholder="https://api.example.com/v1" />
        </Form.Item>
        <Form.Item name="model" label="模型名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="api_key"
          label="API 密钥"
          extra={cfg.data?.api_key_masked ? `当前：${cfg.data.api_key_masked}（留空则保持不变）` : "未设置"}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Space wrap>
          <Form.Item name="temperature" label="温度">
            <InputNumber min={0} max={2} step={0.1} />
          </Form.Item>
          <Form.Item name="max_tokens" label="最大 token 数">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="timeout_s" label="超时（秒）">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="max_steps" label="最大步数">
            <InputNumber min={1} max={200} />
          </Form.Item>
        </Space>
        <Typography.Title level={5}>用例自动化</Typography.Title>
        <Space wrap align="start">
          <Form.Item
            name="max_self_checks"
            label="自检次数"
            extra="AI 写完脚本后最多运行多少次 pytest 自检；如果最后一次失败，脚本不会绑定，用例会标记为“待修复”"
          >
            <InputNumber min={1} max={20} />
          </Form.Item>
          <Form.Item
            name="default_scope_depth"
            label="用例范围默认深度"
            extra="0 只含需求已引用的对象，1 再向外一层，2 再向外一层。单条需求可以改。"
          >
            <InputNumber min={0} max={2} />
          </Form.Item>
          <Form.Item
            name="auto_automate"
            label="AI 生成用例后接着生成自动化脚本"
            valuePropName="checked"
            extra="会在后台逐条生成并自检；进度在版本页查看；每次生成都可以关闭此选项"
          >
            <Switch />
          </Form.Item>
        </Space>
        <Space>
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            保存
          </Button>
          <Button onClick={test} loading={testing} disabled={!cfg.data?.configured}>
            测试连接
          </Button>
        </Space>
      </Form>
    </Card>
  );
}
