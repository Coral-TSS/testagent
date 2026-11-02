import { CheckCircleFilled, ClockCircleOutlined, MinusCircleOutlined } from "@ant-design/icons";
import { Button, List, Space, Tag, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import type { StepStatus, SutProgress } from "../api/types";

const ICON: Record<StepStatus, React.ReactNode> = {
  done: <CheckCircleFilled style={{ color: "#52c41a" }} />,
  doing: <ClockCircleOutlined style={{ color: "#1677ff" }} />,
  todo: <MinusCircleOutlined style={{ color: "#bfbfbf" }} />,
};
const TEXT: Record<StepStatus, string> = { done: "Done", doing: "In progress", todo: "Not started" };
const WHY: Record<string, string> = {
  sut: "Register the SUT's address (environment); the platform checks it is reachable before running",
  model: "Describe business objects, actions and links; the AI generates cases and scripts from it. Check each item in “Model review” when done",
  requirements: "Create a version, enter and confirm requirements, then freeze them (creates a model snapshot)",
  strategy: "Decide the test scope, types and depth",
  tasks: "Group cases into tasks, choose the executor and environment, optionally scheduled",
  cases: "Generate cases by AI or by hand; a person reviews and sets them ready; the AI can generate automation scripts",
  runs: "Run tasks and look at each case's result, screenshots and assertions",
  results: "Handle defects from failures (assigned to requirements, attributed to people) and read the reports",
};

/** Onboarding checklist of the main flow with one action per step. */
export function OnboardingChecklist({ progress }: { progress: SutProgress }) {
  const navigate = useNavigate();
  return (
    <List
      size="small"
      data-testid="onboarding"
      dataSource={progress.steps}
      renderItem={(s, i) => (
        <List.Item
          actions={[
            s.action ? (
              <Button key="a" size="small" type={progress.next?.key === s.key ? "primary" : "default"} onClick={() => navigate(s.action!.path)}>
                {s.action.label}
              </Button>
            ) : (
              <Button key="o" size="small" type="link" onClick={() => navigate(s.path)}>
                View
              </Button>
            ),
          ]}
        >
          <Space align="start">
            {ICON[s.status]}
            <div>
              <Space>
                <Typography.Text strong>{`${i + 1}. ${s.title}`}</Typography.Text>
                <Tag>{TEXT[s.status]}</Tag>
                <Typography.Text type="secondary">{s.summary}</Typography.Text>
              </Space>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {WHY[s.key]}
                </Typography.Text>
              </div>
            </div>
          </Space>
        </List.Item>
      )}
    />
  );
}
