import { Alert, Collapse, Space, Tag, Typography } from "antd";
import type { MouseEvent } from "react";

import type { TaskBindingFeedback, TaskBindingInfo } from "../api/types";
import { TaskStatusTag } from "./StatusTags";

const REASON: Record<string, string> = {
  no_rule: "手工任务：请从任务中添加该用例，或使用“加入任务”。",
  rule_mismatch: "该用例不符合此任务的选择规则。",
  manually_excluded: "已手工移除；自动规则不会再把它加回来。如需恢复请到任务中操作。",
  task_running: "任务正在运行；其用例列表不会被更改。",
  task_archived: "任务已归档；已关闭自动关联。",
  version_closed: "版本已关闭；已关闭自动关联。",
  sync_unconfirmed: "匹配规则尚未确认该用例如入任务。请打开任务并使用“保存规则并同步”，然后重新加载本用例。",
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
        <a href={`/tasks/${task.id}`} aria-label={`打开任务 ${task.name}`} onClick={(event) => go(event, `/tasks/${task.id}`)}>{task.name}</a>
        <Tag>Version {task.version_name}</Tag>
        <TaskStatusTag status={task.status} />
        {linked && <Tag>{task.source === "rule" ? "自动规则" : "已手工添加"}</Tag>}
      </Space>
      <div>{linked ? task.reason : REASON[task.reason] || "无法确认任务关联。"}</div>
    </li>
  );
  const manage = feedback.version_id ? `/versions/${feedback.version_id}/tasks` : `/suts/${feedback.sut_id}/versions`;
  return (
    <section aria-label={`任务 ${feedback.code} 的关联`}>
      <Alert
        type={feedback.sync_warning ? "warning" : "info"}
        showIcon
        title={feedback.sync_warning ? "就绪已保存；任务关联需要关注" : feedback.linked.length ? `已关联 ${feedback.linked.length} 个任务` : "已就绪，但未关联到任何任务"}
        description={
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text>{feedback.code}: Ready does not start a run. Tasks run separately after they are set ready.</Typography.Text>
            {feedback.linked.length > 0 && <ul style={{ paddingInlineStart: 18, margin: 0 }}>{feedback.linked.map((task) => item(task, true))}</ul>}
            {!feedback.linked.length && !feedback.not_added.length && <Typography.Text>该系统还没有测试任务。请创建策略或添加任务。</Typography.Text>}
            {feedback.not_added.length > 0 && (
              <Collapse size="small" style={{ width: "100%" }} items={[{
                key: "not-added", label: `为何未加入 ${feedback.not_added.length} 个任务`,
                children: <ul style={{ paddingInlineStart: 18, margin: 0 }}>{feedback.not_added.map((task) => item(task, false))}</ul>,
              }]} />
            )}
            <a href={manage} onClick={(event) => go(event, manage)}>管理测试任务</a>
          </Space>
        }
      />
    </section>
  );
}
