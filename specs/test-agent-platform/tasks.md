# TestAgent 任务清单 v1.2

2026-11-09；基线develop `f8eb361`。原始81项任务逐项状态在 [task-status](task-status.md)；下方原文保留验收义务与参考测试名，不因历史写“完成”就视为当前逐条签收。真实测试入口以 [test-design](design/test-design.md) 为准。

## 当前任务队列

| ID | 状态/优先级 | 交付与验收 | 依赖 |
|---|---|---|---|
| DOC-009 | 文档已更新，交付状态见提交记录 | spec/plan/tasks/架构/详细设计/测试映射/入口同步，链接和状态一致 | f8eb361 |
| UX-009 | 待做 P1 | 实体引用显示可读名称，保留原始标识；悬停/详情可查代码；改名、缺失值、结构化关联和跨系统测试 | DOC-009 |
| UX-010 | 待做 P1 | 统一长标题省略与全文访问、操作区换行/更多；长中文/英文及窄窗真实浏览器检查 | DOC-009 |
| FLOW-011 | 待做 P1 | 需求→用例→规则任务的引导/手册；核签#11与#13局部定位；不更改已存执行事实 | UX-009 |
| MODEL-012 | 待设计 P1 | 建议恢复、missing补建与关联的状态图、API、事务、冻结/去重边界和失败用例 | DOC-009 |
| MODEL-013 | 待做 P1 | 按MODEL-012实现；恢复不自动采纳，创建并关联原子化，重复提交安全 | MODEL-012 |
| MODEL-014 | 待做 P1 | M:N中间字段覆盖修正，定义单边/双边证据，三处覆盖视图一致且不过度计数 | DOC-009 |
| NAV-015 | 本轮交付 | 左侧导航固定为被测系统（切换当前系统，以及概览、版本与需求、策略、任务、用例、执行、缺陷）、建模（模型图谱、模型评审、API 注册表）、跨系统的执行、缺陷和测试报告，以及人员、Agent、用户分组。策略与任务有独立路由，旧的 `?tab=strategy` 会重定向。菜单按流程阶段高亮。不再增加“顶层需求/用例/任务/执行”，也不做全局编号查找。 | — |
| QA-016 | 待验收 P1 | AC-01…20逐条证据、NFR-03性能和NFR-08服务覆盖率实测、error终态报告完整性核验；不足开缺陷 | DOC-009 |
| OPS-017 | 待做 P1 | GitHub Actions测试/构建；测试库隔离、禁止秘密输出；校准包元数据/README/CHANGELOG的版本口径，不自动发版部署 | DOC-009 |
| VALID-018 | 待环境复验 P1 | 修复后真实模型全链路、统计及人工干预记录；服务器SHA/升级/备份恢复单独验收 | 稳定修复；模型/服务器环境 |
| TEAM-019 | 后续设计 | SUT认证凭据、expected_revision并发保护、SUT成员授权；角色与Person映射独立决策 | QA-016 |
| INTEGRATION-020 | 后续 P1 | 每SUT远程测试仓/分支/PR review与外部缺陷适配；先选目标、定义幂等/重试再拆任务 | TEAM-019相关凭据设计 |
| RUNNER-021 | 后续 | 独立执行环境/远程Runner/并行，回执重送、取消和制品关联协议 | INTEGRATION-020、TEAM-019 |
| I18N-022 | 后续，可提前 | 界面中文资源/切换；不混淆Agent输出语言，长文本与回退测试 | DOC-009 |

NAV-015 已按 2026-11-21 与负责人确认的方向改写，见 [导航与面板设计](design/ux-navigation-and-panels.md)。UX-009、UX-010、FLOW-011 仍是待做：本轮把菜单顺序对齐了主流程，节点面板里的引用也改成了中文类型和可读名称；悬停查代码、改名、跨系统引用、页头长标题省略，以及需求到用例的引导手册，都不在本轮。

## 已交付维护批次

DEMO-FIX-001…008已验证并推送，分别为9c04707、25d21f8、68234e0、796432a、c7c5aac、bccf2e2、c470b4f、f8eb361。结果可信度/来源去重及账号基础已实现，见 [审查](review-2026-11-09.md)。#10/#11仍部分完成，不能整批勾选。

## 历史说明

下面的正式库脚本、备份和目录搬迁是当时的操作记录/要求，不是本轮再次执行的命令。原参考测试名可能已改名；未找到当前路径的项目在task-status中列为历史或待验收。新开发使用上面的队列及plan依赖。

## 历史 M1 与后续批次任务要求（保留编号）

约定：
- 每个任务写明交付、验收和测试。**先写测试**，测试名供参考。
- “API 测试”：FastAPI TestClient + `testagent_test` 中的隔离 schema（见 architecture §11）。
- “假模型”：FakeChatModel 按脚本返回工具调用。
- 任何测试和代码都不能出现数据库密码，连接串只从 `.env` 读取。

---

