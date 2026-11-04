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
      message.success(`AI automation queued for ${out.queued} case(s); run the task again when they are bound`);
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
      message.success(`Moved ${ids.length} case(s) to an agent task`);
      refresh();
      onClose();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} footer={null} width={640} title="Some cases in this automated task have no automation script" destroyOnHidden>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        title={`${gaps.length} case(s) have no script yet. If you run anyway they are skipped (not executed, not an error, not counted in the pass rate).`}
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
            Generate scripts (AI automation)
          </Button>
          <Typography.Text type="secondary"> Queues AI automation for these cases.</Typography.Text>
        </div>
        <Space wrap>
          <Button loading={busy === "move"} onClick={move}>
            Move to an agent task
          </Button>
          <Select
            aria-label="Target task"
            style={{ width: 260 }}
            value={target}
            onChange={setTarget}
            options={[{ value: "new", label: "New agent task" }, ...agentTasks.map((t) => ({ value: t.id, label: t.name }))]}
          />
        </Space>
        <div>
          <Button
            onClick={() => {
              onClose();
              onProceed();
            }}
          >
            {action === "run" ? "Skip these cases and run" : "Set ready anyway"}
          </Button>
        </div>
      </Space>
    </Modal>
  );
}
