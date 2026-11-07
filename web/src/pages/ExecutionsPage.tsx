import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Card, Typography } from "antd";
import dayjs from "dayjs";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { TaskRunRow } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { TaskRunStatusTag } from "../components/StatusTags";

/** Executions: recent task runs (single-case debug runs and manual records are on the case detail page) */
export function ExecutionsPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const versionId = params.get("version_id");
  const sutId = params.get("sut_id");
  const runs = useQuery({
    queryKey: ["runs", sutId, versionId],
    queryFn: () => api<TaskRunRow[]>("/runs", { params: { sut_id: sutId, version_id: versionId } }),
    refetchInterval: 10000,
  });
  const rows = runs.data;
  return (
    <Card title="Recent task runs">
      <Typography.Paragraph type="secondary">
        Run tasks or set schedules under “Test strategy & tasks” on the version page; debug runs and manual records of a single case are on the <Link to="/cases">case</Link> detail page.
      </Typography.Paragraph>
      <ListTable<TaskRunRow>
        label="Recent task runs"
        error={runs.isError}
        onRetry={() => runs.refetch()}
        recordLimit={50}
        size="small"
        rowKey="id"
        loading={runs.isLoading}
        dataSource={rows}
        locale={{
          emptyText: (
            <EmptyState
              title={versionId ? "No task has run in this version yet" : "No task has run yet"}
              hint="Execution is task-based: on the version page under “Test strategy & tasks”, create a task, choose cases and an environment, then click “Run”. A single case can be debug-run from its detail page."
              actionLabel={versionId ? "Go to test strategy & tasks" : undefined}
              onAction={() => navigate(`/versions/${versionId}?tab=strategy`)}
            />
          ),
        }}
        columns={[
          { title: "Time", dataIndex: "created_at", render: (v: string, r) => <Link to={`/runs/${r.id}`}>{dayjs(v).format("YYYY-MM-DD HH:mm:ss")}</Link> },
          { title: "System", dataIndex: "sut_code" },
          { title: "Version", dataIndex: "version_name", render: (v: string, r) => <Link to={`/versions/${r.version_id}`}>{`Version ${v}`}</Link> },
          { title: "Task", dataIndex: "task_name", render: (v: string, r) => <Link to={`/tasks/${r.task_id}`}>{v}</Link> },
          { title: "Result", dataIndex: "status", render: (v: string) => <TaskRunStatusTag status={v} /> },
          { title: "Passed/total", render: (_: unknown, r) => `${r.counts.passed}/${r.counts.total}` },
          { title: "Trigger", dataIndex: "trigger", render: (v: string) => (v === "schedule" ? "Schedule" : "Manual") },
        ]}
      />
    </Card>
  );
}
