import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Card, Select, Space, Tag } from "antd";
import dayjs from "dayjs";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { ReportRow, ReportSummary, Sut, Version } from "../api/types";

export const SCOPE_LABEL: Record<string, string> = { task_run: "任务报告", version: "版本报告" };
export const pct = (v: number | null) => (v === null ? "-" : `${Math.round(v * 1000) / 10}%`);

export function SummaryText({ s }: { s: ReportSummary }) {
  return (
    <span>
      共 {s.total}：通过 {s.passed} · 失败 {s.failed} · 错误 {s.error} · 阻塞 {s.blocked} · 跳过 {s.skipped ?? 0} · 未跑 {s.not_executed}
    </span>
  );
}

/** A zero denominator has no test conclusion, regardless of why cases did not run. */
export function nothingExecuted(s: ReportSummary): boolean {
  const executed = s.executed ?? s.passed + s.failed + s.error;
  return executed === 0;
}

/** Pass-rate cell: "未执行" instead of "-" when nothing could run. */
export const passRateText = (s: ReportSummary) => (nothingExecuted(s) ? "未执行" : pct(s.pass_rate));

/** skipped / blocked / not run never count as passed — say so next to every pass rate. */
export function passRateNote(s: ReportSummary): string | null {
  const executed = s.executed ?? s.passed + s.failed + s.error;
  const noScript = s.skipped_no_script || 0;
  if (nothingExecuted(s)) {
    const reasons = [
      noScript ? `${noScript} 个无自动化脚本` : "",
      s.skipped > noScript ? `${s.skipped - noScript} 个已跳过` : "",
      s.blocked ? `${s.blocked} 个等待手工执行` : "",
      s.not_executed ? `${s.not_executed} 个未跑` : "",
    ].filter(Boolean);
    return `未执行：没有用例真正跑过${reasons.length ? `（${reasons.join("，")}）` : ""}，因此没有通过率`;
  }
  const left = [
    s.skipped ? (noScript ? `${s.skipped} 个已跳过（${noScript} 个无自动化脚本）` : `${s.skipped} 个已跳过`) : "",
    s.blocked ? `${s.blocked} 个等待手工执行` : "",
    s.not_executed ? `${s.not_executed} 个未跑` : "",
  ].filter(Boolean);
  return `通过率 = 通过 ${s.passed} / 已执行 ${executed}${left.length ? `；${left.join("，")}不计为通过` : ""}`;
}

/** P11 report list: task reports (generated automatically at run end) and version reports; reports are immutable once generated */
export function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const sutId = params.get("sut_id") || undefined;
  const versionId = params.get("version_id") || undefined;
  const scopeType = params.get("scope_type") || undefined;
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
  const rows = useQuery({
    queryKey: ["reports", sutId, versionId, scopeType],
    queryFn: () => api<ReportRow[]>("/reports", { params: { sut_id: sutId, version_id: versionId, scope_type: scopeType } }),
  });
  return (
    <Card title="测试报告">
      <Space wrap style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="被测系统" style={{ width: 150 }} value={sutId} onChange={(v) => set("sut_id", v)} options={(suts.data || []).map((s) => ({ value: s.id, label: s.code }))} />
        <Select allowClear placeholder="版本" style={{ width: 130 }} disabled={!sutId} value={versionId} onChange={(v) => set("version_id", v)} options={(versions.data || []).map((v) => ({ value: v.id, label: v.name }))} />
        <Select allowClear placeholder="类型" style={{ width: 120 }} value={scopeType} onChange={(v) => set("scope_type", v)} options={Object.entries(SCOPE_LABEL).map(([value, label]) => ({ value, label }))} />
      </Space>
      <ListTable<ReportRow>
        label="报告"
        error={rows.isError}
        onRetry={() => rows.refetch()}
        recordLimit={200}
        size="small"
        rowKey="id"
        loading={rows.isLoading}
        dataSource={rows.data}
        locale={{
          emptyText: (
            <EmptyState title="暂无报告" hint="任务执行结束后会自动生成任务报告；版本进入测试中后，可在版本页点击“生成版本报告”。报告一经生成不可更改。" />
          ),
        }}
        columns={[
          {
            title: "报告",
            key: "name",
            render: (_: unknown, r) => (
              <Link to={`/reports/${r.id}`}>{r.scope_type === "version" ? `版本 ${r.version_name ?? ""} 报告` : `${r.task_name ?? "测试任务"} 报告`}</Link>
            ),
          },
          { title: "类型", dataIndex: "scope_type", width: 100, render: (v: string) => <Tag color={v === "version" ? "blue" : "default"}>{SCOPE_LABEL[v] || v}</Tag> },
          { title: "版本", dataIndex: "version_name", width: 100, render: (v: string | null) => v || "-" },
          { title: "结果", dataIndex: "summary", render: (s: ReportSummary) => <SummaryText s={s} /> },
          { title: "通过率", dataIndex: "summary", key: "rate", width: 80, render: (s: ReportSummary) => <span title={passRateNote(s) || undefined}>{passRateText(s)}{(s.skipped || s.not_executed) && !nothingExecuted(s) ? "*" : ""}</span> },
          { title: "AI 摘要", dataIndex: "has_ai_summary", width: 80, render: (v: boolean) => (v ? <Tag color="purple">有</Tag> : "-") },
          { title: "生成于", dataIndex: "created_at", width: 130, render: (v: string) => dayjs(v).format("MM-DD HH:mm") },
        ]}
      />
    </Card>
  );
}