## 历史前置：目录整理（不再次执行）
- **T-P.1** 根据 architecture §1.1 生成移动清单（源 → 目标），交用户确认。
- **T-P.2** 执行移动：旧规格、outputs、Praxis-review、migration-validation、build 脚本、迁移清单 → `archive\2026-10-pre-prd\`；PRD → `docs\prd\`；更新顶层 README。不改 `sources\`。
- **T-P.3** 代码仓内：`src/ontology_platform` 和 99 条旧测试复制到 `archive\2026-10-pre-prd\legacy-code\` 后，从仓库工作区移除（git 历史和 tag 中仍有）；保留 `examples/procurement` 和 `tests/samples`。
  验收：`pytest tests/samples` 28 条通过；所有链接都能打开。

## M1-00 新骨架、Postgres 连接与测试隔离
- **T-00.1 新包骨架**：建立后端骨架（当前目录按 architecture §1：执行服务在 services，Worker 在 core，不再要求 execution 目录）；`create_app()`；`GET /api/v1/health` 返回数据库状态（脱敏后）。依赖：加入 psycopg[binary,pool]、pydantic-settings、langgraph-checkpoint-postgres、langchain-openai、playwright、croniter；移除 rdflib、pyshacl、langgraph-checkpoint-sqlite。
  测试：`test_health_ok`、`test_health_hides_dsn`。
- **T-00.2 core/config**：用 pydantic-settings 读取 `.env`；缺少变量时给出明确错误；`repr` 和日志里都脱敏。
  测试：`test_missing_database_url_clear_error`、`test_dsn_redacted_in_repr`。
- **T-00.3 core/db**：连接池、`tx()` 事务、错误映射（唯一约束 → CONFLICT，外键 → NOT_FOUND，连接失败 → DB_UNAVAILABLE）。
  测试：`test_tx_commit_and_rollback`、`test_unique_violation_maps_conflict`。
- **T-00.4 迁移运行器**：`schema_migrations` 表 + 校验和 + `pg_advisory_lock`；每个文件一个事务。
  测试：`test_migrate_idempotent`、`test_changed_applied_migration_refused`、`test_concurrent_migrate_serialized`。
- **T-00.5 测试隔离 fixture**：在会话级为每个 worker 建一个 schema 并执行迁移；每个测试前 TRUNCATE 并重写种子数据；会话结束时删除 schema。库名不以 `_test` 结尾就拒绝运行；变量缺失时 skip。
  测试：`test_isolation_between_tests`、`test_refuses_non_test_database`、`test_schema_dropped_after_session`（用子进程运行 pytest 来验证）。
- **T-00.6 防泄漏检查**：扫描仓库已跟踪的文件，不能出现 `postgres://…:…@` 这类带密码的连接串，也不能出现 `.env` 中的值。
  测试：`test_no_credentials_in_repo`。
- **T-00.7 `ops/init_db.py`**：库不存在就创建 `testagent` / `testagent_test`；检查服务器版本 ≥ 17。
- **T-00.8 前端工程初始化**：Vite + React + TS + AntD + Router + React Query + @xyflow/react，配好 eslint；构建输出到 `src/testagent/web/`。
  验收：`npm --prefix web run build` 成功，`GET /` 返回首页。
- **T-00.9 `reports/progress.md` 模板**。

## M1-01 数据底座、鉴权、扩展点骨架、人员
- **T-01.1 `0001_init.sql`**：建 architecture §2 的全部表、索引、触发器和种子数据（severity_weight）。
  测试：`test_all_tables_exist`、`test_snapshot_and_report_immutable`、`test_updated_at_trigger`、`test_severity_weight_seeded`。
- **T-01.2 core/errors + 统一错误体**。
  测试：`test_error_body_shape`。
- **T-01.3 core/auth + 启动器**：会话/CSRF 中间件、Host/Origin 校验（0022替代原token方案）；`python -m testagent.launch`（先检查数据库，再迁移，再打开浏览器）；实例 advisory lock。
  测试：`test_requests_without_token_401`、`test_cross_origin_403`、`test_non_loopback_host_403`、`test_static_index_public`、`test_launch_fragment_url`、`test_second_instance_cannot_take_worker_lock`。
- **T-01.4 core/events + pipeline**。
  测试：`test_subscriber_error_isolated`、`test_stage_override`。
- **T-01.5 core/artifacts**。
  测试：`test_artifact_roundtrip_digest`、`test_corrupt_artifact_detected`。
- **T-01.6 状态机框架 + change_log**。
  测试：`test_illegal_transition_rejected`（参数化覆盖 spec §5.3 的全部状态机）。
- **T-01.7 Person / SUT / Environment / Module（可选）CRUD**。
  测试：`test_sut_crud`、`test_sut_code_unique`、`test_environment_base_url_validated`、`test_person_deactivate_keeps_history`。
- **T-01.8 secrets**（DPAPI 或 600 权限）+ 日志脱敏。
  测试：`test_secret_not_in_logs`、`test_secret_file_permissions_posix`。

## M1-02 前端工作台骨架与基础管理页
- **T-02.1** 布局和账号会话处理（本机ticket换会话，或账号登录）；401进入登录流程（替代原token方案）。
- **T-02.2** 用 openapi-typescript 生成客户端类型，统一错误提示。
- **T-02.3** 页面：P01 被测系统列表、被测系统概览（环境、可选分组、版本清单）、P13 人员列表（统计页放到 M1-11）。
- **T-02.4** E2E：启动器 URL → 自动登录 → 新建被测系统 → 刷新后仍在。
  验收：AC-01、AC-20。

## M1-03 本体模型与 API 注册表
- **T-03.1 节点和边**：kind 校验；attributes 用 Pydantic 定义 `conditions/states/constraints: list[{text, expr?}]`，存成 JSONB；新建节点仅entity/action，关系使用ModelLink并按BR-22校验（替代原BR-01关系节点）。
  测试：`test_relation_requires_source_and_target`、`test_node_name_unique_per_kind_excluding_deleted`、`test_attributes_schema`。
- **T-03.2 引用查询与软删除**。
  测试：`test_delete_lists_references_then_soft_deletes`。
- **T-03.3 图查询**：递归 CTE（深度上限 5、防环）；按可选分组过滤；按属性查询（GIN 索引）。
  测试：`test_graph_payload`、`test_neighbors_depth_limit_and_cycle_safe`、`test_find_nodes_by_constraint_text`。
- **T-03.4 API 注册表**：code_ref 是普通文本或链接；只有动作节点能关联 API。
  测试：`test_api_unique_method_path`、`test_only_action_nodes_link_api`。
- **T-03.5 前端 P02/P03/P04**：图 + 列表 + 节点抽屉；API 注册表页。
- **T-03.6 `ops/seed_procurement.py`**：目标≥10个实体/动作节点及2条ModelLink（种子数量按实际AC验收，不以历史关系节点计数）、4 个 API、4 名人员。
  验收：AC-02、AC-03；E2E `model_graph_list_sync`。

## M1-04 LLM 配置与 ReAct Agent 运行时
- **T-04.1 AgentConfig API**：key 存密钥文件，接口返回脱敏值；有连接测试接口。
  测试：`test_config_masks_key`、`test_key_not_in_db`、`test_unconfigured_returns_model_unavailable`。
