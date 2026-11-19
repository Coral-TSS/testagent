import { ListTable } from "../components/ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Descriptions, Form, Input, Modal, Popconfirm, Row, Select, Space, Tag, Tooltip, Typography } from "antd";
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
  const patch = useApiMutation((body: Record<string, unknown>) => api<Defect>(`/defects/${defectId}`, { method: "PATCH", body }), { onSuccess, success: "已保存" });
  const status = useApiMutation((s: string) => api<Defect>(`/defects/${defectId}/status`, { method: "POST", body: { status: s } }), { onSuccess });
  const setReqs = useApiMutation((ids: string[]) => api<Defect>(`/defects/${defectId}/requirements`, { method: "PUT", body: { requirement_ids: ids } }), { onSuccess });
  const infer = useApiMutation(() => api<Defect>(`/defects/${defectId}/infer-responsible`, { method: "POST" }), { onSuccess, success: "根据需求和原因类别推断" });
  const accept = useApiMutation(() => api<Defect>(`/defects/${defectId}/accept-suggestion`, { method: "POST" }), { onSuccess, success: "已接受 AI 建议" });
  const saveResp = useApiMutation((body: { person_id: string; role: Role }[]) => api<Defect>(`/defects/${defectId}/responsible`, { method: "PUT", body }), {
    onSuccess: (row) => {
      onSuccess(row);
      setRespOpen(false);
    },
    success: "归因已更新",
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
              {d.created_by === "agent" && <Tag color="purple">由 AI 创建</Tag>}
            </Space>
          }
          extra={
            <Space>
              {d.agent_run_id && <Button onClick={() => setRunId(d.agent_run_id!)}>查看 AI 追踪</Button>}
              {(DEFECT_NEXT[d.status] || []).map((s) => (
                <Button key={s} danger={s === "rejected"} onClick={() => status.mutate(s)}>
                  {DEFECT_ACTION[s]}
                </Button>
              ))}
            </Space>
          }
        >
          <Form form={form} layout="vertical" onFinish={(v) => patch.mutate(v)}>
            <Form.Item name="title" label="标题" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="severity" label="严重级别">
              <Select style={{ width: 160 }} options={Object.entries(SEVERITY).map(([value, [label]]) => ({ value, label }))} />
            </Form.Item>
            <Form.Item name="description" label="描述 / 复现步骤">
              <Input.TextArea rows={5} />
            </Form.Item>
            <Button htmlType="submit" loading={patch.isPending}>
              保存
            </Button>
          </Form>
          {d.analysis && (
            <Alert style={{ marginTop: 16 }} type="info" showIcon title="AI 原因分析（仅供参考）" description={<Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{d.analysis}</Typography.Paragraph>} />
          )}
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title="原因类别" style={{ marginBottom: 16 }}>
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Select
              aria-label="原因类别"
              style={{ width: "100%" }}
              value={cause}
              onChange={(v) => patch.mutate({ cause_category: v })}
              options={Object.entries(CAUSE_LABEL).map(([value, label]) => ({ value, label }))}
            />
            {d.suggested_cause && d.suggested_cause !== cause && (
              <Space>
                <Tag color="purple">AI 建议：{CAUSE_LABEL[d.suggested_cause]}</Tag>
                <Button size="small" type="primary" loading={accept.isPending} onClick={() => accept.mutate(undefined)}>
                  接受
                </Button>
              </Space>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {CAUSE_ROLE[cause] ? `归因于需求的${CAUSE_ROLE[cause]}` : "环境问题和待判定缺陷不归因到人员"}
            </Typography.Text>
          </Space>
        </Card>
        <Card size="small" title="需求" style={{ marginBottom: 16 }}>
          <Select
            aria-label="需求"
            mode="multiple"
            style={{ width: "100%" }}
            value={d.requirements.map((r) => r.id)}
            disabled={!d.version_id}
            onChange={(ids) => setReqs.mutate(ids)}
            optionFilterProp="label"
            options={(reqs.data || d.requirements).map((r) => ({ value: r.id, label: `${r.code} ${r.title}` }))}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {d.requirements.some((r) => r.inferred) ? "默认为用例如关联的需求；可以更改" : "已手工调整"}
          </Typography.Text>
        </Card>
        <Card
          size="small"
          title="归因于"
          style={{ marginBottom: 16 }}
          extra={
            <Space>
              <Tooltip title="按原因类别取自需求上对应角色的人员（手工选定的人员会保留）">
                <Button size="small" loading={infer.isPending} onClick={() => infer.mutate(undefined)}>
                  根据需求推断
                </Button>
              </Tooltip>
              <Button
                size="small"
                onClick={() => {
                  setResp(d.responsible.map((r) => ({ person_id: r.person_id, role: r.role })));
                  setRespOpen(true);
                }}
              >
                变更
              </Button>
            </Space>
          }
        >
          {d.responsible.length ? (
            <Space wrap>
              {d.responsible.map((r) => (
                <Tag key={`${r.person_id}-${r.role}`} color={r.inferred ? "blue" : "gold"}>
                  {r.person_name} ({ROLE_LABEL[r.role]}){r.inferred ? " · 推断" : " · 手工"}
                </Tag>
              ))}
            </Space>
          ) : (
            <Typography.Text type="secondary">无</Typography.Text>
          )}
          {d.responsible_manual && (
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Set manually: no automatic recalculation when the cause or requirements change
              </Typography.Text>
            </div>
          )}
        </Card>
        <Card size="small" title="追踪">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="用例">{d.case ? <Link to={`/cases/${d.case.id}`}>{objLabel(d.case.title, d.case.code)}</Link> : "-"}</Descriptions.Item>
            <Descriptions.Item label="执行">{d.execution ? <Link to={`/executions/${d.execution.id}`}>查看执行</Link> : "-"}</Descriptions.Item>
            {d.execution?.task_run_id && (
              <Descriptions.Item label="执行">
                <Link to={`/runs/${d.execution.task_run_id}`}>执行</Link>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="节点 / API">
              {d.links.length ? d.links.map((l) => <Tag key={l.target_id} color={l.target_type === "api" ? "green" : "blue"}>{l.name}{l.code_ref ? ` · ${l.code_ref}` : ""}</Tag>) : "-"}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>
      <Modal title="变更归因人员" open={respOpen} onCancel={() => setRespOpen(false)} onOk={() => saveResp.mutate(resp)} confirmLoading={saveResp.isPending}>
        <Typography.Paragraph type="secondary">一旦手工设定，再变更原因类别或需求都不会覆盖此项。</Typography.Paragraph>
        <ListTable
          label="缺陷责任"
          size="small"
          rowKey="_i"

          dataSource={resp.map((r, _i) => ({ ...r, _i }))}
          columns={[
            {
              title: "人员",
              render: (_: unknown, row) => (
                <Select
                  style={{ width: 160 }}
                  showSearch
                  optionFilterProp="label"
                  value={row.person_id}
                  onChange={(v) => setResp(resp.map((r, j) => (j === row._i ? { ...r, person_id: v } : r)))}
                  options={(persons.data || []).filter((p) => p.active || p.id === row.person_id).map((p) => ({ value: p.id, label: p.name }))}
                />
              ),
            },
            {
              title: "角色",
              render: (_: unknown, row) => (
                <Select style={{ width: 110 }} value={row.role} onChange={(v) => setResp(resp.map((r, j) => (j === row._i ? { ...r, role: v } : r)))} options={Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))} />
              ),
            },
            {
              title: "",
              render: (_: unknown, row) => (
                <Popconfirm title="要移除吗？" onConfirm={() => setResp(resp.filter((_, j) => j !== row._i))}>
                  <a>移除</a>
                </Popconfirm>
              ),
            },
          ]}
        />
        <Button style={{ marginTop: 8 }} onClick={() => setResp([...resp, { person_id: persons.data?.[0]?.id || "", role: "developer" }])}>
          添加
        </Button>
      </Modal>
      <AgentRunDrawer runId={runId} onClose={() => setRunId(null)} />
    </Row>
  );
}
