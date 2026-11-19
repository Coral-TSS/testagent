import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Card, Select, Typography } from "antd";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { AgentRunDrawer, PURPOSE, RefLinks } from "../components/AgentRunDrawer";
import type { RefLabel } from "../api/types";
import { RunStatusTag } from "../components/StatusTags";

interface RunRow {
  id: string;
  purpose: string;
  status: string;
  error_code?: string | null;
  step_count: number;
  created_at: string;
  ended_at?: string | null;
  subjects?: RefLabel[];
}

const PURPOSES = Object.entries(PURPOSE).map(([value, label]) => ({ value, label }));

/** Agent run trace list + detail drawer */
export function AgentRunsPage() {
  const [params, setParams] = useSearchParams();
  const [purpose, setPurpose] = useState<string>();
  const runs = useQuery({
    queryKey: ["agent-runs", purpose],
    queryFn: () => api<RunRow[]>("/agent/runs", { params: { limit: 100, purpose } }),
    refetchInterval: 5000,
  });
  const label = new Map(PURPOSES.map((p) => [p.value, p.label]));
  return (
    <Card>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Agent 运行追踪
      </Typography.Title>
      <Select allowClear placeholder="全部用途" style={{ width: 180, marginBottom: 12 }} options={PURPOSES} value={purpose} onChange={setPurpose} />
      <ListTable<RunRow>
        label="Agent 追踪"
        error={runs.isError}
        onRetry={() => runs.refetch()}
        recordLimit={100}
        size="small"
        rowKey="id"
        loading={runs.isLoading}
        dataSource={runs.data}
        onRow={(r) => ({ onClick: () => setParams({ run: r.id }), style: { cursor: "pointer" } })}
        columns={[
          { title: "时间", dataIndex: "created_at", render: (t: string) => t.replace("T", " ").slice(0, 19) },
          { title: "用途", dataIndex: "purpose", render: (p) => label.get(p) || p },
          { title: "对象", dataIndex: "subjects", render: (s?: RefLabel[]) => <RefLinks refs={s} max={3} /> },
          { title: "状态", dataIndex: "status", render: (s) => <RunStatusTag status={s} /> },
          { title: "步骤", dataIndex: "step_count" },
          { title: "错误", dataIndex: "error_code" },
        ]}
      />
      <AgentRunDrawer runId={params.get("run")} onClose={() => setParams({})} />
    </Card>
  );
}
