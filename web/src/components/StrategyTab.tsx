import { RobotOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, Popconfirm, Select, Space, Tag, Tooltip, Typography } from "antd";
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
import { ListTable } from "./ListView";

const TEST_TYPES = ["功能", "API", "UI", "回归", "冒烟"];
const EXECUTOR: Record<string, string> = { agent: "Agent", automation: "已自动化", human: "手工" };

/** Test strategy (human-confirmed) and test tasks. `section` splits the two routes; `all` keeps both. */
export function StrategyTab({ version, onOpenRun, section = "all" }: { version: Version; onOpenRun: (id: string) => void; section?: "all" | "strategy" | "tasks" }) {
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
  const save = useApiMutation((body: Record<string, unknown>) => api(`/versions/${vid}/strategy`, { method: "PUT", body }), { invalidate: keys, success: "策略已保存" });
  const generate = useApiMutation(() => api<AiOutcome>(`/versions/${vid}/strategy/generate`, { method: "POST" }), {
    invalidate: keys,
    onSuccess: (out) => onOpenRun(out.agent_run_id),
  });
  const confirm = useApiMutation(() => api(`/strategy/${strategy.data!.id}/confirm`, { method: "POST" }), { invalidate: keys, success: "策略已确认" });
  const createTask = useApiMutation((body: Record<string, unknown>) => api(`/versions/${vid}/tasks`, { method: "POST", body }), { invalidate: keys, success: "任务已创建" });
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
    success: "已按类别补全任务",
  });
  const [gapBusy, setGapBusy] = useState<string | null>(null);
  const draftCases = useApiMutation(
    (requirementId: string) => {
      setGapBusy(requirementId);
      return api<AiOutcome>(`/versions/${vid}/cases/generate`, { method: "POST", body: { requirement_ids: [requirementId], automate: false } });
    },
    {
      invalidate: [...keys, ["cases"]],
      success: "已生成草稿用例：评审并设为就绪后会自动加入匹配的任务",
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
          title="测试任务执行信息无法刷新"
          description={tasks.data ? "正在显示上次加载的任务和执行信息。请重试以查看当前状态。" : "无法加载任务。请重试以查看其执行情况。"}
          action={<Button onClick={() => tasks.refetch()} loading={tasks.isFetching}>重试任务</Button>}
        />
      )}
      {section !== "strategy" && activeTasks.length > 0 && (
        <Alert
          type="info"
          showIcon
          title={`${runningCount} 个任务运行中 · ${queuedCount} 个任务排队中`}
          description={
            <Space wrap>
              {activeTasks.map((t) => (
                <Link key={t.id} to={`/runs/${t.latest_run!.id}`} aria-label={`查看 ${t.name} 的现场执行`}>{t.name}：查看执行</Link>
              ))}
            </Space>
          }
        />
      )}
      {section !== "tasks" && <Card
        size="small"
        title={
          <Space>
            测试策略
            {s && <Tag color={s.status === "confirmed" ? "green" : "default"}>{s.status === "confirmed" ? "已确认" : "草稿"}</Tag>}
            {s && <Tag>v{s.revision} · {s.source === "agent" ? "AI 生成" : "手工"}</Tag>}
          </Space>
        }
        extra={
          <Space>
            {s?.agent_run_id && <Button onClick={() => onOpenRun(s.agent_run_id!)}>查看 AI 追踪</Button>}
            {s && <CorrectionButton targetType="strategy" targetId={s.id} />}
            <Button icon={<RobotOutlined />} loading={generate.isPending} onClick={() => generate.mutate()}>
              AI 生成策略
            </Button>
            {s && s.status !== "confirmed" && (
              <Popconfirm title="要确认该策略吗？确认后将创建草稿任务。" onConfirm={() => confirm.mutate()}>
                <Button type="primary">确认策略</Button>
              </Popconfirm>
            )}
          </Space>
        }
      >
        <Form form={form} layout="vertical" onFinish={(vals) => save.mutate(vals)}>
          <Form.Item name="scope" label="范围">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Space wrap>
            <Form.Item name="test_types" label="测试类型">
              <Select mode="tags" style={{ minWidth: 260 }} options={TEST_TYPES.map((t) => ({ value: t, label: t }))} />
            </Form.Item>
            <Form.Item name="intensity" label="深度">
              <Select allowClear style={{ width: 140 }} options={[{ value: "light", label: "轻量" }, { value: "standard", label: "标准" }, { value: "thorough", label: "充分" }]} />
            </Form.Item>
          </Space>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Button htmlType="submit" loading={save.isPending}>
            保存策略
          </Button>
        </Form>
      </Card>}
      {section !== "tasks" && (gaps.data?.length ?? 0) > 0 && (
        <Card size="small" title="需求缺口：还没有就绪用例" data-testid="gaps">
          <Typography.Paragraph type="secondary">
            任务只引用已有用例。以下需求还没有就绪用例：点击“生成草稿用例”，让 AI 起草若干（仅为草稿）；评审并设为就绪后，它们会自动加入匹配的任务。
          </Typography.Paragraph>
          <ListTable<RequirementGap>
            label="需求缺口"
            size="small"
            rowKey="requirement_id"

            dataSource={gaps.data}
            columns={[
              { title: "需求", render: (_, g) => `${g.title} (${g.code})` },
              { title: "草稿用例", dataIndex: "draft_count", render: (n: number) => (n ? <Tooltip title="存在草稿：请评审并设为就绪">{n} 待评审</Tooltip> : 0) },
              {
                title: "动作",
                render: (_, g) => (
                  <Button size="small" icon={<RobotOutlined />} loading={draftCases.isPending && gapBusy === g.requirement_id} disabled={draftCases.isPending} onClick={() => draftCases.mutate(g.requirement_id)}>
                    生成草稿用例
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      )}
      {section !== "strategy" && <Card
        size="small"
        title="测试任务"
        id="strategy-tasks"
        extra={
          <Space>
            <Tooltip title="每个需求一个“需求验证”任务，外加一个“通用质量”任务和一个“回归/冒烟”任务；已有的不会再创建">
              <Button loading={ensure.isPending} onClick={() => ensure.mutate(undefined)}>
                按类别补全任务
              </Button>
            </Tooltip>
            {version.status !== "planning" && version.status !== "closed" && (
              <Button type="primary" onClick={() => setRunAll(true)} disabled={!tasks.data?.length}>
                执行全部可运行任务
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
          title="任务只引用用例：就绪用例按规则挑选（需求、类别、优先级等），也可以在任务中手工增删；手工变更优先。用例设为就绪时会自动加入匹配的任务。"
        />
        <Form form={taskForm} layout="inline" style={{ marginBottom: 12 }} initialValues={{ kind: "requirement", executor: "agent" }} onFinish={(vals) => createTask.mutate(vals, { onSuccess: () => taskForm.resetFields() })}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: "必填" }]}>
            <Input placeholder="任务名称" />
          </Form.Item>
          <Form.Item name="kind" label="类型">
            <Select style={{ width: 120 }} options={(Object.keys(KIND_LABEL) as TaskKind[]).map((value) => ({ value, label: KIND_LABEL[value] }))} />
          </Form.Item>
          <Form.Item name="executor" label="执行者">
            <Select style={{ width: 120 }} options={Object.entries(EXECUTOR).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="environment_id" label="环境">
            <Select allowClear placeholder="环境" style={{ width: 140 }} options={(envs.data || []).map((e) => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Button htmlType="submit" loading={createTask.isPending}>
            新建任务
          </Button>
        </Form>
        <BatchBar
          noun=" 个任务"
          selected={taskSel}
          labelOf={(id) => tasks.data?.find((t) => t.id === id)?.name || id}
          onClear={() => setTaskSel([])}
          onDone={(ok) => {
            for (const k of keys) qc.invalidateQueries({ queryKey: k });
            setTaskSel((sel) => sel.filter((id) => !ok.includes(id)));
          }}
          actions={[
            { key: "ready", label: "设为就绪", primary: true, run: (id) => api(`/tasks/${id}/status`, { method: "POST", body: { status: "ready" } }) },
            { key: "run", label: "执行", confirm: `依次启动选中的 ${taskSel.length} 个任务？`, run: (id) => api(`/tasks/${id}/run`, { method: "POST" }) },
            { key: "archive", label: "归档", confirm: `归档选中的 ${taskSel.length} 个任务？归档后不能再执行或修改。`, run: (id) => api(`/tasks/${id}/status`, { method: "POST", body: { status: "archived" } }) },
            { key: "delete", label: "删除", danger: true, confirm: `删除选中的 ${taskSel.length} 个任务？已有执行记录的任务不能删除（请改为归档）。`, run: (id) => api(`/tasks/${id}`, { method: "DELETE" }) },
          ]}
        />
        <ListTable<Task>
          label="任务"
          error={tasks.isError}
          size="small"
          rowKey="id"
          rowSelection={{ selectedRowKeys: taskSel, onChange: (k) => setTaskSel(k as string[]) }}
          loading={tasks.isLoading}
          dataSource={tasks.data}
          scroll={{ x: "max-content" }}
          locale={{
            emptyText: (
              tasks.isError ? "无法获取任务信息" : tasks.isLoading ? "正在加载任务…" : <EmptyState
                title="暂无测试任务"
                hint="测试任务用于批量执行用例：在上方输入任务名称，选择执行器（Agent 浏览器/自动化脚本/手工）和环境，点击“新建任务”，再在任务详情中挑选用例。"
              />
            ),
          }}
          columns={[
            { title: "测试任务", dataIndex: "name", render: (n: string, t) => <Link to={`/tasks/${t.id}`}>{n}</Link> },
            { title: "类型", dataIndex: "kind", render: (k: TaskKind) => KIND_LABEL[k] || k },
            {
              title: "用例选择规则",
              dataIndex: "selector",
              render: (sel: Task["selector"]) => (sel ? <Tag color="cyan">{describeSelector(sel, reqCode).replace("在就绪用例中：", "")}</Tag> : <Tag>手工</Tag>),
            },
            { title: "执行者", dataIndex: "executor", render: (e) => EXECUTOR[e] || e },
            {
              title: "用例",
              dataIndex: "case_count",
              render: (n: number, t) => (
                <Space size={4}>
                  {n}
                  {(t.script_gap_count || 0) > 0 && (
                    <Tooltip title="没有自动化脚本的用例：任务执行时会跳过（不执行）">
                      <Tag color="orange">{t.script_gap_count} 个缺少脚本</Tag>
                    </Tooltip>
                  )}
                </Space>
              ),
            },
            { title: "状态", dataIndex: "status", render: (st) => <TaskStatusTag status={st} /> },
            {
              title: "最近一次执行",
              render: (_, t) => t.latest_run ? (
                <Space orientation="vertical" size={2}>
                  <Link to={`/runs/${t.latest_run.id}`} aria-label={`查看 ${t.name} 的最近一次执行`}>{fmtTime(t.latest_run.created_at)}</Link>
                  <TaskRunStatusTag status={t.latest_run.status} />
                  <Typography.Text type="secondary">
                    {t.latest_run.status === "queued" ? "等待启动" : `${t.latest_run.counts.done}/${t.latest_run.counts.total} 已处理`}
                  </Typography.Text>
                </Space>
              ) : <Typography.Text type="secondary">尚未执行</Typography.Text>,
            },
            { title: "下次执行", dataIndex: "next_run_at", render: (t: string | null, row) => (t ? fmtTime(t, { tz: row.schedule?.tz }) : "-") },
            {
              title: "动作",
              render: (_, t) => (
                <Space>
                  {t.status === "draft" && <a onClick={() => taskStatus.mutate({ id: t.id, status: "ready" })}>设为就绪</a>}
                  {["ready", "done", "cancelled"].includes(t.status) && <a onClick={() => runTask.mutate(t.id)}>执行</a>}
                  <Link to={`/tasks/${t.id}`}>用例与调度</Link>
                  {!["archived", "running"].includes(t.status) && <a onClick={() => taskStatus.mutate({ id: t.id, status: "archived" })}>归档</a>}
                  <Popconfirm title="要删除该任务吗？" onConfirm={() => removeTask.mutate(t.id)}>
                    <a>删除</a>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>}
    </Space>
  );
}
