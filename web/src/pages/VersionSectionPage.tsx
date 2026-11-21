import { useQuery } from "@tanstack/react-query";
import { Typography } from "antd";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Version } from "../api/types";
import { AgentRunDrawer } from "../components/AgentRunDrawer";
import { StrategyTab } from "../components/StrategyTab";
import { VersionStatusTag } from "../components/StatusTags";

/** Strategy or tasks for one version. The old `?tab=strategy` URL redirects here. */
export function VersionSectionPage({ section }: { section: "strategy" | "tasks" }) {
  const { versionId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const version = useQuery({ queryKey: ["version", versionId], queryFn: () => api<Version>(`/versions/${versionId}`) });
  const setRun = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("run", id);
    else next.delete("run");
    setParams(next, { replace: true });
  };
  const v = version.data;
  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        {section === "strategy" ? "测试策略" : "测试任务"}
        {v && (
          <Typography.Text type="secondary" style={{ marginLeft: 12, fontSize: 16, fontWeight: 400 }}>
            <Link to={`/versions/${v.id}`}>版本 {v.name}</Link> <VersionStatusTag status={v.status} />
          </Typography.Text>
        )}
      </Typography.Title>
      {v && <StrategyTab version={v} section={section} onOpenRun={(id) => setRun(id)} />}
      <AgentRunDrawer runId={params.get("run")} onClose={() => setRun(null)} />
    </>
  );
}
