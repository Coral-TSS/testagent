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
    <Card title="最近的任务执行">
      <Typography.Paragraph type="secondary">
        请在版本页的“测试策略与任务”下执行任务或设置定时；单条用例的调试执行和手工记录在<Link to="/cases">用例</Link>详情页。
      </Typography.Paragraph>
      <ListTable<TaskRunRow>
        label="最近的任务执行"
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
              title={versionId ? "该版本还没有执行过任务" : "还没有执行过任务"}
              hint="执行以任务为单位：请在版本页的“测试策略与任务”下创建任务，选择用例和环境，然后点击“执行”。单个用例也可在其详情页进行调试执行。"
              actionLabel={versionId ? "前往测试策略与任务" : undefined}
              onAction={() => navigate(`/versions/${versionId}?tab=strategy`)}
            />
          ),
        }}
        columns={[
          { title: "时间", dataIndex: "created_at", render: (v: string, r) => <Link to={`/runs/${r.id}`}>{dayjs(v).format("YYYY-MM-DD HH:mm:ss")}</Link> },
          { title: "系统", dataIndex: "sut_code" },
          { title: "版本", dataIndex: "version_name", render: (v: string, r) => <Link to={`/versions/${r.version_id}`}>{`Version ${v}`}</Link> },
          { title: "测试任务", dataIndex: "task_name", render: (v: string, r) => <Link to={`/tasks/${r.task_id}`}>{v}</Link> },
          { title: "结果", dataIndex: "status", render: (v: string) => <TaskRunStatusTag status={v} /> },
          { title: "通过/总数", render: (_: unknown, r) => `${r.counts.passed}/${r.counts.total}` },
          { title: "触发", dataIndex: "trigger", render: (v: string) => (v === "schedule" ? "调度" : "手工") },
        ]}
      />
    </Card>
  );
}
