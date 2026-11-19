import { useQuery } from "@tanstack/react-query";
import { Alert, Progress, Space, Tag, Typography } from "antd";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { AutomationProgress as Progress_ } from "../api/types";

/** Background AI automation progress: queued / in progress / done; lists suspected system issues and needs_fix cases separately */
export function AutomationProgress({ versionId, onChanged }: { versionId: string; onChanged?: () => void }) {
  const progress = useQuery({
    queryKey: ["automation", versionId],
    queryFn: async () => {
      const data = await api<Progress_>(`/versions/${versionId}/automation`);
      onChanged?.();
      return data;
    },
    refetchInterval: (q) => {
      const c = q.state.data?.counts || {};
      return (c.queued || 0) + (c.running || 0) > 0 ? 3000 : false;
    },
  });
  const data = progress.data;
  if (!data || data.jobs.length === 0) return null;
  // newest job per case decides its state
  const latest = new Map<string, (typeof data.jobs)[number]>();
  for (const j of data.jobs) if (j.case_id && !latest.has(j.case_id)) latest.set(j.case_id, j);
  const jobs = [...latest.values()];
  const pending = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
  const finished = jobs.length - pending;
  const ok = jobs.filter((j) => j.status === "done" && j.automation_status === "ok" && j.mode === "automated");
  const needsFix = jobs.filter((j) => j.automation_status === "needs_fix" && j.status !== "queued" && j.status !== "running");
  const sutIssue = jobs.filter((j) => j.automation_status === "sut_mismatch" && j.status !== "queued" && j.status !== "running");
  const envDown = jobs.filter((j) => j.automation_status === "env_unavailable" && j.status !== "queued" && j.status !== "running");
  const failed = jobs.filter((j) => j.status === "error");
  return (
    <Alert
      type={pending ? "info" : sutIssue.length || needsFix.length || failed.length || envDown.length ? "warning" : "success"}
      showIcon
      title={
        <Space wrap>
          <span>AI 自动化{pending ? "进行中" : "已完成"}</span>
          <Progress percent={Math.round((finished / jobs.length) * 100)} size="small" style={{ width: 160 }} />
          <Typography.Text type="secondary">
            {finished}/{jobs.length}: passed and bound {ok.length}
            {sutIssue.length ? `，疑似系统问题 ${sutIssue.length}` : ""}{needsFix.length ? `，待修复 ${needsFix.length}` : ""}
            {envDown.length ? `，环境不可用 ${envDown.length}（启动环境后重新排队）` : ""}
            {failed.length ? `，错误 ${failed.length}` : ""}
          </Typography.Text>
        </Space>
      }
      description={
        sutIssue.length || needsFix.length || failed.length || envDown.length ? (
          <Space orientation="vertical" size={2}>
            {sutIssue.length > 0 && (
              <Typography.Text strong>疑似系统问题（自检发现系统表现与预期不符；不要去“修”脚本）：</Typography.Text>
            )}
            {sutIssue.map((j) => (
              <span key={j.id}>
                <Link to={`/cases/${j.case_id}`}>{j.code}</Link> {j.title} <Tag color="red">疑似被测系统问题</Tag>
                <Typography.Text type="secondary">{j.automation_note}</Typography.Text>
              </span>
            ))}
            {sutIssue.length > 0 && (needsFix.length || envDown.length || failed.length) ? <Typography.Text strong>脚本 / 环境问题：</Typography.Text> : null}
            {[...needsFix, ...envDown, ...failed].map((j) => (
              <span key={j.id}>
                <Link to={`/cases/${j.case_id}`}>{j.code}</Link> {j.title}{" "}
                <Tag color={j.status === "error" || j.automation_status === "env_unavailable" ? "red" : "orange"}>
                  {j.status === "error" ? "错误" : j.automation_status === "env_unavailable" ? "环境不可用" : "待修复"}
                </Tag>
                <Typography.Text type="secondary">{j.status === "error" ? j.error : j.automation_note}</Typography.Text>
              </span>
            ))}
          </Space>
        ) : undefined
      }
    />
  );
}
