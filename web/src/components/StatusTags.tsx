import { Tag } from "antd";

const VERSION: Record<string, [string, string]> = {
  planning: ["Planning", "blue"],
  requirements_frozen: ["Requirements frozen", "purple"],
  testing: ["Testing", "orange"],
  closed: ["Closed", "default"],
};
const REQUIREMENT: Record<string, [string, string]> = {
  draft: ["Draft", "default"],
  structured: ["Structured", "blue"],
  confirmed: ["Confirmed", "green"],
};
const RUN: Record<string, [string, string]> = {
  queued: ["Queued", "default"],
  running: ["Running", "processing"],
  succeeded: ["Success", "green"],
  failed: ["failed", "red"],
  cancelled: ["Cancelled", "default"],
  error: ["Error", "red"],
};

const EXECUTION: Record<string, [string, string]> = {
  queued: ["Queued", "default"],
  running: ["Running", "processing"],
  passed: ["Passed", "green"],
  failed: ["failed", "red"],
  error: ["Error", "volcano"],
  blocked: ["Blocked", "orange"],
  skipped: ["Skipped", "default"],
};
const TASK_RUN: Record<string, [string, string]> = {
  queued: ["Queued", "default"],
  running: ["Running", "processing"],
  passed: ["Passed", "green"],
  failed: ["Has failures", "red"],
  error: ["Error", "volcano"],
  cancelled: ["Cancelled", "default"],
  // nothing ran: every case lacks an automation script (neither passed nor failed)
  not_executed: ["Not executed", "gold"],
};
const TASK: Record<string, [string, string]> = {
  draft: ["Draft", "default"],
  ready: ["Ready", "blue"],
  running: ["Running", "processing"],
  done: ["Done", "green"],
  cancelled: ["Cancelled", "default"],
  archived: ["Archived", "default"],
};
export const EXECUTOR_LABEL: Record<string, string> = {
  agent_browser: "Agent browser",
  agent_api: "Agent API",
  pytest: "pytest script",
  manual: "Manual",
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
export const KIND_LABEL: Record<string, string> = { entity: "entities", action: "Actions", relation: "Link" };
export const KIND_COLOR: Record<string, string> = { entity: "#1677ff", action: "#52c41a", relation: "#fa8c16" };
