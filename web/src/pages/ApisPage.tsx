import { CloudDownloadOutlined, PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { usePageSut } from "../app/modelScope";
import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { ApiEndpoint, Environment } from "../api/types";
import { ApiPanel } from "../components/ApiPanel";
import { ApiSchemaView } from "../components/ApiSchema";
import { EmptyState } from "../components/EmptyState";
import { ListTable } from "../components/ListView";
import { AppModal } from "../components/panel/AppModal";

/** P04 API registry: method, path, purpose, inputs/outputs (parameters, body, response fields) and formats */
export function ApisPage() {
  const { sutId, versionId, ready } = usePageSut();
  const key = ["apis", sutId];
  const apis = useQuery({ queryKey: key, queryFn: () => api<ApiEndpoint[]>(`/suts/${sutId}/apis`), enabled: ready });
  const remove = useApiMutation((id: string) => api(`/apis/${id}`, { method: "DELETE" }), { invalidate: [key] });
  const envs = useQuery({ queryKey: ["environments", sutId], queryFn: () => api<Environment[]>(`/suts/${sutId}/environments`) });
  const [importOpen, setImportOpen] = useState(false);
  const [importForm] = Form.useForm();
  const importer = useApiMutation(
    (body: { environment_id?: string; url?: string }) =>
      api<{ created: number; updated: number; total: number; field_suggestions?: number; link_suggestions?: number }>(`/suts/${sutId}/apis/import-openapi`, { method: "POST", body, params: versionId ? { version_id: versionId } : undefined }),
    {
      invalidate: [key],
      onSuccess: (r) => {
        setImportOpen(false);
        Modal.success({ title: "OpenAPI 导入完成", content:
            `共 ${r.total} 条 API：新增 ${r.created}，模式已更新 ${r.updated}` +
            (r.field_suggestions ? `；根据 API 字段生成了 ${r.field_suggestions} 条实体字段建议（重命名/新增；请在版本页的“模型建议”中评审）` : "") +
            (r.link_suggestions ? `；根据外键字段生成了 ${r.link_suggestions} 条关系建议（请在模型页的“关系”中评审）` : ""),
        });
      },
    },
  );
  const [editing, setEditing] = useState<ApiEndpoint | null | "new">(null);
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
        每条 API 都会记录其用途、输入（参数、请求体字段）、输出（响应字段）和格式；展开行可查看字段表。绑定到 API 的动作会自动获得其输入/输出。AI
        生成用例和自动化脚本时，会严格按字段名、类型和单位构造请求体（例如 amount_minor 以分为单位）。
      </Typography.Paragraph>
      <div className={editing ? "model-stage model-stage-auto" : undefined}>
      <div style={{ flex: 1, minWidth: 0 }}>
      <Space style={{ marginBottom: 12, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={5} style={{ margin: 0 }}>API</Typography.Title>
        <Button size="small" icon={<PlusOutlined />} onClick={() => setEditing("new")}>添加</Button>
      </Space>
      <ListTable<ApiEndpoint>
        error={apis.isError}
        onRetry={() => apis.refetch()}
        label="API"
        size="small"
        rowKey="id"
        loading={apis.isLoading}
        dataSource={apis.data}
        expandable={{ expandedRowRender: (row) => <ApiSchemaView api={row} /> }}
        locale={{ emptyText: <EmptyState title="尚未登记 API" hint="可手工添加，或点击上方“从 OpenAPI 导入”。" actionLabel="添加" onAction={() => setEditing("new")} /> }}
        onRow={(row) => ({ onClick: () => setEditing(row), style: { cursor: "pointer" } })}
        columns={[
          { title: "方法", dataIndex: "method", width: 90, render: (m) => <Tag>{m}</Tag> },
          { title: "路径", dataIndex: "path", render: (p) => <code style={{ whiteSpace: "nowrap" }}>{p}</code> },
          { title: "名称", dataIndex: "name" },
          { title: "用途", dataIndex: "description", ellipsis: true, render: (d) => d || <Typography.Text type="secondary">未填写</Typography.Text> },
          {
            title: "输入 / 输出",
            width: 110,
            render: (_, row) => row.io && (row.io.inputs.length || row.io.outputs.length) ? <span>入 {row.io.inputs.length} · 出 {row.io.outputs.length}</span> : "—",
          },
          {
            title: "代码位置",
            dataIndex: "code_ref",
            render: (r) => r ? (/^https?:\/\//.test(r) ? <a href={r} target="_blank" rel="noreferrer">链接</a> : <code>{r}</code>) : "-",
          },
          { title: "绑定的动作", dataIndex: "node_names", render: (names: string[] = []) => names.map((x) => <Tag key={x}>{x}</Tag>) },
          { title: "模式", width: 90, render: (_, row) => (row.request_schema || row.response_schema ? <Tag color="green">已登记</Tag> : <Tag>未登记</Tag>) },
          {
            title: "动作",
            width: 80,
            render: (_, row) => (
              <Popconfirm title="确定删除？" onConfirm={(event) => { event?.stopPropagation(); remove.mutate(row.id); }}>
                <a onClick={(event) => event.stopPropagation()}>删除</a>
              </Popconfirm>
            ),
          },
        ]}
      />
      </div>
      {editing && <ApiPanel sutId={sutId} row={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      </div>
      <AppModal
        size="sm"
        title="从被测系统的 OpenAPI 导入 API 和模式"
        help="已有 API 按“方法 + 路径”匹配；只更新模式，名称和动作绑定保持不变。"
        okText="导入"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        onOk={() => importForm.submit()}
        confirmLoading={importer.isPending}
      >
        <Form form={importForm} layout="vertical" onFinish={(v) => importer.mutate({ environment_id: v.environment_id || undefined, url: v.url || undefined })}>
          <Form.Item name="environment_id" label="环境（读取 {base_url}/openapi.json）">
            <Select allowClear options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} · ${e.base_url}` }))} />
          </Form.Item>
          <Form.Item name="url" label="或直接输入 OpenAPI 地址">
            <Input placeholder="http://127.0.0.1:8766/openapi.json" />
          </Form.Item>
        </Form>
      </AppModal>
    </Card>
  );
}
