import { ListTable } from "../components/ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card, Input, Select, Space, Tag } from "antd";
import dayjs from "dayjs";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { DefectRow, Person, Sut, Version } from "../api/types";
import { BatchBar } from "../components/BatchBar";
import { EmptyState } from "../components/EmptyState";
import { CAUSE_LABEL, DEFECT_STATUS, DefectStatusTag, SEVERITY, SeverityTag } from "../components/DefectTags";

const FILTERS = ["sut_id", "version_id", "status", "severity", "cause_category", "person_id", "q"] as const;

/** P12 defect list: filter by system, version, status, severity, cause and attributed person (filters are kept in the URL) */
export function DefectsPage() {
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(FILTERS.map((k) => [k, params.get(k) || undefined]));
  const set = (key: string, value?: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "sut_id") next.delete("version_id");
    setParams(next, { replace: true });
  };
  const suts = useQuery({ queryKey: ["suts"], queryFn: () => api<Sut[]>("/suts") });
  const versions = useQuery({
    queryKey: ["versions", filters.sut_id],
    queryFn: () => api<Version[]>(`/suts/${filters.sut_id}/versions`),
    enabled: Boolean(filters.sut_id),
  });
  const persons = useQuery({ queryKey: ["persons"], queryFn: () => api<Person[]>("/persons") });
  const rows = useQuery({ queryKey: ["defects", filters], queryFn: () => api<DefectRow[]>("/defects", { params: filters }) });
  const qc = useQueryClient();
  const [sel, setSel] = useState<string[]>([]);
  const toStatus = (status: string) => (id: string) => api(`/defects/${id}/status`, { method: "POST", body: { status } });
  const opts = (m: Record<string, [string, string]> | Record<string, string>) =>
    Object.entries(m).map(([value, v]) => ({ value, label: Array.isArray(v) ? v[0] : v }));
  return (
    <Card title="Defect">
      <Space wrap style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="SUT" style={{ width: 150 }} value={filters.sut_id} onChange={(v) => set("sut_id", v)} options={(suts.data || []).map((s) => ({ value: s.id, label: s.code }))} />
        <Select allowClear placeholder="Version" style={{ width: 130 }} disabled={!filters.sut_id} value={filters.version_id} onChange={(v) => set("version_id", v)} options={(versions.data || []).map((v) => ({ value: v.id, label: v.name }))} />
        <Select allowClear placeholder="Status" style={{ width: 110 }} value={filters.status} onChange={(v) => set("status", v)} options={opts(DEFECT_STATUS)} />
        <Select allowClear placeholder="Severity" style={{ width: 100 }} value={filters.severity} onChange={(v) => set("severity", v)} options={opts(SEVERITY)} />
        <Select allowClear placeholder="Cause category" style={{ width: 120 }} value={filters.cause_category} onChange={(v) => set("cause_category", v)} options={opts(CAUSE_LABEL)} />
        <Select allowClear showSearch optionFilterProp="label" placeholder="Attributed to" style={{ width: 130 }} value={filters.person_id} onChange={(v) => set("person_id", v)} options={(persons.data || []).map((p) => ({ value: p.id, label: p.name }))} />
        <Input.Search allowClear placeholder="Title / code" style={{ width: 200 }} defaultValue={filters.q} onSearch={(v) => set("q", v)} />
      </Space>
      <BatchBar
        noun=" defect(s)"
        selected={sel}
        labelOf={(id) => {
          const d = rows.data?.find((r) => r.id === id);
          return d ? `${d.title} (${d.code})` : id;
        }}
        onClear={() => setSel([])}
        onDone={(ok) => {
          qc.invalidateQueries({ queryKey: ["defects"] });
          setSel((s) => s.filter((id) => !ok.includes(id)));
        }}
        actions={[
          { key: "in_progress", label: "Set in progress", run: toStatus("in_progress") },
          { key: "resolved", label: "Set resolved", run: toStatus("resolved") },
          { key: "closed", label: "Close", confirm: `Close the ${sel.length} selected defect(s)? (only resolved defects can be closed)`, run: toStatus("closed") },
          { key: "rejected", label: "Reject", danger: true, confirm: `Reject the ${sel.length} selected defect(s)?`, run: toStatus("rejected") },
          { key: "open", label: "Reopen", run: toStatus("open") },
        ]}
      />
      <ListTable<DefectRow>
        label="Defects"
        error={rows.isError}
        onRetry={() => rows.refetch()}
        recordLimit={500}
        size="small"
        rowKey="id"
        rowSelection={{ selectedRowKeys: sel, onChange: (k) => setSel(k as string[]) }}
        loading={rows.isLoading}
        dataSource={rows.data}
        locale={{
          emptyText: (
            <EmptyState
              title="No defects"
              hint="Defects come from failed executions: click “Create defect” or “AI analyse cause” in the execution detail. Defects are assigned to requirements and attributed to people by role. You can also clear the filters."
            />
          ),
        }}
        columns={[
          { title: "Defect", dataIndex: "title", render: (v: string, r) => <Link to={`/defects/${r.id}`}>{`${v} (${r.code})`}</Link> },
          { title: "Severity", dataIndex: "severity", width: 80, render: (v: string) => <SeverityTag value={v} /> },
          { title: "Status", dataIndex: "status", width: 90, render: (v: string) => <DefectStatusTag status={v} /> },
          {
            title: "Reason",
            dataIndex: "cause_category",
            width: 130,
            render: (v: string, r) =>
              v === "unknown" && r.suggested_cause ? <Tag color="purple">AI suggestion: {CAUSE_LABEL[r.suggested_cause]}</Tag> : CAUSE_LABEL[v] || v,
          },
          { title: "Requirements", dataIndex: "requirement_codes", render: (v: string[]) => v.map((c) => <Tag key={c}>{c}</Tag>) },
          { title: "Attributed to", dataIndex: "responsible_names", render: (v: string[]) => v.join(", ") || "-" },
          { title: "Source", dataIndex: "created_by", width: 70, render: (v: string) => (v === "agent" ? <Tag color="purple">AI</Tag> : "Manual") },
          { title: "Created", dataIndex: "created_at", width: 120, render: (v: string) => dayjs(v).format("MM-DD HH:mm") },
        ]}
      />
    </Card>
  );
}
