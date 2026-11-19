import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Modal, Select, Space, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, describeError } from "../api/client";
import type { ScriptGap, Task, TaskDetail } from "../api/types";

/** #18: an automated task has ready cases without an automation script. Three ways on:
 * generate scripts, move the cases to an agent task, or run anyway (they are skipped). */
export function MissingScriptsModal({
  open,
  task,
  gaps,
  action,
  onClose,
  onProceed,
}: {
  open: boolean;
  task: Pick<TaskDetail, "id" | "name" | "version_id" | "environment_id" | "cases">;
  gaps: ScriptGap[];
  /** what the person was doing: "run" or "ready" */
  action: "run" | "ready";
  onClose: () => void;
  onProceed: () => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [target, setTarget] = useState<string>("new");
  const [busy, setBusy] = useState<string | null>(null);
  const tasks = useQuery({
    queryKey: ["tasks", task.version_id],
    queryFn: () => api<Task[]>(`/versions/${task.version_id}/tasks`),
    enabled: open,
  });
  const agentTasks = (tasks.data || []).filter((t) => t.executor === "agent" && t.id !== task.id && t.status !== "archived");
  const ids = gaps.map((g) => g.id);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["task", task.id] });
    qc.invalidateQueries({ queryKey: ["tasks"] });
  };

  const generate = async () => {
    setBusy("generate");
    try {
      const out = await api<{ queued: number }>(`/versions/${task.version_id}/automate`, {
        method: "POST",
        body: { case_ids: ids, environment_id: task.environment_id || undefined },
      });
      message.success(`已为 ${out.queued} 条用例排队 AI 自动化；脚本绑定后再执行任务`);
      onClose();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(null);
    }
  };

  const move = async () => {
    setBusy("move");
    try {
      if (target === "new") {
        await api(`/versions/${task.version_id}/tasks`, {
          method: "POST",
          body: { name: `${task.name} (agent)`, executor: "agent", environment_id: task.environment_id || undefined, case_ids: ids },
        });
      } else {
        const other = await api<TaskDetail>(`/tasks/${target}`);
        const merged = [...other.cases.map((c) => c.id), ...ids.filter((i) => !other.cases.some((c) => c.id === i))];
        await api(`/tasks/${target}/cases`, { method: "PUT", body: { case_ids: merged } });
      }
      // taking them out by hand: the rule will not put them back
      await api(`/tasks/${task.id}/cases`, { method: "PUT", body: { case_ids: task.cases.map((c) => c.id).filter((i) => !ids.includes(i)) } });
      message.success(`已将 ${ids.length} 条用例移到 Agent 任务`);
      refresh();
      onClose();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} footer={null} width={640} title="该自动化任务中的部分用例还没有自动化脚本" destroyOnHidden>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        title={`${gaps.length} 条用例尚无脚本。若仍要执行，这些用例会被跳过（未执行，不算错误，也不计入通过率）。`}
      />
      <Space wrap style={{ marginBottom: 12 }} data-testid="gap-list">
        {gaps.map((g) => (
          <Link key={g.id} to={`/cases/${g.id}`}>
            {g.code} {g.title}
          </Link>
        ))}
      </Space>
      <Space orientation="vertical" style={{ width: "100%" }} size={12}>
        <div>
          <Button type="primary" loading={busy === "generate"} onClick={generate}>
            生成脚本（AI 自动化）
          </Button>
          <Typography.Text type="secondary"> 将这些用例加入 AI 自动化队列。</Typography.Text>
        </div>
        <Space wrap>
          <Button loading={busy === "move"} onClick={move}>
            移到 Agent 任务
          </Button>
          <Select
            aria-label="目标任务"
            style={{ width: 260 }}
            value={target}
            onChange={setTarget}
            options={[{ value: "new", label: "新建 Agent 任务" }, ...agentTasks.map((t) => ({ value: t.id, label: t.name }))]}
          />
        </Space>
        <div>
          <Button
            onClick={() => {
              onClose();
              onProceed();
            }}
          >
            {action === "run" ? "跳过这些用例并执行" : "仍然设为就绪"}
          </Button>
        </div>
      </Space>
    </Modal>
  );
}
