# 验收与测试设计 v1.2

2026-11-09；基线f8eb361。本轮为证据索引和补测设计，不新造运行结果。下面相对路径均以仓库根为准；测试文件存在只能证明验证入口，不能代替实际运行及AC数值断言核签。

## 1 AC证据入口

| AC | 能力 | 当前测试入口 | 验收状态/缺口 |
|---|---|---|---|
| 01 | SUT/环境持久化 | tests/api/test_registry_api.py；tests/e2e/test_launch_e2e.py | 有自动化入口，持久化/重启条款逐条核签 |
| 02 | 实体/动作/ModelLink图 | tests/api/test_model_api.py；tests/api/test_links_api.py | 需按修订后数量和关系类型签收；M:N覆盖另补 |
| 03 | 动作/API/代码位置 | tests/api/test_model_api.py；tests/api/test_io_specs_api.py | 有自动化入口 |
| 04 | 需求责任人 | tests/api/test_requirements_api.py | 有自动化入口 |
| 05 | 结构化及关联 | tests/api/test_requirements_api.py | 假模型验证，真实输出质量待复验 |
| 06 | 建议采纳/拒绝 | tests/api/test_suggestion_trust_api.py；tests/api/test_requirements_api.py | 来源/去重有验证；撤销/补建是后续需求 |
| 07 | 确认/冻结/快照 | tests/api/test_requirements_api.py；tests/db/test_db_foundation.py | 有自动化入口 |
| 08 | 策略与规则任务 | tests/api/test_strategy_tasks_api.py；tests/api/test_task_binding_api.py | 假模型验证 |
| 09 | 用例数量/覆盖 | tests/api/test_cases_api.py；tests/api/test_readable_runs_api.py | 原3需求≥9用例等数值须逐条核签；M:N缺口保留 |
| 10 | 任务引用用例 | tests/api/test_task_binding_api.py；tests/api/test_ready_task_feedback_api.py | 有规则/人工优先/反馈证据 |
| 11 | 浏览器执行 | tests/integrations/test_browser_tools.py；tests/api/test_executions_api.py | 真实浏览器+受控模型，不代表官方Test Agents集成 |
| 12 | 生成脚本/Git/调试 | tests/integrations/test_repo_and_pytest.py；tests/integrations/test_execution_snapshot.py | 固定提交验证；真实生成质量待复验 |
| 13 | 任务/取消/调度 | tests/api/test_runs_api.py；tests/api/test_task_latest_run_api.py | 有自动化入口；5用例/cron条款核签 |
| 14 | 人工结果 | tests/api/test_executions_api.py | 数据/附件等完整条款核签 |
| 15 | 缺陷与归因 | tests/api/test_defects_api.py | 有自动化入口；AI最终原因不可替人决定 |
| 16 | 任务/版本报告 | tests/api/test_stats_reports_api.py；tests/api/test_runs_api.py | 零执行已有证据；编排error报告范围待核验 |
| 17 | 人员统计 | tests/api/test_stats_reports_api.py | 统计口径有验证；完整筛选/下钻核签 |
| 18 | 纠错与生效 | tests/api/test_learning_api.py；tests/e2e/test_main_chain.py | 假模型闭环；非长期学习质量证明 |
| 19 | 模型配置 | tests/agent/test_agent_runtime.py；tests/agent/test_prompt_language.py | 脱敏与未配置行为有测试；真实模型本轮未调 |
| 20 | 登录/启动 | tests/api/test_accounts_api.py；tests/api/test_auth_api.py；tests/e2e/test_launch_e2e.py | 账号会话/ticket替代token验收 |

## 2 已验证维护行为

DEMO-FIX-001…008证据在docs/development/demo-fixes.md及各verification.json。重点保持：零执行不通过、固定代码版本、当前步键盘跳转、最近运行与刷新失败、Ready关联事件失败、跨系统范围先于LIMIT、分页身份不串行、打印第51/65行、鼠标与键盘抽屉调整、取消/禁用存储/未保存文本。

最近完整记录为2026-11-07：478后端通过、1跳过；167前端通过；最终构建另跑3项E2E通过。E2E包含在全量后端中，不重复加总。本轮只做文档一致性与源码审查，没有重跑这些测试。

## 3 待开发功能的失败场景

| 设计用例ID | 对应任务 | 输入/操作 | 期望 |
|---|---|---|---|
| NEW-01 | UX-009 | 采纳实体建议后打开结构化需求，再改显示名称 | 人类名称同步可读，绑定ID/API字段不变 |
| NEW-02 | UX-009 | 空显示名、已删除引用、跨系统同名 | 明确回退/失效提示，不误指另一对象 |
| NEW-03 | UX-010 | 300字中英标题、窄窗、键盘操作 | 标题可读全文；主操作不被挤出；更多菜单可达 |
| NEW-04 | MODEL-013 | 拒绝→恢复，已有同名待审或已采纳项 | 恢复不直接写模型，重复项明确处理 |
| NEW-05 | MODEL-013 | missing一键补建双击/超时重试 | 节点和需求关联整体成功或整体回滚，无重复孤儿 |
| NEW-06 | MODEL-013 | 冻结需求、跨系统节点、字段已删除 | 拒绝不允许的变更并给出恢复路径 |
| NEW-07 | MODEL-014 | 仅一端/两端via字段、经需求关系引用 | 按已批准覆盖规则计算，三个视图一致，不过度声称业务规则覆盖 |
| NEW-08 | FLOW-011/NAV-015 | 无版本/无用例/Ready未同步；浏览器后退刷新 | 下一步明确，保留系统版本范围，不隐式启动任务 |
| NEW-09 | TEAM-019 | 两会话同时编辑同一修订 | 后保存者看到冲突，不静默覆盖 |
| NEW-10 | QA-016 | 无环境/预检失败/重启中断/生成报告失败 | 运行事实与错误可查，明确是否产出报告及补救途径 |

以上为设计用例，尚未实现和执行。实现时先建立失败测试，再修复；不要把“测试设计完成”写成“测试通过”。

## 4 NFR与真实模型验收

- NFR-03：构造500节点/2000用例/5000执行记录，记录设备/数据库/构建、请求范围、样本数及冷/热缓存p95；阈值仍为≤1秒。前端分页与后端LIMIT不能代替性能测量。
- NFR-08：明确service目录覆盖口径，收集覆盖报告并核对≥80%；测试数量和FakeChatModel覆盖不代表这个比例。本轮未找到测量证据。
- 恢复：进程重启后遗留作业error/INTERRUPTED不自动重放；图checkpointer测试不保证外部副作用幂等。
- 真实模型：固定代码SHA/提示词版本/样例重置状态，记录生成数、Ready数、脚本绑定/需修复/疑似系统问题数、执行结果、建议采纳/拒绝、人工干预和找到X/3；未知项保留未知，区分自检发现与正式执行发现。不在公开文档补写未公开的预埋缺陷答案。
- 部署：另行记录服务器实际SHA、迁移、登录、启动/取消、制品访问、备份恢复；GitHub推送不能代替部署验收。
