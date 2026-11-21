# TestAgent 技术架构 v1.2

2026-11-09，对照 develop `f8eb361` 的实际模块。本文描述当前实现；后续扩展见 [plan](../plan.md)。产品约束见 [spec](../spec.md)，字段/接口细节由 SQL 迁移与源码定义，不再把最初的 0001 概要当成完整数据库结构。

## 1 总体与目录

```text
浏览器（React / AntD / React Query / React Flow）
  → 同源 REST + SSE + Cookie 会话
FastAPI 单实例
  api → services → psycopg / PostgreSQL
       ├─ LangGraph StateGraph → 模型 + 受控工具 → 服务校验后落库
       ├─ jobs → 单 Worker → 执行服务 / 自动化 / 纠错 / 用例补全
       └─ scheduler（实例锁）→ 任务运行
执行：本机 pytest 子进程 / Python Playwright / HTTP 工具 / 人工回执
存储：PostgreSQL + 本地测试 Git 仓 + 内容寻址制品 + 密钥文件
部署：本机启动器；或可选 Docker + Caddy 代理同一个平台实例
```

主仓 `D:\CodeWork\TestAgent\release\testagent`。`src/testagent/api` 处理请求，`services` 负责事务和领域规则，`core` 提供队列/Worker/数据库/认证/事件，`agent` 管理工具和图运行时，`integrations` 封装浏览器/HTTP/Git/pytest。SQL 主要在 services，`repos` 当前不是完整的独立仓储层；不存在旧设计所写的 `execution/` 模块。

`web/` 是前端源代码，产物到 `src/testagent/web/`；`tests/{unit,db,api,agent,integrations,e2e,samples}` 分层验证。`examples/supply_chain/` 是可替换的被测样例。`runtime/` 放运行产物、不跟踪；`specs/test-agent-platform/` 随源码版本维护。

### 1.1 依赖与部署边界

Python 3.12、FastAPI、Pydantic、psycopg 3、LangGraph、PostgresSaver、langchain-openai、Python Playwright、pytest；前端 React/Vite/AntD。依赖版本以 `pyproject.toml`、`uv.lock` 和前端锁文件为准。

Node 用于前端开发/构建，不是 Agent 的第二套运行环境。本体逻辑也在 Python 内，无 Java reasoner。默认本机运行；Docker/HTTPS 配置存在不能证明某台服务器已更新。当前用户必须是受信任使用者，脚本与平台同机执行，不提供不可信租户隔离。

## 2 数据库与模型

PostgreSQL 17，psycopg 池及 `db.tx()` 管理事务，不用 ORM。版本化迁移为 `0001`–`0024`，迁移校验和及 advisory lock 保证有序应用；禁止改已应用文件。配置由仓库根 `.env` 或环境读取，数据库连接串不进入文档或日志。

| 数据域 | 当前结构/迁移 |
|---|---|
| 系统与责任人 | sut、environment、module、person；Person 不等于登录账号 |
| 活模型 | model_node（实体/动作）、model_edge、entity_attribute、model_link、node_api_link；0014–0018 扩充字段/IO/关系 |
| 冻结与需求 | version、requirement 及人员/节点/字段/关系关联、model_snapshot |
| 策略与任务 | test_strategy、test_task、task_case、task_case_exclusion；0021 分类与规则绑定 |
| 用例与执行 | test_case、case_revision、task_run、case_execution；0020 结构化报告，0023 失败分类，0024 not_executed |
| 缺陷/报告/学习 | defect 与归属/归因关联、report、correction、agent_memory、prompt_template |
| 运行与认证 | agent_run、jobs、change_log；0022 账号/会话，检查点独立 schema |

每 SUT 一个活模型；冻结保存不可变快照。关系是实体之间的 ModelLink，不是新的 relation 节点；可表达 M:N 和中间实体。图来自这些表，图只是视图，不另存一套图事实。当前不是 RDF/OWL 存储或推理器，也不是独立业务流程图编辑器。

M:N 的表达能力不代表覆盖完整：`services/cases.py::case_relations` 经需求关系或 `fk_attribute_id` 求覆盖，尚未纳入两个 via 字段，见 MODEL-014。

## 3 服务与接口边界

REST 前缀 `/api/v1`；错误体 `{code,message,field_errors,related}`。路由见 `api/*.py`，前端类型见 `web/src/api/schema.d.ts`。不宣称所有列表已有统一服务端 page/size 分页：不少接口返回范围集合，一部分有 LIMIT，前端再分页。

事务完成后发布进程内事件。事件失败被隔离，因此 Ready 已保存和自动关联是否完成必须分别反馈；这不是可靠 outbox。状态机在 `services/state.py`，作业调度在 `core/jobs.py`、`core/worker.py`、`services/scheduler.py`。

## 4 Agent 架构

`agent/runtime.py` 实际使用自定义 LangGraph `StateGraph`，而非旧文档的 `create_react_agent`。agent/tools/nudge 节点构成受控 ReAct 循环；Entry 定义用途、提示模板、工具白名单、Pydantic 输出和可选语义校验。`submit_result` 最多两次校验重试；服务层接收结果后才写业务事实。

模型通过 OpenAI 兼容接口调用；FakeChatModel 可注入做契约测试。`agent/tools.py` 负责工具与当前 SUT 的作用域/引用解析。浏览器和写测试文件工具限定入口与资源；AI 不能完成需求确认、Ready、冻结等人工关口。

