import { CheckCircleFilled, CloseCircleFilled } from "@ant-design/icons";
import { Alert, Collapse, Descriptions, Empty, Space, Steps, Tag, Typography } from "antd";

import type { ReportEvent, ReportStep, RunReport as Report } from "../api/types";

const METHOD_COLOR: Record<string, string> = { GET: "blue", POST: "green", PUT: "orange", PATCH: "gold", DELETE: "red", HEAD: "default" };

function Body({ label, text }: { label: string; text?: string | null }) {
  if (!text) return null;
  let pretty = text;
  try {
    pretty = JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    /* not JSON: show as is */
  }
  return (
    <div>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <pre style={{ margin: "2px 0 6px", maxHeight: 220, overflow: "auto", background: "#f6f8fa", padding: 8, fontSize: 12, borderRadius: 4, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
        {pretty}
      </pre>
    </div>
  );
}

function statusColor(status?: number) {
  if (status === undefined) return "default";
  return status < 300 ? "success" : status < 400 ? "processing" : status < 500 ? "warning" : "error";
}

export function EventLine({ ev }: { ev: ReportEvent }) {
  if (ev.type === "request") {
    return (
      <div data-testid="report-request">
        <Space wrap size={6}>
          <Tag color={METHOD_COLOR[ev.method || ""] || "default"}>{ev.method}</Tag>
          <Typography.Text code style={{ wordBreak: "break-all" }}>
            {ev.url}
          </Typography.Text>
          {ev.status !== undefined && <Tag color={statusColor(ev.status)}>{ev.status}</Tag>}
          {ev.ms !== undefined && <Typography.Text type="secondary">{ev.ms} ms</Typography.Text>}
          {ev.error && <Typography.Text type="danger">{ev.error}</Typography.Text>}
        </Space>
        {(ev.request || ev.response || ev.params) && (
          <Collapse
            size="small"
            ghost
            items={[
              {
                key: "b",
                label: "Request and response content",
                children: (
                  <>
                    <Body label="Query parameters" text={ev.params} />
                    <Body label="Request body" text={ev.request} />
                    <Body label="Response body" text={ev.response} />
                  </>
                ),
              },
            ]}
          />
        )}
      </div>
    );
  }
  if (ev.type === "action") {
    return (
      <Space wrap size={6} data-testid="report-action">
        <Tag color={ev.ok === false ? "red" : "cyan"}>{ev.action}</Tag>
        {ev.target && <Typography.Text code>{ev.target}</Typography.Text>}
        {ev.value != null && <Typography.Text type="secondary">Value: {ev.value}</Typography.Text>}
        {ev.status !== undefined && <Tag color={statusColor(ev.status)}>{ev.status}</Tag>}
        {ev.ms !== undefined && <Typography.Text type="secondary">{ev.ms} ms</Typography.Text>}
        {ev.error && <Typography.Text type="danger">{ev.error}</Typography.Text>}
      </Space>
    );
  }
  if (ev.type === "check") {
    const ok = ev.passed !== false;
    return (
      <div data-testid="report-check">
        <Space wrap size={6} align="start">
          {ok ? <CheckCircleFilled style={{ color: "#52c41a" }} /> : <CloseCircleFilled style={{ color: "#ff4d4f" }} />}
          <Typography.Text strong={!ok}>{ev.assert ? <code>{ev.name}</code> : ev.name}</Typography.Text>
        </Space>
        {(ev.expected != null || ev.actual != null) && (
          <div style={{ marginLeft: 22, fontSize: 12 }}>
            {ev.expected != null && (
              <span>
                <Typography.Text type="secondary">expected</Typography.Text> <code>{ev.expected}</code>
              </span>
            )}
            {ev.actual != null && (
              <span style={{ marginLeft: 12 }}>
                <Typography.Text type="secondary">Actual</Typography.Text> <code style={ok ? undefined : { color: "#cf1322" }}>{ev.actual}</code>
              </span>
            )}
          </div>
        )}
        {!ok && ev.explain && (
          <div style={{ marginLeft: 22 }}>
            <Typography.Text type="danger">{ev.explain}</Typography.Text>
          </div>
        )}
      </div>
    );
  }
  return (
    <div data-testid="report-error">
      <Tag color="red">{ev.name || "Error"}</Tag>
      <Typography.Text type="danger">{ev.message}</Typography.Text>
    </div>
  );
}

function StepBody({ step }: { step: ReportStep }) {
  if (!step.events.length) return <Typography.Text type="secondary">No request, action or assertion recorded for this step</Typography.Text>;
  return (
    <Space orientation="vertical" size={6} style={{ width: "100%" }}>
      {step.events.map((ev) => (
        <EventLine key={ev.seq} ev={ev} />
      ))}
    </Space>
  );
}

/** Readable report of a pytest execution: steps (requests/actions/assertions), test data, error explanation */
export function RunReport({ report, testData, raw }: { report: Report; testData?: Record<string, unknown> | null; raw?: string | null }) {
  if (!report.tests.length) return <Empty description="The script collected no test functions" />;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={16} data-testid="run-report">
      {report.tests.map((t) => {
        const failedStep = t.steps.findIndex((s) => s.status === "failed");
        return (
          <div key={t.name}>
            {t.failure?.explain && (
              <Alert type={t.outcome === "failed" ? "error" : "warning"} showIcon style={{ marginBottom: 12 }} title={t.outcome === "failed" ? "Assertion failed" : "Execution error"} description={t.failure.explain} />
            )}
            <Descriptions size="small" column={4} style={{ marginBottom: 8 }}>
              <Descriptions.Item label="Result">{t.outcome === "passed" ? <Tag color="green">Passed</Tag> : t.outcome === "failed" ? <Tag color="red">Failed</Tag> : <Tag color="orange">Error</Tag>}</Descriptions.Item>
              <Descriptions.Item label="Assertion">{`${t.checks.total - t.checks.failed}/${t.checks.total} passed`}</Descriptions.Item>
              <Descriptions.Item label="API request">{t.requests}</Descriptions.Item>
              <Descriptions.Item label="Duration">{(t.duration_ms / 1000).toFixed(2)} s</Descriptions.Item>
            </Descriptions>
            {t.steps.length ? (
              <Steps
                orientation="vertical"
                size="small"
                current={failedStep >= 0 ? failedStep : t.steps.length}
                status={failedStep >= 0 ? "error" : "finish"}
                items={t.steps.map((s, i) => ({
                  key: i,
                  title: (
                    <Space size={6}>
                      <span>{s.name}</span>
                      {s.checks ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>{`${s.checks} assertion(s)`}</Typography.Text> : null}
                      {s.ms != null && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{s.ms} ms</Typography.Text>}
                    </Space>
                  ),
                  status: s.status === "failed" ? "error" : "finish",
                  content: <StepBody step={s} />,
                }))}
              />
            ) : (
              <Empty description="No steps recorded" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            {t.steps.length > 0 && t.steps.every((s) => s.source !== "step") && (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                Step names come from script comments; after running “AI automation” again, scripts name steps and assertions with step()/check().
              </Typography.Paragraph>
            )}
            <DataUsed test={t} testData={testData} />
          </div>
        );
      })}
      {raw && (
        <Collapse
          size="small"
          items={[
            {
              key: "raw",
              label: "Raw output (pytest)",
              children: <pre style={{ margin: 0, maxHeight: 360, overflow: "auto", fontSize: 12, whiteSpace: "pre-wrap" }}>{raw}</pre>,
            },
          ]}
        />
      )}
    </Space>
  );
}

function DataUsed({ test, testData }: { test: Report["tests"][number]; testData?: Record<string, unknown> | null }) {
  const keys = test.data_keys || [];
  if (!keys.length) return null;
  return (
    <div data-testid="report-data">
      <Typography.Text type="secondary">Test data read by the script: </Typography.Text>
      {keys.map((k) => {
        const has = testData ? k in testData : test.data_used ? k in test.data_used : false;
        const value = testData?.[k] ?? test.data_used?.[k];
        return (
          <Tag key={k} color={has ? "blue" : "default"}>
            {has ? `${k} = ${JSON.stringify(value)}` : `${k} (not provided, script defaults used)`}
          </Tag>
        );
      })}
    </div>
  );
}

/** Old pytest executions without a report: hide warnings noise, keep the summary line. */
export function summarizeRawOutput(raw: string): { summary: string; body: string } {
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  const summary = [...lines].reverse().find((l) => /\d+ (passed|failed|error)/.test(l)) || "";
  const start = lines.findIndex((l) => /warnings summary/.test(l));
  const end = lines.findIndex((l, i) => i > start && /^-- Docs:/.test(l));
  const kept = start >= 0 ? [...lines.slice(0, start), ...lines.slice(end >= 0 ? end + 1 : lines.length)] : lines;
  return { summary: summary.replace(/=+/g, "").trim(), body: kept.join("\n").trim() };
}
