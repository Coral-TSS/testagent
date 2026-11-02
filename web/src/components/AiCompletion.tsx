import { RobotOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Popconfirm, Space, Table, Tag, Typography } from "antd";
import { useMemo, useState, type ReactNode } from "react";

import type { AiProposal, CaseCategory, CaseStep, TestCase } from "../api/types";
import { CATEGORY_LABEL, QUALITY_TAGS } from "../utils/categories";

type FieldKey = keyof AiProposal["fields"];
export const PROPOSAL_LABEL: Record<FieldKey, string> = {
  test_point: "Test point",
  preconditions: "Preconditions",
  steps: "Steps",
  test_data: "Test data",
  expected: "Expected result",
  requirement_ids: "Requirements",
  node_ids: "Nodes",
  attribute_ids: "Linked fields",
  category: "category",
  quality_tags: "Quality attributes",
};
const ORDER = Object.keys(PROPOSAL_LABEL) as FieldKey[];

function current(tc: TestCase, key: FieldKey): unknown {
  if (key === "requirement_ids") return tc.requirements.map((r) => r.id);
  if (key === "node_ids") return tc.nodes.map((n) => n.id);
  if (key === "attribute_ids") return (tc.fields || []).map((f) => f.id);
  return (tc as unknown as Record<string, unknown>)[key] ?? null;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function currentNames(tc: TestCase): Record<string, string> {
  return {
    ...Object.fromEntries(tc.requirements.map((r) => [r.id, `${r.code} ${r.title}`])),
    ...Object.fromEntries(tc.nodes.map((n) => [n.id, n.name])),
    ...Object.fromEntries((tc.fields || []).map((f) => [f.id, `${f.node_name}.${f.name}`])),
  };
}

function Steps({ steps }: { steps?: CaseStep[] | null }) {
  if (!steps?.length) return <Typography.Text type="secondary">(empty)</Typography.Text>;
  return (
    <ol style={{ margin: 0, paddingInlineStart: 18 }}>
      {steps.map((s, i) => (
        <li key={i}>
          {s.action}
          {s.data ? <Typography.Text type="secondary"> | data: {s.data}</Typography.Text> : null}
          {s.expected ? <Typography.Text type="success"> | expected: {s.expected}</Typography.Text> : null}
        </li>
      ))}
    </ol>
  );
}

function Value({ k, v, names, other }: { k: FieldKey; v: unknown; names: Record<string, string>; other?: unknown }): ReactNode {
  if (k === "steps") return <Steps steps={v as CaseStep[]} />;
  if (k === "category") return v ? <Tag>{CATEGORY_LABEL[v as CaseCategory] || String(v)}</Tag> : <Typography.Text type="secondary">(empty)</Typography.Text>;
  if (k === "quality_tags") {
    const tags = (v as string[]) || [];
    return tags.length ? tags.map((t) => <Tag key={t}>{QUALITY_TAGS[t] || t}</Tag>) : <Typography.Text type="secondary">(none)</Typography.Text>;
  }
  if (k === "test_data")
    return v ? <Typography.Text code style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(v, null, 1)}</Typography.Text> : <Typography.Text type="secondary">(empty)</Typography.Text>;
  if (k.endsWith("_ids")) {
    const ids = (v as string[]) || [];
    const before = new Set((other as string[]) || []);
    if (!ids.length) return <Typography.Text type="secondary">(none)</Typography.Text>;
    return (
      <Space size={[4, 4]} wrap>
        {ids.map((id) => (
          <Tag key={id} color={other !== undefined && !before.has(id) ? "green" : undefined}>
            {other !== undefined && !before.has(id) ? "+ " : ""}
            {names[id] || id.slice(0, 8)}
          </Tag>
        ))}
      </Space>
    );
  }
  return v ? <span style={{ whiteSpace: "pre-wrap" }}>{String(v)}</span> : <Typography.Text type="secondary">(empty)</Typography.Text>;
}

/** AI completion: compares current and suggested values item by item; a person accepts the ticked ones (a new revision, still a draft). */
export function ProposalDiff({
  tc,
  proposal,
  accepting,
  rejecting,
  onAccept,
  onReject,
  onOpenRun,
}: {
  tc: TestCase;
  proposal: AiProposal;
  accepting?: boolean;
  rejecting?: boolean;
  onAccept: (fields: string[]) => void;
  onReject: () => void;
  onOpenRun?: (id: string) => void;
}) {
  const rows = useMemo(
    () =>
      ORDER.filter((k) => k in proposal.fields).map((k) => ({
        key: k,
        before: current(tc, k),
        after: proposal.fields[k],
        changed: !same(current(tc, k), proposal.fields[k]),
      })),
    [tc, proposal],
  );
  const changed = rows.filter((r) => r.changed).map((r) => r.key);
  const [picked, setPicked] = useState<string[]>(changed);
  const names = { ...currentNames(tc), ...proposal.labels };
  const stale = proposal.base_revision !== tc.revision;
  return (
    <Card
      size="small"
      data-testid="ai-proposal"
      style={{ marginBottom: 16, borderColor: "#d3adf7" }}
      title={
        <Space>
          <RobotOutlined /> AI completion suggestion <Tag color="purple">Awaiting your review</Tag>
        </Space>
      }
      extra={
        <Space>
          {onOpenRun && (
            <Button size="small" onClick={() => onOpenRun(proposal.agent_run_id)}>
              View AI trace
            </Button>
          )}
          <Button size="small" loading={rejecting} onClick={onReject}>
            Dismiss suggestion
          </Button>
          <Popconfirm
            title={`Accept the ${picked.length} selected item(s)?`}
            description="A new revision is created; the case keeps its current status and still needs your review before it is set ready."
            onConfirm={() => onAccept(picked)}
            disabled={!picked.length}
          >
            <Button size="small" type="primary" disabled={!picked.length} loading={accepting}>
              Accept selected ({picked.length})
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        {proposal.rationale}
      </Typography.Paragraph>
      {stale && <Alert type="warning" showIcon style={{ marginBottom: 8 }} title={`The suggestion is based on revision ${proposal.base_revision} , but the case changed afterwards (current revision ${tc.revision}); compare before accepting.`} />}
      {!changed.length && <Alert type="info" showIcon style={{ marginBottom: 8 }} title="The suggestion matches the current content; nothing to accept." />}
      <Table
        size="small"
        pagination={false}
        rowKey="key"
        dataSource={rows}
        columns={[
          {
            title: "",
            width: 36,
            render: (_, r) => (
              <Checkbox
                aria-label={`Accept ${PROPOSAL_LABEL[r.key]}`}
                disabled={!r.changed}
                checked={picked.includes(r.key)}
                onChange={(e) => setPicked((p) => (e.target.checked ? [...p, r.key] : p.filter((x) => x !== r.key)))}
              />
            ),
          },
          {
            title: "Item",
            width: 90,
            render: (_, r) => (
              <Space orientation="vertical" size={0}>
                {PROPOSAL_LABEL[r.key]}
                {r.changed ? <Tag color="orange">Changed</Tag> : <Tag>Unchanged</Tag>}
              </Space>
            ),
          },
          { title: "Current", render: (_, r) => <Value k={r.key} v={r.before} names={names} /> },
          { title: "AI suggestion", render: (_, r) => <Value k={r.key} v={r.after} names={names} other={r.before} /> },
        ]}
      />
    </Card>
  );
}
