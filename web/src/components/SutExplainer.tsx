import { Alert, Typography } from "antd";

import { PathText } from "./ObjLink";

/** Plain-language explanation of what a SUT is. */
export function SutExplainer({ repoPath, closable }: { repoPath?: string | null; closable?: boolean }) {
  return (
    <Alert
      type="info"
      showIcon
      closable={closable}
      style={{ marginBottom: 16 }}
      title="什么是“被测系统”？"
      description={
        <div data-testid="sut-explainer">
          <Typography.Paragraph style={{ marginBottom: 4 }}>
            被测系统（SUT）是你要测试的软件（例如“采购审批”）。平台的全部测试工作都围绕它组织：
          </Typography.Paragraph>
          <ul style={{ margin: 0, paddingInlineStart: 20 }}>
            <li>
              <b>环境</b>：被测系统的地址（例如 http://127.0.0.1:8766），可选配置启动命令；平台在执行前会检查其是否可达。
            </li>
            <li>
              <b>模型</b>：系统中有哪些业务对象（实体，例如 PurchaseOrder）、可以做什么（动作，例如 Approve purchase order）以及对象如何关联（例如 PurchaseOrder belongs to Supplier）。AI
              会基于模型生成用例和自动化脚本，因此需要由人评审（见“模型评审”）。
            </li>
            <li>
              <b>版本</b>：每次要测的一批需求。需求确认并冻结后，再创建测试策略和任务，生成并执行用例，然后查看缺陷和报告。
            </li>
            <li>
              <b>本地测试仓库</b>：AI 编写的自动化脚本存放在本机的 git 仓库中
              {repoPath ? (
                <>
                  : <PathText path={repoPath} />
                </>
              ) : (
                "（每个被测系统一个；路径在被测系统概览页）"
              )}
              . 
            </li>
          </ul>
        </div>
      }
    />
  );
}
