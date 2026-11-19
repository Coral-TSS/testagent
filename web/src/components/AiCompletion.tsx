import { ListTable } from "./ListView";
import { RobotOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Popconfirm, Space, Tag, Typography } from "antd";
import { useMemo, useState, type ReactNode } from "react";

import type { AiProposal, CaseCategory, CaseStep, TestCase } from "../api/types";
import { CATEGORY_LABEL, QUALITY_TAGS } from "../utils/categories";

type FieldKey = keyof AiProposal["fields"];
export const PROPOSAL_LABEL: Record<FieldKey, string> = {
  test_point: "测试点",
  preconditions: "前置条件",
  steps: "步骤",
  test_data: "测试数据",
  expected: "预期结果",
  requirement_ids: "需求",
  node_ids: "节点",
  attribute_ids: "关联字段",
  category: "category",
  quality_tags: "质量属性",
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
  if (!steps?.length) return <Typography.Text type="secondary">（空）</Typography.Text>;
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
  if (k === "category") return v ? <Tag>{CATEGORY_LABEL[v as CaseCategory] || String(v)}</Tag> : <Typography.Text type="secondary">（空）</Typography.Text>;
  if (k === "quality_tags") {
    const tags = (v as string[]) || [];
    return tags.length ? tags.map((t) => <Tag key={t}>{QUALITY_TAGS[t] || t}</Tag>) : <Typography.Text type="secondary">（无）</Typography.Text>;
  }
  if (k === "test_data")
    return v ? <Typography.Text code style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(v, null, 1)}</Typography.Text> : <Typography.Text type="secondary">（空）</Typography.Text>;
  if (k.endsWith("_ids")) {
    const ids = (v as string[]) || [];
    const before = new Set((other as string[]) || []);
    if (!ids.length) return <Typography.Text type="secondary">（无）</Typography.Text>;
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
  return v ? <span style={{ whiteSpace: "pre-wrap" }}>{String(v)}</span> : <Typography.Text type="secondary">（空）</Typography.Text>;
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
          <RobotOutlined /> AI 补全建议 <Tag color="purple">等待你评审</Tag>
        </Space>
      }
      extra={
        <Space>
          {onOpenRun && (
            <Button size="small" onClick={() => onOpenRun(proposal.agent_run_id)}>
              查看 AI 追踪
            </Button>
          )}
          <Button size="small" loading={rejecting} onClick={onReject}>
            忽略建议
          </Button>
          <Popconfirm
            title={`确定接受已选的 ${picked.length} 项？`}
            description="将创建新的修订；用例保持当前状态，设为就绪前仍需你评审。"
            onConfirm={() => onAccept(picked)}
            disabled={!picked.length}
          >
            <Button size="small" type="primary" disabled={!picked.length} loading={accepting}>
              接受所选（{picked.length}）
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        {proposal.rationale}
      </Typography.Paragraph>
      {stale && <Alert type="warning" showIcon style={{ marginBottom: 8 }} title={`该建议基于修订 ${proposal.base_revision}，但用例之后已变更（当前修订 ${tc.revision}）；接受前请先对比。`} />}
      {!changed.length && <Alert type="info" showIcon style={{ marginBottom: 8 }} title="建议与当前内容一致，无需接受。" />}
      <ListTable
        label="补全变更"
        size="small"

        rowKey="key"
        dataSource={rows}
        columns={[
          {
            title: "",
            width: 36,
            render: (_, r) => (
              <Checkbox
                aria-label={`接受${PROPOSAL_LABEL[r.key]}`}
                disabled={!r.changed}
                checked={picked.includes(r.key)}
                onChange={(e) => setPicked((p) => (e.target.checked ? [...p, r.key] : p.filter((x) => x !== r.key)))}
              />
            ),
          },
          {
            title: "项",
            width: 90,
            render: (_, r) => (
              <Space orientation="vertical" size={0}>
                {PROPOSAL_LABEL[r.key]}
                {r.changed ? <Tag color="orange">已变更</Tag> : <Tag>未变更</Tag>}
              </Space>
            ),
          },
          { title: "当前", render: (_, r) => <Value k={r.key} v={r.before} names={names} /> },
          { title: "AI 建议", render: (_, r) => <Value k={r.key} v={r.after} names={names} other={r.before} /> },
        ]}
      />
    </Card>
  );
}
