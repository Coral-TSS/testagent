import { ListTable } from "./ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Modal, Space, Switch, Tag, Tooltip, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, describeError } from "../api/client";
import type { RunVersionResult, RunnableTask } from "../api/types";

export const REASON_LABEL: Record<NonNullable<RunnableTask["reason"]>, string> = {
  running: "Already running",
  no_cases: "No cases",
  not_ready: "Not set ready",
  no_environment: "No environment",
  no_ready_cases: "No ready cases",
};
const EXECUTOR: Record<string, string> = { agent: "Agent", automation: "Automated", human: "Manual" };

/** Which rows can be ticked: runnable ones, plus drafts when "set ready first" is on. */
export function selectable(t: RunnableTask, setReady: boolean): boolean {
  return t.runnable || (setReady && t.reason === "not_ready" && t.case_count > 0 && !t.active_run_id);
}

/** #13: start every runnable task of a version in one go ("Run tasks" / "Start testing"). */
export function RunTasksModal({
  open,
  versionId,
  startTesting = false,
  onClose,
  onDone,
}: {
  open: boolean;
  versionId: string;
  /** opened from "Start testing": also move the version to testing, and offer "only change status" */
  startTesting?: boolean;
  onClose: () => void;
  onDone?: (r: RunVersionResult | null) => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message, notification } = App.useApp();
  const q = useQuery({ queryKey: ["runnable-tasks", versionId], queryFn: () => api<RunnableTask[]>(`/versions/${versionId}/runnable-tasks`), enabled: open });
  const rows = useMemo(() => q.data || [], [q.data]);
  const [setReady, setSetReady] = useState(false);
  const [allowMissing, setAllowMissing] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setPicked(rows.filter((t) => t.runnable).map((t) => t.id));
  }, [rows]);
  useEffect(() => {
    if (!setReady) setPicked((p) => p.filter((id) => rows.find((t) => t.id === id)?.runnable));
  }, [setReady, rows]);
  const gapCount = rows.filter((t) => picked.includes(t.id)).reduce((n, t) => n + t.script_gaps.length, 0);
  const gapIds = rows.filter((t) => picked.includes(t.id)).flatMap((t) => t.script_gap_ids);

  const refresh = () => {
    for (const k of [["tasks", versionId], ["version", versionId], ["runnable-tasks", versionId], ["progress"]]) qc.invalidateQueries({ queryKey: k });
  };
  const submit = async (onlyStatus = false) => {
    setBusy(true);
    try {
      if (onlyStatus) {
        await api(`/versions/${versionId}/status`, { method: "POST", body: { status: "testing" } });
        message.success("Version moved to testing; no task was started");
        refresh();
        onDone?.(null);
        onClose();
        return;
      }
      const out = await api<RunVersionResult>(`/versions/${versionId}/run-tasks`, {
        method: "POST",
        body: { task_ids: picked, set_ready: setReady, allow_missing_scripts: allowMissing, start_testing: startTesting },
      });
      notification.open({
        type: out.skipped.length ? "warning" : "success",
        title: `Started ${out.started.length} task(s)${out.skipped.length ? `, ${out.skipped.length} not started` : ""}`,
        description: (
          <Space orientation="vertical" size={2}>
            {/* the notification renders outside the router: navigate by hand */}
            {out.started.map((s) => (
              <a key={s.run_id} href={`/runs/${s.run_id}`} onClick={(e) => (e.preventDefault(), navigate(`/runs/${s.run_id}`))}>
                {s.name}: view run
              </a>
            ))}
            {out.skipped.map((s) => (
              <span key={s.task_id}>
                {s.name || s.task_id}: {s.code === "MISSING_SCRIPTS" ? `cases without script (${(s.related || []).join(", ")})` : s.message}
              </span>
            ))}
          </Space>
        ),
      });
      refresh();
      onDone?.(out);
      onClose();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };
  const generate = async () => {
    try {
      const out = await api<{ queued: number }>(`/versions/${versionId}/automate`, { method: "POST", body: { case_ids: gapIds } });
      message.success(`AI automation queued for ${out.queued} case(s)`);
    } catch (err) {
      message.error(describeError(err));
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={760}
      title={startTesting ? "Start testing: run the version's tasks" : "Run tasks"}
      destroyOnHidden
      footer={
        <Space>
          {startTesting && (
            <Button onClick={() => submit(true)} disabled={busy}>
              Only change status
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button type="primary" loading={busy} disabled={!picked.length} onClick={() => submit()}>
            Run {picked.length} task(s)
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 8 }}>
        <Switch size="small" checked={setReady} onChange={setSetReady} aria-label="Set draft tasks ready first" />
        <Typography.Text>Also set draft tasks ready first</Typography.Text>
      </Space>
      <ListTable<RunnableTask>
        label="Task selection"
        error={q.isError}
        onRetry={() => q.refetch()}
        size="small"
        rowKey="id"
        loading={q.isLoading}
        dataSource={q.data}

        rowSelection={{
          selectedRowKeys: picked,
          onChange: (k) => setPicked(k as string[]),
          getCheckboxProps: (t) => ({ disabled: !selectable(t, setReady) }),
        }}
        columns={[
          { title: "Task", dataIndex: "name", render: (n: string, t) => <Link to={`/tasks/${t.id}`}>{n}</Link> },
          { title: "Actor", dataIndex: "executor", render: (e: string) => EXECUTOR[e] || e },
          { title: "Ready cases", render: (_: unknown, t) => `${t.ready_cases}/${t.case_count}` },
          { title: "Environment", dataIndex: "environment_name", render: (e: string | null) => e || "-" },
          {
            title: "",
            render: (_: unknown, t) => (
              <Space size={4}>
                {t.reason && !selectable(t, setReady) && <Tag>{REASON_LABEL[t.reason]}</Tag>}
                {t.script_gaps.length > 0 && (
                  <Tooltip title={t.script_gaps.join(", ")}>
                    <Tag color="orange">{t.script_gaps.length} without script</Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
        ]}
      />
      {gapCount > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 12 }}
          data-testid="run-tasks-gaps"
          title={`${gapCount} case(s) in the chosen automated tasks have no automation script`}
          description={
            <Space orientation="vertical" size={4}>
              <Checkbox checked={allowMissing} onChange={(e) => setAllowMissing(e.target.checked)}>
                Run anyway: those cases are skipped (not executed, not counted as passed)
              </Checkbox>
              <Space wrap>
                <Button size="small" onClick={generate}>
                  Generate scripts (AI automation)
                </Button>
                <Typography.Text type="secondary">To move cases to an agent task, open the task.</Typography.Text>
              </Space>
              {!allowMissing && <Typography.Text type="secondary">Without “run anyway”, those tasks are not started.</Typography.Text>}
            </Space>
          }
        />
      )}
    </Modal>
  );
}
