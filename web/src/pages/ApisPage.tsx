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
    success: "Saved",
  });
  const update = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/apis/${id}`, { method: "PATCH", body }),
    { invalidate: [key], success: "Saved" },
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
        Modal.success({ title: "OpenAPI import finished", content:
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
          ...(!req.ok ? [{ name: "request_schema" as const, errors: ["is not valid JSON"] }] : []),
          ...(!resp.ok ? [{ name: "response_schema" as const, errors: ["is not valid JSON"] }] : []),
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
          API registry
        </Typography.Title>
        <Button
          icon={<CloudDownloadOutlined />}
          onClick={() => {
            importForm.setFieldsValue({ environment_id: envs.data?.[0]?.id, url: "" });
            setImportOpen(true);
          }}
        >
          Import from OpenAPI
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
        emptyTitle="No APIs registered yet"
        emptyHint="Add one by hand, or click “Import from OpenAPI” above to import the SUT's /openapi.json in one go (with fields; field and link suggestions are generated automatically)."
        rows={apis.data}
        loading={apis.isLoading}
        columns={[
          { title: "Method", dataIndex: "method", width: 90, render: (m) => <Tag>{m}</Tag> },
          { title: "Path", dataIndex: "path", render: (p) => <code style={{ whiteSpace: "nowrap" }}>{p}</code> },
          { title: "Name", dataIndex: "name" },
          { title: "Purpose", dataIndex: "description", ellipsis: true, render: (d) => d || <Typography.Text type="secondary">Not filled in</Typography.Text> },
          {
            title: "Inputs / outputs",
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
            title: "Code location",
            dataIndex: "code_ref",
            render: (r) =>
              r ? (
                /^https?:\/\//.test(r) ? (
                  <a href={r} target="_blank" rel="noreferrer">
                    Link
                  </a>
                ) : (
                  <code>{r}</code>
                )
              ) : (
                "-"
              ),
          },
          { title: "Bound actions", dataIndex: "node_names", render: (names: string[] = []) => names.map((x) => <Tag key={x}>{x}</Tag>) },
          {
            title: "Schema",
            width: 90,
            render: (_, row) =>
              row.request_schema || row.response_schema ? <Tag color="green">Registered</Tag> : <Tag>not registered</Tag>,
          },
        ]}
        expandable={{ expandedRowRender: (row) => <ApiSchemaView api={row} /> }}
        extraActions={(row) => <a onClick={() => openDoc(row)}>Edit description & fields</a>}
        fields={
          <>
            <Form.Item name="method" label="Method" rules={[{ required: true }]} initialValue="GET">
              <Select options={METHODS.map((m) => ({ value: m, label: m }))} />
            </Form.Item>
            <Form.Item name="path" label="Path" rules={[{ required: true, pattern: /^\//, message: "Starts with /" }]}>
              <Input placeholder="/api/orders/{id}" />
            </Form.Item>
            <Form.Item name="name" label="Name">
              <Input />
            </Form.Item>
            <Form.Item name="code_ref" label="Code location (link)">
              <Input />
            </Form.Item>
            <Form.Item name="description" label="Purpose (what this API does)">
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
        title="Import APIs and schemas from the SUT's OpenAPI"
        onCancel={() => setImportOpen(false)}
        onOk={() => importForm.submit()}
        confirmLoading={importer.isPending}
      >
        <Form
          form={importForm}
          layout="vertical"
          onFinish={(v) => importer.mutate({ environment_id: v.environment_id || undefined, url: v.url || undefined })}
        >
          <Form.Item name="environment_id" label="Environment (reads {base_url}/openapi.json)">
            <Select allowClear options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} · ${e.base_url}` }))} />
          </Form.Item>
          <Form.Item name="url" label="Or enter the OpenAPI address directly">
            <Input placeholder="http://127.0.0.1:8766/openapi.json" />
          </Form.Item>
          <Typography.Text type="secondary">Existing APIs are matched by “method + path”; only the schema is updated, names and action bindings stay.</Typography.Text>
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
          <Form.Item name="description" label="Purpose (what this API does)">
            <Input.TextArea rows={2} placeholder="e.g. Create a purchase order and decide by amount and currency whether approval is required" />
          </Form.Item>
          <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
            <Form.Item name="request_content_type" label="Input format (request body type)">
              <AutoComplete options={CONTENT_TYPES} placeholder="application/json" />
            </Form.Item>
            <Form.Item name="response_content_type" label="Output format (response type)">
              <AutoComplete options={CONTENT_TYPES} placeholder="application/json" />
            </Form.Item>
          </Space>
          <Tabs
            activeKey={docTab}
            onChange={(k) => setDocTab(k as "fields" | "json")}
            items={[
              {
                key: "fields",
                label: "Field table",
                children: (
                  <>
                    <Form.Item name="request_fields" label="Inputs: parameters and body fields">
                      <IoParamsTable label="Input parameters" showLocation locations={["body", "path", "query", "header", "form"]} addLabel="Add input field" />
                    </Form.Item>
                    <Form.Item name="response_fields" label="Outputs: success response fields">
                      <IoParamsTable label="Output parameters" addLabel="Add output field" />
                    </Form.Item>
                    <Typography.Text type="secondary">
                      Saving writes back to the API schema (existing constraints such as ranges are kept); switch to the “JSON (advanced)” tab to edit the schema directly.
                    </Typography.Text>
                  </>
                ),
              },
              {
                key: "json",
                label: "JSON (advanced)",
                children: (
                  <>
                    <Form.Item name="request_schema" label='Request schema (JSON, e.g. {"body": {"type": "object", "properties": {...}}})'>
                      <Input.TextArea rows={10} style={{ fontFamily: "monospace" }} />
                    </Form.Item>
                    <Form.Item name="response_schema" label='Response schema (JSON, e.g. {"201": {"description": "Created", "schema": {...}}})'>
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
