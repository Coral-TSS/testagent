# TestAgent 团队可用性差距分析与演进路线（t33u）

> 2026-11-09维护说明：本文件下方以8d9f36e为历史基线，现有0022已补账号、会话与actor；本地固定Git版本执行也已补齐。SUT授权/凭据、乐观锁、远程仓/Runner、外部缺陷等仍未闭环。当前排序见../plan.md，外部缺陷提升为P1规划；旧工期不作为当前承诺。

日期：2026-11-03 · 基线：v0.1.0（GitHub `Coral-TSS/testagent` main `8d9f36e`，迁移 0001–0021）
性质：只读分析，未改代码、未写生产库。证据路径相对于仓库根目录。

## 0 结论先行

v0.1 是一个**单人、本机、单实例**的平台：一个访问令牌、一个后台 Worker 线程串行执行、脚本只提交到本机 git 仓、被测系统没有登录机制。
本体建模、用例生成、自检绑定、追溯这条主链路是扎实的；要让团队用，最先补的是**人和权限（用户/RBAC）、被测系统鉴权、并发编辑保护**三件事（P0），
然后是**远程仓库 + 远程执行器 + CI**（P1），最后才是 SSO、审计合规、规模化（P2）。

| 阶段 | 主题 | 粗估工作量（1 人，含测试） |
|---|---|---|
| P0 团队基础 | 用户与角色、SUT 鉴权与凭据库、乐观锁、操作审计（基础版）、中间表建模补齐 | 6–8 周 |
| P1 协作与执行 | 远程 git（分支/PR）、远程执行器（Runner）、并行执行、CI/Webhook、通知、不稳定用例处理 | 8–10 周 |
| P2 企业级 | OIDC/LDAP/SSO、完整审计与合规、多实例/高可用、可观测性、成本治理、外部系统对接、i18n | 8–12 周 |

---

## 1 用户提出的 6 项

### 1.1 建模：中间表能不能处理？队列/任务表要不要建模？

**现状**
- **建模层面已支持 M:N + 中间实体**（t19u 起）：`model_link` 有 `cardinality`（1:1 / N:1 / 1:N / M:N）、`via_node_id`、`via_from_attribute_id`、`via_to_attribute_id`。
  校验在 `src/testagent/services/links.py`（约 228–285 行）：M:N 不能有单一外键，必须用中间实体；只有 M:N 能设中间实体；中间实体必须有分别指向两端的外键字段，且字段必须属于中间实体。
- **模型审阅**能显示“作为某关系的中间实体”（`services/model_review.py` 37 行），关系列表带 `via_name`。
- **Agent 能看到中间实体**：`agent/tools.py` 的 links 工具返回读法、基数、外键/中间实体。
- **用例生成**：`services/case_gen.py` 提示词只泛泛提到“N 侧多个对象（1:N/M:N）、解除关联”，**没有针对中间实体的规则**（如：中间行重复、一端删除后中间行如何处理、中间实体自身属性）。
- **覆盖率**：`services/cases.py` 约 79–83 行，关系覆盖只通过“需求引用关系”或“用例关联了 `fk_attribute_id` 字段”计算；**M:N 关系的 `via_from/via_to` 字段不计入**，所以中间表上的用例不会让 M:N 关系显示为已覆盖。
- **关系建议**：`links.py` `link_suggestions()` 只根据引用字段或 `<resource>_id` 字段推断 **N:1**；一个实体有两个外键时会生成两条 N:1 建议，**不会识别为中间表并建议 M:N**。

**差距**：建模“能表达”，但“自动识别、生成、覆盖”三处没跟上；中间表带业务属性（如 订单-商品 的数量、价格）时，它到底是“关系”还是“实体”没有引导。

**建议设计**
1. 判定规则写进模型指南：中间表**只有两个外键 + 审计字段** → 建模为 M:N 关系 + 中间实体（隐藏在图上，仅审阅页可见）；**有业务属性或自己的生命周期**（订单行、成绩单）→ 升格为普通实体，两条 N:1。
2. 关系建议：同一实体有两个指向不同实体的外键、且除审计字段外无其他字段 → 建议“M:N（中间实体 X）”。
3. 用例生成提示词增加 M:N 规则：重复关联、一端删除后的级联/孤儿、中间实体唯一约束、中间实体属性边界。
4. 覆盖率把 `via_from_attribute_id / via_to_attribute_id` 计入关系覆盖。

