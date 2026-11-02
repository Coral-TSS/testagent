import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RobotOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Col, Descriptions, Form, Popconfirm, Row, Space, Tag, Timeline, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

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

/** P09 test case detail: edit (creates revisions automatically), review status, revision history, correction */
export function CasePage() {
  const { caseId = "" } = useParams();
  const qc = useQueryClient();
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
      message.success(c.revision !== tc.data?.revision ? `Saved as revision ${c.revision}` : "No changes");
      refresh();
    },
  });
  const complete = useApiMutation(() => api<AiOutcome>(`/cases/${caseId}/ai-complete`, { method: "POST" }), {
    onSuccess: (out) => {
      refresh();
      if (out.status === "succeeded") message.success("AI completion suggestion generated; review it item by item and accept");
      else message.warning(`AI completion not finished (${out.error_code || out.status}); see the trace`);
    },
  });
  const accept = useApiMutation(
    (fields: string[]) => api<TestCase>(`/cases/${caseId}/ai-complete/accept`, { method: "POST", body: { fields } }),
    { onSuccess: refresh, success: "Accepted; a new revision was created" },
  );
  const reject = useApiMutation(() => api<TestCase>(`/cases/${caseId}/ai-complete/reject`, { method: "POST" }), {
    onSuccess: refresh,
    success: "Suggestion dismissed",
  });
  const suggestion = useApiMutation((accept: boolean) => api<TestCase>(`/cases/${caseId}/category-suggestion`, { method: "POST", body: { accept } }), {
    onSuccess: refresh,
    success: "Category handled",
  });
  const setStatus = useApiMutation((status: string) => api(`/cases/${caseId}/status`, { method: "POST", body: { status } }), {
    onSuccess: refresh,
    success: "Status updated",
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
              {c.source === "agent" && <Tag color="purple">AI generated</Tag>}
            </Space>
          }
          extra={
            <Space>
              {c.agent_run_id && <Button onClick={() => setRunId(c.agent_run_id!)}>View AI trace</Button>}
              {!readOnly && (
                <Tooltip title="Let the AI complete steps, expected result and test data, and link requirements / model nodes / fields; the result is a suggestion you accept item by item">
                  <Button icon={<RobotOutlined />} loading={complete.isPending} onClick={() => complete.mutate(undefined)}>
                    AI completion
                  </Button>
                </Tooltip>
              )}
              <CorrectionButton targetType="case" targetId={c.id} />
              {c.status === "draft" && (
                <Popconfirm title="Reviewed: set ready? Only ready cases are run by tasks." onConfirm={() => setStatus.mutate("ready")}>
                  <Button type="primary">Set ready</Button>
                </Popconfirm>
              )}
              {c.status === "ready" && (
                <>
                  <Button onClick={() => setStatus.mutate("draft")}>Back to draft</Button>
                  <Popconfirm title="A deprecated case can no longer be edited or run. Continue?" onConfirm={() => setStatus.mutate("deprecated")}>
                    <Button danger>Deprecate</Button>
                  </Popconfirm>
                </>
              )}
            </Space>
          }
        >
          {c.status === "draft" && c.source === "agent" && (
            <Alert type="info" showIcon style={{ marginBottom: 12 }} title="Case drafted by the AI: review, edit and set it ready; if you see a recurring problem click “Correct” and the agent will improve later generations." />
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
              title={`Category to confirm: suggested change from “${CATEGORY_LABEL[c.category || "requirement"]}” to “${CATEGORY_LABEL[c.category_suggestion.category]}”${
                c.category_suggestion.quality_tags?.length ? ` (${c.category_suggestion.quality_tags.map((t) => QUALITY_TAGS[t] || t).join(", ")})` : ""
              }`}
              description={c.category_suggestion.reason}
              action={
                <Space orientation="vertical">
                  <Button size="small" type="primary" loading={suggestion.isPending} onClick={() => suggestion.mutate(true)}>
                    Accept
                  </Button>
                  <Button size="small" loading={suggestion.isPending} onClick={() => suggestion.mutate(false)}>
                    Keep as is
                  </Button>
                </Space>
              }
            />
          )}
          {readOnly && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title="The case is deprecated and read-only." />}
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
              Save
            </Button>
          )}
        </Card>
        <CaseExecutionPanel tc={c} onAgentRun={setRunId} />
      </Col>
      <Col span={7}>
        <Card size="small" title="Trace" style={{ marginBottom: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Requirement">
              {c.requirements.length ? c.requirements.map((r) => <Tag key={r.id}><Link to={`/versions/${r.version_id}?req=${r.id}`}>{objLabel(r.title, r.code)}</Link></Tag>) : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="Coverage">
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
            <Descriptions.Item label="Tasks">
              {c.tasks.length ? c.tasks.map((t) => <Tag key={t.id}><Link to={`/tasks/${t.id}`}>{`${t.name} (#${t.seq} )`}</Link></Tag>) : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="Local test repo">
              <PathText path={c.repo_path} />
            </Descriptions.Item>
            <Descriptions.Item label="Code">
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
            <Descriptions.Item label="Model snapshot">{c.snapshot_id ? <Tag color="purple">Recorded</Tag> : "-"}</Descriptions.Item>
          </Descriptions>
        </Card>
        <Card size="small" title={`Revision history (current ${c.revision})`}>
          <Timeline
            items={(revisions.data || []).map((r) => ({
              key: r.revision,
              content: (
                <>
                  <Typography.Text strong>Rev {r.revision}</Typography.Text>{" "}
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
