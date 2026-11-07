import { ArrowRightOutlined } from "@ant-design/icons";
import { Button, Space, Steps, Tooltip, Typography } from "antd";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import type { StepStatus, SutProgress } from "../api/types";
import { RunTasksModal } from "./RunTasksModal";

const STATUS: Record<StepStatus, "finish" | "process" | "wait"> = { done: "finish", doing: "process", todo: "wait" };

/** The SUT main flow (SUT → model → version/requirements → strategy → tasks → cases → execution → defects/reports), clickable. */
export function FlowSteps({ progress, compact }: { progress: SutProgress; compact?: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [runTasks, setRunTasks] = useState<string | null>(null);
  const next = progress.next;
  /** "Run tasks" opens the batch-run dialog in place; going to the page you are on scrolls to its target. */
  const go = () => {
    if (!next) return;
    if (next.kind === "run_tasks" && next.version_id) {
      setRunTasks(next.version_id);
      return;
    }
    if (location.pathname + location.search === next.path) {
      const el = document.getElementById("strategy-tasks") || document.querySelector("main");
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    navigate(next.path);
  };
  const current = Math.max(
    0,
    progress.steps.findIndex((s) => s.key === progress.next?.key),
  );
  return (
    <div data-testid="flow-steps" style={{ display: "flex", alignItems: "center", gap: 16 }}>
      {runTasks && <RunTasksModal open versionId={runTasks} onClose={() => setRunTasks(null)} />}
      <Steps
        size="small"
        style={{ flex: 1 }}
        current={progress.next ? current : progress.steps.length}
        onChange={(i) => navigate(progress.steps[i].path)}
        items={progress.steps.map((s, i) => ({
          title: <span style={{ whiteSpace: "nowrap" }}>{s.title}</span>,
          status: STATUS[s.status],
          // Steps suppresses onChange for the current item; it still links to its page.
          onClick: progress.next && i === current ? () => navigate(s.path) : undefined,
          content: compact ? undefined : (
            <Tooltip title={s.summary}>
              <Typography.Text type="secondary" style={{ fontSize: 12, maxWidth: 140 }} ellipsis>
                {s.summary}
              </Typography.Text>
            </Tooltip>
          ),
        }))}
      />
      {progress.next ? (
        <Space orientation="vertical" size={0} style={{ minWidth: 150, flexShrink: 0 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Next
          </Typography.Text>
          <Button type="primary" size="small" icon={<ArrowRightOutlined />} onClick={go}>
            {progress.next.label}
          </Button>
        </Space>
      ) : (
        <Typography.Text type="success" style={{ whiteSpace: "nowrap", flexShrink: 0 }}>
          Main flow complete
        </Typography.Text>
      )}
    </div>
  );
}