**关于队列、任务表**：同意不从需求侧建模。建议把它们视为**基础设施 / 可观测副作用**：
- 不作为实体出现在业务模型里；
- 在动作的“影响（effects）”里允许一种 `kind: "observable"`（如“发出 OrderApproved 事件”“写入通知任务”），只用于断言，不参与关系和覆盖统计；
- 断言方式由环境提供“观测点”（查询接口、消息探针、数据库只读查询），在 SUT 鉴权和数据隔离（1.6、2.3）落地后再做。

**工作量**：规则 + 建议 + 覆盖修正 + 提示词 约 1–1.5 周；observable effects 约 1 周（P1）。**优先级**：P0（覆盖修正和建议）/ P1（observable）。

### 1.2 用例/脚本只能写到本地测试仓，不能推远程

**现状**：`src/testagent/integrations/git_repo.py`
- 每个 SUT 一个仓库 `runtime/repos/<sut_code>`，`git init` 本地创建（`ensure()`，178 行）；
- 每次自动化 `write` + `commit_files` 直接提交到当前分支，用例绑定 `code_path + code_commit`；
- 有人工未提交修改时拒绝自动提交（`ensure_clean` → `REPO_DIRTY`）；
- **没有 remote、没有分支、没有 push/pull、没有冲突处理**。spec D07 明确“推送远程放 M2”。

**差距**：团队无法评审脚本（PR）、无法在 CI 里跑、多人各自本地仓会分叉；平台换机器脚本就丢（只能靠数据卷备份）。

**建议设计**
- SUT 增加 `repo_remote_url`、`default_branch`、`repo_credential_id`（凭据库，见 2.1）。
- 平台持有一个工作副本：生成脚本时在 `testagent/<case-code>-<短 hash>` 分支提交并 push，可选自动开 PR/MR（GitHub、GitLab、Gitea 适配器）；
  用例绑定改为 `code_path + commit + branch`，**合并后**才算“已绑定到主线”，未合并显示“待评审”。
- 执行时按绑定的 commit `git fetch` + 检出（worktree），保证执行的就是被评审过的代码。
- 冲突：平台只写自己的分支，主线变更通过 rebase 或重新生成解决；人工在远程改了脚本，平台通过 webhook / 定时 fetch 感知并更新绑定。

**工作量**：2–3 周（含两种托管平台适配器）。**优先级**：P1（团队用起来后很快就会需要）。

### 1.3 执行只在本地，不能分发到专门的测试虚拟机

**现状**
- `core/worker.py`：**一个 Worker 线程**，用 `FOR UPDATE SKIP LOCKED` 领取任务（`core/jobs.py`），但 `core/db.py` 的 `InstanceLock`（advisory lock）限制**每个数据库只能有一个平台实例**；
- pytest 执行：`integrations/pytest_runner.py` 在平台机器上起子进程，`cwd` = 本地测试仓；
- Agent 浏览器执行：`integrations/browser.py` 在平台进程里驱动本机 Chromium；
- 任务内用例串行（spec BR-06），所以整体是**串行、本机**。

**差距**：不能并行、不能隔离（脚本和平台同机同权限）、不能放到能访问内网测试环境的机器上、不能按浏览器/OS 分发。

**建议设计：Runner 模型**
- 新增 `runner` 实体：名称、标签（`linux`、`chromium`、`env:staging`）、并发数、心跳、版本。
- Runner 是一个独立的轻量进程（同一个 Docker 镜像的 `runner` 命令），**主动连接平台**（HTTPS 长轮询或 WebSocket，Runner 侧出站，内网友好），用 Runner 令牌认证。
- 平台把“执行一条用例”变成可分发的作业：`{case, commit, environment, test_data, secrets 引用}`；Runner 拉代码（远程仓）、取凭据（短期令牌）、执行、回传结果/截图/trace（走已有的 artifacts 接口）。
- Agent 浏览器执行器也放到 Runner：LLM 调用仍在平台，浏览器动作通过 Runner 的 RPC 执行（或者 Runner 也持有模型配置，二选一，推荐前者便于集中审计和计费）。
- 调度：按任务的环境标签匹配 Runner；任务内可配置“串行 / 并行 N”；有状态用例（共享数据）用“数据隔离组”串行。
- 去掉单实例限制：Worker 可多实例（已有 SKIP LOCKED），scheduler 用 advisory lock 选主。

