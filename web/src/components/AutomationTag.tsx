import { Tag, Tooltip, Typography } from "antd";

import type { AutomationStatus } from "../api/types";

/** A case's automation status: queued / generating / bound / suspected SUT issue / needs fix (reason) / env unavailable (retryable) / not automated */
export function AutomationTag({
  row,
  job,
}: {
  row: { mode: string; automation_status?: AutomationStatus | null; automation_note?: string | null };
  job?: string;
}) {
  if (job === "queued") return <Tag color="blue">排队中</Tag>;
  if (job === "running") return <Tag color="processing">生成中</Tag>;
  if (row.automation_status === "sut_mismatch")
    return (
      <Tooltip title={`${row.automation_note || "系统表现与预期结果不符"} — 疑似系统问题，不是脚本问题`}>
        <Tag color="red">疑似被测系统问题</Tag>
      </Tooltip>
    );
  if (row.automation_status === "needs_fix")
    return (
      <Tooltip title={row.automation_note || "上次自检失败"}>
        <Tag color="orange">待修复</Tag>
      </Tooltip>
    );
  if (row.automation_status === "env_unavailable")
    return (
      <Tooltip title={`${row.automation_note || "环境不可达"}；请启动环境后再次运行“AI 自动化”`}>
        <Tag color="red">环境不可用</Tag>
      </Tooltip>
    );
  if (row.mode === "automated") return <Tag color="green">已绑定</Tag>;
  return <Typography.Text type="secondary">未自动化</Typography.Text>;
}
