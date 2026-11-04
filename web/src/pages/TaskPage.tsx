import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Col, DatePicker, Form, Input, Radio, Row, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
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
  const patch = useApiMutation((body: Record<string, unknown>) => api(`/tasks/${taskId}`, { method: "PATCH", body }), { success: "Saved", onSuccess: refresh });
  const saveCases = useApiMutation((ids: string[]) => api(`/tasks/${taskId}/cases`, { method: "PUT", body: { case_ids: ids } }), {
    success: "Case order saved",
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
              <Link to={`/versions/${t.version_id}?tab=strategy`}>{t.version_name ? `Test strategy & tasks (version ${t.version_name})` : "Test strategy & tasks"}</Link>
              {(t.script_gaps?.length || 0) > 0 && (
                <Tooltip title="Automated task cases with no automation script: they are skipped (not executed) when the task runs">
                  <Tag color="orange" data-testid="gap-tag" style={{ cursor: "pointer" }} onClick={() => setGapAction("run")}>
                    {t.script_gaps!.length} without script
                  </Tag>
                </Tooltip>
              )}
              {t.status === "draft" && <Button onClick={() => setStatus.mutate({ status: "ready" })}>Set ready</Button>}
              <Button type="primary" disabled={!STARTABLE.has(t.status)} loading={start.isPending} onClick={() => start.mutate(false)}>
                Run now
              </Button>
            </Space>
          }
        >
          <Form layout="inline" style={{ marginBottom: 12 }}>
            <Form.Item label="Actor">
              <Select
                style={{ width: 120 }}
                value={t.executor}
                disabled={!editable}
                onChange={(executor) => patch.mutate({ executor })}
                options={Object.entries({ agent: "Agent", automation: "Automated", human: "Manual" }).map(([value, label]) => ({ value, label }))}
              />
            </Form.Item>
            <Form.Item label="Environment">
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
          <Typography.Paragraph type="secondary">Runs serially in the chosen order; only “Ready” cases run, and errors do not stop the following cases. Deleting a case in the box below = removing it by hand (the rule will not add it back); adding a case = adding it by hand.</Typography.Paragraph>
          <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
            <Select
              aria-label="Task cases"
              mode="multiple"
              style={{ width: "100%" }}
              value={selected}
              disabled={!editable}
              onChange={setCaseIds}
              optionFilterProp="label"
              options={(cases.data || []).filter((c) => c.status !== "deprecated").map((c) => ({ value: c.id, label: `${c.code} ${c.title}` }))}
            />
            <Button disabled={caseIds === null} loading={saveCases.isPending} onClick={() => saveCases.mutate(selected)}>
              Save order
            </Button>
          </Space.Compact>
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={t.cases}
            columns={[
              { title: "#", dataIndex: "seq", width: 50 },
              { title: "Case", render: (_: unknown, c: TaskCaseRow) => <Link to={`/cases/${c.id}`}>{objLabel(c.title, c.code)}</Link> },
              {
                title: "Source",
                dataIndex: "source",
                render: (src: string, c: TaskCaseRow) => (
                  <Tooltip title={c.reason || undefined}>
                    <Tag color={src === "rule" ? "cyan" : "default"}>{src === "rule" ? "Rule" : "Manual"}</Tag>
                  </Tooltip>
                ),
              },
              { title: "Reason", dataIndex: "reason", ellipsis: true, render: (r: string | null) => <Typography.Text type="secondary">{r || "-"}</Typography.Text> },
              { title: "category", dataIndex: "category", render: (c: CaseCategory | undefined) => (c ? <Tag color={CATEGORY_COLOR[c]}>{CATEGORY_LABEL[c]}</Tag> : "-") },
              { title: "Status", dataIndex: "status", render: (s: string) => <CaseStatusTag status={s} /> },
              { title: "Mode", dataIndex: "mode", render: (m: string) => (m === "automated" ? "Automated" : "Manual") },
              { title: "Type", dataIndex: "type_tag" },
            ]}
          />
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title="Schedule / recurrence" style={{ marginBottom: 16 }}>
          <Form<ScheduleValues> form={form} layout="vertical" disabled={!editable} onFinish={(v) => patch.mutate({ schedule: scheduleBody(v) })}>
            <Form.Item name="kind">
              <Radio.Group
                options={[
                  { value: "none", label: "No schedule" },
                  { value: "once", label: "Once at a time" },
                  { value: "cron", label: "cron recurrence" },
                ]}
              />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(a, b) => a.kind !== b.kind}>
              {({ getFieldValue }) =>
                getFieldValue("kind") === "once" ? (
                  <Form.Item name="at" label="Run at" rules={[{ required: true, message: "Choose a time" }]}>
                    <DatePicker showTime />
                  </Form.Item>
                ) : getFieldValue("kind") === "cron" ? (
                  <>
                    <Form.Item name="expr" label="cron expression (minute hour day month weekday, local time of the time zone below)" rules={[{ required: true, message: "Enter a cron expression" }]} extra="e.g. 0 9 * * 1-5 runs at 09:00 on weekdays">
                      <Input placeholder="0 9 * * *" />
                    </Form.Item>
                    <Form.Item name="tz" label="Time zone">
                      <Select showSearch options={tzOptions} style={{ width: 200 }} />
                    </Form.Item>
                  </>
                ) : null
              }
            </Form.Item>
            <Button htmlType="submit" loading={patch.isPending}>
              Save
            </Button>
          </Form>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            Next run: {t.next_run_at ? `${fmtTime(t.next_run_at, { tz: t.schedule?.tz || defaultTz })} (${t.schedule?.tz || defaultTz})` : "-"}. Checked every 30 seconds while the platform runs; skipped while the previous run is still going; runs missed while the platform is off are not caught up.
          </Typography.Paragraph>
        </Card>
        <Card size="small" title="Run history">
          <Table<TaskRunRow>
            size="small"
            rowKey="id"
            loading={runs.isLoading}
            dataSource={runs.data || []}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            locale={{ emptyText: "Never run yet" }}
            columns={[
              { title: "Time", dataIndex: "created_at", render: (v: string, r) => <Link to={`/runs/${r.id}`}>{dayjs(v).format("MM-DD HH:mm")}</Link> },
              { title: "Result", dataIndex: "status", render: (v: string) => <TaskRunStatusTag status={v} /> },
              { title: "Passed", render: (_: unknown, r) => `${r.counts.passed}/${r.counts.total}` },
              { title: "Trigger", dataIndex: "trigger", render: (v: string) => (v === "schedule" ? "Schedule" : "Manual") },
            ]}
          />
        </Card>
      </Col>
    </Row>
  );
}