- **T-04.2 模型工厂**：注入 FakeChatModel 的入口。
- **T-04.3 工具注册表 + 读工具**（含 `get_requirement_people`）；每个入口有工具白名单。
  测试：`test_entry_cannot_call_unlisted_tool`。
- **T-04.4 Agent 入口框架**：`submit_result` 校验失败时重试；步数上限、超时、取消。
  测试：`test_submit_result_validation_retry`、`test_max_steps_stops_run`、`test_timeout`、`test_cancel_between_steps`。
- **T-04.5 PostgresSaver 检查点**（独立 schema，测试时用测试 schema）+ agent_run 轨迹 + jobs 队列（SKIP LOCKED + NOTIFY）。
  测试：`test_checkpoint_resume_after_interrupt`、`test_run_trace_recorded`、`test_jobs_skip_locked_single_consumer`、`test_notify_wakes_worker`、`test_restart_marks_interrupted`。
- **T-04.6 提示词组装 + 记忆注入**。
  测试：`test_disabled_memory_not_injected`、`test_injected_items_recorded_in_run`。
- **T-04.7 前端 P14 + 轨迹抽屉**。
  验收：AC-19；可选 `@pytest.mark.llm test_real_model_roundtrip`。

## M1-05 版本、需求（含责任人）、结构化、补全、冻结
- **T-05.1 版本 CRUD 与状态机**（解冻必须写理由）。
  测试：`test_version_transitions`、`test_unfreeze_requires_reason`。
- **T-05.2 需求 CRUD**：编码 REQ-001…，版本内唯一；冻结后不能编辑。
  测试：`test_requirement_code_sequence`、`test_requirement_locked_after_freeze`。
- **T-05.3 需求责任人**：`PUT /requirements/{id}/people`，角色为 owner/developer/tester，每种角色可以多人；停用的人员不能新挂到需求上；确认需求时至少要有 1 个 owner。
  测试：`test_set_requirement_people_roles`、`test_confirm_requires_owner`、`test_inactive_person_rejected`、`test_person_requirements_listing`。
- **T-05.4 入口 `structure_requirement`**：每项输出 `node_id | missing`；服务层写入关联，缺失项生成建议。
  测试（假模型）：`test_structure_links_existing_nodes`、`test_missing_items_become_suggestions`、`test_invalid_node_id_rejected`。
- **T-05.5 入口 `complete_model`** + 建议的采纳和拒绝（采纳后回填需求的关联）。
  测试：`test_suggestions_deduplicated`、`test_accept_creates_node_and_backfills_link`、`test_reject_keeps_record`。
- **T-05.6 确认与冻结**：所有需求都已确认才能冻结；生成快照（jsonb 聚合 + sha256）；发布 `version.frozen` 事件。
  测试：`test_freeze_requires_all_confirmed`、`test_snapshot_digest_stable`、`test_snapshot_immutable`。
- **T-05.7 前端 P05（基础）/P06**：需求编辑、责任人选择器、结构化对照、建议面板、冻结按钮。
  验收：AC-04 至 AC-07。

## M1-06 测试策略与任务集
- **T-06.1 策略状态机与修订号**。
  测试：`test_strategy_edit_after_confirm_returns_draft`。
- **T-06.2 入口 `generate_strategy`**：生成策略和任务。
  测试（假模型）：`test_generate_strategy_creates_tasks`、`test_nonfunctional_types_are_tags_only`。
- **T-06.3 任务 CRUD**：用例排序；cron 校验；选择环境。
  测试：`test_task_case_order`、`test_invalid_cron_rejected`。
- **T-06.4 前端 P07/P08** + 版本任务树。
  验收：AC-08、AC-10。

## M1-07 用例与覆盖报告
- **T-07.1 用例 CRUD + 修订 + 状态机**（只有人能把用例设为 ready）。
  测试：`test_case_revision_on_update`、`test_only_human_sets_ready`。
- **T-07.2 入口 `generate_cases`**：每条需求生成 ≥3 个用例，关联需求和节点。
  测试（假模型）：`test_generate_cases_min_per_requirement`、`test_cases_link_requirements_and_nodes`、`test_unknown_node_ref_rejected`。
- **T-07.3 覆盖报告**：需求覆盖、动作节点覆盖、等级和类型分布、未覆盖清单。
  测试：`test_coverage_lists_uncovered`（预期值手算）。
- **T-07.4 用例清单导出**（CSV/Markdown）。
  测试：`test_case_list_export_columns`。
- **T-07.5 前端 P09** + 覆盖视图。
  验收：AC-09。

## M1-08 执行器
- **T-08.1 执行器接口与选择逻辑**。
  测试：`test_executor_selection_matrix`。
- **T-08.2 浏览器工具**（Python Playwright 封装，记录结构化步骤，断言回执是唯一的判定来源）。
  测试（真实浏览器 + 夹具）：`test_assert_pass_and_fail_receipts`、`test_steps_recorded_with_screenshot`、`test_tool_timeout_is_error`。
- **T-08.3 入口 `execute_case_browser`** + agent_browser 执行器。
  测试：`test_agent_exec_pass`、`test_agent_exec_detects_injected_bug`、`test_no_assertion_is_error`、`test_agent_claim_pass_ignored`。
- **T-08.4 测试仓初始化与 REPO_DIRTY 保护**。
  测试：`test_repo_initialized_with_template`、`test_dirty_repo_blocks_commit`。
- **T-08.5 入口 `automate_case`**：文件写到 `tests/<req_code>/test_<case_code>.py`，提交 commit，回写到用例。
  测试：`test_write_outside_tests_rejected`、`test_automate_commits_and_binds_case`、`test_path_uses_first_requirement_code`。
- **T-08.6 pytest 执行器**。
  测试：`test_pytest_results_parsed`、`test_failed_assertion_extracted`、`test_timeout_kills_process`。
- **T-08.7 人工执行**。
  测试：`test_manual_execution_recorded`。
- **T-08.8 单用例调试**。
  测试：`test_debug_execution_has_no_run`。
- **T-08.9 前端 P10**。
  验收：AC-11、AC-12、AC-14。

