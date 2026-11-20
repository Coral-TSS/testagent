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
    <Card title="缺陷">
      <Space wrap style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="被测系统" style={{ width: 150 }} value={filters.sut_id} onChange={(v) => set("sut_id", v)} options={(suts.data || []).map((s) => ({ value: s.id, label: s.code }))} />
        <Select allowClear placeholder="版本" style={{ width: 130 }} disabled={!filters.sut_id} value={filters.version_id} onChange={(v) => set("version_id", v)} options={(versions.data || []).map((v) => ({ value: v.id, label: v.name }))} />
        <Select allowClear placeholder="状态" style={{ width: 110 }} value={filters.status} onChange={(v) => set("status", v)} options={opts(DEFECT_STATUS)} />
        <Select allowClear placeholder="严重级别" style={{ width: 100 }} value={filters.severity} onChange={(v) => set("severity", v)} options={opts(SEVERITY)} />
        <Select allowClear placeholder="原因类别" style={{ width: 120 }} value={filters.cause_category} onChange={(v) => set("cause_category", v)} options={opts(CAUSE_LABEL)} />
        <Select allowClear showSearch optionFilterProp="label" placeholder="归因于" style={{ width: 130 }} value={filters.person_id} onChange={(v) => set("person_id", v)} options={(persons.data || []).map((p) => ({ value: p.id, label: p.name }))} />
        <Input.Search allowClear placeholder="标题 / 编号" style={{ width: 200 }} defaultValue={filters.q} onSearch={(v) => set("q", v)} />
      </Space>
      <BatchBar
        noun=" 个缺陷"
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
          { key: "in_progress", label: "设为进行中", run: toStatus("in_progress") },
          { key: "resolved", label: "设为已解决", run: toStatus("resolved") },
          { key: "closed", label: "关闭", confirm: `要关闭选中的 ${sel.length} 个缺陷吗？（只能关闭已解决的缺陷）`, run: toStatus("closed") },
          { key: "rejected", label: "拒绝", danger: true, confirm: `要拒绝选中的 ${sel.length} 个缺陷吗？`, run: toStatus("rejected") },
          { key: "open", label: "重新打开", run: toStatus("open") },
        ]}
      />
      <ListTable<DefectRow>
        label="缺陷"
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
              title="暂无缺陷"
              hint="缺陷来自失败的执行：请在执行详情中点击“创建缺陷”或“AI 分析原因”。缺陷会关联到需求，并按角色归因到人员。也可以清除筛选条件。"
            />
          ),
        }}
        columns={[
          { title: "缺陷", dataIndex: "title", render: (v: string, r) => <Link to={`/defects/${r.id}`}>{`${v} (${r.code})`}</Link> },
          { title: "严重级别", dataIndex: "severity", width: 80, render: (v: string) => <SeverityTag value={v} /> },
          { title: "状态", dataIndex: "status", width: 90, render: (v: string) => <DefectStatusTag status={v} /> },
          {
            title: "原因",
            dataIndex: "cause_category",
            width: 130,
            render: (v: string, r) =>
              v === "unknown" && r.suggested_cause ? <Tag color="purple">AI 建议：{CAUSE_LABEL[r.suggested_cause]}</Tag> : CAUSE_LABEL[v] || v,
          },
          { title: "需求", dataIndex: "requirement_codes", render: (v: string[]) => v.map((c) => <Tag key={c}>{c}</Tag>) },
          { title: "归因于", dataIndex: "responsible_names", render: (v: string[]) => v.join(", ") || "-" },
          { title: "来源", dataIndex: "created_by", width: 70, render: (v: string) => (v === "agent" ? <Tag color="purple">AI</Tag> : "手工") },
          { title: "创建时间", dataIndex: "created_at", width: 120, render: (v: string) => dayjs(v).format("MM-DD HH:mm") },
        ]}
      />
    </Card>
  );
}
