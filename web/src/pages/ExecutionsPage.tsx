import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Card, Select, Space, Typography } from "antd";
import dayjs from "dayjs";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Sut, TaskRunRow, Version } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { TaskRunStatusTag } from "../components/StatusTags";

/** Executions: recent task runs (single-case debug runs and manual records are on the case detail page) */
export function ExecutionsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const versionId = params.get("version_id") || undefined;
  const sutId = params.get("sut_id") || undefined;
  const set = (key: string, value?: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "sut_id") next.delete("version_id");
    setParams(next, { replace: true });
  };
  const suts = useQuery({ queryKey: ["suts"], queryFn: () => api<Sut[]>("/suts") });
  const versions = useQuery({
    queryKey: ["versions", sutId],
    queryFn: () => api<Version[]>(`/suts/${sutId}/versions`),
    enabled: Boolean(sutId),
  });
  const runs = useQuery({
    queryKey: ["runs", sutId, versionId],
    queryFn: () => api<TaskRunRow[]>("/runs", { params: { sut_id: sutId, version_id: versionId } }),
    refetchInterval: 10000,
  });
  const rows = runs.data;
  return (
    <Card title="最近的任务执行">
      <Typography.Paragraph type="secondary">
        请在版本的“任务”页执行任务或设置定时；单条用例的调试执行和手工记录在用例详情页。不选被测系统时列出全部系统。
      </Typography.Paragraph>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select allowClear aria-label="按被测系统筛选" placeholder="全部被测系统" style={{ width: 180 }} value={sutId} onChange={(v) => set("sut_id", v)} options={(suts.data || []).map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))} />
        <Select allowClear aria-label="按版本筛选" placeholder="全部版本" style={{ width: 140 }} disabled={!sutId} value={versionId} onChange={(v) => set("version_id", v)} options={(versions.data || []).map((v) => ({ value: v.id, label: `版本 ${v.name}` }))} />
      </Space>
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
              hint="执行以任务为单位：请在版本的“任务”页创建任务，选择用例和环境，然后点击“执行”。单个用例也可在其详情页进行调试执行。"
              actionLabel={versionId ? "前往任务" : undefined}
              onAction={() => navigate(`/versions/${versionId}/tasks`)}
            />
          ),
        }}
        columns={[
          { title: "时间", dataIndex: "created_at", render: (v: string, r) => <Link to={`/runs/${r.id}`}>{dayjs(v).format("YYYY-MM-DD HH:mm:ss")}</Link> },
          { title: "系统", dataIndex: "sut_code" },
          { title: "版本", dataIndex: "version_name", render: (v: string, r) => <Link to={`/versions/${r.version_id}`}>{`版本 ${v}`}</Link> },
          { title: "测试任务", dataIndex: "task_name", render: (v: string, r) => <Link to={`/tasks/${r.task_id}`}>{v}</Link> },
          { title: "结果", dataIndex: "status", render: (v: string) => <TaskRunStatusTag status={v} /> },
          { title: "通过/总数", render: (_: unknown, r) => `${r.counts.passed}/${r.counts.total}` },
          { title: "触发", dataIndex: "trigger", render: (v: string) => (v === "schedule" ? "调度" : "手工") },
        ]}
      />
    </Card>
  );
}
