import { useQueryClient } from "@tanstack/react-query";
import { App, AutoComplete, Collapse, Input, Select, Space, Tabs, Typography } from "antd";
import { useState, type ReactNode } from "react";

import { api, describeError } from "../api/client";
import type { ApiEndpoint, IoParam } from "../api/types";
import { IoParamsTable } from "./IoParams";
import { SideDetailPanel } from "./panel/SideDetailPanel";
import { confirmDiscard } from "./panel/UnsavedGuard";

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];
const CONTENT_TYPES = ["application/json", "application/x-www-form-urlencoded", "multipart/form-data", "text/plain", "text/html"].map((value) => ({ value }));

interface ApiDraft {
  method: string;
  path: string;
  name: string;
  code_ref: string;
  description: string;
  request_content_type: string;
  response_content_type: string;
  request_fields: IoParam[];
  response_fields: IoParam[];
}

function fromApi(row?: ApiEndpoint | null): ApiDraft {
  return {
    method: row?.method || "POST",
    path: row?.path || "",
    name: row?.name || "",
    code_ref: row?.code_ref || "",
    description: row?.description || "",
    request_content_type: row?.request_content_type || "",
    response_content_type: row?.response_content_type || "",
    request_fields: row?.io?.inputs || [],
    response_fields: row?.io?.outputs || [],
  };
}

/** One editor for an API: identity, fields and a read-only schema, saved together. */
export function ApiPanel({ sutId, row, onClose }: { sutId: string; row: ApiEndpoint | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const [draft, setDraft] = useState<ApiDraft>(() => fromApi(row));
  const [baseline] = useState(() => JSON.stringify(fromApi(row)));
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(draft) !== baseline;
  const patch = (part: Partial<ApiDraft>) => setDraft((current) => ({ ...current, ...part }));

  const close = async () => {
    if (dirty && !(await confirmDiscard(modal))) return;
    onClose();
  };

  const save = async () => {
    if (!draft.path.startsWith("/")) {
      message.error("路径要以 / 开头");
      return;
    }
    const body = {
      method: draft.method,
      path: draft.path.trim(),
      name: draft.name.trim() || null,
      code_ref: draft.code_ref.trim() || null,
      description: draft.description.trim() || null,
      request_content_type: draft.request_content_type.trim() || null,
      response_content_type: draft.response_content_type.trim() || null,
      request_fields: draft.request_fields.filter((item) => item.name.trim()),
      response_fields: draft.response_fields.filter((item) => item.name.trim()),
    };
    setSaving(true);
    try {
      if (row) await api(`/apis/${row.id}`, { method: "PATCH", body });
      else {
        const created = await api<ApiEndpoint>(`/suts/${sutId}/apis`, { method: "POST", body: { method: body.method, path: body.path, name: body.name, code_ref: body.code_ref, description: body.description } });
        if (body.request_fields.length || body.response_fields.length || body.request_content_type || body.response_content_type) {
          await api(`/apis/${created.id}`, { method: "PATCH", body });
        }
      }
      message.success("已保存");
      qc.invalidateQueries({ queryKey: ["apis", sutId] });
      onClose();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SideDetailPanel
      kind="api"
      title={row ? `${row.method} ${row.path}` : "新建 API"}
      saving={saving}
      onClose={() => void close()}
      onCancel={() => void close()}
      onSave={() => void save()}
    >
      <Tabs
        items={[
          {
            key: "basic",
            label: "基本信息",
            children: (
              <>
                <Field label="方法">
                  <Select style={{ width: "100%" }} value={draft.method} options={METHODS.map((method) => ({ value: method, label: method }))} onChange={(method) => patch({ method })} />
                </Field>
                <Field label="路径">
                  <Input value={draft.path} placeholder="/api/orders/{id}" onChange={(e) => patch({ path: e.target.value })} />
                </Field>
                <Field label="名称">
                  <Input value={draft.name} onChange={(e) => patch({ name: e.target.value })} />
                </Field>
                <Field label="代码位置（链接）">
                  <Input value={draft.code_ref} onChange={(e) => patch({ code_ref: e.target.value })} />
                </Field>
                <Field label="用途（该 API 做什么）">
                  <Input.TextArea rows={2} value={draft.description} placeholder="例如：创建采购订单，并根据金额和币种决定是否需要审批" onChange={(e) => patch({ description: e.target.value })} />
                </Field>
              </>
            ),
          },
          {
            key: "io",
            label: "输入输出",
            children: (
              <>
                <Space style={{ width: "100%" }} styles={{ item: { flex: 1 } }}>
                  <Field label="输入格式">
                    <AutoComplete style={{ width: "100%" }} options={CONTENT_TYPES} value={draft.request_content_type} placeholder="application/json" onChange={(request_content_type) => patch({ request_content_type })} />
                  </Field>
                  <Field label="输出格式">
                    <AutoComplete style={{ width: "100%" }} options={CONTENT_TYPES} value={draft.response_content_type} placeholder="application/json" onChange={(response_content_type) => patch({ response_content_type })} />
                  </Field>
                </Space>
                <IoParamsTable label="输入参数" value={draft.request_fields} onChange={(request_fields) => patch({ request_fields })} showLocation locations={["body", "path", "query", "header", "form"]} emptyText="还没有输入" />
                <div style={{ height: 12 }} />
                <IoParamsTable label="输出参数" value={draft.response_fields} onChange={(response_fields) => patch({ response_fields })} emptyText="还没有输出" />
                <Typography.Paragraph type="secondary">保存时按字段写回 API 模式，已有约束（例如取值范围）会保留。</Typography.Paragraph>
              </>
            ),
          },
          {
            key: "advanced",
            label: "高级",
            children: (
              <Collapse
                defaultActiveKey={["schema"]}
                items={[{
                  key: "schema",
                  label: "原始模式（只读）",
                  children: (
                    <Input.TextArea readOnly rows={8} style={{ fontFamily: "monospace" }} value={JSON.stringify({ request: row?.request_schema || null, response: row?.response_schema || null }, null, 2)} />
                  ),
                }]}
              />
            ),
          },
        ]}
      />
    </SideDetailPanel>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}