启动器注入 PostgresSaver（`agent_ckpt`），未注入的运行时默认 InMemorySaver（主要供测试）；轨迹写 agent_run。检查点恢复测试只证明图可续接，不代表业务任务重启会自动续跑或工具副作用仅一次。启动恢复把遗留作业标 error/INTERRUPTED，不自动重跑。取消/预算在步骤和工具边界检查，不承诺立即打断正在阻塞的网络调用。

提示词、记忆可版本化/停用/追溯；纠错整理直接生效。记忆是真实配置变更，不能把回归测试当成长期学习质量证明。

官方 Playwright Test Agents 的 planner/generator/healer 未直接集成；当前是平台自有 Python 浏览器工具、脚本生成和自检流程。未来适配必须保留人工关口与回执判定，不能让 healer 静默修改需求预期。

## 5 执行与调度

`services/executions.py::select_executor`：非功能类型先跳过；有绑定脚本的 automated 用例走 pytest；无脚本且任务 executor=agent 时按 API 特征选择 agent_api 或 agent_browser；human 记 blocked/awaiting_human；自动化任务无脚本记 skipped/no_script。

Worker 串行处理作业，任务内按用例顺序执行；用例失败不中止后续用例。PostgreSQL `SKIP LOCKED` 领取、NOTIFY 唤醒及轮询兜底；进度通过 SSE/读取接口恢复。单实例 advisory lock 仍在，不能因队列表支持锁而宣称分布式执行已完成。

pytest 从 `integrations/git_repo.py::execution_snapshot` 的独立完整检出运行，固定完整 SHA，保留 fixtures/helpers，结束清理；绑定不可用报错，旧未绑定仅固定启动 HEAD。生成脚本写受限 tests 路径；REPO_DIRTY 保护人工修改。生成/自检与正式执行使用不同阶段记录。

结果看执行器回执，不看 Agent 自报 passed；无断言不能当成功。运行质量聚合和编排 error/cancelled 分开。详细时序与零执行口径见 [详细设计](detailed-design.md)。

## 6 缺陷与报告

缺陷归属需求，按 cause_category 与 requirement_person 推断责任人；环境/未知不归因。人工修改的归因不会被规则覆盖，AI 仅提 suggested_cause。Person 统计不是按账号权限的数据隔离。

实际统计由 `services/stats.py` 的查询和聚合复用，不要求另建旧计划中的两个数据库视图。通过率分母为 passed/failed/error；缺陷密度按范围内已执行用例去重；rejected 缺陷不计入。报告冻结范围、结果及权重，不能原地重写旧快照。

`api/app.py` 在 passed/failed/cancelled/not_executed 的 finished 事件上自动生成任务报告；编排 error 路径不宜概括成“一切终态都有自动报告”，完整性列 QA-016 核验。可选 AI 总结失败不应改执行事实。

## 7 测试仓与扩展

每 SUT 本地 Git 仓，生成→自检→绑定/人工确认→按固定提交执行。平台源码推送 GitHub 不等于产品支持推送用户测试仓。远程仓、PR review、远程 Runner 均未落地。

`core/pipeline.py` 有 StageRegistry，但默认为 NotImplementedStage，生产流程并未全量接入可替换阶段。现有技能/MCP 是登记数据；没有完整的第三方插件执行宿主。外部缺陷/API 平台同步、RDF 导出不能以扩展点编号认定已交付。

## 8 前端

React Query 保存远端状态；URL 保存系统/版本上下文；FlowSteps、面包屑和互链提供导航。ReadyTaskFeedback 读取实际关系，LatestTaskRun/运行提示显示最近执行。ListTable/ListCount/ListSection 统一数量、区域滚动、最近记录上限及错误；打印解除裁剪。ReadingDrawer/ExpandableDescription 统一宽度和长文本。细节见 [详细设计](detailed-design.md)。

当前英文界面；Agent 输出语言独立设置。360px 的抽屉验收不等于全站移动端可用；完整顶层导航/搜索、中文界面仍在计划。

## 9 认证和部署

`services/auth.py`、`core/auth.py`、`api/auth.py`：Argon2 密码、服务端会话、HttpOnly Cookie、写请求 CSRF、登录限速/锁定、admin/member、本机一次性 ticket；旧共享 token 仅告警，不授权。

auto Cookie 策略按实际请求协议：HTTPS 为 `__Host-ta_session`（Secure），本地 HTTP 为 `ta_session`；CSRF 通过会话响应传给客户端并附请求头，不采用旧提案里的独立 ta_csrf Cookie。配置 Host 白名单，提供 Origin 时校验同源；不能描述为“缺 Origin 的所有请求必拒绝”。管理用户、模型配置和环境启动命令等需 admin。

本机启动器连接数据库→迁移→获取实例锁/恢复遗留工作→启动服务和环境→ticket 登录；无头 Docker 使用账号。部署文件及代理设置见仓库 `docs/deployment.md`、`docs/server-upgrade.zh.md`；本轮未登录服务器、不修改数据、不部署。

## 10 当前限制和风险

单机串行、无测试脚本沙箱、无 SUT 成员隔离/乐观锁、无完整 SUT 登录态注入；事务事件没有可靠投递保证；大列表多为加载后分页。现有架构可支撑受信任使用者的小规模单实例验证。团队能力应先补边界与冲突检测，再引入远程执行和并行，不能只加 Worker 数量。

## 11 验证

测试库名以 `_test` 结尾，每次会话独立 schema，执行全部迁移；业务测试可以真实提交，不能依赖外层事务回滚隔离。浏览器/E2E 基于固定构建；假模型/合成 API 与真实模型记录分别保存。最近已记录回归见 [审查](../review-2026-11-09.md)，本轮未重跑产品测试。性能 p95 和服务覆盖率仍待测量，见 [测试设计](test-design.md)。
