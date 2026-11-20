import { ListTable } from "../components/ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Col, DatePicker, Form, Input, Radio, Row, Select, Space, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { CaseCategory, CaseRow, Environment, TaskCaseRow, TaskDetail, TaskRun, TaskRunRow } from "../api/types";
import { CaseStatusTag } from "../components/CaseTags";
import { TaskRunStatusTag, TaskStatusTag } from "../components/StatusTags";
import { browserTimezone, fmtTime } from "../utils/time";
import { objLabel } from "../components/ObjLink";
import { TaskRuleCard } from "../components/TaskRuleCard";
import { MissingScriptsModal } from "../components/MissingScriptsModal";
import { CATEGORY_COLOR, CATEGORY_LABEL, KIND_LABEL } from "../utils/categories";

type ScheduleKind = "none" | "once" | "cron";
interface ScheduleValues {
  kind: ScheduleKind;
  at?: dayjs.Dayjs;
  expr?: string;
  tz?: string;
}
type ScheduleBody = { type: "once"; at: string; tz?: string } | { type: "cron"; expr: string; tz?: string };

/** Converts the schedule form into the API body (`null` clears the schedule). Cron fields are wall-clock time in `tz`. */
export function scheduleBody(v: ScheduleValues): ScheduleBody | null {
  const tz = v.tz ? { tz: v.tz } : {};
  if (v.kind === "once" && v.at) return { type: "once", at: v.at.toDate().toISOString(), ...tz };
  if (v.kind === "cron" && v.expr?.trim()) return { type: "cron", expr: v.expr.trim().replace(/\s+/g, " "), ...tz };
  return null;
}

const STARTABLE = new Set(["ready", "done", "cancelled"]);

