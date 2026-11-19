import { Tag } from "antd";

export const SCENARIO: Record<string, [string, string]> = {
  normal: ["正常", "green"],
  boundary: ["边界", "gold"],
  exception: ["异常", "red"],
};
const STATUS: Record<string, [string, string]> = {
  draft: ["草稿", "default"],
  ready: ["就绪", "green"],
  deprecated: ["已废弃", "default"],
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
