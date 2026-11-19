import { Tag } from "antd";

export const SEVERITY: Record<string, [string, string]> = {
  critical: ["严重", "red"],
  major: ["主要", "volcano"],
  minor: ["次要", "gold"],
  trivial: ["轻微", "default"],
};
export const DEFECT_STATUS: Record<string, [string, string]> = {
  open: ["待处理", "red"],
  in_progress: ["进行中", "processing"],
  resolved: ["已解决", "green"],
  closed: ["已关闭", "default"],
  rejected: ["已拒绝", "default"],
};
export const CAUSE_LABEL: Record<string, string> = {
  requirement: "需求问题",
  design: "设计问题",
  development: "开发问题",
  test: "测试问题",
  environment: "环境问题",
  unknown: "待判定",
};
export const CAUSE_ROLE: Record<string, string> = {
  requirement: "负责人",
  design: "负责人（设计）",
  development: "开发人员",
  test: "测试人员",
};
export const ROLE_LABEL: Record<string, string> = { owner: "负责人", developer: "开发", tester: "测试" };
/** Allowed next states (mirrors services/state.py). */
export const DEFECT_NEXT: Record<string, string[]> = {
  open: ["in_progress", "resolved", "rejected"],
  in_progress: ["resolved", "rejected", "open"],
  resolved: ["closed", "open"],
  closed: ["open"],
  rejected: ["open"],
};
export const DEFECT_ACTION: Record<string, string> = {
  in_progress: "开始处理",
  resolved: "标记已解决",
  closed: "关闭",
  rejected: "拒绝",
  open: "重新打开",
};

export function SeverityTag({ value }: { value: string }) {
  const [label, color] = SEVERITY[value] || [value, "default"];
  return <Tag color={color}>{label}</Tag>;
}
export function DefectStatusTag({ status }: { status: string }) {
  const [label, color] = DEFECT_STATUS[status] || [status, "default"];
  return <Tag color={color}>{label}</Tag>;
}
