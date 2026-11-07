import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Card, Select, Space, Tag } from "antd";
import dayjs from "dayjs";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { ReportRow, ReportSummary, Sut, Version } from "../api/types";

export const SCOPE_LABEL: Record<string, string> = { task_run: "Task report", version: "Version report" };
export const pct = (v: number | null) => (v === null ? "-" : `${Math.round(v * 1000) / 10}%`);

export function SummaryText({ s }: { s: ReportSummary }) {
  return (
    <span>
      Total {s.total}: passed {s.passed} · failed {s.failed} · error {s.error} · blocked {s.blocked} · skipped {s.skipped ?? 0} · not run {s.not_executed}
    </span>
  );
}

/** A zero denominator has no test conclusion, regardless of why cases did not run. */
export function nothingExecuted(s: ReportSummary): boolean {
  const executed = s.executed ?? s.passed + s.failed + s.error;
  return executed === 0;
}

/** Pass-rate cell: "Not executed" instead of "-" when nothing could run. */
export const passRateText = (s: ReportSummary) => (nothingExecuted(s) ? "Not executed" : pct(s.pass_rate));

/** skipped / blocked / not run never count as passed — say so next to every pass rate. */
export function passRateNote(s: ReportSummary): string | null {
  const executed = s.executed ?? s.passed + s.failed + s.error;
  const noScript = s.skipped_no_script || 0;
  if (nothingExecuted(s)) {
    const reasons = [
      noScript ? `${noScript} without an automation script` : "",
      s.skipped > noScript ? `${s.skipped - noScript} skipped` : "",
      s.blocked ? `${s.blocked} awaiting manual` : "",
      s.not_executed ? `${s.not_executed} not run` : "",
    ].filter(Boolean);
    return `Not executed: no case ran${reasons.length ? ` (${reasons.join(", ")})` : ""}, so there is no pass rate`;
  }
  const left = [
    s.skipped ? (noScript ? `${s.skipped} skipped (${noScript} without an automation script)` : `${s.skipped} skipped`) : "",
    s.blocked ? `${s.blocked} awaiting manual` : "",
    s.not_executed ? `${s.not_executed} not run` : "",
  ].filter(Boolean);
  return `Pass rate = passed ${s.passed} / executed ${executed}${left.length ? `; ${left.join(", ")} do not count as passed` : ""}`;
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
    <Card title="Test reports">
      <Space wrap style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="SUT" style={{ width: 150 }} value={sutId} onChange={(v) => set("sut_id", v)} options={(suts.data || []).map((s) => ({ value: s.id, label: s.code }))} />
        <Select allowClear placeholder="Version" style={{ width: 130 }} disabled={!sutId} value={versionId} onChange={(v) => set("version_id", v)} options={(versions.data || []).map((v) => ({ value: v.id, label: v.name }))} />
        <Select allowClear placeholder="Type" style={{ width: 120 }} value={scopeType} onChange={(v) => set("scope_type", v)} options={Object.entries(SCOPE_LABEL).map(([value, label]) => ({ value, label }))} />
      </Space>
      <ListTable<ReportRow>
        label="Reports"
        error={rows.isError}
        onRetry={() => rows.refetch()}
        recordLimit={200}
        size="small"
        rowKey="id"
        loading={rows.isLoading}
        dataSource={rows.data}
        locale={{
          emptyText: (
            <EmptyState title="No reports yet" hint="A task report is generated automatically when a task run ends; once a version is in testing, click “Generate version report” on the version page. Reports cannot be changed once generated." />
          ),
        }}
        columns={[
          {
            title: "Report",
            key: "name",
            render: (_: unknown, r) => (
              <Link to={`/reports/${r.id}`}>{r.scope_type === "version" ? `Version ${r.version_name ?? ""} report` : `${r.task_name ?? "Task"} report`}</Link>
            ),
          },
          { title: "Type", dataIndex: "scope_type", width: 100, render: (v: string) => <Tag color={v === "version" ? "blue" : "default"}>{SCOPE_LABEL[v] || v}</Tag> },
          { title: "Version", dataIndex: "version_name", width: 100, render: (v: string | null) => v || "-" },
          { title: "Result", dataIndex: "summary", render: (s: ReportSummary) => <SummaryText s={s} /> },
          { title: "Pass rate", dataIndex: "summary", key: "rate", width: 80, render: (s: ReportSummary) => <span title={passRateNote(s) || undefined}>{passRateText(s)}{(s.skipped || s.not_executed) && !nothingExecuted(s) ? "*" : ""}</span> },
          { title: "AI summary", dataIndex: "has_ai_summary", width: 80, render: (v: boolean) => (v ? <Tag color="purple">has</Tag> : "-") },
          { title: "Generated at", dataIndex: "created_at", width: 130, render: (v: string) => dayjs(v).format("MM-DD HH:mm") },
        ]}
      />
    </Card>
  );
}
