import { FileTextOutlined, LockOutlined, PlusOutlined, RobotOutlined, UnlockOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Timeline } from "antd";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { CompletionOutcome, Requirement, Suggestion, Version } from "../api/types";
import { AgentRunDrawer } from "../components/AgentRunDrawer";
import { CaseList } from "../components/CaseList";
import { BatchBar } from "../components/BatchBar";
import { EmptyState } from "../components/EmptyState";
import { RequirementDrawer } from "../components/RequirementDrawer";
import { RequirementStatusTag, VersionStatusTag } from "../components/StatusTags";
import { StrategyTab } from "../components/StrategyTab";
import { RunTasksModal } from "../components/RunTasksModal";
import { SuggestionList, completionNote } from "../components/SuggestionList";
import { fmtTime } from "../utils/time";

const ROLE: Record<string, string> = { owner: "Owner", developer: "Developer", tester: "Tester" };

/** P05 version detail + requirement list; P06 requirement drawer; strategy & tasks */
export function VersionPage() {
  const { versionId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { modal, message } = App.useApp();
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();
  const [unfreezeReason, setUnfreezeReason] = useState<string | null>(null);

  const version = useQuery({ queryKey: ["version", versionId], queryFn: () => api<Version>(`/versions/${versionId}`) });
  const sutId = version.data?.sut_id || "";
  const reqs = useQuery({
    queryKey: ["requirements", versionId],
    queryFn: () => api<Requirement[]>(`/versions/${versionId}/requirements`),
  });
  const history = useQuery({
    queryKey: ["version-history", versionId],
    queryFn: () => api<{ action: string; actor: string; diff: unknown; created_at: string }[]>(`/versions/${versionId}/history`),
  });
  const suggestions = useQuery({
    queryKey: ["suggestions", sutId],
    queryFn: () => api<Suggestion[]>(`/suts/${sutId}/suggestions`, { params: { status: "pending" } }),
    enabled: Boolean(sutId),
  });

  const [reqSel, setReqSel] = useState<string[]>([]);
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const refreshVersion = () => {
    qc.invalidateQueries({ queryKey: ["version", versionId] });
    qc.invalidateQueries({ queryKey: ["version-history", versionId] });
    qc.invalidateQueries({ queryKey: ["versions"] });
  };
  const create = useApiMutation((body: Record<string, unknown>) => api(`/versions/${versionId}/requirements`, { method: "POST", body }), {
    invalidate: [["requirements", versionId]],
    success: "Requirement created",
    onSuccess: () => {
      setCreating(false);
      form.resetFields();
    },
  });
  const freeze = useApiMutation(() => api(`/versions/${versionId}/freeze`, { method: "POST" }), { onSuccess: refreshVersion, success: "Requirements frozen; model snapshot created" });
  const unfreeze = useApiMutation((reason: string) => api(`/versions/${versionId}/unfreeze`, { method: "POST", body: { reason } }), {
    onSuccess: () => {
      setUnfreezeReason(null);
      refreshVersion();
    },
    success: "Unfrozen",
  });
  const setStatus = useApiMutation((status: string) => api(`/versions/${versionId}/status`, { method: "POST", body: { status } }), {
    onSuccess: refreshVersion,
    success: "Status updated",
  });
  const complete = useApiMutation(() => api<CompletionOutcome>(`/suts/${sutId}/model/complete`, { method: "POST", body: { version_id: versionId } }), {
    invalidate: [["suggestions", sutId]],
    onSuccess: (out) => {
      const note = completionNote(out);
      if (note) message.info(note, 8);
      setParam("run", out.agent_run_id);
    },
  });

  const versionReport = useApiMutation(() => api<{ id: string }>(`/versions/${versionId}/report`, { method: "POST" }), {
    success: "Version report generated",
    invalidate: [["reports"]],
    onSuccess: (r) => navigate(`/reports/${r.id}`),
  });

  const [runTasks, setRunTasks] = useState(false);
  const v = version.data;
  const locked = Boolean(v && v.status !== "planning");
  return (
    <>
      {v && <RunTasksModal open={runTasks} versionId={v.id} startTesting={v.status === "requirements_frozen"} onClose={() => setRunTasks(false)} onDone={refreshVersion} />}
      <Card style={{ marginBottom: 16 }} loading={version.isLoading}>
        {v && (
          <Descriptions
            title={
              <Space>
                Version {v.name} <VersionStatusTag status={v.status} />
              </Space>
            }
            extra={
              <Space>
                {v.status === "planning" && (
                  <Button
                    type="primary"
                    icon={<LockOutlined />}
                    loading={freeze.isPending}
                    onClick={() =>
                      modal.confirm({
                        title: "Freeze requirements?",
                        content: "All requirements must be confirmed. Freezing creates a model snapshot and makes the requirements read-only.",
                        onOk: () => freeze.mutateAsync(),
                      })
                    }
                  >
                    Freeze requirements
                  </Button>
                )}
                {v.status === "requirements_frozen" && (
                  <>
                    <Button icon={<UnlockOutlined />} onClick={() => setUnfreezeReason("")}>
                      Unfreeze
                    </Button>
                    <Button type="primary" onClick={() => setRunTasks(true)}>
                      Start testing
                    </Button>
                  </>
                )}
                {v.status === "testing" && <Button onClick={() => setStatus.mutate("closed")}>Close version</Button>}
                {v.status !== "planning" && (
                  <Button icon={<FileTextOutlined />} loading={versionReport.isPending} onClick={() => versionReport.mutate()}>
                    Generate version report
                  </Button>
                )}
                <Link to={`/reports?sut_id=${v.sut_id}&version_id=${v.id}`}>Report history</Link>
              </Space>
            }
            column={3}
          >
            <Descriptions.Item label="SUT">
              <Link to={`/suts/${v.sut_id}`}>{v.sut_name ? `${v.sut_name} (${v.sut_code})` : "View"}</Link>
            </Descriptions.Item>
            <Descriptions.Item label="Frozen at">{fmtTime(v.frozen_at, { seconds: true })}</Descriptions.Item>
            <Descriptions.Item label="Model snapshot">{v.model_snapshot_id ? <Tag color="purple">Generated</Tag> : "-"}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
      <Card>
        <Tabs
          activeKey={params.get("tab") || "requirements"}
          onChange={(k) => setParam("tab", k === "requirements" ? null : k)}
          items={[
            {
              key: "requirements",
              label: `Requirements (${reqs.data?.length ?? 0})`,
              children: (
                <>
                  <Button icon={<PlusOutlined />} disabled={locked} style={{ marginBottom: 12 }} onClick={() => setCreating(true)}>
                    Add requirement
                  </Button>
                  <BatchBar
                    noun=" requirement(s)"
                    selected={reqSel}
                    labelOf={(id) => {
                      const r = reqs.data?.find((x) => x.id === id);
                      return r ? `${r.code} ${r.title}` : id;
                    }}
                    onClear={() => setReqSel([])}
                    onDone={(ok) => {
                      qc.invalidateQueries({ queryKey: ["requirements", versionId] });
                      qc.invalidateQueries({ queryKey: ["progress"] });
                      setReqSel((sel) => sel.filter((id) => !ok.includes(id)));
                    }}
                    actions={[
                      ...(locked
                        ? []
                        : [
                            {
                              key: "structure",
                              label: "AI structure",
                              run: (id: string) => api(`/requirements/${id}/structure`, { method: "POST" }),
                            },
                          ]),
                      {
                        key: "confirm",
                        label: "Confirm",
                        primary: true,
                        confirm: `Confirm the ${reqSel.length} selected requirement(s)? (only structured requirements can be confirmed)`,
                        run: (id: string) => api(`/requirements/${id}/confirm`, { method: "POST" }),
                      },
                      ...(locked
                        ? []
                        : [
                            {
                              key: "delete",
                              label: "Delete",
                              danger: true,
                              confirm: `Delete the ${reqSel.length} selected requirement(s)? Requirements with linked cases cannot be deleted.`,
                              run: (id: string) => api(`/requirements/${id}`, { method: "DELETE" }),
                            },
                          ]),
                    ]}
                  />
                  <Table<Requirement>
                    size="small"
                    rowKey="id"
                    rowSelection={{ selectedRowKeys: reqSel, onChange: (k) => setReqSel(k as string[]) }}
                    loading={reqs.isLoading}
                    dataSource={reqs.data}
                    pagination={false}
                    locale={{
                      emptyText: (
                        <EmptyState
                          title="This version has no requirements yet"
                          hint="Enter the requirements to test this time (title and text), assign owners, click “AI structure” to split them into actor/preconditions/action/expected result/constraints linked to the model, confirm, then freeze."
                          actionLabel={locked ? undefined : "Add requirement"}
                          onAction={() => setCreating(true)}
                        />
                      ),
                    }}
                    onRow={(r) => ({
                      onClick: (e) => {
                        if ((e.target as HTMLElement).closest(".ant-table-selection-column")) return;
                        setParam("req", r.id);
                      },
                      style: { cursor: "pointer" },
                    })}
                    columns={[
                      { title: "Code", dataIndex: "code", width: 110 },
                      { title: "Title", dataIndex: "title" },
                      { title: "Priority", dataIndex: "priority", width: 80 },
                      { title: "Status", dataIndex: "status", width: 100, render: (s) => <RequirementStatusTag status={s} /> },
                      {
                        title: "Owners",
                        render: (_, r) => (r.people || []).map((p) => <Tag key={`${p.person_id}-${p.role}`}>{`${ROLE[p.role]}: ${p.name}`}</Tag>),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: "suggestions",
              label: `Model suggestions (${suggestions.data?.length ?? 0})`,
              children: (
                <>
                  <Button icon={<RobotOutlined />} loading={complete.isPending} disabled={!sutId} onClick={() => complete.mutate()} style={{ marginBottom: 12 }}>
                    AI complete model
                  </Button>
                  <SuggestionList
                    sutId={sutId}
                    items={suggestions.data || []}
                    onChanged={() => {
                      qc.invalidateQueries({ queryKey: ["suggestions", sutId] });
                      qc.invalidateQueries({ queryKey: ["graph", sutId] });
                    }}
                  />
                </>
              ),
            },
            {
              key: "cases",
              label: "Test cases & coverage",
              children: sutId && <CaseList sutId={sutId} versionId={versionId} onOpenRun={(id) => setParam("run", id)} />,
            },
            {
              key: "strategy",
              label: "Test strategy & tasks",
              children: v && <StrategyTab version={v} onOpenRun={(id) => setParam("run", id)} />,
            },
            {
              key: "history",
              label: "Change log",
              children: (
                <Timeline
                  items={(history.data || []).map((h, i) => ({
                    key: i,
                    content: (
                      <>
                        <Tag>{h.action}</Tag> {h.actor} · {h.created_at.replace("T", " ").slice(0, 19)}
                        {h.diff ? <code style={{ marginLeft: 8, fontSize: 12 }}>{JSON.stringify(h.diff)}</code> : null}
                      </>
                    ),
                  }))}
                />
              ),
            },
          ]}
        />
      </Card>
      <RequirementDrawer
        reqId={params.get("req")}
        sutId={sutId}
        locked={locked}
        onClose={() => setParam("req", null)}
        onOpenRun={(id) => setParam("run", id)}
      />
      <AgentRunDrawer runId={params.get("run")} onClose={() => setParam("run", null)} />
      <Modal title="Add requirement" open={creating} onCancel={() => setCreating(false)} onOk={() => form.submit()} confirmLoading={create.isPending} forceRender>
        <Form form={form} layout="vertical" initialValues={{ priority: "P1" }} onFinish={(vals) => create.mutate(vals)}>
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="priority" label="Priority">
            <Select options={["P0", "P1", "P2"].map((p) => ({ value: p, label: p }))} />
          </Form.Item>
          <Form.Item name="raw_text" label="Requirement text">
            <Input.TextArea rows={5} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="Unfreeze version"
        open={unfreezeReason !== null}
        onCancel={() => setUnfreezeReason(null)}
        okButtonProps={{ disabled: !unfreezeReason?.trim() }}
        confirmLoading={unfreeze.isPending}
        onOk={() => unfreeze.mutate(unfreezeReason!.trim())}
      >
        <p>After unfreezing, requirements can be edited again and must be confirmed and frozen again. Please give a reason (recorded in the change log).</p>
        <Input.TextArea rows={3} value={unfreezeReason || ""} onChange={(e) => setUnfreezeReason(e.target.value)} />
      </Modal>
    </>
  );
}
