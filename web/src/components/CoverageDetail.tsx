import { Collapse, Space, Table, Tag, Typography } from "antd";
import { Link } from "react-router-dom";

import type { CaseBrief, CaseCoverage, Coverage, CoverageBlock, CoveredItem, NamedRef } from "../api/types";

/** Case tags that link to the case page: "TC-001". */
export function CaseRefs({ cases, empty = "Not covered" }: { cases?: CaseBrief[]; empty?: string }) {
  if (!cases?.length) return <Tag color="red">{empty}</Tag>;
  return (
    <Space size={[4, 4]} wrap>
      {cases.map((c) => (
        <Tag key={c.id} style={{ marginInlineEnd: 0 }}>
          <Link to={`/cases/${c.id}`} title={c.title}>
            {c.code}
          </Link>
        </Tag>
      ))}
    </Space>
  );
}

const modelPath = (sutId: string | undefined, kind: string, item: { id: string; node_id?: string }) =>
  !sutId ? undefined : kind === "relations" ? `/suts/${sutId}/model?view=links` : `/suts/${sutId}/model?node=${item.node_id || item.id}`;

/** Name with a link to the model element (action/entity/field/relation). */
export function ModelRef({ sutId, kind, item, color }: { sutId?: string; kind: string; item: NamedRef; color?: string }) {
  const to = modelPath(sutId, kind, item);
  return (
    <Tag color={color} style={{ marginInlineEnd: 0 }}>
      {to ? <Link to={to}>{item.name}</Link> : item.name}
    </Tag>
  );
}

const KIND_COLOR: Record<string, string> = { actions: "blue", entities: "cyan", fields: "purple", relations: "volcano" };
export const KIND_LABEL: Record<string, string> = { actions: "Actions", entities: "Entities", fields: "Fields", relations: "Links" };

/** One case's coverage as linked tags per kind (case page trace / list tooltip). */
export function CaseCoverageTags({ coverage, sutId, compact }: { coverage: CaseCoverage; sutId?: string; compact?: boolean }) {
  const kinds = (["actions", "entities", "fields", "relations"] as const).filter((k) => coverage[k]?.length);
  if (!kinds.length) return <Typography.Text type="secondary">Not linked to any model element</Typography.Text>;
  return (
    <div>
      {kinds.map((k) => (
        <div key={k} style={{ marginBottom: 4 }}>
          <Typography.Text type={compact ? undefined : "secondary"} style={compact ? { color: "inherit" } : undefined}>
            {`${KIND_LABEL[k]} (${coverage[k].length}): `}
          </Typography.Text>
          <Space size={[4, 4]} wrap>
            {coverage[k].map((i) => (
              <ModelRef key={i.id} sutId={sutId} kind={k} item={i} color={KIND_COLOR[k]} />
            ))}
          </Space>
        </div>
      ))}
    </div>
  );
}

/** "Actions 2 · Fields 3 · Links 1" summary for the case list column. */
export function coverageSummary(c?: CaseCoverage): string {
  if (!c) return "-";
  const parts = (["actions", "entities", "fields", "relations"] as const).filter((k) => c[k]?.length).map((k) => `${KIND_LABEL[k]} ${c[k].length}`);
  return parts.join(" · ") || "-";
}

function ItemsTable({ block, kind, sutId, versionId }: { block: CoverageBlock; kind: string; sutId?: string; versionId: string }) {
  return (
    <Table
      size="small"
      rowKey="id"
      pagination={false}
      dataSource={block.items}
      columns={[
        {
          title: kind === "requirements" ? "Requirement" : KIND_LABEL[kind],
          render: (_, i) =>
            kind === "requirements" ? (
              <Link to={`/versions/${versionId}?req=${i.id}`}>{`${i.code} ${i.title || ""}`}</Link>
            ) : (
              <ModelRef sutId={sutId} kind={kind} item={{ id: i.id, name: i.name || "", node_id: i.node_id }} color={KIND_COLOR[kind]} />
            ),
        },
        { title: "Covering cases", render: (_, i) => <CaseRefs cases={i.case_list} /> },
        { title: "Count", dataIndex: "cases", width: 60 },
      ]}
    />
  );
}

/** Coverage detail: which cases cover each requirement / action / field / link. */
export function CoverageDetail({ coverage }: { coverage: Coverage }) {
  const blocks = [
    ["requirements", "Requirement", coverage.requirements],
    ["actions", "Action", coverage.actions],
    ["fields", "Field", coverage.fields],
    ["relations", "Link", coverage.relations],
  ] as const;
  return (
    <Collapse
      size="small"
      data-testid="coverage-detail"
      items={blocks
        .filter(([, , b]) => b && b.total > 0)
        .map(([kind, label, b]) => ({
          key: kind,
          label: `${label} coverage detail ${b!.covered}/${b!.total}`,
          children: <ItemsTable block={b!} kind={kind} sutId={coverage.sut_id} versionId={coverage.version_id} />,
        }))}
    />
  );
}

/** Requirement drawer: each referenced element and the cases that cover it. */
export function RequirementCoverage({ coverage, sutId }: { coverage: Record<string, CoveredItem[]>; sutId: string }) {
  const kinds = ["actions", "entities", "fields", "relations"].filter((k) => coverage[k]?.length);
  if (!kinds.length) return <Typography.Text type="secondary">The requirements have not been structured onto model elements yet; structure and confirm them to see per-item coverage.</Typography.Text>;
  const rows = kinds.flatMap((k) => coverage[k].map((i) => ({ ...i, kind: k })));
  return (
    <Table
      size="small"
      rowKey={(r) => `${r.kind}:${r.id}`}
      pagination={false}
      dataSource={rows}
      columns={[
        { title: "Kind", dataIndex: "kind", width: 60, render: (k: string) => KIND_LABEL[k] },
        { title: "Element", render: (_, r) => <ModelRef sutId={sutId} kind={r.kind} item={r} color={KIND_COLOR[r.kind]} /> },
        { title: "Covering cases", render: (_, r) => <CaseRefs cases={r.cases} /> },
      ]}
    />
  );
}
