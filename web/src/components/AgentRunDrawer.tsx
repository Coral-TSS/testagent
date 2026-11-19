import { ReadingDrawer } from "./ReadingDrawer";
import { ListSection } from "./ListView";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Collapse, Descriptions, Empty, Space, Tag, Timeline, Typography } from "antd";

import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AgentRun, AgentStep, RefLabel } from "../api/types";
import { RunStatusTag } from "./StatusTags";
import { toolLabel, withLabels } from "./agentLabels";
import { fmtTime } from "../utils/time";

const ACTIVE = new Set(["queued", "running"]);
export const PURPOSE: Record<string, string> = {
  structure_requirement: "需求结构化",
  complete_model: "模型补全",
  generate_strategy: "策略生成",
  generate_cases: "用例生成",
  complete_case: "用例 AI 补全",
  automate_case: "用例自动化",
  execute_case_browser: "浏览器执行",
  execute_case_api: "API 执行",
  analyze_failure: "失败分析",
  summarize_report: "报告摘要",
  digest_correction: "纠正处理",
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
            { key: "a", label: "参数", children: json(step.args, labels) },
            ...(step.resolved_args
              ? [{ key: "x", label: "实际参数（已按当前系统/编号解析）", children: json(step.resolved_args, labels) }]
              : []),
            { key: "r", label: "结果", children: json(step.result, labels) },
          ]}
        />
      </>
    );
  }
  if (step.type === "submit_invalid") {
    return (
      <>
        <Tag color="orange">提交校验失败</Tag>
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
        <Tag color="green">提交结果</Tag>
        <Collapse size="small" ghost items={[{ key: "r", label: "结果", children: json(step.result, labels) }]} />
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
    success: "已请求取消",
  });
  const r = run.data;
  return (
    <ReadingDrawer kind="agent" open={Boolean(runId)} onClose={onClose} title="Agent 运行追踪">
      {r && (
        <>
          <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="用途">{PURPOSE[r.purpose] || r.purpose}</Descriptions.Item>
            <Descriptions.Item label="对象" span={2}>
              <RefLinks refs={r.subjects} />
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Space>
                <RunStatusTag status={r.status} />
                {ACTIVE.has(r.status) && (
                  <Button size="small" danger disabled={r.cancel_requested} onClick={() => cancel.mutate()}>
                    {r.cancel_requested ? "正在取消" : "取消"}
                  </Button>
                )}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="开始">{fmtTime(r.started_at, { seconds: true })}</Descriptions.Item>
            <Descriptions.Item label="结束">{fmtTime(r.ended_at, { seconds: true })}</Descriptions.Item>
            <Descriptions.Item label="已注入的提示词">
              {[r.injected?.template, r.injected?.entry_template]
                .filter(Boolean)
                .map((t) => `${t!.name} v${t!.version}`)
                .join(", ") || "内置默认"}
            </Descriptions.Item>
            <Descriptions.Item label="已注入的记忆">
              {r.injected?.memory_ids?.length ? <Link to="/agent/tools?tab=memories">{r.injected.memory_ids.length} 项</Link> : "无"}
            </Descriptions.Item>
            <Descriptions.Item label="执行 ID">
              <Typography.Text copyable style={{ fontSize: 12 }}>
                {r.id}
              </Typography.Text>
            </Descriptions.Item>
          </Descriptions>
          {r.error_code && <Alert type="error" showIcon style={{ marginBottom: 16 }} title={r.error_code} description={r.error} />}
        </>
      )}
      <ListSection label="Agent 追踪步骤" count={r?.steps.length} error={run.isError} onRetry={() => run.refetch()}>
        {r?.steps.length ? <Timeline items={r.steps.map((s, i) => ({ key: i, content: <StepItem step={s} labels={r.labels} /> }))} /> : <Empty description="暂无步骤" />}
      </ListSection>
    </ReadingDrawer>
  );
}