## M1-09 任务执行、进度与调度
- **T-09.1 run 编排**：串行执行；出错后继续；非功能类型跳过；人工用例记为待人工。
  测试：`test_serial_order`、`test_error_continues`、`test_nonfunctional_skipped`、`test_only_ready_cases_run`、`test_human_case_not_blocking`。
- **T-09.2 取消**。
  测试：`test_cancel_stops_new_cases`。
- **T-09.3 进度**：NOTIFY → SSE；断线后可以用 `GET /runs/{id}` 补齐。
  测试：`test_sse_emits_case_progress`。
- **T-09.4 调度器**：持有实例锁才运行；不重入；不补跑。时钟可注入。
  测试：`test_cron_enqueues_on_due`、`test_no_reentry_while_running`、`test_missed_ticks_not_backfilled`、`test_scheduler_requires_instance_lock`。
- **T-09.5 首次执行后版本进入 testing 状态**。
  测试：`test_first_run_moves_version_to_testing`。
- **T-09.6 前端：执行、进度、历史、调度设置**。
  验收：AC-13。

## M1-10 缺陷：需求归属与人员归因
- **T-10.1 缺陷 CRUD 与状态机**。
  测试：`test_defect_transitions`。
- **T-10.2 从执行创建缺陷**：所属需求默认等于用例关联的全部需求（inferred=true），可以增删；同时关联节点和 API。
  测试：`test_defect_requirements_inferred_from_case`、`test_edit_defect_requirements_marks_not_inferred`。
- **T-10.3 归因推断**（EP-09 映射）：原因类别决定角色 → 从所属需求的对应角色中带出人员；environment/unknown 不归因；人工修改过的归因不会被覆盖；改了需求或原因类别后，只重算 inferred 的记录。
  测试：`test_cause_development_attributes_developers`、`test_cause_design_attributes_owner`、`test_environment_no_attribution`、`test_manual_responsible_not_overwritten`、`test_reinfer_on_requirement_change`、`test_multi_requirement_union_of_people`。
- **T-10.4 入口 `analyze_failure`**：输出原因分类建议（只写入 suggested_cause）、分析和缺陷草稿；判断为产品问题时，由 Agent 创建缺陷（created_by=agent），cause_category 保持 unknown，等人确认（C01）。
  测试（假模型）：`test_agent_defect_has_suggestion_not_final_cause`、`test_non_product_cause_no_defect`。
- **T-10.5 前端 P12**：所属需求、原因类别（显示 Agent 建议，一键采纳）、归因人、按需求推断按钮；执行页上的建缺陷和 AI 分析按钮。
  验收：AC-15。

## M1-11 报告与人员统计
- **T-11.1 统计视图**：`v_defect_by_requirement`、`v_defect_by_person`（排除 rejected，按权重加权）；支持按 version 或时间筛选。
  测试（构造数据，预期值手算）：`test_requirement_count_weighted_density`、`test_person_attributed_vs_related`、`test_by_role_breakdown`、`test_rejected_excluded`、`test_weights_change_affects_new_stats_only`。
- **T-11.2 统计 API**：`/stats/people`、`/stats/requirements`，可排序。
  测试：`test_people_ranking_sorted_by_score`。
- **T-11.3 任务报告**：订阅 `task_run.finished`；content 按 architecture §6.3 的结构；记录使用的权重和快照 ID。
  测试：`test_report_metrics_match_executions`、`test_report_by_requirement_and_person`、`test_report_code_links_via_nodes`、`test_report_immutable`。
- **T-11.4 入口 `summarize_report`**：模型不可用时报告照常生成，只是没有 AI 总结；提示词要求只做客观描述。
  测试：`test_report_without_model_still_generated`。
- **T-11.5 版本报告**（每个用例取最新一次执行）。
  测试：`test_version_report_uses_latest_execution_per_case`。
- **T-11.6 前端**：P11 报告（需求表、人员排行）、P13 人员统计页（筛选、排序、下钻）、严重度权重设置。
  验收：AC-16、AC-17。

## M1-12 纠错与自我演化 + 端到端验收
- **T-12.1 Correction API + 各页面的“指正”按钮**。
  测试：`test_correction_saved_raw`。
- **T-12.2 入口 `digest_correction`**（由事件触发，直接写入，可追溯来源）。
  测试：`test_digest_creates_memory_with_source`、`test_prompt_patch_new_active_version`、`test_failed_digest_retryable`。
- **T-12.3 生效验证**。
  测试：`test_new_memory_injected_next_generation`。
- **T-12.4 前端 P15**（提示词回滚、记忆停用、纠错记录、技能/MCP 登记、轨迹）。
  测试：`test_prompt_rollback`、`test_skill_mcp_register_only`。
- **T-12.5 端到端** `tests/e2e/test_main_chain.py`：
  - 流程：建模 → 需求 + 责任人 → 结构化 → 冻结 → 策略 → 用例 → Agent 执行（注入错误）→ 自动化 → 任务执行 → 缺陷（归属需求、归因开发人员）→ 报告和人员排行 → 纠错 → 再生成。
  - 默认用假模型；可选一个真实模型版本。
  - 验收：输出 `reports/m1-acceptance.md`，逐条列出 AC 的证据。

## 批次 1：DeepSeek 试用反馈修正（2026-11-01）
- **B1-1 工具作用域与编号**（D20）：解析器强制当前 sut_id、补 version_id、接受 REQ/TC 编号与名称；结构化输入带模型目录；提示词“作用域”段落。
  测试：`test_tools_default_to_current_sut_and_accept_codes`、`test_structuring_links_existing_nodes_regression`。
- **B1-2 节点去重**（BR-16）：结构化、建议入库、采纳三处按归一名称匹配已有节点。
  测试：`test_node_suggestion_for_similar_name_skipped`、回归测试同上。
- **B1-3 实体字段**（D17）：entity_attribute + 关联表、迁移 0014（data_schema → 字段）、快照含字段、需求条目关联字段、“新增字段”建议、字段覆盖；前端实体“字段”表、结构编辑器选字段。
  测试：`test_field_crud_and_listing`、`test_snapshot_includes_fields`、`test_structure_item_links_field`、`test_case_links_fields_and_field_coverage`、`test_field_suggestion_accept_creates_field`、`test_data_schema_migrated_to_fields`。
