import { ListTable } from "./ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Modal, Space, Switch, Tag, Tooltip, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { EXECUTION_MODE_LABEL } from "../app/executionMode";
import { api, describeError } from "../api/client";
import type { RunVersionResult, RunnableTask } from "../api/types";

export const REASON_LABEL: Record<NonNullable<RunnableTask["reason"]>, string> = {
  running: "已在运行",
  no_cases: "暂无用例",
  not_ready: "未设为就绪",
  no_environment: "无环境",
  no_ready_cases: "没有就绪用例",
  browser_use: "Browser Use 尚未接入",
};

/** Which rows can be ticked: runnable ones, plus drafts when "请先设为就绪" is on. */
export function selectable(t: RunnableTask, setReady: boolean): boolean {
  return t.runnable || (setReady && t.reason === "not_ready" && t.case_count > 0 && !t.active_run_id);
}

/** #13: start every runnable task of a version in one go ("执行任务" / "开始测试"). */
export function RunTasksModal({
  open,
  versionId,
  startTesting = false,
  onClose,
  onDone,
}: {
  open: boolean;
  versionId: string;
  /** opened from "Start testing": also move the version to testing, and offer "仅变更状态" */
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
        message.success("版本已进入测试中；没有启动任务");
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
        title: `已启动 ${out.started.length} 个任务${out.skipped.length ? `，${out.skipped.length} 个未启动` : ""}`,
        description: (
          <Space orientation="vertical" size={2}>
            {/* the notification renders outside the router: navigate by hand */}
            {out.started.map((s) => (
              <a key={s.run_id} href={`/runs/${s.run_id}`} onClick={(e) => (e.preventDefault(), navigate(`/runs/${s.run_id}`))}>
                {s.name}：查看执行
              </a>
            ))}
            {out.skipped.map((s) => (
              <span key={s.task_id}>
                {s.name || s.task_id}: {s.code === "MISSING_SCRIPTS" ? `无脚本的用例（${(s.related || []).join("、")}）` : s.message}
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
      message.success(`已为 ${out.queued} 条用例排队 AI 自动化`);
    } catch (err) {
      message.error(describeError(err));
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={760}
      title={startTesting ? "开始测试：执行该版本的任务" : "执行任务"}
      destroyOnHidden
      footer={
        <Space>
          {startTesting && (
            <Button onClick={() => submit(true)} disabled={busy}>
              仅变更状态
            </Button>
          )}
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={busy} disabled={!picked.length} onClick={() => submit()}>
            执行 {picked.length} 个任务
          </Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 8 }}>
        <Switch size="small" checked={setReady} onChange={setSetReady} aria-label="先把草稿任务设为就绪" />
        <Typography.Text>同时先把草稿任务设为就绪</Typography.Text>
      </Space>
      <ListTable<RunnableTask>
        label="任务选择"
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
          { title: "测试任务", dataIndex: "name", render: (n: string, t) => <Link to={`/tasks/${t.id}`}>{n}</Link> },
          { title: "执行方式", dataIndex: "executor", render: (e: string) => EXECUTION_MODE_LABEL[e] || e },
          { title: "就绪用例", render: (_: unknown, t) => `${t.ready_cases}/${t.case_count}` },
          { title: "环境", dataIndex: "environment_name", render: (e: string | null) => e || "-" },
          {
            title: "",
            render: (_: unknown, t) => (
              <Space size={4}>
                {t.reason && !selectable(t, setReady) && <Tag>{REASON_LABEL[t.reason]}</Tag>}
                {t.script_gaps.length > 0 && (
                  <Tooltip title={t.script_gaps.join(", ")}>
                    <Tag color="orange">{t.script_gaps.length} 个无脚本</Tag>
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
          title={`所选自动化任务中有 ${gapCount} 条用例尚无自动化脚本`}
          description={
            <Space orientation="vertical" size={4}>
              <Checkbox checked={allowMissing} onChange={(e) => setAllowMissing(e.target.checked)}>
                仍要执行：这些用例会被跳过（未执行，不计为通过）
              </Checkbox>
              <Space wrap>
                <Button size="small" onClick={generate}>
                  生成脚本（AI 自动化）
                </Button>
                <Typography.Text type="secondary">要把用例移到 Agent 任务，请打开该任务。</Typography.Text>
              </Space>
              {!allowMissing && <Typography.Text type="secondary">若不选择“仍然执行”，这些任务不会启动。</Typography.Text>}
            </Space>
          }
        />
      )}
    </Modal>
  );
}
