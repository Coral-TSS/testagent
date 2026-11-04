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
  if (job === "queued") return <Tag color="blue">Queued</Tag>;
  if (job === "running") return <Tag color="processing">Generating</Tag>;
  if (row.automation_status === "sut_mismatch")
    return (
      <Tooltip title={`${row.automation_note || "The system behaved differently from the expected result"} — suspected system issue, not a script problem`}>
        <Tag color="red">Suspected SUT issue</Tag>
      </Tooltip>
    );
  if (row.automation_status === "needs_fix")
    return (
      <Tooltip title={row.automation_note || "The last self-check failed"}>
        <Tag color="orange">Needs fix</Tag>
      </Tooltip>
    );
  if (row.automation_status === "env_unavailable")
    return (
      <Tooltip title={`${row.automation_note || "Environment unreachable"}; start the environment and run “AI automation” again`}>
        <Tag color="red">Env unavailable</Tag>
      </Tooltip>
    );
  if (row.mode === "automated") return <Tag color="green">Bound</Tag>;
  return <Typography.Text type="secondary">Not automated</Typography.Text>;
}