- **B1-4 接口 schema 与 OpenAPI 导入**（D19、BR-15）：`get_api_schema`、导入接口、生成用例的请求体校验；前端 schema 视图、导入与编辑。
  测试：`test_openapi_import_and_get_api_schema`、`test_openapi_import_unreachable_502`、`test_case_steps_checked_against_api_schema`、`test_generate_rejects_body_not_matching_schema`。
- **B1-5 自动化绑定规则与后台自动化**（BR-13、D18）：自检上限可配、最后一次自检通过才绑定、需修复草稿、禁止 probe；生成后自动入队、批量入队、进度接口；前端需修复提示、绝对路径与代码查看器、生成对话框开关、批量按钮与进度。
  测试：`test_automate_commits_and_binds_case`、`test_automate_failed_self_check_marks_needs_fix`、`test_automate_without_check_is_not_bound`、`test_automate_probe_file_rejected`、`test_generate_enqueues_automation_and_batch`、`test_generate_without_automation`。
- **B1-6 接口用例执行器**（BR-14）：agent_api 执行器、选择逻辑、浏览器文本断言默认 body。
  测试：`test_api_case_detection_and_selection`、`test_agent_api_executor_uses_receipts`。
- **B1-7 可读性**：运行 labels、工具中文名、建议显示节点名、访问日志格式。
  测试：`test_access_log_is_readable`、前端 `AgentRunDrawer.test.tsx`、`SuggestionList.test.tsx`。
- 不在本批：步骤条、面包屑、被测系统说明、模型审阅视图（批次 2）。——已在批次 2（2026-11-02）完成。

## 批次 1b：用途、输入/输出与类型（用户反馈 t16u，2026-11-01）
- **B1b-1 数据与校验**（D21、BR-18）：迁移 0015；`io_spec`（IoParam 校验、schema ↔ 参数表、`api_io`、合并与字段绑定）；字段类型必填、枚举取值、引用实体。
  测试：`test_schema_params_flatten_types_formats_and_enums`、`test_edited_fields_write_back_into_schema_and_keep_limits`、`test_action_io_crud_binds_entity_fields_and_validates`、`test_field_types_enum_reference_and_required`、`test_field_crud_and_listing`（类型必填）。
- **B1b-2 API 注册表**：用途说明、内容类型、`io` 字段表、PATCH 字段表回写；OpenAPI 导入填用途和内容类型、保留字段顺序、替换 FastAPI 默认摘要名；演示系统补中文摘要/说明/字段说明和响应模型（仅文档）。
  测试：`test_api_io_from_demo_openapi`、`test_api_list_has_purpose_content_types_and_io`、`test_import_keeps_manual_name_and_purpose_but_replaces_default_summary`、`test_patch_api_fields_tables`、`test_default_summary_detection`。
- **B1b-3 动作继承接口**（BR-17）：绑定时自动继承、手动“带出（合并）/按 API 重建”、对象实体优先的字段绑定。
  测试：`test_linking_api_inherits_io_and_purpose`、`test_existing_io_is_not_overwritten_when_linking`、`test_inherited_io_binds_only_fields_of_the_object_entity`。
- **B1b-4 快照与 Agent 上下文**：快照、模型目录、`get_node`、`get_api_schema`、生成用例/自动化的 `actions` 与接口响应字段；结构化 `io_suggestions`、补全 kind=io 建议及采纳合并。
  测试：`test_snapshot_and_agent_context_include_io`、`test_complete_model_io_suggestion_accept_merges`、`test_io_suggestion_for_entity_is_rejected_by_validation`、`test_structure_io_suggestions`、`test_field_suggestion_accept_creates_field`。
- **B1b-5 前端**：节点抽屉（动作：用途说明、绑定 API、输入/输出表与格式、带出/重建；实体：字段表在前，类型/必填/格式/枚举/引用）、API 注册表（用途列、输入/输出计数、展开字段表、“编辑说明与字段”字段表 + JSON 高级页签）、模型列表“输入/输出 · 字段（类型）”列、io 建议文案。
  测试：`IoParams.test.tsx`（参数表、删除、接口详情、io 建议文案）。
- **B1b-6 正式库回填**：`ops/backfill_io.py`（备份 → 迁移 → 重新导入 OpenAPI → 动作继承 → 字段说明 → 待审字段建议）。

## 批次 1c：字段名以接口为准、归档 AI 实例节点（用户反馈 t17u，2026-11-01）
- **B1c-1 字段名对齐**（D22、BR-19）：迁移 0016（storage_name）；`field_align`（改名/新增字段建议，导入 OpenAPI 后自动生成）；改名建议采纳时原地改名；字段新增/改名后刷新动作参数绑定；AI 字段建议支持 rename_from；前端字段表“数据库列名”、改名建议文案、导入结果提示。
  测试：`test_rename_match`、`test_alignment_proposes_renames_and_missing_fields`、`test_accepting_a_rename_keeps_requirement_and_case_links`、`test_storage_name_is_kept_and_in_snapshot`、`test_ai_field_rename_suggestion`、前端 `IoParams.test.tsx`（改名文案）。
- **B1c-2 正式库修正**：`ops/align_fields_t17u.py`（备份 → 迁移 → 采购单 amount→amount_minor、status→state 原地改名，新增 currency/approval_required、付款记录 id/order_id/callback_id，对应 7 条待审建议按用户指示关闭；归档“金额审批流程实例”并拒绝其待审建议）。

## 批次 1d：环境预检与自动化状态可见（用户反馈 t18u，2026-11-01）
- **B1d-1 环境预检**（D23、BR-20）：`services/environments.py`（probe、中文提示、require_reachable）；AI 自动化、调试、手动执行前检查；新状态 env_unavailable（迁移 0017）；错误码 ENV_UNREACHABLE → 503；批量自动化重新排队需修复/环境不可用的用例并包含草稿。
  测试：`tests/api/test_env_preflight_api.py`（probe、环境停时自动化不调用模型并标环境不可用且可重排队、调试/手动执行 503、定时执行 error、启动命令启动）。
