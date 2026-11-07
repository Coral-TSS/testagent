import { ListSection } from "./ListView";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Collapse, Descriptions, Drawer, Empty, Space, Tag, Timeline, Typography } from "antd";

import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AgentRun, AgentStep, RefLabel } from "../api/types";
import { RunStatusTag } from "./StatusTags";
import { toolLabel, withLabels } from "./agentLabels";
import { fmtTime } from "../utils/time";

const ACTIVE = new Set(["queued", "running"]);
export const PURPOSE: Record<string, string> = {
  structure_requirement: "Requirement structuring",
  complete_model: "Model completion",
  generate_strategy: "Strategy generation",
  generate_cases: "Case generation",
  complete_case: "Case AI completion",
  automate_case: "Case automation",
  execute_case_browser: "Browser execution",
  execute_case_api: "API execution",
  analyze_failure: "Failure analysis",
  summarize_report: "Report summary",
  digest_correction: "Correction processing",
};

function json(value: unknown, labels?: Record<string, string>) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: 12, maxHeight: 280, overflow: "auto" }}>
      {withLabels(text ?? "", labels)}
    </pre>
  );
}

export function StepItem({ step, labels }: { step: AgentStep & { resolved_args?: unknown }; labels?: Record<string, string> }) {
  if (step.type === "model") {
    return (
      <>
        <Tag color="blue">Model #{step.seq}</Tag>
        {step.ms !== undefined && <Typography.Text type="secondary">{step.ms} ms</Typography.Text>}
        {step.content && <div style={{ marginTop: 4 }}>{withLabels(step.content, labels)}</div>}
        {step.tool_calls?.map((c, i) => (
          <div key={i}>
            → call <code>{toolLabel(c.name)}</code>
          </div>
        ))}
      </>
    );
  }
  if (step.type === "tool") {
    return (
      <>
        <Tag color={step.status === "ok" ? "green" : "red"}>{toolLabel(step.tool)}</Tag>
        {step.ms !== undefined && <Typography.Text type="secondary">{step.ms} ms</Typography.Text>}
        <Collapse
          size="small"
          ghost
          items={[
            { key: "a", label: "Parameter", children: json(step.args, labels) },
            ...(step.resolved_args
              ? [{ key: "x", label: "Actual arguments (resolved against the current system/codes)", children: json(step.resolved_args, labels) }]
              : []),
            { key: "r", label: "Result", children: json(step.result, labels) },
          ]}
        />
      </>
    );
  }
  if (step.type === "submit_invalid") {
    return (
      <>
        <Tag color="orange">Submission check failed</Tag>
        <ul style={{ margin: 0 }}>
          {step.errors?.map((e, i) => (
            <li key={i}>
              <code>{e.loc}</code> {withLabels(e.msg, labels)}
            </li>
          ))}
        </ul>
      </>
    );
  }
  if (step.type === "submit") {
    return (
      <>
        <Tag color="green">Submission result</Tag>
        <Collapse size="small" ghost items={[{ key: "r", label: "Result", children: json(step.result, labels) }]} />
      </>
    );
  }
  return (
    <>
      <Tag>{step.type}</Tag>
      {json(step, labels)}
    </>
  );
}

/** “Case Title (TC-001)” links for what a run / log line was about */
export function RefLinks({ refs, max }: { refs?: RefLabel[]; max?: number }) {
  if (!refs?.length) return <Typography.Text type="secondary">-</Typography.Text>;
  const shown = max ? refs.slice(0, max) : refs;
  return (
    <Space size={[4, 4]} wrap>
      {shown.map((r) => (
        <Tag key={r.id} style={{ marginInlineEnd: 0 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.kind}{" "}
          </Typography.Text>
          <Link to={r.path} onClick={(e) => e.stopPropagation()}>
            {r.label}
          </Link>
        </Tag>
      ))}
      {max && refs.length > max ? <Typography.Text type="secondary">+{refs.length - max}</Typography.Text> : null}
    </Space>
  );
}

/** Agent run trace: step timeline (refreshes every 1.5 s while running), cancellable */
export function AgentRunDrawer({ runId, onClose }: { runId: string | null; onClose: () => void }) {
  const run = useQuery({
    queryKey: ["agent-run", runId],
    queryFn: () => api<AgentRun>(`/agent/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 1500 : false),
  });
  const cancel = useApiMutation(() => api(`/agent/runs/${runId}/cancel`, { method: "POST" }), {
    invalidate: [["agent-run", runId]],
    success: "Cancellation requested",
  });
  const r = run.data;
  return (
    <Drawer open={Boolean(runId)} onClose={onClose} size={640} title="Agent run trace">
      {r && (
        <>
          <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="Purpose">{PURPOSE[r.purpose] || r.purpose}</Descriptions.Item>
            <Descriptions.Item label="object" span={2}>
              <RefLinks refs={r.subjects} />
            </Descriptions.Item>
            <Descriptions.Item label="Status">
              <Space>
                <RunStatusTag status={r.status} />
                {ACTIVE.has(r.status) && (
                  <Button size="small" danger disabled={r.cancel_requested} onClick={() => cancel.mutate()}>
                    {r.cancel_requested ? "Cancelling" : "Cancel"}
                  </Button>
                )}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="Start">{fmtTime(r.started_at, { seconds: true })}</Descriptions.Item>
            <Descriptions.Item label="End">{fmtTime(r.ended_at, { seconds: true })}</Descriptions.Item>
            <Descriptions.Item label="Injected prompts">
              {[r.injected?.template, r.injected?.entry_template]
                .filter(Boolean)
                .map((t) => `${t!.name} v${t!.version}`)
                .join(", ") || "Built-in default"}
            </Descriptions.Item>
            <Descriptions.Item label="Injected memories">
              {r.injected?.memory_ids?.length ? <Link to="/agent/tools?tab=memories">{r.injected.memory_ids.length} item(s)</Link> : "None"}
            </Descriptions.Item>
            <Descriptions.Item label="Run ID">
              <Typography.Text copyable style={{ fontSize: 12 }}>
                {r.id}
              </Typography.Text>
            </Descriptions.Item>
          </Descriptions>
          {r.error_code && <Alert type="error" showIcon style={{ marginBottom: 16 }} title={r.error_code} description={r.error} />}
        </>
      )}
      <ListSection label="Agent trace steps" count={r?.steps.length} error={run.isError} onRetry={() => run.refetch()}>
        {r?.steps.length ? <Timeline items={r.steps.map((s, i) => ({ key: i, content: <StepItem step={s} labels={r.labels} /> }))} /> : <Empty description="No steps yet" />}
      </ListSection>
    </Drawer>
  );
}
