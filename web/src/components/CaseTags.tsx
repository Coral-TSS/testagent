import { Tag } from "antd";

export const SCENARIO: Record<string, [string, string]> = {
  normal: ["Normal", "green"],
  boundary: ["Boundary", "gold"],
  exception: ["Exception", "red"],
};
const STATUS: Record<string, [string, string]> = {
  draft: ["Draft", "default"],
  ready: ["Ready", "green"],
  deprecated: ["Deprecated", "default"],
};

export function ScenarioTag({ value }: { value?: string | null }) {
  if (!value) return null;
  const [label, color] = SCENARIO[value] || [value, "default"];
  return <Tag color={color}>{label}</Tag>;
}

export function CaseStatusTag({ status }: { status: string }) {
  const [label, color] = STATUS[status] || [status, "default"];
  return <Tag color={color}>{label}</Tag>;
}