/** Test task: case order, execution, schedule/recurrence, run history (AC-13) */
export function TaskPage() {
  const { taskId = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [form] = Form.useForm<ScheduleValues>();
  const [caseIds, setCaseIds] = useState<string[] | null>(null);
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => api<TaskDetail>(`/tasks/${taskId}`) });
  const runs = useQuery({ queryKey: ["task-runs", taskId], queryFn: () => api<TaskRunRow[]>(`/tasks/${taskId}/runs`) });
  const t = task.data;
  const envs = useQuery({
    queryKey: ["envs", t?.sut_id],
    queryFn: () => api<Environment[]>(`/suts/${t!.sut_id}/environments`),
    enabled: Boolean(t?.sut_id),
  });
  const cases = useQuery({
    queryKey: ["cases", t?.sut_id, "task-picker"],
    queryFn: () => api<CaseRow[]>(`/suts/${t!.sut_id}/cases`),
    enabled: Boolean(t?.sut_id),
  });
  const general = useQuery({ queryKey: ["settings-general"], queryFn: () => api<{ timezone: string }>("/settings/general") });
  const defaultTz = general.data?.timezone || "UTC";
  const tzOptions = [...new Set([defaultTz, browserTimezone(), "UTC", t?.schedule?.tz].filter(Boolean) as string[])].map((z) => ({ value: z, label: z }));
  useEffect(() => {
    if (!t) return;
    const s = t.schedule;
    form.setFieldsValue({ kind: s?.type || "none", at: s?.type === "once" && s.at ? dayjs(s.at) : undefined, expr: s?.type === "cron" ? s.expr : undefined, tz: s?.tz || defaultTz });
  }, [t, form, defaultTz]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["task", taskId] });
    qc.invalidateQueries({ queryKey: ["task-runs", taskId] });
    qc.invalidateQueries({ queryKey: ["tasks"] });
  };
  const patch = useApiMutation((body: Record<string, unknown>) => api(`/tasks/${taskId}`, { method: "PATCH", body }), { success: "已保存", onSuccess: refresh });
  const saveCases = useApiMutation((ids: string[]) => api(`/tasks/${taskId}/cases`, { method: "PUT", body: { case_ids: ids } }), {
    success: "用例顺序已保存",
    onSuccess: () => {
      setCaseIds(null);
      refresh();
    },
  });
  const [params, setParams] = useSearchParams();
  const [gapAction, setGapAction] = useState<"run" | "ready" | null>(null);
  useEffect(() => {
    const m = params.get("missing");
    if (m === "run" || m === "ready") {
      setGapAction(m);
      const next = new URLSearchParams(params);
      next.delete("missing");
      setParams(next, { replace: true });
    }
  }, [params, setParams]);
  /** a MISSING_SCRIPTS 409 opens the three-way choice instead of an error toast (#18) */
  const missing = (err: unknown) => {
    if (err instanceof ApiError && err.code === "MISSING_SCRIPTS") {
      qc.invalidateQueries({ queryKey: ["task", taskId] });
      return true;
    }
    return false;
  };
  const setStatus = useApiMutation(
    (v: { status: string; allow?: boolean }) =>
      api(`/tasks/${taskId}/status`, { method: "POST", body: { status: v.status, allow_missing_scripts: v.allow || undefined } }),
    { onSuccess: refresh, onError: (err) => missing(err) && (setGapAction("ready"), true) },
  );
  const start = useApiMutation(
    (allow?: boolean) => api<TaskRun>(`/tasks/${taskId}/run`, { method: "POST", body: allow ? { allow_missing_scripts: true } : {} }),
    {
      onSuccess: (run) => {
        refresh();
        navigate(`/runs/${run.id}`);
      },
      onError: (err) => missing(err) && (setGapAction("run"), true),
    },
  );

  if (!t) return <Card loading />;
  const selected = caseIds ?? t.cases.map((c) => c.id);
  const editable = !["running", "archived"].includes(t.status);
  return (
    <Row gutter={16}>
      <MissingScriptsModal
        open={gapAction !== null}
        task={t}
        gaps={t.script_gaps || []}
        action={gapAction || "run"}
        onClose={() => setGapAction(null)}
        onProceed={() => (gapAction === "ready" ? setStatus.mutate({ status: "ready", allow: true }) : start.mutate(true))}
      />
      <Col span={15}>
        <Card
          title={
            <Space>
              {t.name} <TaskStatusTag status={t.status} />
              {t.kind && <Tag>{KIND_LABEL[t.kind] || t.kind}</Tag>}
            </Space>
          }
          extra={
            <Space>
              <Link to={`/versions/${t.version_id}?tab=strategy`}>{t.version_name ? `测试策略与任务（版本 ${t.version_name}）` : "测试策略与任务"}</Link>
              {(t.script_gaps?.length || 0) > 0 && (
                <Tooltip title="没有自动化脚本的自动化任务用例：任务执行时会被跳过（不执行）">
                  <Tag color="orange" data-testid="gap-tag" style={{ cursor: "pointer" }} onClick={() => setGapAction("run")}>
                    {t.script_gaps!.length} without script
                  </Tag>
                </Tooltip>
              )}
              {t.status === "draft" && <Button onClick={() => setStatus.mutate({ status: "ready" })}>设为就绪</Button>}
              <Button type="primary" disabled={!STARTABLE.has(t.status)} loading={start.isPending} onClick={() => start.mutate(false)}>
                立即执行
              </Button>
            </Space>
          }
        >
          <Form layout="inline" style={{ marginBottom: 12 }}>
            <Form.Item label="执行者">
              <Select
                style={{ width: 120 }}
                value={t.executor}
                disabled={!editable}
                onChange={(executor) => patch.mutate({ executor })}
                options={Object.entries({ agent: "Agent", automation: "已自动化", human: "手工" }).map(([value, label]) => ({ value, label }))}
              />
            </Form.Item>
            <Form.Item label="环境">
              <Select
                style={{ width: 220 }}
                allowClear
                value={t.environment_id || undefined}
                disabled={!editable}
                onChange={(environment_id) => patch.mutate({ environment_id: environment_id ?? null })}
                options={(envs.data || []).map((e) => ({ value: e.id, label: `${e.name} (${e.base_url})` }))}
              />
            </Form.Item>
          </Form>
          <TaskRuleCard task={t} editable={editable} onChanged={refresh} />
          <Typography.Paragraph type="secondary">按选定顺序串行执行；只有“就绪”用例会跑，出错也不会停止后续用例。在下方框中删除用例 = 手工移除（规则不会再加回来）；添加用例 = 手工添加。</Typography.Paragraph>
          <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
            <Select
              aria-label="任务用例"
              mode="multiple"
              style={{ width: "100%" }}
              value={selected}
              disabled={!editable}
              onChange={setCaseIds}
              optionFilterProp="label"
              options={(cases.data || []).filter((c) => c.status !== "deprecated").map((c) => ({ value: c.id, label: `${c.code} ${c.title}` }))}
            />
            <Button disabled={caseIds === null} loading={saveCases.isPending} onClick={() => saveCases.mutate(selected)}>
              保存顺序
            </Button>
          </Space.Compact>
          <ListTable
            label="任务用例"
            size="small"
            rowKey="id"

            dataSource={t.cases}
            columns={[
              { title: "#", dataIndex: "seq", width: 50 },
              { title: "用例", render: (_: unknown, c: TaskCaseRow) => <Link to={`/cases/${c.id}`}>{objLabel(c.title, c.code)}</Link> },
              {
                title: "来源",
                dataIndex: "source",
                render: (src: string, c: TaskCaseRow) => (
                  <Tooltip title={c.reason || undefined}>
                    <Tag color={src === "rule" ? "cyan" : "default"}>{src === "rule" ? "规则" : "手工"}</Tag>
                  </Tooltip>
                ),
              },
              { title: "原因", dataIndex: "reason", ellipsis: true, render: (r: string | null) => <Typography.Text type="secondary">{r || "-"}</Typography.Text> },
              { title: "类别", dataIndex: "category", render: (c: CaseCategory | undefined) => (c ? <Tag color={CATEGORY_COLOR[c]}>{CATEGORY_LABEL[c]}</Tag> : "-") },
              { title: "状态", dataIndex: "status", render: (s: string) => <CaseStatusTag status={s} /> },
              { title: "模式", dataIndex: "mode", render: (m: string) => (m === "automated" ? "已自动化" : "手工") },
              { title: "类型", dataIndex: "type_tag" },
            ]}
          />
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title="调度 / 周期" style={{ marginBottom: 16 }}>
          <Form<ScheduleValues> form={form} layout="vertical" disabled={!editable} onFinish={(v) => patch.mutate({ schedule: scheduleBody(v) })}>
            <Form.Item name="kind">
              <Radio.Group
                options={[
                  { value: "none", label: "无调度" },
                  { value: "once", label: "单次定时" },
                  { value: "cron", label: "cron 周期" },
                ]}
              />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(a, b) => a.kind !== b.kind}>
              {({ getFieldValue }) =>
                getFieldValue("kind") === "once" ? (
                  <Form.Item name="at" label="执行时间" rules={[{ required: true, message: "选择时间" }]}>
                    <DatePicker showTime />
                  </Form.Item>
                ) : getFieldValue("kind") === "cron" ? (
                  <>
                    <Form.Item name="expr" label="cron 表达式（分 时 日 月 星期，使用下方时区的本地时间）" rules={[{ required: true, message: "请输入 cron 表达式" }]} extra="例如 0 9 * * 1-5 表示工作日 09:00 执行">
                      <Input placeholder="0 9 * * *" />
                    </Form.Item>
                    <Form.Item name="tz" label="时区">
                      <Select showSearch options={tzOptions} style={{ width: 200 }} />
                    </Form.Item>
                  </>
                ) : null
              }
            </Form.Item>
            <Button htmlType="submit" loading={patch.isPending}>
              保存
            </Button>
          </Form>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            Next run: {t.next_run_at ? `${fmtTime(t.next_run_at, { tz: t.schedule?.tz || defaultTz })} (${t.schedule?.tz || defaultTz})` : "-"}. Checked every 30 seconds while the platform runs; skipped while the previous run is still going; runs missed while the platform is off are not caught up.
          </Typography.Paragraph>
        </Card>
        <Card size="small" title="执行历史">
          <ListTable<TaskRunRow>
            label="任务执行历史"
            error={runs.isError}
            onRetry={() => runs.refetch()}
            recordLimit={100}
            size="small"
            rowKey="id"
            loading={runs.isLoading}
            dataSource={runs.data}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            locale={{ emptyText: "尚未执行" }}
            columns={[
              { title: "时间", dataIndex: "created_at", render: (v: string, r) => <Link to={`/runs/${r.id}`}>{dayjs(v).format("MM-DD HH:mm")}</Link> },
              { title: "结果", dataIndex: "status", render: (v: string) => <TaskRunStatusTag status={v} /> },
              { title: "通过", render: (_: unknown, r) => `${r.counts.passed}/${r.counts.total}` },
              { title: "触发", dataIndex: "trigger", render: (v: string) => (v === "schedule" ? "调度" : "手工") },
            ]}
          />
        </Card>
      </Col>
    </Row>
  );
}
