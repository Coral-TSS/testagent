import { Collapse, Space, Tag, Typography } from "antd";
import { Link } from "react-router-dom";

import type { FailureKind, FailureSummary as Summary, SuspectedCause } from "../api/types";

/** Suspected cause → label and colour (batch 2). Always "suspected": a person confirms. */
export const CAUSE_TAG: Record<SuspectedCause, [string, string]> = {
  sut: ["疑似系统问题", "red"],
  script: ["疑似脚本 / 用例问题", "orange"],
  environment: ["环境问题", "blue"],
  platform: ["平台 / 配置问题", "default"],
  unknown: ["原因不明", "default"],
};
export const KIND_LABEL: Record<FailureKind, string> = {
  assertion: "断言失败",
  locator: "未找到元素",
  timeout: "超时",
  script_error: "脚本错误",
  http_error: "错误响应",
  env_unreachable: "系统不可达",
  platform: "平台 / 配置",
  agent_error: "Agent 未完成",
  no_script: "无脚本",
  non_functional: "非功能（未执行）",
  unknown: "未知",
};

export function CauseTag({ cause }: { cause?: SuspectedCause | null }) {
  if (!cause) return null;
  const [label, color] = CAUSE_TAG[cause] || CAUSE_TAG.unknown;
  return <Tag color={color}>{label}</Tag>;
}

/** Readable failure summary: cause + one sentence, expected / actual / requirement / step, the
 * agent's note, and the raw text folded away (#15). */
export function FailureSummary({ summary, raw, versionId }: { summary: Summary; raw?: string | null; versionId?: string | null }) {
  const rawText = raw ?? summary.raw;
  const rows: [string, React.ReactNode][] = [];
  if (summary.expected) rows.push(["预期", <Typography.Text code>{summary.expected}</Typography.Text>]);
  if (summary.actual) rows.push(["实际", <Typography.Text code>{summary.actual}</Typography.Text>]);
  if (summary.requirement_refs?.length)
    rows.push([
      "需求",
      <Space size={4} wrap>
        {summary.requirement_refs.map((r) => (
          <span key={r.code}>
            {r.id && versionId ? <Link to={`/versions/${versionId}?req=${r.id}`}>{r.code}</Link> : r.code}
            {r.title ? ` ${r.title}` : ""}
            {r.rule ? <Typography.Text type="secondary"> — {r.rule}</Typography.Text> : null}
          </span>
        ))}
      </Space>,
    ]);
  if (summary.step) rows.push(["步骤", summary.step]);
  return (
    <div data-testid="failure-summary">
      <Space size={6} wrap style={{ marginBottom: 6 }}>
        <CauseTag cause={summary.cause} />
        <Tag>{KIND_LABEL[summary.kind] || summary.kind}</Tag>
        <Typography.Text strong>{summary.headline}</Typography.Text>
      </Space>
      {rows.length > 0 && (
        <table style={{ borderSpacing: "8px 2px", marginLeft: -8 }}>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td style={{ color: "rgba(0,0,0,0.45)", whiteSpace: "nowrap", verticalAlign: "top" }}>{k}</td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {summary.agent_note && (
        <Typography.Paragraph type="secondary" style={{ margin: "4px 0" }}>
          Agent: {summary.agent_note}
        </Typography.Paragraph>
      )}
      {rawText && (
        <Collapse
          size="small"
          ghost
          items={[
            {
              key: "raw",
              label: "原始错误输出",
              children: <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: 12 }}>{rawText}</pre>,
            },
          ]}
        />
      )}
    </div>
  );
}
