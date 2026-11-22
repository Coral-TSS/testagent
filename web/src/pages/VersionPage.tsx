import { FileTextOutlined, LockOutlined, PlusOutlined, RobotOutlined, UnlockOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Tabs, Tag, Timeline } from "antd";
import { useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { CaseRow, CompletionOutcome, Requirement, Suggestion, Version } from "../api/types";
import { AgentRunDrawer } from "../components/AgentRunDrawer";
import { CaseList } from "../components/CaseList";
import { ListSection, ListTable, listTitle } from "../components/ListView";
import { BatchBar } from "../components/BatchBar";
import { EmptyState } from "../components/EmptyState";
import { RequirementDrawer } from "../components/RequirementDrawer";
import { RequirementStatusTag, VersionStatusTag } from "../components/StatusTags";
import { RunTasksModal } from "../components/RunTasksModal";
import { SuggestionList, completionNote } from "../components/SuggestionList";
import { fmtTime } from "../utils/time";

const ROLE: Record<string, string> = { owner: "负责人", developer: "开发", tester: "测试" };

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
  // Observe the tables' existing caches without fetching unvisited tabs just to show a number.
  const caseCount = useQuery({ queryKey: ["cases", sutId, versionId, null, null, ""], queryFn: () => api<CaseRow[]>(`/suts/${sutId}/cases`, { params: { version_id: versionId } }), enabled: false });
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
    success: "需求已创建",
    onSuccess: () => {
      setCreating(false);
      form.resetFields();
    },
  });
  const freeze = useApiMutation(() => api(`/versions/${versionId}/freeze`, { method: "POST" }), { onSuccess: refreshVersion, success: "需求已冻结，并已创建模型快照" });
  const unfreeze = useApiMutation((reason: string) => api(`/versions/${versionId}/unfreeze`, { method: "POST", body: { reason } }), {
    onSuccess: () => {
      setUnfreezeReason(null);
      refreshVersion();
    },
    success: "已解冻",
  });
  const setStatus = useApiMutation((status: string) => api(`/versions/${versionId}/status`, { method: "POST", body: { status } }), {
    onSuccess: refreshVersion,
    success: "状态已更新",
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
    success: "版本报告已生成",
    invalidate: [["reports"]],
    onSuccess: (r) => navigate(`/reports/${r.id}`),
  });

  const [runTasks, setRunTasks] = useState(false);
  const v = version.data;
  const sealed = Boolean(v?.sealed);
  const locked = Boolean(v && (v.status !== "planning" || sealed));
  const tab = params.get("tab");
  if (tab === "strategy" || tab === "tasks") {
    const next = new URLSearchParams(params);
    next.delete("tab");
    const qs = next.toString();
    return <Navigate to={`/versions/${versionId}/${tab}${qs ? `?${qs}` : ""}`} replace />;
  }
  return (
    <>
      {v && <RunTasksModal open={runTasks} versionId={v.id} startTesting={v.status === "requirements_frozen"} onClose={() => setRunTasks(false)} onDone={refreshVersion} />}
      {sealed && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title="已封板"
          description="该版本已封板，模型和需求只读。可以基于它新建版本。"
        />
      )}
      <Card style={{ marginBottom: 16 }} loading={version.isLoading}>
        {v && (
          <Descriptions
            title={
              <Space>
                版本 {v.name} <VersionStatusTag status={v.status} />
                {sealed && <Tag color="gold">已封板</Tag>}
              </Space>
            }
            extra={
              <Space>
                {v.status === "planning" && !sealed && (
                  <Button
                    type="primary"
                    icon={<LockOutlined />}
                    loading={freeze.isPending}
                    onClick={() =>
                      modal.confirm({
                        title: "要冻结需求吗？",
                        content: "所有需求都必须已确认。冻结会生成模型快照，并使需求变为只读。",
                        onOk: () => freeze.mutateAsync(),
                      })
                    }
                  >
                    冻结需求
                  </Button>
                )}
                {v.status === "requirements_frozen" && (
                  <>
                    <Button icon={<UnlockOutlined />} onClick={() => setUnfreezeReason("")}>
                      取消冻结
                    </Button>
                    <Button type="primary" onClick={() => setRunTasks(true)}>
                      开始测试
                    </Button>
                  </>
                )}
                {v.status === "testing" && <Button onClick={() => setStatus.mutate("closed")}>关闭版本</Button>}
                {v.status !== "planning" && (
                  <Button icon={<FileTextOutlined />} loading={versionReport.isPending} onClick={() => versionReport.mutate()}>
                    生成版本报告
                  </Button>
                )}
                <Link to={`/reports?sut_id=${v.sut_id}&version_id=${v.id}`}>报告历史</Link>
              </Space>
            }
            column={3}
          >
            <Descriptions.Item label="被测系统">
              <Link to={`/suts/${v.sut_id}`}>{v.sut_name ? `${v.sut_name} (${v.sut_code})` : "查看"}</Link>
            </Descriptions.Item>
            <Descriptions.Item label="冻结于">{fmtTime(v.frozen_at, { seconds: true })}</Descriptions.Item>
            <Descriptions.Item label="模型快照">{v.model_snapshot_id ? <Tag color="purple">已生成</Tag> : "-"}</Descriptions.Item>
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
              label: listTitle("需求", reqs.data?.length),
              children: (
                <>
                  <Button icon={<PlusOutlined />} disabled={locked} style={{ marginBottom: 12 }} onClick={() => setCreating(true)}>
                    添加需求
                  </Button>
                  <BatchBar
                    noun=" 条需求"
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
                              label: "AI 结构化",
                              run: (id: string) => api(`/requirements/${id}/structure`, { method: "POST" }),
                            },
                            {
                              key: "confirm",
                              label: "确认",
                              primary: true,
                              confirm: `要确认所选的 ${reqSel.length} 条需求吗？（只有已结构化的需求可以确认）`,
                              run: (id: string) => api(`/requirements/${id}/confirm`, { method: "POST" }),
                            },
                          ]),
                      ...(locked
                        ? []
                        : [
                            {
                              key: "delete",
                              label: "删除",
                              danger: true,
                              confirm: `要删除所选的 ${reqSel.length} 条需求吗？已关联用例的需求不能删除。`,
                              run: (id: string) => api(`/requirements/${id}`, { method: "DELETE" }),
                            },
                          ]),
                    ]}
                  />
                  <ListTable<Requirement>
                    label="需求"
                    error={reqs.isError}
                    onRetry={() => reqs.refetch()}
                    size="small"
                    rowKey="id"
                    rowSelection={{ selectedRowKeys: reqSel, onChange: (k) => setReqSel(k as string[]) }}
                    loading={reqs.isLoading}
                    dataSource={reqs.data}
                    locale={{
                      emptyText: (
                        <EmptyState
                          title="该版本还没有需求"
                          hint="录入本次要测的需求（标题和正文），指定负责人，点击“AI 结构化”拆成与模型关联的执行者/前置条件/动作/预期结果/约束，确认后再冻结。"
                          actionLabel={locked ? undefined : "添加需求"}
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
                      { title: "编号", dataIndex: "code", width: 110 },
                      { title: "标题", dataIndex: "title" },
                      { title: "优先级", dataIndex: "priority", width: 80 },
                      { title: "状态", dataIndex: "status", width: 100, render: (s) => <RequirementStatusTag status={s} /> },
                      {
                        title: "负责人",
                        render: (_, r) => (r.people || []).map((p) => <Tag key={`${p.person_id}-${p.role}`}>{`${ROLE[p.role]}: ${p.name}`}</Tag>),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: "suggestions",
              label: listTitle("模型建议", suggestions.data?.length),
              children: (
                <>
                  <Button icon={<RobotOutlined />} loading={complete.isPending} disabled={!sutId || sealed} onClick={() => complete.mutate()} style={{ marginBottom: 12 }}>
                    AI 补全模型
                  </Button>
                  <SuggestionList
                    loading={suggestions.isLoading}
                    error={suggestions.isError}
                    onRetry={() => suggestions.refetch()}
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
              label: listTitle("测试用例与覆盖", caseCount.data?.length),
              children: sutId && <CaseList sutId={sutId} versionId={versionId} onOpenRun={(id) => setParam("run", id)} />,
            },
            {
              key: "history",
              label: listTitle("变更日志", history.data?.length),
              children: (
                <ListSection label="版本变更" count={history.data?.length} error={history.isError} onRetry={() => history.refetch()}>
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
                </ListSection>
              ),
            },
          ]}
        />
      </Card>
      <RequirementDrawer
        reqId={params.get("req")}
        sutId={sutId}
        locked={locked}
        sealed={sealed}
        onClose={() => setParam("req", null)}
        onOpenRun={(id) => setParam("run", id)}
      />
      <AgentRunDrawer runId={params.get("run")} onClose={() => setParam("run", null)} />
      <Modal title="添加需求" open={creating} onCancel={() => setCreating(false)} onOk={() => form.submit()} confirmLoading={create.isPending} forceRender>
        <Form form={form} layout="vertical" initialValues={{ priority: "P1" }} onFinish={(vals) => create.mutate(vals)}>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={["P0", "P1", "P2"].map((p) => ({ value: p, label: p }))} />
          </Form.Item>
          <Form.Item name="raw_text" label="需求正文">
            <Input.TextArea rows={5} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="解冻版本"
        open={unfreezeReason !== null}
        onCancel={() => setUnfreezeReason(null)}
        okButtonProps={{ disabled: !unfreezeReason?.trim() }}
        confirmLoading={unfreeze.isPending}
        onOk={() => unfreeze.mutate(unfreezeReason!.trim())}
      >
        <p>解冻后需求可再次编辑，并且必须重新确认并冻结。请填写原因（会记入变更日志）。</p>
        <Input.TextArea rows={3} value={unfreezeReason || ""} onChange={(e) => setUnfreezeReason(e.target.value)} />
      </Modal>
    </>
  );
}
