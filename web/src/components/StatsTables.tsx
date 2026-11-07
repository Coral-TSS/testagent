import { ListTable } from "./ListView";
import { Tag } from "antd";
import { Link } from "react-router-dom";

import type { RequirementStat, RoleStat } from "../api/types";
import { ROLE_LABEL, SEVERITY } from "./DefectTags";

export const fmtDensity = (v: number | null) => (v === null ? "-" : v.toFixed(2));
export const fmtScore = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

export function BySeverity({ value }: { value: Record<string, number> }) {
  const keys = Object.keys(SEVERITY).filter((k) => value[k]);
  if (!keys.length) return <>-</>;
  return (
    <>
      {keys.map((k) => (
        <Tag key={k} color={SEVERITY[k][1]}>
          {SEVERITY[k][0]} {value[k]}
        </Tag>
      ))}
    </>
  );
}

export function ByRole({ value }: { value: Record<string, RoleStat> }) {
  const keys = Object.keys(value);
  if (!keys.length) return <>-</>;
  return (
    <>
      {keys.map((k) => (
        <Tag key={k}>
          {ROLE_LABEL[k] || k} {value[k].count} ({fmtScore(value[k].score)})
        </Tag>
      ))}
    </>
  );
}

/** Defects / weighted score / density per requirement (defects ÷ executed cases) */
export function RequirementStatsTable({ rows, loading, error, onRetry, paginate = true }: { rows?: RequirementStat[]; loading?: boolean; error?: boolean; onRetry?: () => void; paginate?: boolean }) {
  return (
    <ListTable<RequirementStat>
      pagination={paginate ? undefined : false}
      error={error}
      onRetry={onRetry}
      label="Requirement statistics"
      size="small"
      rowKey="requirement_id"
      loading={loading}
      dataSource={rows}

      locale={{ emptyText: "No requirements" }}
      columns={[
        {
          title: "Requirement",
          dataIndex: "code",
          width: 220,
          render: (v: string, r) => (
            <Link to={`/versions/${r.version_id}?req=${r.requirement_id}`}>
              {v} {r.title}
            </Link>
          ),
        },
        { title: "Defects", dataIndex: "defect_count", width: 80, sorter: (a, b) => a.defect_count - b.defect_count },
        { title: "Weighted score", dataIndex: "weighted_score", width: 80, render: fmtScore, sorter: (a, b) => a.weighted_score - b.weighted_score },
        { title: "Executed cases", dataIndex: "executed_cases", width: 100 },
        { title: "Defect density", dataIndex: "density", width: 90, render: fmtDensity, sorter: (a, b) => (a.density ?? -1) - (b.density ?? -1) },
        { title: "Severity distribution", dataIndex: "by_severity", render: (v: Record<string, number>) => <BySeverity value={v} /> },
        {
          title: "Owner / developer / tester",
          key: "people",
          render: (_: unknown, r) => [r.owner.join(", ") || "-", r.developers.join(", ") || "-", r.testers.join(", ") || "-"].join(" / "),
        },
      ]}
    />
  );
}
