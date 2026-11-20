import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RobotOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Col, Descriptions, Form, Popconfirm, Row, Space, Tag, Timeline, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AiOutcome, CaseRevision, TestCase } from "../api/types";
import { ProposalDiff } from "../components/AiCompletion";
import { AgentRunDrawer } from "../components/AgentRunDrawer";
import { AutomationTag } from "../components/AutomationTag";
import { CaseExecutionPanel } from "../components/CaseExecutionPanel";
import { CaseForm, caseToForm, formToBody, type CaseFormValues } from "../components/CaseForm";
import { CaseStatusTag, ScenarioTag } from "../components/CaseTags";
import { CorrectionButton } from "../components/CorrectionButton";
import { CaseCoverageTags } from "../components/CoverageDetail";
import { fmtTime } from "../utils/time";
import { objLabel, PathText } from "../components/ObjLink";
import { CATEGORY_LABEL, QUALITY_TAGS } from "../utils/categories";
import { ReadyTaskFeedback } from "../components/ReadyTaskFeedback";

/** P09 test case detail: edit (creates revisions automatically), review status, revision history, correction */
export function CasePage() {
  const { caseId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [form] = Form.useForm<CaseFormValues>();
  const [runId, setRunId] = useState<string | null>(null);
  const tc = useQuery({ queryKey: ["case", caseId], queryFn: () => api<TestCase>(`/cases/${caseId}`) });
  const revisions = useQuery({ queryKey: ["case-revisions", caseId], queryFn: () => api<CaseRevision[]>(`/cases/${caseId}/revisions`) });
  useEffect(() => {
    if (tc.data) form.setFieldsValue(caseToForm(tc.data));
  }, [tc.data, form]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["case", caseId] });
    qc.invalidateQueries({ queryKey: ["case-revisions", caseId] });
    qc.invalidateQueries({ queryKey: ["cases"] });
    qc.invalidateQueries({ queryKey: ["coverage"] });
  };
  const save = useApiMutation((body: Record<string, unknown>) => api<TestCase>(`/cases/${caseId}`, { method: "PATCH", body }), {
    onSuccess: (c) => {
      message.success(c.revision !== tc.data?.revision ? `已保存为修订 ${c.revision}` : "没有变更");
      refresh();
    },
  });
  const complete = useApiMutation(() => api<AiOutcome>(`/cases/${caseId}/ai-complete`, { method: "POST" }), {
    onSuccess: (out) => {
      refresh();
      if (out.status === "succeeded") message.success("已生成 AI 补全建议；请逐项评审并接受");
      else message.warning(`AI 补全未完成（${out.error_code || out.status}）；请查看追踪`);
    },
  });
  const accept = useApiMutation(
    (fields: string[]) => api<TestCase>(`/cases/${caseId}/ai-complete/accept`, { method: "POST", body: { fields } }),
    { onSuccess: refresh, success: "已接受；已创建新修订" },
  );
  const reject = useApiMutation(() => api<TestCase>(`/cases/${caseId}/ai-complete/reject`, { method: "POST" }), {
    onSuccess: refresh,
    success: "已忽略建议",
  });
  const suggestion = useApiMutation((accept: boolean) => api<TestCase>(`/cases/${caseId}/category-suggestion`, { method: "POST", body: { accept } }), {
    onSuccess: refresh,
    success: "类别已处理",
  });
  const setStatus = useApiMutation((status: string) => api<TestCase>(`/cases/${caseId}/status`, { method: "POST", body: { status } }), {
    onSuccess: (updated) => {
      qc.setQueryData(["case", caseId], updated);
      qc.invalidateQueries({ queryKey: ["tasks"] });
      refresh();
    },
    success: "状态已更新",
  });

  const c = tc.data;
  if (!c) return <Card loading />;
  const versionId = c.origin_version_id || c.requirements[0]?.version_id;
  const readOnly = c.status === "deprecated";
  return (
    <Row gutter={16}>
      <Col span={17}>
        <Card
          title={
            <Space>
              {c.code} {c.title} <CaseStatusTag status={c.status} /> <ScenarioTag value={c.scenario} />
              {c.source === "agent" && <Tag color="purple">AI 生成</Tag>}
            </Space>
          }
          extra={
            <Space>
              {c.agent_run_id && <Button onClick={() => setRunId(c.agent_run_id!)}>查看 AI 追踪</Button>}
              {!readOnly && (
                <Tooltip title="让 AI 补全步骤、预期结果和测试数据，并关联需求 / 模型节点 / 字段；结果是建议，需你逐项接受">
                  <Button icon={<RobotOutlined />} loading={complete.isPending} onClick={() => complete.mutate(undefined)}>
                    AI 补全
                  </Button>
                </Tooltip>
              )}
              <CorrectionButton targetType="case" targetId={c.id} />
              {c.status === "draft" && (
                <Popconfirm title="已评审：要设为就绪吗？只有就绪用例会被任务执行。" onConfirm={() => setStatus.mutate("ready")}>
                  <Button type="primary">设为就绪</Button>
                </Popconfirm>
              )}
              {c.status === "ready" && (
                <>
                  <Button onClick={() => setStatus.mutate("draft")}>退回草稿</Button>
                  <Popconfirm title="已废弃的用例不能再编辑或执行。要继续吗？" onConfirm={() => setStatus.mutate("deprecated")}>
                    <Button danger>废弃</Button>
                  </Popconfirm>
                </>
              )}
            </Space>
          }
        >
          {c.status === "ready" && c.task_binding && (
            <div style={{ marginBottom: 12 }}><ReadyTaskFeedback feedback={c.task_binding} onNavigate={navigate} /></div>
          )}
          {c.status === "draft" && c.source === "agent" && (
            <Alert type="info" showIcon style={{ marginBottom: 12 }} title="这是 AI 起草的用例：请评审、编辑并设为就绪；如果发现反复出现的问题，点击“纠正”，Agent 会改进后续生成。" />
          )}
          {c.ai_proposal && !readOnly && (
            <ProposalDiff
              key={c.ai_proposal.created_at}
              tc={c}
              proposal={c.ai_proposal}
              accepting={accept.isPending}
              rejecting={reject.isPending}
              onAccept={(f) => accept.mutate(f)}
              onReject={() => reject.mutate(undefined)}
              onOpenRun={setRunId}
            />
          )}
          {c.category_suggestion && !readOnly && (
            <Alert
              data-testid="category-suggestion"
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              title={`待确认类别：建议从“${CATEGORY_LABEL[c.category || "requirement"]}”改为“${CATEGORY_LABEL[c.category_suggestion.category]}”${
                c.category_suggestion.quality_tags?.length ? ` (${c.category_suggestion.quality_tags.map((t) => QUALITY_TAGS[t] || t).join(", ")})` : ""
              }`}
              description={c.category_suggestion.reason}
              action={
                <Space orientation="vertical">
                  <Button size="small" type="primary" loading={suggestion.isPending} onClick={() => suggestion.mutate(true)}>
                    接受
                  </Button>
                  <Button size="small" loading={suggestion.isPending} onClick={() => suggestion.mutate(false)}>
                    保持原样
                  </Button>
                </Space>
              }
            />
          )}
          {readOnly && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title="该用例已废弃且只读。" />}
          <CaseForm
            form={form}
            sutId={c.sut_id}
            versionId={versionId}
            disabled={readOnly}
            onFinish={(v) => {
              const { body, error } = formToBody(v);
              if (error) return message.error(error);
              save.mutate(body!);
            }}
          />
          {!readOnly && (
            <Button type="primary" loading={save.isPending} onClick={() => form.submit()}>
              保存
            </Button>
          )}
        </Card>
        <CaseExecutionPanel tc={c} onAgentRun={setRunId} />
      </Col>
      <Col span={7}>
        <Card size="small" title="追踪" style={{ marginBottom: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="需求">
              {c.requirements.length ? c.requirements.map((r) => <Tag key={r.id}><Link to={`/versions/${r.version_id}?req=${r.id}`}>{objLabel(r.title, r.code)}</Link></Tag>) : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="覆盖">
              <CaseCoverageTags
                sutId={c.sut_id}
                coverage={{
                  actions: c.nodes.filter((n) => n.kind === "action" && !n.deleted),
                  entities: c.nodes.filter((n) => n.kind !== "action" && !n.deleted),
                  fields: (c.fields || []).map((f) => ({ id: f.id, node_id: f.node_id, name: `${f.node_name}.${f.name}${f.display_name ? ` (${f.display_name})` : ""}` })),
                  relations: c.relations || [],
                }}
              />
            </Descriptions.Item>
            <Descriptions.Item label="任务">
              {c.tasks.length ? c.tasks.map((t) => <Tag key={t.id}><Link to={`/tasks/${t.id}`}>{`${t.name} (#${t.seq} )`}</Link></Tag>) : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="本地测试仓库">
              <PathText path={c.repo_path} />
            </Descriptions.Item>
            <Descriptions.Item label="编号">
              {c.code_path ? (
                <Typography.Text code copyable={{ text: c.code_abs_path || c.code_path }}>
                  {c.code_abs_path || c.code_path}
                  {c.code_commit ? `@${c.code_commit.slice(0, 8)}` : ""}
                </Typography.Text>
              ) : c.automation_status ? (
                <AutomationTag row={c} />
              ) : (
                "-"
              )}
            </Descriptions.Item>
            <Descriptions.Item label="模型快照">{c.snapshot_id ? <Tag color="purple">已记录</Tag> : "-"}</Descriptions.Item>
          </Descriptions>
        </Card>
        <Card size="small" title={`修订历史（当前修订 ${c.revision}）`}>
          <Timeline
            items={(revisions.data || []).map((r) => ({
              key: r.revision,
              content: (
                <>
                  <Typography.Text strong>修订 {r.revision}</Typography.Text>{" "}
                  <Typography.Text type="secondary">
                    {r.author.startsWith("agent") ? "AI" : r.author} · {fmtTime(r.created_at, { seconds: true })}
                  </Typography.Text>
                  <div style={{ fontSize: 12 }}>{String(r.content.title || "")}</div>
                </>
              ),
            }))}
          />
        </Card>
      </Col>
      <AgentRunDrawer runId={runId} onClose={() => setRunId(null)} />
    </Row>
  );
}