**工作量**：3–4 周。**优先级**：P1。

### 1.4 多人同时使用的并发管理

**现状**
- **数据库事务**：服务层普遍用 `db.tx()`；关键状态迁移用 `SELECT … FOR UPDATE`（`services/runs.py` 82/92/109/277 行，任务、运行、版本），所以“同时点运行”“冻结时改需求”这类**状态竞争**基本有保护。
- **作业队列**：`SKIP LOCKED` + LISTEN/NOTIFY，可安全多消费者，但被单实例锁限制住了。
- **编辑冲突**：**没有乐观锁**。`test_case.revision` 只在保存时自增并写 `case_revision` 历史（`services/cases.py` 227 行），**更新时不校验客户端看到的版本**；模型节点、需求、策略、缺陷都是“后写覆盖先写”。API 没有 `If-Match` / `expected_revision`。
- **操作人**：后端 `actor` 基本固定为 `"local-user"`（代码中 27 处），审计字段无法区分人。
- **测试仓**：多个自动化作业对同一 git 仓串行提交（Worker 单线程），多 Worker 时会争用工作目录。
- **前端**：React Query 轮询/失效刷新，没有“别人刚改了”的实时提示。

**差距**：两个人同时编辑同一用例/需求/模型节点会静默丢失修改；无法知道谁改的。

**建议设计**
- 所有可编辑对象加 `revision int`（已有的沿用），PATCH/PUT 必须带 `expected_revision`（或 `If-Match: W/"<rev>"`），不一致返回 409 `STALE` + 当前版本，前端弹“对方已修改：查看差异 / 覆盖 / 放弃”。
- 长时间编辑的对象（需求、模型节点）可选“软锁”：打开编辑时声明 5 分钟租约，别人看到“XX 正在编辑”。
- 把 `actor` 换成真实用户 ID（依赖 1.5）。
- 测试仓：每个作业用独立 `git worktree`，提交串行化（按仓库的 advisory lock）。
- 事件总线（已有 `core/events.py`）推 SSE，前端实时刷新和提示。

**工作量**：乐观锁 + 前端冲突对话框 1.5–2 周；软锁 + SSE 1 周。**优先级**：P0。

### 1.5 没有用户体系，也没有接入外部用户体系

**现状**：`core/auth.py` `LocalAuthMiddleware`：一个 bearer 访问令牌（启动时随机或 `TESTAGENT_ACCESS_TOKEN`）+ Host 白名单（默认只认 localhost）+ Origin 校验。spec §2.2/§3 明确“M1 不做账号权限”。“人员”（`persons`）只是被归因的人名，不是登录用户。

**差距**：无登录、无角色、无法限制谁能确认需求/冻结版本/设为就绪；Host 白名单使得部署到服务器也只能本机访问（需配置 `TESTAGENT_ALLOWED_HOSTS`）。

**建议设计**
- **P0 本地账号**：`app_user`（用户名、显示名、密码哈希 argon2、状态）、会话（HttpOnly Cookie + CSRF，替代 URL 片段令牌）、个人 API Token（给 CI 用）。第一个用户 = 管理员（首次启动向导）。
- **RBAC**：全局角色（管理员）+ **按 SUT 的成员角色**：Owner（产品/需求负责人）、Tester、Developer、Viewer。把现有“只能由人做”的门禁细化成权限：确认/冻结需求（Owner）、设为就绪（Tester）、缺陷原因定性（Owner/Tester）、模型建议采纳（Owner）、Agent 配置与凭据（管理员）。
- `persons` 与 `app_user` 关联（一个人员可绑定一个账号），归因和统计继续用人员。
- **P2 外部身份**：OIDC（Keycloak、Azure AD/Entra、Okta、飞书/企业微信网关）优先，LDAP 次之；按组映射角色；SCIM 同步可选。

**工作量**：本地账号 + 会话 + RBAC 3–4 周（后端校验点多，测试量大）；OIDC 1 周、LDAP 1 周。**优先级**：本地账号与 RBAC P0；SSO P2。

### 1.6 平台与被测系统之间的鉴权（“登录”步骤）