- **B1d-2 启动命令**（BR-21）：`environment.start_command`；`EnvironmentProcesses`（启动、等待可达、退出时结束）；`GET /environments/{id}/check`、`POST /environments/{id}/start`；启动器自动启动（`--no-env-start` 关闭）；示例数据和迁移 0017 为演示环境填好启动命令。
- **B1d-3 前端**：环境列表“状态”列和“启动”按钮、启动命令表单项；用例清单“自动化”列逐条显示 排队中/生成中/已绑定/需修复/环境不可用/未自动化（原因在提示里），环境不可达提示条；进度条统计环境不可用；用例页环境状态与“环境不可用”说明。
  测试：`AutomationTag.test.tsx`。
- **B1d-4 关系建模（Palantir 对照）**：方案见 `design/link-types-proposal-t18u.md`；用户选方案 A 加扩展，见批次 1e。

## 批次 1e：关系类型、前置条件与影响（用户决定 t19u，2026-11-01）
- **B1e-1 关系类型**（D24、D25、BR-22、BR-23）：迁移 0018（model_link、requirement_link_ref）；`LinkService`（两端读法、API 名、基数 1:1/N:1/1:N/M:N、外键在多的一端并可自动识别、M:N 中间实体及两个外键、重名冲突、软删除需确认）；不再新建关系节点；图/快照/实体详情/引用带关系；字段删除时外键置空。
  测试：`tests/api/test_links_api.py`（关系节点被拒、两端/外键/API 名冲突/快照/删除、M:N 中间实体、关系节点迁移、需求关联关系）、`test_model_api.py::test_relations_are_links_not_nodes`。
- **B1e-2 前置条件与影响**（D26、BR-24）：`model_node.preconditions/effects`；`action_rules`（校验、文字、改名刷新）；字段引用检查。
  测试：`test_links_api.py`（前置条件/影响的保存、标签刷新、Agent 摘要）。
- **B1e-3 建议与 AI**（D27、BR-25、BR-26）：引用/`<资源>_id` 字段与 OpenAPI 导入后的关系建议，采纳时可改名；AI link/rules 建议；`list_links` 工具；模型目录、`get_node`、生成用例/自动化提示词使用关系、基数和前置条件/影响。
  测试：`test_links_api.py`（字段与资源名建议、采纳覆盖、AI 建议、生成用例看到关系和规则）。
- **B1e-4 前端**：关系编辑器（两端读法预览、基数、外键/中间实体、删除确认）、关系表与“关系”页签、图上的关系连线（双向介词 + 基数徽标，点击编辑）、实体抽屉“关系”小节、动作“前置条件与影响”编辑器、关系/规则建议文案与采纳改名、需求结构“关联关系”、导入结果提示关系建议。
  测试：`LinkEditor.test.tsx`、`links.test.ts`、`graph/layout.test.ts`（布局与关系连线）、`SuggestionList.test.tsx`（关系/规则建议文案）。
- **B1e-5 正式库**：`ops/link_types_t19u.py`（备份 → 迁移 0018 → 两个关系节点迁为关系：采购单 属于 供应商 ／ 供应商 提供 采购单（supplier / purchaseOrders），付款记录 支付 采购单 ／ 采购单 收到 付款记录（order / payments，外键 付款记录.order_id）→ 4 个动作的前置条件/影响按示例代码写入 → 校验）。
  测试：`tests/api/test_link_types_ops.py`（演练回滚、应用、重复执行不变）。

## 批次 2：主流程导航、被测系统说明与模型审阅（用户反馈 #3、#4，2026-11-02）
- **B2-1 主流程进度**（D28、BR-27）：`services/navigation.py::progress`、`GET /suts/{id}/progress?version_id`（8 步状态、摘要、跳转路径、下一步、测试仓绝对路径）；前端 `FlowSteps`（布局顶部常驻、可点击、“下一步”按钮）、`OnboardingChecklist`（概览页上手清单）；写操作后自动刷新。
  测试：`tests/api/test_navigation_api.py::test_progress_walks_the_main_flow`、`components/batch2.test.tsx`（步骤条、上手清单）。
- **B2-2 面包屑、互链与上下文**（D29、BR-28）：`navigation.py::context`、`GET /nav/context?kind&id`（被测系统/版本/需求/任务/执行批次/用例/执行/缺陷/报告）；`app/navContext.ts`（从 URL 推出对象和上下文、列表链接带 sut_id/version_id）；`Layout` 面包屑 + 当前被测系统/版本选择器 + 被测系统菜单“模型审阅”；各详情页互链改为“名称 (编号)”（`ObjLink/objLabel`）：用例↔需求/任务/脚本、任务→测试策略（版本）/用例、执行批次/执行/缺陷→用例、缺陷→执行批次、需求→字段（模型）/关系（审阅）/用例；版本、任务详情接口带 sut_name/sut_code、version_name。
  测试：`test_navigation_api.py::test_context_chains_for_every_detail_page`、`app/navContext.test.ts`、`app/Layout.test.tsx`、`batch2.test.tsx`（ObjLink）、`CasePage.test.tsx`/`DefectPage.test.tsx`（名称 (编号)）。
- **B2-3 被测系统说明与空状态**（D30、BR-29）：`SutExplainer`（列表和概览页）、`PathText`（绝对路径 + 复制）、`EmptyState`（被测系统、环境、分组、接口、人员、版本、需求、任务、用例、执行、缺陷、报告列表）；用例页显示本地测试仓绝对路径。
  测试：`SutsPage.test.tsx`（说明、空状态、名称 (编码)）、`batch2.test.tsx`（PathText 复制、EmptyState）。
