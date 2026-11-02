import { Tag } from "antd";

export const SEVERITY: Record<string, [string, string]> = {
  critical: ["Critical", "red"],
  major: ["Major", "volcano"],
  minor: ["Minor", "gold"],
  trivial: ["Trivial", "default"],
};
export const DEFECT_STATUS: Record<string, [string, string]> = {
  open: ["Open", "red"],
  in_progress: ["In progress", "processing"],
  resolved: ["Resolved", "green"],
  closed: ["Closed", "default"],
  rejected: ["Rejected", "default"],
};
export const CAUSE_LABEL: Record<string, string> = {
  requirement: "Requirement issue",
  design: "Design issue",
  development: "Development issue",
  test: "Test issue",
  environment: "Environment issue",
  unknown: "Undetermined",
};
export const CAUSE_ROLE: Record<string, string> = {
  requirement: "owner",
  design: "owner (design)",
  development: "developer",
  test: "tester",
};
export const ROLE_LABEL: Record<string, string> = { owner: "Owner", developer: "Developer", tester: "Tester" };
/** Allowed next states (mirrors services/state.py). */
export const DEFECT_NEXT: Record<string, string[]> = {
  open: ["in_progress", "resolved", "rejected"],
  in_progress: ["resolved", "rejected", "open"],
  resolved: ["closed", "open"],
  closed: ["open"],
  rejected: ["open"],
};
export const DEFECT_ACTION: Record<string, string> = {
  in_progress: "Start work",
  resolved: "Mark resolved",
  closed: "Close",
  rejected: "Reject",
  open: "Reopen",
};

export function SeverityTag({ value }: { value: string }) {
  const [label, color] = SEVERITY[value] || [value, "default"];
  return <Tag color={color}>{label}</Tag>;
}
export function DefectStatusTag({ status }: { status: string }) {
  const [label, color] = DEFECT_STATUS[status] || [status, "default"];
  return <Tag color={color}>{label}</Tag>;
}