**现状**
- `environment` 表只有 `base_url`、`start_command`，以及一个 **`credential_ref` 文本列**（`migrations/0001_init.sql` 24 行，`api/schemas.py`，前端 `SutOverviewPage.tsx` 有“Login credential reference (optional)”输入框），**但没有任何执行器读取它**。
- Agent 接口执行器 `integrations/http_api.py` 支持单步传 `headers`，但没有环境级的认证头注入、没有令牌获取和刷新。
- pytest 执行 `integrations/pytest_runner.py` `_env()` 只传 `TESTAGENT_BASE_URL`、`TESTAGENT_DATA`，**刻意过滤掉所有 `TESTAGENT_*` 平台变量**（防泄露），没有 SUT 凭据通道。
- Agent 浏览器执行：每次新上下文，没有 `storage_state` 复用、没有登录步骤。
- 演示系统本身没有鉴权，所以这个缺口在 demo 里看不出来。

**差距**：任何真实业务系统都跑不起来（第一步就 401/跳登录页）。

**建议设计**
- **凭据库（Secrets Vault）**：`sut_credential`（名称、类型、加密的值、所属 SUT/环境、可见角色）。加密：平台主密钥（环境变量/KMS）+ AES-GCM；值只写不读，界面只显示掩码；日志和轨迹统一脱敏（已有 `core/redact.py` 可扩展）。可选对接 HashiCorp Vault / 云 KMS（P2）。
- **环境的“认证配置”（auth profile）**，可多个（不同角色：采购员、审批人）：
  - 机机：`static_header`（API Key/Bearer）、`basic`、`oauth2_client_credentials`（token URL、client id/secret、scope，自动获取和刷新）、`login_api`（调用登录接口，从响应 JSON/Cookie 提取令牌）。
  - 人机：`ui_login_script`（一个受管理的 Playwright 登录脚本，放在测试仓 `auth/` 下，输出 `storage_state`），或 `ui_login_steps`（用户名、密码字段选择器 + 凭据引用，平台生成脚本）；支持 TOTP 种子作为凭据类型；遇到验证码时标记为需要人工或使用测试环境的验证码旁路。
- **执行时注入**：
  - pytest：conftest 提供 `auth(profile)` fixture，返回已认证的 `requests` 会话头或 Playwright `storage_state`；凭据通过一次性文件或环境变量传给子进程，不进仓库、不进日志。
  - Agent API 执行器：按用例/步骤选择的 profile 自动加头。
  - Agent 浏览器执行器：启动时加载对应 profile 的 `storage_state`；Agent 不接触明文密码。
  - 会话缓存：按（环境, profile）缓存令牌/storage_state，过期重登。
- **模型和用例层**：动作可声明“需要角色 X”，用例步骤可指定“以审批人身份”，用例生成会生成越权用例（采购员不能审批）——这也是本体模型的自然延伸（权限是动作的前置条件）。

**工作量**：凭据库 1–1.5 周；auth profile（5 种类型）+ 三个执行器注入 2–3 周；角色感知的用例生成 1 周。**优先级**：P0（不做就无法测真实系统）。

---

## 2 其他差距