- **B2-4 模型审阅**（D31、BR-30）：迁移 0019 `model_review_mark`；`services/model_review.py`（覆盖：需求经节点/字段/关系关联，用例经节点/字段及关系→需求→用例；关系双向读法；动作 IO/规则/接口；摘要与“审阅后已变更”；Markdown 导出）；`GET /suts/{id}/model-review`、`PUT /suts/{id}/model-review/marks`、`GET /suts/{id}/model-review.md`；前端 `ModelReviewPage`（统计、审阅清单、筛选 未审阅/未覆盖、逐项“已审阅”+ 备注、导出 Markdown、打印），模型页入口。
  测试：`tests/api/test_model_review_api.py`（覆盖与未覆盖、双向读法、标记/取消/变更后失效、404、Markdown）、`pages/ModelReviewPage.test.tsx`。
- **B2-5 正式库**：先备份（`archive/2026-11-02-prod-backup-before-batch2.json`），再执行迁移 0019（只新建表，不改已有行）。

## 批次 t20u：示例被测系统升级与从零体验（用户请求 t20u，2026-11-02）
- **T20-1 示例被测系统**（D32）：`examples/procurement`：供应商资源与 `supplier_id` 外键、采购事由、创建时间；小额自动通过；采购单列表/详情/筛选；`POST /sample/reset` 与 `PROCUREMENT_RESET_ON_START`；中文 OpenAPI（标签、摘要、说明、类型化响应、示例；隔离空间接口隐藏）；新界面（稳定 data-testid）；预埋缺陷 3 个（`PROCUREMENT_DEMO_BUGS`，默认开，`tests/conftest.py` 关闭）；旧库结构自动升级；示例 README（规则、地址、接口、体验路线、答案）。
  测试：`tests/samples/test_demo_upgrade.py`（供应商、外键、自动通过、中文错误、重置、启动重置、旧库升级、OpenAPI 可读、data-testid 与缺陷开关、缺陷只在开启时出现）、`tests/samples/test_demo_ui.py`（真实浏览器走完整流程；缺陷开启时驳回显示错误）；调整 `test_procurement.py`（小额自动通过）、`test_io_specs_api.py`（输入多了 title/supplier_id，列表接口与创建接口同路径）、`tests/e2e/test_main_chain.py`。
- **T20-2 被测系统重置**（BR-31）：`ops/reset_sut_data.py`（`reset_sut`、`reset_repo`，默认演练，`--apply --repo-archive`）。
  测试：`tests/api/test_reset_sut_ops.py`（演练不改数据、执行只清该系统且保留环境/人员/记忆/其他系统、保护触发器恢复、步骤条从头开始、幂等、未知系统拒绝、测试仓归档并重新初始化且不覆盖归档）。
- **T20-3 正式库**：pg_dump 全量备份（`archive/2026-11-02-prod-full-backup-before-reset.dump`，`pg_restore --list` 校验）→ 演练 → `--apply`（测试仓移到 `archive/2026-11-02-test-repo-procurement-before-reset`）。

## 批次 t22u：后台代建示例被测系统模型（用户请求 t22u，2026-11-02）
- **T22-1 建模脚本**：`ops/build_procurement_model.py`（经服务层写入，变更日志执行者“pearl（按用户要求代建模型 t22u）”；默认演练，`--apply --backup`；只补缺失项，可重复执行）：按第一个环境导入 OpenAPI（10 个接口）→ 分组 基础资料/采购审批/付款/演示数据 → 实体 供应商（4 字段）、采购单（9）、付款记录（5）→ 关系 采购单 属于 供应商 ／ 供应商 提供 采购单（supplier / purchaseOrders，外键 采购单.supplier_id，可空）、付款记录 支付 采购单 ／ 采购单 收到 付款记录（order / payments，外键 付款记录.order_id，必填）；先建关系再建外键字段，不产生重复的关系建议 → 10 个动作一一绑定接口（用途和输入输出从接口继承），前置条件/影响按示例 README 的业务规则写入。不建版本、需求、用例。
  测试：`tests/api/test_build_procurement_model_ops.py`（演练不改数据；执行后数量、关系与外键、金额单位、状态枚举、规则、接口绑定、变更日志执行者、无待处理建议、无需求/用例；再次执行无变化）。
- **T22-2 正式库**：备份（`archive/2026-11-02-prod-backup-before-t22u.json`）→ 演练 → `--apply`。

## 批次 t24u：可读的执行结果、覆盖明细、AI 补全、批量操作与可读日志（用户反馈 t24u，2026-11-02）
- **T24-1 可读的执行结果**（D33、BR-32）：平台自带 pytest 插件 `integrations/pytest_report.py`（只在 `TESTAGENT_REPORT` 设置时生效）：记录 Playwright 页面动作（打开/点击/填写…）、接口请求（方法、地址、状态码、耗时、截断的请求/响应体）、每个断言的期望/实际/是否通过（`enable_assertion_pass_hook`）、失败的中文解释（如“接口返回状态码 409，期望等于 201”、连接被拒、超时、KeyError）、用到的测试数据；步骤优先取 `with step('步骤 1：…')`，其次取注释（前置/步骤 N/校验），否则一个“测试过程”。测试仓模板 v2 的 `conftest.py` 增加 `step`/`check` 夹具（未改过的 v1 conftest 自动升级并单独提交，改过的不动）；自动化提示词要求使用 step/check。迁移 0020 `case_execution.report`。前端 `RunReport`：失败说明、摘要（结果、断言 x/y、接口请求数、耗时）、步骤时间线（请求、动作、断言）、测试数据、可折叠的原始输出；旧的执行记录（无 report）显示摘要行 + 原始输出。
  测试：`tests/integrations/test_pytest_report.py`（注释步骤、请求与断言、失败解释、数据键、仓库无 __pycache__；step/check 夹具与不装插件独立运行；错误解释；模板升级保留人工修改；浏览器动作与 expect）、`test_executions_api.py`（调试结果带 report）、`ExecutionPage.test.tsx`。
- **T24-2 覆盖明细**（BR-33）：用例清单每行 `coverage`（动作/实体/字段/关系的名称）和“覆盖”列（悬停看明细，可点到模型）；用例详情 `relations`，“追溯”卡按 动作/实体/字段/关系 列出；版本覆盖每项带覆盖用例 `case_list`，新增“关系覆盖”和“覆盖明细”折叠表；需求抽屉“覆盖明细”（需求引用的每个动作/实体/字段/关系由哪些用例覆盖）。关系覆盖：用例关联的需求引用了该关系，或用例关联了该关系的外键字段。
  测试：`tests/api/test_t24u_api.py`（用例/版本/需求三处明细）、`components/t24u.test.tsx`。
