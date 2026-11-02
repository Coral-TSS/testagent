import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Descriptions, Form, Input, Modal, Popconfirm, Row, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Defect, Person, Requirement, Role } from "../api/types";
import { AgentRunDrawer } from "../components/AgentRunDrawer";
import { CAUSE_LABEL, CAUSE_ROLE, DEFECT_ACTION, DEFECT_NEXT, DefectStatusTag, ROLE_LABEL, SEVERITY, SeverityTag } from "../components/DefectTags";
import { objLabel } from "../components/ObjLink";

/** P12 defect detail: requirement, cause category (accept the AI suggestion in one click), attributed people (inferred/manual), status flow */
export function DefectPage() {
  const { defectId = "" } = useParams();
  const qc = useQueryClient();
  const [form] = Form.useForm<{ title: string; description?: string; severity: string }>();
  const [runId, setRunId] = useState<string | null>(null);
  const [respOpen, setRespOpen] = useState(false);
  const [resp, setResp] = useState<{ person_id: string; role: Role }[]>([]);
  const q = useQuery({ queryKey: ["defect", defectId], queryFn: () => api<Defect>(`/defects/${defectId}`) });
  const d = q.data;
  const reqs = useQuery({
    queryKey: ["requirements", d?.version_id],
    queryFn: () => api<Requirement[]>(`/versions/${d!.version_id}/requirements`),
    enabled: Boolean(d?.version_id),
  });
  const persons = useQuery({ queryKey: ["persons"], queryFn: () => api<Person[]>("/persons") });
  useEffect(() => {
    if (d) form.setFieldsValue({ title: d.title, description: d.description || "", severity: d.severity });
  }, [d, form]);

  const onSuccess = (row: Defect) => {
    qc.setQueryData(["defect", defectId], row);
    qc.invalidateQueries({ queryKey: ["defects"] });
  };
  const patch = useApiMutation((body: Record<string, unknown>) => api<Defect>(`/defects/${defectId}`, { method: "PATCH", body }), { onSuccess, success: "Saved" });
  const status = useApiMutation((s: string) => api<Defect>(`/defects/${defectId}/status`, { method: "POST", body: { status: s } }), { onSuccess });
  const setReqs = useApiMutation((ids: string[]) => api<Defect>(`/defects/${defectId}/requirements`, { method: "PUT", body: { requirement_ids: ids } }), { onSuccess });
  const infer = useApiMutation(() => api<Defect>(`/defects/${defectId}/infer-responsible`, { method: "POST" }), { onSuccess, success: "Inferred from the requirement and cause category" });
  const accept = useApiMutation(() => api<Defect>(`/defects/${defectId}/accept-suggestion`, { method: "POST" }), { onSuccess, success: "AI suggestion accepted" });
  const saveResp = useApiMutation((body: { person_id: string; role: Role }[]) => api<Defect>(`/defects/${defectId}/responsible`, { method: "PUT", body }), {
    onSuccess: (row) => {
      onSuccess(row);
      setRespOpen(false);
    },
    success: "Attribution updated",
  });

  if (!d) return <Card loading />;
  const cause = d.cause_category;
  return (
    <Row gutter={16}>
      <Col span={15}>
        <Card
          title={
            <Space>
              {d.code} <DefectStatusTag status={d.status} /> <SeverityTag value={d.severity} />
              {d.created_by === "agent" && <Tag color="purple">Created by AI</Tag>}
            </Space>
          }
          extra={
            <Space>
              {d.agent_run_id && <Button onClick={() => setRunId(d.agent_run_id!)}>View AI trace</Button>}
              {(DEFECT_NEXT[d.status] || []).map((s) => (
                <Button key={s} danger={s === "rejected"} onClick={() => status.mutate(s)}>
                  {DEFECT_ACTION[s]}
                </Button>
              ))}
            </Space>
          }
        >
          <Form form={form} layout="vertical" onFinish={(v) => patch.mutate(v)}>
            <Form.Item name="title" label="Title" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="severity" label="Severity">
              <Select style={{ width: 160 }} options={Object.entries(SEVERITY).map(([value, [label]]) => ({ value, label }))} />
            </Form.Item>
            <Form.Item name="description" label="Description / repro steps">
              <Input.TextArea rows={5} />
            </Form.Item>
            <Button htmlType="submit" loading={patch.isPending}>
              Save
            </Button>
          </Form>
          {d.analysis && (
            <Alert style={{ marginTop: 16 }} type="info" showIcon title="AI cause analysis (for reference only)" description={<Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{d.analysis}</Typography.Paragraph>} />
          )}
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title="Cause category" style={{ marginBottom: 16 }}>
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Select
              aria-label="Cause category"
              style={{ width: "100%" }}
              value={cause}
              onChange={(v) => patch.mutate({ cause_category: v })}
              options={Object.entries(CAUSE_LABEL).map(([value, label]) => ({ value, label }))}
            />
            {d.suggested_cause && d.suggested_cause !== cause && (
              <Space>
                <Tag color="purple">AI suggestion: {CAUSE_LABEL[d.suggested_cause]}</Tag>
                <Button size="small" type="primary" loading={accept.isPending} onClick={() => accept.mutate(undefined)}>
                  Accept
                </Button>
              </Space>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {CAUSE_ROLE[cause] ? `Attributed to the requirement’s ${CAUSE_ROLE[cause]}` : "Environment issues and undetermined defects are not attributed to people"}
            </Typography.Text>
          </Space>
        </Card>
        <Card size="small" title="Requirements" style={{ marginBottom: 16 }}>
          <Select
            aria-label="Requirements"
            mode="multiple"
            style={{ width: "100%" }}
            value={d.requirements.map((r) => r.id)}
            disabled={!d.version_id}
            onChange={(ids) => setReqs.mutate(ids)}
            optionFilterProp="label"
            options={(reqs.data || d.requirements).map((r) => ({ value: r.id, label: `${r.code} ${r.title}` }))}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {d.requirements.some((r) => r.inferred) ? "Defaults to the case's linked requirements; can be changed" : "Adjusted manually"}
          </Typography.Text>
        </Card>
        <Card
          size="small"
          title="Attributed to"
          style={{ marginBottom: 16 }}
          extra={
            <Space>
              <Tooltip title="Taken from the matching role of the requirement by cause category (manually chosen people are kept)">
                <Button size="small" loading={infer.isPending} onClick={() => infer.mutate(undefined)}>
                  Infer from requirement
                </Button>
              </Tooltip>
              <Button
                size="small"
                onClick={() => {
                  setResp(d.responsible.map((r) => ({ person_id: r.person_id, role: r.role })));
                  setRespOpen(true);
                }}
              >
                Change
              </Button>
            </Space>
          }
        >
          {d.responsible.length ? (
            <Space wrap>
              {d.responsible.map((r) => (
                <Tag key={`${r.person_id}-${r.role}`} color={r.inferred ? "blue" : "gold"}>
                  {r.person_name} ({ROLE_LABEL[r.role]}){r.inferred ? " · inferred" : " · manual"}
                </Tag>
              ))}
            </Space>
          ) : (
            <Typography.Text type="secondary">None</Typography.Text>
          )}
          {d.responsible_manual && (
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Set manually: no automatic recalculation when the cause or requirements change
              </Typography.Text>
            </div>
          )}
        </Card>
        <Card size="small" title="Trace">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Case">{d.case ? <Link to={`/cases/${d.case.id}`}>{objLabel(d.case.title, d.case.code)}</Link> : "-"}</Descriptions.Item>
            <Descriptions.Item label="Execution">{d.execution ? <Link to={`/executions/${d.execution.id}`}>View execution</Link> : "-"}</Descriptions.Item>
            {d.execution?.task_run_id && (
              <Descriptions.Item label="Run">
                <Link to={`/runs/${d.execution.task_run_id}`}>Run</Link>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="Node / API">
              {d.links.length ? d.links.map((l) => <Tag key={l.target_id} color={l.target_type === "api" ? "green" : "blue"}>{l.name}{l.code_ref ? ` · ${l.code_ref}` : ""}</Tag>) : "-"}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>
      <Modal title="Change attributed people" open={respOpen} onCancel={() => setRespOpen(false)} onOk={() => saveResp.mutate(resp)} confirmLoading={saveResp.isPending}>
        <Typography.Paragraph type="secondary">Once set manually, changing the cause category or requirements will not overwrite this.</Typography.Paragraph>
        <Table
          size="small"
          rowKey={(_, i) => String(i)}
          pagination={false}
          dataSource={resp}
          columns={[
            {
              title: "Person",
              render: (_: unknown, row, i) => (
                <Select
                  style={{ width: 160 }}
                  showSearch
                  optionFilterProp="label"
                  value={row.person_id}
                  onChange={(v) => setResp(resp.map((r, j) => (j === i ? { ...r, person_id: v } : r)))}
                  options={(persons.data || []).filter((p) => p.active || p.id === row.person_id).map((p) => ({ value: p.id, label: p.name }))}
                />
              ),
            },
            {
              title: "Role",
              render: (_: unknown, row, i) => (
                <Select style={{ width: 110 }} value={row.role} onChange={(v) => setResp(resp.map((r, j) => (j === i ? { ...r, role: v } : r)))} options={Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))} />
              ),
            },
            {
              title: "",
              render: (_: unknown, __, i) => (
                <Popconfirm title="Remove?" onConfirm={() => setResp(resp.filter((_, j) => j !== i))}>
                  <a>Remove</a>
                </Popconfirm>
              ),
            },
          ]}
        />
        <Button style={{ marginTop: 8 }} onClick={() => setResp([...resp, { person_id: persons.data?.[0]?.id || "", role: "developer" }])}>
          Add
        </Button>
      </Modal>
      <AgentRunDrawer runId={runId} onClose={() => setRunId(null)} />
    </Row>
  );
}
