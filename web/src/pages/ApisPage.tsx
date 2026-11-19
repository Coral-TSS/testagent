import { CloudDownloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { AutoComplete, Button, Card, Form, Input, Modal, Select, Space, Tabs, Tag, Typography } from "antd";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { ApiEndpoint, Environment, IoParam } from "../api/types";
import { ApiSchemaView } from "../components/ApiSchema";
import { IoParamsTable } from "../components/IoParams";
import { SimpleCrud } from "../components/SimpleCrud";

function parseJson(raw: unknown): { ok: boolean; value: unknown } {
  const text = String(raw || "").trim();
  if (!text) return { ok: true, value: null };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, value: null };
  }
}

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];
const CONTENT_TYPES = ["application/json", "application/x-www-form-urlencoded", "multipart/form-data", "text/plain", "text/html"].map(
  (value) => ({ value }),
);

interface DocForm {
  description?: string;
  request_content_type?: string;
  response_content_type?: string;
  request_fields?: IoParam[];
  response_fields?: IoParam[];
  request_schema?: string;
  response_schema?: string;
}

/** P04 API registry: method, path, purpose, inputs/outputs (parameters, body, response fields) and formats */
export function ApisPage() {
  const { sutId = "" } = useParams();
  const key = ["apis", sutId];
  const apis = useQuery({ queryKey: key, queryFn: () => api<ApiEndpoint[]>(`/suts/${sutId}/apis`) });
  const create = useApiMutation((body: Record<string, unknown>) => api(`/suts/${sutId}/apis`, { method: "POST", body }), {
    invalidate: [key],
    success: "已保存",
  });
  const update = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/apis/${id}`, { method: "PATCH", body }),
    { invalidate: [key], success: "已保存" },
  );
  const remove = useApiMutation((id: string) => api(`/apis/${id}`, { method: "DELETE" }), { invalidate: [key] });
  const envs = useQuery({ queryKey: ["environments", sutId], queryFn: () => api<Environment[]>(`/suts/${sutId}/environments`) });
  const [importOpen, setImportOpen] = useState(false);
  const [importForm] = Form.useForm();
  const importer = useApiMutation(
    (body: { environment_id?: string; url?: string }) =>
      api<{ created: number; updated: number; total: number; field_suggestions?: number; link_suggestions?: number }>(`/suts/${sutId}/apis/import-openapi`, { method: "POST", body }),
    {
      invalidate: [key],
      onSuccess: (r) => {
        setImportOpen(false);
        Modal.success({ title: "OpenAPI 导入完成", content:
            `Total ${r.total} API(s): new ${r.created}, schema updated ${r.updated}` +
            (r.field_suggestions ? `; entity field suggestions from API fields ${r.field_suggestions} (rename/add; review them under “Model suggestions” on the version page)` : "") +
            (r.link_suggestions ? `; link suggestions from foreign-key fields ${r.link_suggestions} (review them under “Links” on the model page)` : ""),
        });
      },
    },
  );
  const [schemaOf, setSchemaOf] = useState<ApiEndpoint | null>(null);
  const [docTab, setDocTab] = useState<"fields" | "json">("fields");
  const [schemaForm] = Form.useForm<DocForm>();
  const openDoc = (row: ApiEndpoint) => {
    setSchemaOf(row);
    setDocTab("fields");
    schemaForm.resetFields();
    schemaForm.setFieldsValue({
      description: row.description || "",
      request_content_type: row.request_content_type || "",
      response_content_type: row.response_content_type || "",
      request_fields: row.io?.inputs || [],
      response_fields: row.io?.outputs || [],
      request_schema: row.request_schema ? JSON.stringify(row.request_schema, null, 2) : "",
      response_schema: row.response_schema ? JSON.stringify(row.response_schema, null, 2) : "",
    });
  };
  const saveSchema = (v: DocForm) => {
    const body: Record<string, unknown> = {
      description: v.description || null,
      request_content_type: v.request_content_type || null,
      response_content_type: v.response_content_type || null,
    };
    if (docTab === "json") {
      const req = parseJson(v.request_schema);
      const resp = parseJson(v.response_schema);
      if (!req.ok || !resp.ok) {
        schemaForm.setFields([
          ...(!req.ok ? [{ name: "request_schema" as const, errors: ["不是合法 JSON"] }] : []),
          ...(!resp.ok ? [{ name: "response_schema" as const, errors: ["不是合法 JSON"] }] : []),
        ]);
        return;
      }
      body.request_schema = req.value;
      body.response_schema = resp.value;
    } else {
      body.request_fields = v.request_fields || [];
      body.response_fields = v.response_fields || [];
    }
    update.mutate({ id: schemaOf!.id, body }, { onSuccess: () => setSchemaOf(null) });
  };
  return (
    <Card>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          API 注册表
        </Typography.Title>
        <Button
          icon={<CloudDownloadOutlined />}
          onClick={() => {
            importForm.setFieldsValue({ environment_id: envs.data?.[0]?.id, url: "" });
            setImportOpen(true);
          }}
        >
          从 OpenAPI 导入
        </Button>
      </Space>
      <Typography.Paragraph type="secondary">
        Each API records its purpose, inputs (parameters, body fields), outputs (response fields) and formats; expand a row to see the field table. Actions bound to an API get its inputs/outputs automatically. The AI
        builds request bodies for generated cases and automation scripts strictly by field name, type and unit (e.g. amount_minor in cents).
      </Typography.Paragraph>
      <SimpleCrud<ApiEndpoint>
        error={apis.isError}
        onRetry={() => apis.refetch()}
        title="API"
        emptyTitle="尚未登记 API"
        emptyHint="可手工添加，或点击上方“从 OpenAPI 导入”，一次性导入被测系统的 /openapi.json（含字段；字段和关系建议会自动生成）。"
        rows={apis.data}
        loading={apis.isLoading}
        columns={[
          { title: "方法", dataIndex: "method", width: 90, render: (m) => <Tag>{m}</Tag> },
          { title: "路径", dataIndex: "path", render: (p) => <code style={{ whiteSpace: "nowrap" }}>{p}</code> },
          { title: "名称", dataIndex: "name" },
          { title: "用途", dataIndex: "description", ellipsis: true, render: (d) => d || <Typography.Text type="secondary">未填写</Typography.Text> },
          {
            title: "输入 / 输出",
            width: 110,
            render: (_, row) =>
              row.io && (row.io.inputs.length || row.io.outputs.length) ? (
                <span>
                  In {row.io.inputs.length} · out {row.io.outputs.length}
                </span>
              ) : (
                "—"
              ),
          },
          {
            title: "代码位置",
            dataIndex: "code_ref",
            render: (r) =>
              r ? (
                /^https?:\/\//.test(r) ? (
                  <a href={r} target="_blank" rel="noreferrer">
                    关系
                  </a>
                ) : (
                  <code>{r}</code>
                )
              ) : (
                "-"
              ),
          },
          { title: "绑定的动作", dataIndex: "node_names", render: (names: string[] = []) => names.map((x) => <Tag key={x}>{x}</Tag>) },
          {
            title: "模式",
            width: 90,
            render: (_, row) =>
              row.request_schema || row.response_schema ? <Tag color="green">已登记</Tag> : <Tag>未登记</Tag>,
          },
        ]}
        expandable={{ expandedRowRender: (row) => <ApiSchemaView api={row} /> }}
        extraActions={(row) => <a onClick={() => openDoc(row)}>编辑描述和字段</a>}
        fields={
          <>
            <Form.Item name="method" label="方法" rules={[{ required: true }]} initialValue="GET">
              <Select options={METHODS.map((m) => ({ value: m, label: m }))} />
            </Form.Item>
            <Form.Item name="path" label="路径" rules={[{ required: true, pattern: /^\//, message: "以 / 开头" }]}>
              <Input placeholder="/api/orders/{id}" />
            </Form.Item>
            <Form.Item name="name" label="名称">
              <Input />
            </Form.Item>
            <Form.Item name="code_ref" label="代码位置（链接）">
              <Input />
            </Form.Item>
            <Form.Item name="description" label="用途（该 API 做什么）">
              <Input.TextArea rows={2} />
            </Form.Item>
          </>
        }
        onCreate={(v) => create.mutateAsync(v)}
        onUpdate={(row, v) => {
          const body = Object.fromEntries(
            Object.entries(v).filter(([k]) => !["request_schema", "response_schema", "io"].includes(k)),
          );
          return update.mutateAsync({ id: row.id, body });
        }}
        onDelete={(row) => remove.mutate(row.id)}
      />
      <Modal
        open={importOpen}
        title="从被测系统的 OpenAPI 导入 API 和模式"
        onCancel={() => setImportOpen(false)}
        onOk={() => importForm.submit()}
        confirmLoading={importer.isPending}
      >
        <Form
          form={importForm}
          layout="vertical"
          onFinish={(v) => importer.mutate({ environment_id: v.environment_id || undefined, url: v.url || undefined })}
        >
          <Form.Item name="environment_id" label="环境（读取 {base_url}/openapi.json）">
            <Select allowClear options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} · ${e.base_url}` }))} />
          </Form.Item>
          <Form.Item name="url" label="或直接输入 OpenAPI 地址">
            <Input placeholder="http://127.0.0.1:8766/openapi.json" />
          </Form.Item>
          <Typography.Text type="secondary">已有 API 按“方法 + 路径”匹配；只更新模式，名称和动作绑定保持不变。</Typography.Text>
        </Form>
      </Modal>
      <Modal
        open={schemaOf !== null}
        title={schemaOf ? `Description & fields · ${schemaOf.method} ${schemaOf.path}` : ""}
        width={1000}
        onCancel={() => setSchemaOf(null)}
        onOk={() => schemaForm.submit()}
        confirmLoading={update.isPending}
        forceRender
      >
        <Form form={schemaForm} layout="vertical" onFinish={saveSchema}>
          <Form.Item name="description" label="用途（该 API 做什么）">
            <Input.TextArea rows={2} placeholder="例如：创建采购订单，并根据金额和币种决定是否需要审批" />
          </Form.Item>
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="request_content_type" label="输入格式（请求体类型）">
              <AutoComplete options={CONTENT_TYPES} placeholder="application/json" />
            </Form.Item>
            <Form.Item name="response_content_type" label="输出格式（响应类型）">
              <AutoComplete options={CONTENT_TYPES} placeholder="application/json" />
            </Form.Item>
          </Space>
          <Tabs
            activeKey={docTab}
            onChange={(k) => setDocTab(k as "fields" | "json")}
            items={[
              {
                key: "fields",
                label: "字段表",
                children: (
                  <>
                    <Form.Item name="request_fields" label="输入：参数和请求体字段">
                      <IoParamsTable label="输入参数" showLocation locations={["body", "path", "query", "header", "form"]} addLabel="添加输入字段" />
                    </Form.Item>
                    <Form.Item name="response_fields" label="输出：成功响应字段">
                      <IoParamsTable label="输出参数" addLabel="添加输出字段" />
                    </Form.Item>
                    <Typography.Text type="secondary">
                      Saving writes back to the API schema (existing constraints such as ranges are kept); switch to the “JSON (advanced)” tab to edit the schema directly.
                    </Typography.Text>
                  </>
                ),
              },
              {
                key: "json",
                label: "JSON（高级）",
                children: (
                  <>
                    <Form.Item name="request_schema" label='请求模式（JSON，例如 {"body": {"type": "object", "properties": {...}}}）'>
                      <Input.TextArea rows={10} style={{ fontFamily: "monospace" }} />
                    </Form.Item>
                    <Form.Item name="response_schema" label='响应模式（JSON，例如 {"201": {"description": "Created", "schema": {...}}}）'>
                      <Input.TextArea rows={6} style={{ fontFamily: "monospace" }} />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>
    </Card>
  );
}
