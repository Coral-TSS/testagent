import { RobotOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, Popconfirm, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AiOutcome, Environment, Requirement, RequirementGap, Strategy, Task, TaskKind, TaskRun, Version } from "../api/types";
import { KIND_LABEL, describeSelector } from "../utils/categories";
import { BatchBar } from "./BatchBar";
import { EmptyState } from "./EmptyState";
import { TaskRunStatusTag, TaskStatusTag } from "./StatusTags";
import { fmtTime } from "../utils/time";
import { CorrectionButton } from "./CorrectionButton";
import { RunTasksModal } from "./RunTasksModal";

const TEST_TYPES = ["Functional", "API", "UI", "Regression", "Smoke"];
const EXECUTOR: Record<string, string> = { agent: "Agent", automation: "Automated", human: "Manual" };

/** Test strategy (human-confirmed) and test tasks */
export function StrategyTab({ version, onOpenRun }: { version: Version; onOpenRun: (id: string) => void }) {
  const vid = version.id;
  const [form] = Form.useForm();
  const strategy = useQuery({
    queryKey: ["strategy", vid],
    queryFn: async () => {
      try {
        return await api<Strategy>(`/versions/${vid}/strategy`);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
  });
  const tasks = useQuery({
    queryKey: ["tasks", vid],
    queryFn: () => api<Task[]>(`/versions/${vid}/tasks`),
    // Keep polling even when idle: a schedule or another page can start a task.
    refetchInterval: 5000,
    retry: false,
  });
  const activeTasks = (tasks.data || []).filter((t) => ["queued", "running"].includes(t.latest_run?.status || ""));
  const runningCount = activeTasks.filter((t) => t.latest_run?.status === "running").length;
  const queuedCount = activeTasks.length - runningCount;
  const envs = useQuery({ queryKey: ["envs", version.sut_id], queryFn: () => api<Environment[]>(`/suts/${version.sut_id}/environments`) });
  useEffect(() => {
    if (strategy.data) form.setFieldsValue(strategy.data);
  }, [strategy.data, form]);

  const reqs = useQuery({ queryKey: ["requirements", vid], queryFn: () => api<Requirement[]>(`/versions/${vid}/requirements`) });
  const reqCode = (id: string) => reqs.data?.find((r) => r.id === id)?.code || id.slice(0, 8);
  const gaps = useQuery({ queryKey: ["gaps", vid], queryFn: () => api<RequirementGap[]>(`/versions/${vid}/gaps`) });
  const keys = [["strategy", vid], ["tasks", vid], ["gaps", vid]];
  const qc = useQueryClient();
  const [taskSel, setTaskSel] = useState<string[]>([]);
  const save = useApiMutation((body: Record<string, unknown>) => api(`/versions/${vid}/strategy`, { method: "PUT", body }), { invalidate: keys, success: "Strategy saved" });
  const generate = useApiMutation(() => api<AiOutcome>(`/versions/${vid}/strategy/generate`, { method: "POST" }), {
    invalidate: keys,
    onSuccess: (out) => onOpenRun(out.agent_run_id),
  });
  const confirm = useApiMutation(() => api(`/strategy/${strategy.data!.id}/confirm`, { method: "POST" }), { invalidate: keys, success: "Strategy confirmed" });
  const createTask = useApiMutation((body: Record<string, unknown>) => api(`/versions/${vid}/tasks`, { method: "POST", body }), { invalidate: keys, success: "Task created" });
  const navigate = useNavigate();
  /** #18: a task with cases lacking scripts opens its page with the three-way choice */
  const gapError = (id: string, action: "run" | "ready") => (err: unknown) => {
    if (err instanceof ApiError && err.code === "MISSING_SCRIPTS") {
      navigate(`/tasks/${id}?missing=${action}`);
      return true;
    }
    return false;
  };
  const taskStatus = useApiMutation(
    ({ id, status }: { id: string; status: string }) => api(`/tasks/${id}/status`, { method: "POST", body: { status } }),
    { invalidate: keys, onError: (err, v) => gapError(v.id, "ready")(err) },
  );
  const [runAll, setRunAll] = useState(false);
  const removeTask = useApiMutation((id: string) => api(`/tasks/${id}`, { method: "DELETE" }), { invalidate: keys });
  const ensure = useApiMutation(() => api<{ created: { name: string }[] }>(`/versions/${vid}/tasks/ensure`, { method: "POST" }), {
    invalidate: keys,
    success: "Tasks completed per category",
  });
  const [gapBusy, setGapBusy] = useState<string | null>(null);
  const draftCases = useApiMutation(
    (requirementId: string) => {
      setGapBusy(requirementId);
      return api<AiOutcome>(`/versions/${vid}/cases/generate`, { method: "POST", body: { requirement_ids: [requirementId], automate: false } });
    },
    {
      invalidate: [...keys, ["cases"]],
      success: "Draft cases generated: once reviewed and set ready they join the matching tasks automatically",
      onSuccess: (out) => {
        setGapBusy(null);
        onOpenRun(out.agent_run_id);
      },
    },
  );
  const [taskForm] = Form.useForm();
  const runTask = useApiMutation(
    (id: string) => api<TaskRun>(`/tasks/${id}/run`, { method: "POST" }),
    {
      invalidate: keys,
      onSuccess: (run) => navigate(`/runs/${run.id}`),
      onError: (err, id) => gapError(id, "run")(err),
    },
  );

  const s = strategy.data;
  return (
    <Space direction="vertical" style={{ width: "100%" }} size={16}>
      {tasks.isError && (
        <Alert
          type="warning"
          showIcon
          title="Task run information could not be refreshed"
          description={tasks.data ? "Showing the last loaded task and run information. Retry to check the current state." : "Tasks could not be loaded. Retry to check their runs."}
          action={<Button onClick={() => tasks.refetch()} loading={tasks.isFetching}>Retry tasks</Button>}
        />
      )}
      {activeTasks.length > 0 && (
        <Alert
          type="info"
          showIcon
          title={`${runningCount} task(s) running · ${queuedCount} task(s) queued`}
          description={
            <Space wrap>
              {activeTasks.map((t) => (
                <Link key={t.id} to={`/runs/${t.latest_run!.id}`} aria-label={`View live run for ${t.name}`}>{t.name}: view run</Link>
              ))}
            </Space>
          }
        />
      )}
      <Card
        size="small"
        title={
          <Space>
            Test strategy
            {s && <Tag color={s.status === "confirmed" ? "green" : "default"}>{s.status === "confirmed" ? "Confirmed" : "Draft"}</Tag>}
            {s && <Tag>v{s.revision} · {s.source === "agent" ? "AI generated" : "Manual"}</Tag>}
          </Space>
        }
        extra={
          <Space>
            {s?.agent_run_id && <Button onClick={() => onOpenRun(s.agent_run_id!)}>View AI trace</Button>}
            {s && <CorrectionButton targetType="strategy" targetId={s.id} />}
            <Button icon={<RobotOutlined />} loading={generate.isPending} onClick={() => generate.mutate()}>
              AI generate strategy
            </Button>
            {s && s.status !== "confirmed" && (
              <Popconfirm title="Confirm the strategy? Draft tasks will be created after confirmation." onConfirm={() => confirm.mutate()}>
                <Button type="primary">Confirm strategy</Button>
              </Popconfirm>
            )}
          </Space>
        }
      >
        <Form form={form} layout="vertical" onFinish={(vals) => save.mutate(vals)}>
          <Form.Item name="scope" label="Scope">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Space wrap>
            <Form.Item name="test_types" label="Test types">
              <Select mode="tags" style={{ minWidth: 260 }} options={TEST_TYPES.map((t) => ({ value: t, label: t }))} />
            </Form.Item>
            <Form.Item name="intensity" label="Depth">
              <Select allowClear style={{ width: 140 }} options={["light", "standard", "thorough"].map((t) => ({ value: t, label: t }))} />
            </Form.Item>
          </Space>
          <Form.Item name="notes" label="Notes">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Button htmlType="submit" loading={save.isPending}>
            Save strategy
          </Button>
        </Form>
      </Card>
      {(gaps.data?.length ?? 0) > 0 && (
        <Card size="small" title="Requirement gap: no ready cases yet" data-testid="gaps">
          <Typography.Paragraph type="secondary">
            Tasks only reference existing cases. The requirements below have no ready cases yet: click “Generate draft cases” to let the AI draft some (drafts only); after review set them ready and they join the matching tasks automatically.
          </Typography.Paragraph>
          <Table<RequirementGap>
            size="small"
            rowKey="requirement_id"
            pagination={false}
            dataSource={gaps.data}
            columns={[
              { title: "Requirement", render: (_, g) => `${g.title} (${g.code})` },
              { title: "Draft cases", dataIndex: "draft_count", render: (n: number) => (n ? <Tooltip title="Drafts exist: review them and set them ready">{n} to review</Tooltip> : 0) },
              {
                title: "Action",
                render: (_, g) => (
                  <Button size="small" icon={<RobotOutlined />} loading={draftCases.isPending && gapBusy === g.requirement_id} disabled={draftCases.isPending} onClick={() => draftCases.mutate(g.requirement_id)}>
                    Generate draft cases
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      )}
      <Card
        size="small"
        title="Test tasks"
        id="strategy-tasks"
        extra={
          <Space>
            <Tooltip title="One “requirement validation” task per requirement, one “general quality” task and one “regression/smoke” task; existing ones are not created again">
              <Button loading={ensure.isPending} onClick={() => ensure.mutate(undefined)}>
                Complete tasks per category
              </Button>
            </Tooltip>
            {version.status !== "planning" && version.status !== "closed" && (
              <Button type="primary" onClick={() => setRunAll(true)} disabled={!tasks.data?.length}>
                Run all runnable tasks
              </Button>
            )}
          </Space>
        }
      >
        <RunTasksModal open={runAll} versionId={vid} startTesting={version.status === "requirements_frozen"} onClose={() => setRunAll(false)} />
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          title="Tasks only reference cases: ready cases are picked by rules (requirement, category, priority, …), and you can also add/remove cases by hand in the task; manual changes win. Cases join matching tasks automatically when set ready."
        />
        <Form form={taskForm} layout="inline" style={{ marginBottom: 12 }} initialValues={{ kind: "requirement", executor: "agent" }} onFinish={(vals) => createTask.mutate(vals, { onSuccess: () => taskForm.resetFields() })}>
          <Form.Item name="name" rules={[{ required: true, message: "Required" }]}>
            <Input placeholder="Task name" />
          </Form.Item>
          <Form.Item name="kind">
            <Select style={{ width: 120 }} options={(Object.keys(KIND_LABEL) as TaskKind[]).map((value) => ({ value, label: KIND_LABEL[value] }))} />
          </Form.Item>
          <Form.Item name="executor">
            <Select style={{ width: 100 }} options={Object.entries(EXECUTOR).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="environment_id">
            <Select allowClear placeholder="Environment" style={{ width: 140 }} options={(envs.data || []).map((e) => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Button htmlType="submit" loading={createTask.isPending}>
            New task
          </Button>
        </Form>
        <BatchBar
          noun=" task(s)"
          selected={taskSel}
          labelOf={(id) => tasks.data?.find((t) => t.id === id)?.name || id}
          onClear={() => setTaskSel([])}
          onDone={(ok) => {
            for (const k of keys) qc.invalidateQueries({ queryKey: k });
            setTaskSel((sel) => sel.filter((id) => !ok.includes(id)));
          }}
          actions={[
            { key: "ready", label: "Set ready", primary: true, run: (id) => api(`/tasks/${id}/status`, { method: "POST", body: { status: "ready" } }) },
            { key: "run", label: "Execution", confirm: `Start the ${taskSel.length} selected task(s) one after another?`, run: (id) => api(`/tasks/${id}/run`, { method: "POST" }) },
            { key: "archive", label: "Archive", confirm: `Archive the ${taskSel.length} selected task(s)? Archived tasks can no longer run or change.`, run: (id) => api(`/tasks/${id}/status`, { method: "POST", body: { status: "archived" } }) },
            { key: "delete", label: "Delete", danger: true, confirm: `Delete the ${taskSel.length} selected task(s)? Tasks with executions cannot be deleted (archive them instead).`, run: (id) => api(`/tasks/${id}`, { method: "DELETE" }) },
          ]}
        />
        <Table<Task>
          size="small"
          rowKey="id"
          rowSelection={{ selectedRowKeys: taskSel, onChange: (k) => setTaskSel(k as string[]) }}
          loading={tasks.isLoading}
          dataSource={tasks.data}
          pagination={false}
          scroll={{ x: "max-content" }}
          locale={{
            emptyText: (
              tasks.isError ? "Task information unavailable" : tasks.isLoading ? "Loading tasks…" : <EmptyState
                title="No tasks yet"
                hint="A task runs a batch of cases: enter a task name above, choose the executor (agent browser/automation script/manual) and environment, click “New task”, then pick cases in the task detail."
              />
            ),
          }}
          columns={[
            { title: "Task", dataIndex: "name", render: (n: string, t) => <Link to={`/tasks/${t.id}`}>{n}</Link> },
            { title: "Type", dataIndex: "kind", render: (k: TaskKind) => KIND_LABEL[k] || k },
            {
              title: "Case selection rule",
              dataIndex: "selector",
              render: (sel: Task["selector"]) => (sel ? <Tag color="cyan">{describeSelector(sel, reqCode).replace("Among ready cases: ", "")}</Tag> : <Tag>Manual</Tag>),
            },
            { title: "Actor", dataIndex: "executor", render: (e) => EXECUTOR[e] || e },
            {
              title: "Cases",
              dataIndex: "case_count",
              render: (n: number, t) => (
                <Space size={4}>
                  {n}
                  {(t.script_gap_count || 0) > 0 && (
                    <Tooltip title="Cases without an automation script: skipped (not executed) when the task runs">
                      <Tag color="orange">{t.script_gap_count} without script</Tag>
                    </Tooltip>
                  )}
                </Space>
              ),
            },
            { title: "Status", dataIndex: "status", render: (st) => <TaskStatusTag status={st} /> },
            {
              title: "Latest run",
              render: (_, t) => t.latest_run ? (
                <Space orientation="vertical" size={2}>
                  <Link to={`/runs/${t.latest_run.id}`} aria-label={`Latest run for ${t.name}`}>{fmtTime(t.latest_run.created_at)}</Link>
                  <TaskRunStatusTag status={t.latest_run.status} />
                  <Typography.Text type="secondary">
                    {t.latest_run.status === "queued" ? "Awaiting start" : `${t.latest_run.counts.done}/${t.latest_run.counts.total} processed`}
                  </Typography.Text>
                </Space>
              ) : <Typography.Text type="secondary">Never run yet</Typography.Text>,
            },
            { title: "Next run", dataIndex: "next_run_at", render: (t: string | null, row) => (t ? fmtTime(t, { tz: row.schedule?.tz }) : "-") },
            {
              title: "Action",
              render: (_, t) => (
                <Space>
                  {t.status === "draft" && <a onClick={() => taskStatus.mutate({ id: t.id, status: "ready" })}>Set ready</a>}
                  {["ready", "done", "cancelled"].includes(t.status) && <a onClick={() => runTask.mutate(t.id)}>Execution</a>}
                  <Link to={`/tasks/${t.id}`}>Cases & schedule</Link>
                  {!["archived", "running"].includes(t.status) && <a onClick={() => taskStatus.mutate({ id: t.id, status: "archived" })}>Archive</a>}
                  <Popconfirm title="Delete the task?" onConfirm={() => removeTask.mutate(t.id)}>
                    <a>Delete</a>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
