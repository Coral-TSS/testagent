import { Collapse, Space, Tag, Typography } from "antd";
import { Link } from "react-router-dom";

import type { FailureKind, FailureSummary as Summary, SuspectedCause } from "../api/types";

/** Suspected cause → label and colour (batch 2). Always "suspected": a person confirms. */
export const CAUSE_TAG: Record<SuspectedCause, [string, string]> = {
  sut: ["Suspected system issue", "red"],
  script: ["Suspected script / case issue", "orange"],
  environment: ["Environment issue", "blue"],
  platform: ["Platform / configuration issue", "default"],
  unknown: ["Cause unclear", "default"],
};
export const KIND_LABEL: Record<FailureKind, string> = {
  assertion: "Assertion failed",
  locator: "Element not found",
  timeout: "Timed out",
  script_error: "Script error",
  http_error: "Error response",
  env_unreachable: "System unreachable",
  platform: "Platform / config",
  agent_error: "Agent did not finish",
  no_script: "No script",
  non_functional: "Non-functional (not run)",
  unknown: "Unknown",
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
  if (summary.expected) rows.push(["Expected", <Typography.Text code>{summary.expected}</Typography.Text>]);
  if (summary.actual) rows.push(["Actual", <Typography.Text code>{summary.actual}</Typography.Text>]);
  if (summary.requirement_refs?.length)
    rows.push([
      "Requirement",
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
  if (summary.step) rows.push(["Step", summary.step]);
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
              label: "Raw error output",
              children: <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: 12 }}>{rawText}</pre>,
            },
          ]}
        />
      )}
    </div>
  );
}
