import { Tag } from "antd";

const VERSION: Record<string, [string, string]> = {
  planning: ["规划中", "blue"],
  requirements_frozen: ["需求已冻结", "purple"],
  testing: ["测试中", "orange"],
  closed: ["已关闭", "default"],
};
const REQUIREMENT: Record<string, [string, string]> = {
  draft: ["草稿", "default"],
  structured: ["已结构化", "blue"],
  confirmed: ["已确认", "green"],
};
const RUN: Record<string, [string, string]> = {
  queued: ["排队中", "default"],
  running: ["运行中", "processing"],
  succeeded: ["成功", "green"],
  failed: ["失败", "red"],
  cancelled: ["已取消", "default"],
  error: ["错误", "red"],
};

const EXECUTION: Record<string, [string, string]> = {
  queued: ["排队中", "default"],
  running: ["运行中", "processing"],
  passed: ["通过", "green"],
  failed: ["失败", "red"],
  error: ["错误", "volcano"],
  blocked: ["阻塞", "orange"],
  skipped: ["跳过", "default"],
};
const TASK_RUN: Record<string, [string, string]> = {
  queued: ["排队中", "default"],
  running: ["运行中", "processing"],
  passed: ["通过", "green"],
  failed: ["存在失败", "red"],
  error: ["错误", "volcano"],
  cancelled: ["已取消", "default"],
  // nothing ran: every case lacks an automation script (neither passed nor failed)
  not_executed: ["未执行", "gold"],
};
const TASK: Record<string, [string, string]> = {
  draft: ["草稿", "default"],
  ready: ["就绪", "blue"],
  running: ["运行中", "processing"],
  done: ["已完成", "green"],
  cancelled: ["已取消", "default"],
  archived: ["已归档", "default"],
};
export const EXECUTOR_LABEL: Record<string, string> = {
  agent_browser: "Agent 浏览器",
  agent_api: "Agent API",
  pytest: "pytest 脚本",
  manual: "手工",
};

function make(map: Record<string, [string, string]>) {
  return function StatusTag({ status }: { status: string }) {
    const [label, color] = map[status] || [status, "default"];
    return <Tag color={color}>{label}</Tag>;
  };
}

export const VersionStatusTag = make(VERSION);
export const RequirementStatusTag = make(REQUIREMENT);
export const RunStatusTag = make(RUN);
export const ExecutionStatusTag = make(EXECUTION);
export const TaskRunStatusTag = make(TASK_RUN);
export const TaskStatusTag = make(TASK);
export const KIND_LABEL: Record<string, string> = { entity: "实体", action: "动作", relation: "关系" };
export const KIND_COLOR: Record<string, string> = { entity: "#1677ff", action: "#52c41a", relation: "#fa8c16" };
