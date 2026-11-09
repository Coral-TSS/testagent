# 原始任务实现定位（81项）

2026-11-09；f8eb361。81项来自tasks.md的T-00.1…T-12.5，不含3项历史目录整理及后续B/T批次。下表逐项保留编号；“实现已定位”只表示源码与相关测试可定位，并非每条历史参考测试名都存在、每项AC已签收。替代项按新决策验收；部分项留在当前队列。不要把此表转成“81/81完成”。

源代码缩写core/agent/services/integrations均相对src/testagent；其余路径相对仓库根。相关测试列是工作包入口，完整AC对应关系见design/test-design.md。

| 原任务 | 状态 | 实现入口 | 相关测试入口 | 验收说明 |
|---|---|---|---|---|
| T-00.1 | 实现已定位 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-00.2 | 实现已定位 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-00.3 | 实现已定位 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-00.4 | 实现已定位 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-00.5 | 部分验收 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 库隔离/拒连保护有测试；原要求独立子进程证明session结束删除schema须QA-016逐条核签 |
| T-00.6 | 实现已定位 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-00.7 | 实现已定位 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-00.8 | 实现已定位 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-00.9 | 替代 | core/config.py、db.py、migrations.py；ops/init_db.py；web/package.json | tests/db/test_db_foundation.py；tests/unit/test_core_units.py | 原reports/progress.md不在发布仓；由本目录task-status及docs/development验证记录承接 |
| T-01.1 | 替代 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 全部结构由0001–0024逐步迁移，不要求全部挤进0001 |
| T-01.2 | 实现已定位 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-01.3 | 替代 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 共享token方案被0022账号会话/本机ticket替代 |
| T-01.4 | 部分实现 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 事件总线可用，StageRegistry仍是骨架，默认阶段未接入生产主链 |
| T-01.5 | 实现已定位 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-01.6 | 实现已定位 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-01.7 | 实现已定位 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-01.8 | 实现已定位 | core/auth.py、events.py、artifacts.py、secrets.py；services/state.py、registry.py | tests/api/test_accounts_api.py；tests/api/test_registry_api.py；tests/unit/test_state.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-02.1 | 替代 | web/src/app；web/src/api/schema.d.ts；web/src/pages | tests/e2e/test_launch_e2e.py；web/src/app/AuthGate.test.tsx | 共享token前端被账号会话、登录页、一次性ticket替代 |
| T-02.2 | 实现已定位 | web/src/app；web/src/api/schema.d.ts；web/src/pages | tests/e2e/test_launch_e2e.py；web/src/app/AuthGate.test.tsx | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-02.3 | 实现已定位 | web/src/app；web/src/api/schema.d.ts；web/src/pages | tests/e2e/test_launch_e2e.py；web/src/app/AuthGate.test.tsx | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-02.4 | 实现已定位 | web/src/app；web/src/api/schema.d.ts；web/src/pages | tests/e2e/test_launch_e2e.py；web/src/app/AuthGate.test.tsx | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-03.1 | 替代 | services/model.py、links.py、apis.py；seed.py | tests/api/test_model_api.py；tests/api/test_links_api.py | D24以ModelLink替代relation节点要求；字段/关系校验已有实现 |
| T-03.2 | 实现已定位 | services/model.py、links.py、apis.py；seed.py | tests/api/test_model_api.py；tests/api/test_links_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-03.3 | 实现已定位 | services/model.py、links.py、apis.py；seed.py | tests/api/test_model_api.py；tests/api/test_links_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-03.4 | 实现已定位 | services/model.py、links.py、apis.py；seed.py | tests/api/test_model_api.py；tests/api/test_links_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-03.5 | 实现已定位 | services/model.py、links.py、apis.py；seed.py | tests/api/test_model_api.py；tests/api/test_links_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-03.6 | 部分验收 | services/model.py、links.py、apis.py；seed.py | tests/api/test_model_api.py；tests/api/test_links_api.py | 种子存在；原节点数量及旧关系节点AC不能沿用，QA-016按修订AC-02验收 |
| T-04.1 | 实现已定位 | agent/runtime.py、config.py、tools.py、checkpoint.py、prompts.py | tests/agent/test_agent_runtime.py；tests/agent/test_jobs_checkpoint.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-04.2 | 实现已定位 | agent/runtime.py、config.py、tools.py、checkpoint.py、prompts.py | tests/agent/test_agent_runtime.py；tests/agent/test_jobs_checkpoint.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-04.3 | 实现已定位 | agent/runtime.py、config.py、tools.py、checkpoint.py、prompts.py | tests/agent/test_agent_runtime.py；tests/agent/test_jobs_checkpoint.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-04.4 | 实现已定位 | agent/runtime.py、config.py、tools.py、checkpoint.py、prompts.py | tests/agent/test_agent_runtime.py；tests/agent/test_jobs_checkpoint.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-04.5 | 实现已定位 | agent/runtime.py、config.py、tools.py、checkpoint.py、prompts.py | tests/agent/test_agent_runtime.py；tests/agent/test_jobs_checkpoint.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-04.6 | 实现已定位 | agent/runtime.py、config.py、tools.py、checkpoint.py、prompts.py | tests/agent/test_agent_runtime.py；tests/agent/test_jobs_checkpoint.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-04.7 | 实现已定位 | agent/runtime.py、config.py、tools.py、checkpoint.py、prompts.py | tests/agent/test_agent_runtime.py；tests/agent/test_jobs_checkpoint.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-05.1 | 实现已定位 | services/versions.py、requirements.py、suggestions.py | tests/api/test_requirements_api.py；tests/api/test_suggestion_trust_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-05.2 | 实现已定位 | services/versions.py、requirements.py、suggestions.py | tests/api/test_requirements_api.py；tests/api/test_suggestion_trust_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-05.3 | 实现已定位 | services/versions.py、requirements.py、suggestions.py | tests/api/test_requirements_api.py；tests/api/test_suggestion_trust_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-05.4 | 实现已定位 | services/versions.py、requirements.py、suggestions.py | tests/api/test_requirements_api.py；tests/api/test_suggestion_trust_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-05.5 | 部分实现 | services/versions.py、requirements.py、suggestions.py | tests/api/test_requirements_api.py；tests/api/test_suggestion_trust_api.py | 采纳/拒绝/去重有实现；演示#8恢复与missing一键补建待MODEL-012/013 |
| T-05.6 | 实现已定位 | services/versions.py、requirements.py、suggestions.py | tests/api/test_requirements_api.py；tests/api/test_suggestion_trust_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-05.7 | 实现已定位 | services/versions.py、requirements.py、suggestions.py | tests/api/test_requirements_api.py；tests/api/test_suggestion_trust_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-06.1 | 实现已定位 | services/strategy.py、tasks.py、task_binding.py | tests/api/test_strategy_tasks_api.py；tests/api/test_task_binding_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-06.2 | 实现已定位 | services/strategy.py、tasks.py、task_binding.py | tests/api/test_strategy_tasks_api.py；tests/api/test_task_binding_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-06.3 | 实现已定位 | services/strategy.py、tasks.py、task_binding.py | tests/api/test_strategy_tasks_api.py；tests/api/test_task_binding_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-06.4 | 实现已定位 | services/strategy.py、tasks.py、task_binding.py | tests/api/test_strategy_tasks_api.py；tests/api/test_task_binding_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-07.1 | 实现已定位 | services/cases.py、case_gen.py；web/src/components/CaseList.tsx | tests/api/test_cases_api.py；tests/api/test_readable_runs_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-07.2 | 实现已定位 | services/cases.py、case_gen.py；web/src/components/CaseList.tsx | tests/api/test_cases_api.py；tests/api/test_readable_runs_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-07.3 | 部分实现 | services/cases.py、case_gen.py；web/src/components/CaseList.tsx | tests/api/test_cases_api.py；tests/api/test_readable_runs_api.py | 现有覆盖与明细有实现；M:N中间字段覆盖缺口见MODEL-014 |
| T-07.4 | 实现已定位 | services/cases.py、case_gen.py；web/src/components/CaseList.tsx | tests/api/test_cases_api.py；tests/api/test_readable_runs_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-07.5 | 实现已定位 | services/cases.py、case_gen.py；web/src/components/CaseList.tsx | tests/api/test_cases_api.py；tests/api/test_readable_runs_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.1 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.2 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.3 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.4 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.5 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.6 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.7 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.8 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-08.9 | 实现已定位 | services/executions.py、automation.py；integrations/git_repo.py、pytest_runner.py、browser.py | tests/api/test_executions_api.py；tests/integrations/test_execution_snapshot.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-09.1 | 实现已定位 | services/runs.py、run_progress.py、scheduler.py；core/worker.py | tests/api/test_runs_api.py；tests/api/test_task_latest_run_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-09.2 | 实现已定位 | services/runs.py、run_progress.py、scheduler.py；core/worker.py | tests/api/test_runs_api.py；tests/api/test_task_latest_run_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-09.3 | 实现已定位 | services/runs.py、run_progress.py、scheduler.py；core/worker.py | tests/api/test_runs_api.py；tests/api/test_task_latest_run_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-09.4 | 实现已定位 | services/runs.py、run_progress.py、scheduler.py；core/worker.py | tests/api/test_runs_api.py；tests/api/test_task_latest_run_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-09.5 | 实现已定位 | services/runs.py、run_progress.py、scheduler.py；core/worker.py | tests/api/test_runs_api.py；tests/api/test_task_latest_run_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-09.6 | 实现已定位 | services/runs.py、run_progress.py、scheduler.py；core/worker.py | tests/api/test_runs_api.py；tests/api/test_task_latest_run_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-10.1 | 实现已定位 | services/defects.py、attribution.py、failure_analysis.py | tests/api/test_defects_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-10.2 | 实现已定位 | services/defects.py、attribution.py、failure_analysis.py | tests/api/test_defects_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-10.3 | 实现已定位 | services/defects.py、attribution.py、failure_analysis.py | tests/api/test_defects_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-10.4 | 实现已定位 | services/defects.py、attribution.py、failure_analysis.py | tests/api/test_defects_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-10.5 | 实现已定位 | services/defects.py、attribution.py、failure_analysis.py | tests/api/test_defects_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-11.1 | 替代 | services/stats.py、reports.py | tests/api/test_stats_reports_api.py；tests/api/test_list_scopes_api.py | 实际stats.py查询/聚合复用；不以原计划两个SQL视图名称作为交付条件 |
| T-11.2 | 实现已定位 | services/stats.py、reports.py | tests/api/test_stats_reports_api.py；tests/api/test_list_scopes_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-11.3 | 部分验收 | services/stats.py、reports.py | tests/api/test_stats_reports_api.py；tests/api/test_list_scopes_api.py | 主要终态报告有实现；编排error的报告完整性纳入QA-016 |
| T-11.4 | 实现已定位 | services/stats.py、reports.py | tests/api/test_stats_reports_api.py；tests/api/test_list_scopes_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-11.5 | 实现已定位 | services/stats.py、reports.py | tests/api/test_stats_reports_api.py；tests/api/test_list_scopes_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-11.6 | 实现已定位 | services/stats.py、reports.py | tests/api/test_stats_reports_api.py；tests/api/test_list_scopes_api.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-12.1 | 实现已定位 | services/learning.py；web/src/pages/AgentToolsPage.tsx | tests/api/test_learning_api.py；tests/e2e/test_main_chain.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-12.2 | 实现已定位 | services/learning.py；web/src/pages/AgentToolsPage.tsx | tests/api/test_learning_api.py；tests/e2e/test_main_chain.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-12.3 | 实现已定位 | services/learning.py；web/src/pages/AgentToolsPage.tsx | tests/api/test_learning_api.py；tests/e2e/test_main_chain.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-12.4 | 实现已定位 | services/learning.py；web/src/pages/AgentToolsPage.tsx | tests/api/test_learning_api.py；tests/e2e/test_main_chain.py | 模块与对应测试存在；尚不据此逐条AC签收 |
| T-12.5 | 部分验收 | services/learning.py；web/src/pages/AgentToolsPage.tsx | tests/api/test_learning_api.py；tests/e2e/test_main_chain.py | 假模型+真实浏览器E2E存在；AC逐条签收/NFR测量及真实模型复验未齐全 |

## 其他批次

- T-P.1…3：历史目录整理，不在release主线重新执行；sources/archive只读。
- B1/B1b/B1c/B1d/B1e、B2导航审阅、T20样例、T24可读报告/补全、T25规则绑定：当前有对应模块与迁移；按当前架构和AC矩阵验收，历史正式库应用记录不当成本次验证。
- B1b-6、B1c-2、B1e-5、B2-5、T20-3、T22：涉及旧仓一次性脚本或正式库数据操作，release不一定携带这些脚本；不因脚本缺失重建并运行，不计为通用产品未完成功能。
- t98u：账号/会话/用户管理实现存在（0022），团队授权仍未完整。
- 结果可信度批次：0023/0024及来源/去重已实现；历史提案不再是待确认开发项。
- DEMO-FIX-001…008：已验证并推develop，详细证据见docs/development/demo-fixes.md。
