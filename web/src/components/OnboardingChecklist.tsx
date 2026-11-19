import { CheckCircleFilled, ClockCircleOutlined, MinusCircleOutlined } from "@ant-design/icons";
import { Button, List, Space, Tag, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import type { StepStatus, SutProgress } from "../api/types";

const ICON: Record<StepStatus, React.ReactNode> = {
  done: <CheckCircleFilled style={{ color: "#52c41a" }} />,
  doing: <ClockCircleOutlined style={{ color: "#1677ff" }} />,
  todo: <MinusCircleOutlined style={{ color: "#bfbfbf" }} />,
};
const TEXT: Record<StepStatus, string> = { done: "已完成", doing: "进行中", todo: "未开始" };
const WHY: Record<string, string> = {
  sut: "登记被测系统的地址（环境）；平台在执行前会检查其是否可达",
  model: "描述业务对象、动作和关系；AI 据此生成用例和脚本。完成后请在“模型评审”中逐项检查",
  requirements: "创建版本，录入并确认需求，然后冻结（会生成模型快照）",
  strategy: "确定测试范围、类型和深度",
  tasks: "把用例编成任务，选择执行器和环境，必要时设置调度",
  cases: "用 AI 或手工生成用例；由人评审并设为就绪；AI 可以生成自动化脚本",
  runs: "执行任务，并查看每个用例的结果、截图和断言",
  results: "处理失败产生的缺陷（关联到需求、归因到人员）并阅读报告",
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
                查看
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