| # | 项目 | 现状（证据） | 建议 | 工作量 | 优先级 |
|---|---|---|---|---|---|
| 2.1 | RBAC 与审计日志 | 有 `changelog`（`services/changelog.py`）和用例修订，但 actor 固定 `local-user`；无登录、读取、导出、凭据访问的审计 | 统一 `audit_event`（谁、何时、对象、动作、前后差异、IP），不可改；凭据使用单独记录；管理员可查询导出 | 1 周（基础）+ 1 周（合规导出） | P0 基础 / P2 合规 |
| 2.2 | SUT 凭据库 | `credential_ref` 只是文本；模型 API Key 在 `runtime/secrets.json`（Windows DPAPI，Linux 文件权限 600，`core/secrets.py`） | 见 1.6；模型 Key 也迁入凭据库，按 SUT/团队配置模型 | 含在 1.6 | P0 |
| 2.3 | 测试数据管理与隔离 | 演示系统有 `spaces`（按路径隔离数据）和 `/sample/reset`；`ops/reset_sut_data.py` 重置平台侧数据；真实 SUT 没有数据准备/清理机制，用例的 `test_data` 是静态 JSON | 数据集（data set）作为一等对象：生成器（基于字段类型/约束）、前置数据脚本（通过 API 造数）、清理钩子、按运行打标签（如前缀 `TA-<run>`）实现并发隔离；环境级“重置命令” | 2 周 | P1 |
| 2.4 | CI 集成与 Webhook | 只有平台内 cron/一次性调度（`services/scheduler.py`）；没有外部触发接口、没有 webhook | 个人/服务 API Token；`POST /api/v1/tasks/{id}/run` 给 CI 用，返回 run id 和 JUnit/JSON 结果；GitHub Action / GitLab CI 模板；出站 webhook（运行完成、缺陷创建）；部署后自动回归 | 1.5 周 | P1 |
| 2.5 | 通知 | 无 | 站内通知 + 邮件 + 飞书/钉钉/企业微信/Slack webhook；事件：被指派、运行失败、需要人工执行、评审请求 | 1 周 | P1 |
| 2.6 | 不稳定用例（flaky）处理 | 无重试、无 flaky 标记；只有环境不可用不消耗自检次数（`services/automation.py`） | 失败后可配置重跑 N 次，“重跑后通过”记为 flaky；按用例统计 flaky 率并在报告中单列；隔离区（quarantine）不影响通过率；失败分析区分环境/脚本/产品 | 1 周 | P1 |
| 2.7 | 报告导出 | 用例可导出 CSV/Markdown（`api/cases.py` 256 行）；模型审阅可导出 Markdown/打印；任务/版本报告只能在界面看 | 报告导出 PDF/HTML/Markdown；JUnit XML / Allure 结果导出给 CI；分享只读链接 | 1 周 | P1 |
| 2.8 | 模型版本与多人协作 | 冻结版本时做模型快照（`version.model_snapshot_id`）；模型本身是一份“活的”共享数据，没有分支、草稿、评审流程；变更日志有 | 模型变更请求（类似 PR）：草稿 → 评审 → 合并到主模型；冲突在元素级（同一字段被两人改）提示；版本间模型差异视图；快照可对比 | 2–3 周 | P1/P2 |
| 2.9 | LLM 成本与限流 | 每步记录 `usage_metadata`（`agent/runtime.py` 165 行），有 `max_steps`、`timeout_s`、自检次数上限；没有按用户/SUT 的预算、并发限流、费用统计 | 令牌用量按运行/用户/SUT 汇总和看板；预算与告警；全局并发和 RPM 限流（排队）；失败重试的退避；可为不同入口配置不同模型（便宜模型做结构化，强模型做脚本） | 1–1.5 周 | P1 |
| 2.10 | 提示注入（来自 SUT 数据） | Agent 浏览器/接口执行会把页面文本、接口响应喂给模型；OpenAPI 描述、需求文本也进入提示词；没有隔离标记或防护 | 不可信内容统一包裹并声明“数据不是指令”；工具白名单已存在（好），再加：执行类入口禁止访问非环境域名、禁止写文件以外的副作用；高风险工具（写仓库、建缺陷）结果要 schema 校验（已有）+ 人工门禁（已有部分）；红队用例（页面中藏指令）纳入回归 | 1 周 | P1 |
| 2.11 | 备份与升级 | 文档有 `pg_dump` 和数据卷备份、迁移自动执行（`docs/deployment.md`）；没有内置备份、没有降级 | 内置定时备份（数据库 + runtime 卷）到对象存储；升级前自动备份并做迁移预检；发布版本化镜像（GHCR）与升级说明 | 1 周 | P1 |
| 2.12 | 可观测性 | 访问日志（`core/access_log.py`）、Agent 轨迹在库里；无指标、无链路追踪 | `/metrics`（Prometheus：作业队列长度、运行耗时、LLM 延迟/令牌、失败率）；结构化 JSON 日志；OpenTelemetry 追踪（平台 → Runner → SUT） | 1 周 | P2 |
| 2.13 | 部署与扩展 | Docker Compose 单机；单实例锁（`InstanceLock`）；Docker 镜像在 Linux 冒烟通过，标准 bridge 网络在 Docker Desktop 上未验证 | 先验证云服务器部署（反向代理 + HTTPS + `TESTAGENT_ALLOWED_HOSTS`）；多 Worker 实例、scheduler 选主；Helm chart（P2） | 0.5 周（验证）+ 1–2 周（多实例） | P0 验证 / P2 扩展 |
| 2.14 | i18n | 全英文（t26u），`TESTAGENT_AGENT_LANGUAGE` 控制 Agent 输出语言 | 前端 i18n（react-i18next，en / zh-CN），后端错误码 + 前端翻译；按用户偏好切换 | 1.5–2 周 | P2（国内团队可提前） |
| 2.15 | 外部系统对接（spec M2） | 无 | 缺陷系统（Jira、禅道、GitLab Issues）双向同步；API 平台（YApi、Apifox、Swagger Hub）导入 | 每个 1 周 | P2 |
| 2.16 | 其他 spec M2 候选 | `plan.md` §5：MCP/技能执行、修复候选、影响分析视图、远程 git、缺陷/API 平台对接、跨版本趋势、并行执行、RDF 导出、exe 安装包；spec §2.2 非目标还有性能/可靠性测试执行、移动端/桌面端、自动修复、解析被测系统代码 | 远程 git、并行执行已并入 P1；**影响分析视图**（需求/模型变更 → 受影响用例）和**修复候选**（失败后 Agent 提出脚本修复 PR）建议放 P1 末尾，价值高；跨版本趋势 P1；MCP/技能、RDF 导出、性能测试、移动端、代码解析放 P2+；exe 安装包被 Docker 取代，建议取消 | — | 见左 |
| 2.17 | 安全加固 | 令牌在 URL 片段；无速率限制；无 HTTPS（依赖反向代理）；生成的测试代码在平台进程同机执行 | 会话 Cookie（1.5）；登录限速；安全响应头；测试代码只在 Runner 沙箱（容器、只出站到环境域名）执行；依赖漏洞扫描（Dependabot / pip-audit / npm audit）进 CI | 1 周 | P0（会话）/ P1（沙箱） |