- **T24-3 AI 补全**（D34、BR-34）：入口 `complete_case`（补测试点、前置条件、步骤、测试数据、预期，关联需求/节点/字段；校验节点/字段 ID 和接口请求体）；`POST /cases/{id}/ai-complete` 把建议存到 `test_case.ai_proposal`（迁移 0020），不改用例；`…/accept`（只能由人，按勾选字段生成新修订，原有关联只增不减）、`…/reject`；批量通过后台任务 `complete_case`。前端用例页“AI 补全”按钮和逐项对比（当前/建议、勾选采纳、忽略）。顺带修复：用例原来没有字段关联时更新字段关联会报错（修订差异 KeyError）。
  测试：`test_t24u_api.py`（提议→人采纳所选字段、Agent 不能采纳、无建议时 409、保留人工关联、忽略）、`t24u.test.tsx`（对比与采纳）。
- **T24-4 返回与批量操作**（BR-35）：页头“返回”按钮（应用内有历史则后退，否则回到上级页面）；用例清单勾选 + `POST /cases/batch`（设为可执行、设为草稿、AI 自动化、AI 补全、加入任务、废弃，逐条处理并返回成功/跳过/失败）；需求列表（AI 结构化、确认、删除）、任务列表（设为就绪、执行、归档、删除）、缺陷列表（处理中、已解决、关闭、驳回、重新打开）批量操作，逐条调用并汇总结果；有风险的操作需确认。
  测试：`test_t24u_api.py`（批量状态逐条结果、加入任务跳过已在任务中的、批量排队自动化与补全）、`t24u.test.tsx`（批量栏、返回的上级页面）。
- **T24-5 可读日志**（BR-36）：`services/labels.py::resolve_refs`（被测系统、版本、需求、用例、任务、执行批次、执行记录、缺陷、报告、Agent 运行、节点、字段、关系、接口、环境、策略、人员 → 类别、“名称 (编号)”、页面路径）；访问日志在路由模板后追加对象名称（如“PATCH /api/v1/cases/{case_id} → 200 (12 ms) · 用例「大额审批 (TC-001)」”）；后台任务开始/完成日志带对象名称；任务执行每个用例一行 INFO 日志；Agent 轨迹列表和详情返回 `subjects` 并显示为可点击的“对象”。
  测试：`test_t24u_api.py`（resolve_refs、访问日志、后台任务日志、Agent 轨迹对象）、`t24u.test.tsx`。
- **T24-6 任务与用例打通**：原方案已被t25决定并实现，见T25-2，不重复排期待确认。

## 批次 t25：任务与用例打通、边界用例不再跳过（用户决定 t25，2026-11-02）
- **T25-1 边界用例跳过修复**（D38，单独提交 `96dba2a`）：`select_executor` 只跳过 `NON_FUNCTIONAL_TYPES`（performance、load、stress、security、reliability、usability、compatibility、accessibility）；AI 生成的用例若把 normal/boundary/exception 写进 `type_tag`，改为 functional（场景仍在 `scenario`）；跳过原因写明“不计入通过”；报告摘要加 `executed`，执行页和报告页说明“通过率 = 通过 / 已执行；跳过、待人工、未执行不计入通过”。
  测试：执行器选择矩阵（boundary/exception/regression/smoke/validation/idempotency 都执行）、边界/异常用例在任务中执行、生成时 type_tag 归一、报告 `executed`；前端 `passRate.test.ts`。
- **T25-2 任务与用例打通**（D35–D37、BR-37–BR-41）：迁移 0021（`test_case.category/quality_tags/category_suggestion`，`test_task.kind` 增加 quality、`test_task.selector`，`task_case.source/reason/added_at`，存量行为 manual，`task_case_exclusion`）；`services/task_binding.py`（规则校验与匹配、同步、事件驱动的自动加入/移出、恢复、预览、按分类补齐任务、需求缺口、分类建议的采纳/忽略）；`TaskService._set_cases` 保留来源并记录手工移出；策略生成改为规则任务；用例生成与 AI 补全给出分类；报告 `by_category`。
  接口：`PUT /tasks/{id}/selector`、`POST /tasks/{id}/selector/preview`、`POST /tasks/{id}/sync`、`DELETE /tasks/{id}/exclusions/{case_id}`、`POST /versions/{id}/tasks/ensure`、`GET /versions/{id}/gaps`、`POST /cases/{id}/category-suggestion`；任务创建可带 `selector`；用例字段 `category`、`quality_tags`。
  前端：任务页“选用例规则”卡片（规则编辑、预览匹配、保存并同步、立即同步、清除规则、手工移出列表与恢复）、用例来源/原因/分类列；策略页“需求缺口”（生成草稿用例）、“按分类补齐任务”、任务类型与规则列；用例表单分类与质量属性、用例清单分类列与“待确认”标记、用例页分类建议；报告“按用例分类”。
  测试：`tests/api/test_task_binding_api.py`（14 个：分类、规则选用例、单个/批量自动加入与原因、手工优先与排除、离开规则、运行中不动、回归任务、规则校验、补齐任务、策略生成与缺口、缺口草稿、AI 分类、分类建议、报告按分类）、`test_t24u_api.py` AI 补全分类、策略与主链路测试更新；`tests/api/test_task_binding_ops.py`；前端 `t25.test.tsx`（5 个）。
- **T25-3 正式库迁移**：`ops/task_binding_t25.py`（默认演练，`--apply` 写入）：存量需求任务加规则“其需求 · 需求验证”，用例和顺序不变（全部为手工）；TC-014 → 通用质量/幂等；TC-011/013/015 保持需求验证（输入校验）；不确定的 TC-008、TC-016 只写分类建议；type_tag 里的场景词移回场景。执行前完整备份 `archive/2026-11-02-prod-full-backup-before-t25.dump`。不替用户重跑任务。
