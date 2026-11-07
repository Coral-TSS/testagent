import { Alert, Collapse, Space, Tag, Typography } from "antd";
import type { MouseEvent } from "react";

import type { TaskBindingFeedback, TaskBindingInfo } from "../api/types";
import { TaskStatusTag } from "./StatusTags";

const REASON: Record<string, string> = {
  no_rule: "Manual task: add this case from the task or use Add to task.",
  rule_mismatch: "The case does not match this task's selection rule.",
  manually_excluded: "Removed manually; automatic rules will not add it back. Restore it from the task if needed.",
  task_running: "Task is running; its case list is not changed.",
  task_archived: "Task is archived; automatic association is disabled.",
  version_closed: "Version is closed; automatic association is disabled.",
  sync_unconfirmed: "A matching rule has not confirmed membership. Open the task and use Save rule and sync, then reload this case.",
};

/** Native links also work in App modal content, which sits outside the router context. */
export function ReadyTaskFeedback({ feedback, onNavigate }: { feedback: TaskBindingFeedback; onNavigate: (path: string) => void }) {
  const go = (event: MouseEvent<HTMLAnchorElement>, path: string) => {
    if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      onNavigate(path);
    }
  };
  const item = (task: TaskBindingInfo, linked: boolean) => (
    <li key={task.id} style={{ marginBottom: 8 }}>
      <Space wrap size={4}>
        <a href={`/tasks/${task.id}`} aria-label={`Open task ${task.name}`} onClick={(event) => go(event, `/tasks/${task.id}`)}>{task.name}</a>
        <Tag>Version {task.version_name}</Tag>
        <TaskStatusTag status={task.status} />
        {linked && <Tag>{task.source === "rule" ? "Automatic rule" : "Added manually"}</Tag>}
      </Space>
      <div>{linked ? task.reason : REASON[task.reason] || "Task association could not be confirmed."}</div>
    </li>
  );
  const manage = feedback.version_id ? `/versions/${feedback.version_id}?tab=strategy` : `/suts/${feedback.sut_id}/versions`;
  return (
    <section aria-label={`Task associations for ${feedback.code}`}>
      <Alert
        type={feedback.sync_warning ? "warning" : "info"}
        showIcon
        title={feedback.sync_warning ? "Ready saved; task association needs attention" : feedback.linked.length ? `Linked to ${feedback.linked.length} task(s)` : "Ready, but not linked to any task"}
        description={
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text>{feedback.code}: Ready does not start a run. Tasks run separately after they are set ready.</Typography.Text>
            {feedback.linked.length > 0 && <ul style={{ paddingInlineStart: 18, margin: 0 }}>{feedback.linked.map((task) => item(task, true))}</ul>}
            {!feedback.linked.length && !feedback.not_added.length && <Typography.Text>No tasks exist for this system yet. Create a strategy or add a task.</Typography.Text>}
            {feedback.not_added.length > 0 && (
              <Collapse size="small" style={{ width: "100%" }} items={[{
                key: "not-added", label: `Why ${feedback.not_added.length} task(s) were not added`,
                children: <ul style={{ paddingInlineStart: 18, margin: 0 }}>{feedback.not_added.map((task) => item(task, false))}</ul>,
              }]} />
            )}
            <a href={manage} onClick={(event) => go(event, manage)}>Manage test tasks</a>
          </Space>
        }
      />
    </section>
  );
}