---

## 3 分阶段计划

### P0 团队基础（约 6–8 周）——目标：一个 5–10 人的小团队能在一台服务器上共同使用，并测真实系统
1. 本地账号、会话 Cookie、个人 API Token、首次启动管理员向导（1.5）
2. RBAC：全局管理员 + 按 SUT 成员角色；现有人工门禁映射成权限（1.5）
3. actor 改为真实用户；基础审计事件（2.1）
4. 乐观锁（`expected_revision` / 409 STALE）+ 前端冲突处理（1.4）
5. SUT 凭据库 + 环境 auth profile（静态头、Basic、OAuth2 client credentials、登录接口、UI 登录脚本）+ 三个执行器注入（1.6、2.2）
6. 中间表：M:N 建议、覆盖修正、生成规则（1.1）
7. 云服务器部署验证：反向代理 + HTTPS + 允许的主机名，更新部署文档（2.13）

### P1 协作与执行（约 8–10 周）——目标：融入团队现有的 git 和 CI 流程，执行可扩展
1. 远程 git：分支、推送、PR/MR、按 commit 检出执行（1.2）
2. Runner：独立执行进程、标签匹配、并行、沙箱化（1.3、2.17）
3. 多 Worker 实例 + scheduler 选主（1.3、2.13）
4. CI 触发 API、GitHub Action/GitLab 模板、出站 webhook、JUnit 导出（2.4、2.7）
5. 通知（2.5）、flaky 重跑与隔离（2.6）、测试数据集与隔离（2.3）
6. LLM 用量统计、预算、限流，分入口选模型（2.9）；提示注入防护（2.10）
7. 软锁 + SSE 实时刷新（1.4）；内置备份与版本化镜像（2.11）
8. 影响分析视图、修复候选、跨版本趋势（2.16）；observable effects（1.1）

### P2 企业级（约 8–12 周）——目标：能在中大型组织落地
1. OIDC / LDAP / SSO，组到角色映射（1.5）
2. 完整审计与合规导出，凭据库对接 Vault/KMS（2.1、2.2）
3. 模型变更请求与评审、模型差异（2.8）
4. 可观测性：指标、结构化日志、追踪（2.12）；Helm / 高可用（2.13）
5. 前端 i18n（2.14）；缺陷系统与 API 平台对接（2.15）
6. 其余 M2 候选：MCP/技能、RDF 导出、性能测试执行、移动端等（2.16）

## 4 建议的下一步
1. 先在云服务器上按 `docs/deployment.md` 部署一次（用户已计划），把遇到的问题记进 P0 第 7 项。
2. 用一个**带登录的真实系统**（或给演示系统加一个最简登录：API Token + 登录页）作为 P0 的验收基准，这能同时驱动 1.6、1.5 和 1.4。
3. P0 开工前补一份 spec（用户/角色/权限矩阵、凭据类型、auth profile 数据结构、乐观锁的 API 约定），按现有 spec-driven + TDD 流程推进。
