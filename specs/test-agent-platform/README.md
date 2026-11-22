# TestAgent 规格与设计 · v1.2 维护基线

更新：2026-11-09。审查代码基线：`f8eb3618acfcbed4f54915e03e43db01bbd3e2a8`（develop）；当日已核对 GitHub develop 与本地一致。文档版本 v1.2 不代表新的软件发布版本。

TestAgent 是测试平台与 Agent 的结合：人指导和审阅测试设计，AI 起草需求结构、策略、用例和脚本，平台负责状态、执行证据和追溯。自带演示被测系统是供应链执行（`supply-chain`），说明见仓库 [docs/demo-supply-chain.md](../../docs/demo-supply-chain.md)。

## 阅读入口

| 文档 | 用途 |
|---|---|
| [review-2026-11-09.md](review-2026-11-09.md) | 本轮审查结论、18 项反馈状态、事实与证据边界 |
| [spec.md](spec.md) | 产品需求、保留的决策编号、当前验收约束 |
| [plan.md](plan.md) | 下一阶段顺序、依赖和完成定义 |
| [tasks.md](tasks.md) | 当前可执行任务及历史任务要求 |
| [task-status.md](task-status.md) | 原始 81 项任务逐项实现定位；不等于全部验收完成 |
| [design/architecture.md](design/architecture.md) | 当前代码架构、真实运行边界 |
| [design/detailed-design.md](design/detailed-design.md) | 运行、自检、任务关联、列表和抽屉的详细契约 |
| [design/test-design.md](design/test-design.md) | AC 与测试证据映射、待补验收场景 |

## 唯一维护入口

- 代码和这些文档的主线均为 `D:\CodeWork\TestAgent\release\testagent`，分支 `develop`。规格位于仓库内 `specs/test-agent-platform/`，随代码提交。
- 原 `D:\CodeWork\TestAgent\specs\test-agent-platform/` 保留相同内容的本地查阅镜像；先改仓库版本，再按文件同步并核对摘要，不分别编辑两套。
- `ontology-test-platform/` 是历史开发仓；`sources/` 与 `archive/` 为只读参考。PRD 保持在顶层 `docs/prd/TestAgentPRD.docx`，不随本轮上传。
- 旧提案保留决策背景；带“历史”标记的段落、工期和待确认问题不再作为当前待办。当前状态以本目录的审查、任务及证据为准。

## 当前判断

主链路已有实现和自动化回归；账号基础、结果可信度和 DEMO-FIX-001…008 已落地。尚不能宣布 M1 全量签收或团队版完成：真实模型复验、逐条 AC 验收、性能/覆盖率测量、并发编辑与按系统授权等仍有缺口。

最近已记录的回归是 2026-11-07 的 478 项后端通过、1 项 Windows 不适用跳过，以及 167 项前端通过、最终构建 3 项 E2E 通过。本轮维护只审查文档和源码，不把这些数字描述成 11 月 9 日重新运行的结果。
