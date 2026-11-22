# TestAgent 平台规格 v1.2（维护基线）


> 2026-11-09 维护：对应 develop `f8eb361`。沿用 D01–D38、C、US/AC、BR 编号；本轮校正被后续实现替代的条款，并新增 BR-42–BR-48。下方旧日期记录需求来源，不表示当前仍待确认。实现程度见 [审查](review-2026-11-09.md) 和 [任务状态](task-status.md)；页面标为“完整”表示目标深度，不是验收签收。
>
> 产品定位：通用测试平台 + 受控 Agent。测试设计和测试用例/脚本开发由 AI 在测试人员指导下完成，关键业务决策由人确认。当前本体是 Python + PostgreSQL 关系模型，不是 OWL 推理引擎；官方 Playwright Test Agents 尚未直接接入。

日期：2026-10-31（v1.1 已按用户对假设的审阅意见修订；2026-11-01 按 DeepSeek 试用反馈和用户决定补充 D17–D20、BR-13–BR-16，见批次 1；同日按用户反馈 t16u 补充 D21、BR-17–BR-18，见批次 1b；t17u 补充 D22、BR-19，见批次 1c；t18u 补充 D23、BR-20–BR-21，见批次 1d；t19u 补充 D24–D27、BR-22–BR-26，见批次 1e；2026-11-02 按用户反馈 #3、#4 补充 D28–D31、BR-27–BR-30，见批次 2；t20u 补充 D32、BR-31，见批次 t20u；t24u 补充 D33–D34、BR-32–BR-36，见文末“批次 t24u 补充”；t25 补充 D35–D38、BR-37–BR-41，见文末“批次 t25 补充”）。依据：TestAgentPRD.docx、用户澄清和确认的决策。“必须”是 M1 的验收义务；“M2”表示明确后置。

## 1 目标与已确认决策

### 1.1 目标
让 AI 有效、深度地参与 Web 软件测试。以**被测系统的本体模型**为核心、以**需求**为推进主线，把需求、代码（通过 API 注册）、测试策略/任务/用例、执行结果、缺陷和报告串起来。AI 与测试人员协作完成从模型补全到报告的全流程。缺陷能追溯到需求和真实的责任人。系统借助人工纠错持续改进 Agent。

M1 主链路：**模型补全 → 需求结构化 → AI 生成用例 → Agent 用 Playwright 执行 → 报告**。

### 1.2 已确认决策
| 编号 | 决策 |
|---|---|
| D01 | 代码里原来的“项目”指整个平台。业务层级为：被测系统 → 版本 → 需求 → 测试策略（任务集）→ 测试任务 → 测试用例 → 执行结果/报告 |
| D02 | 经 D24 替代：节点分实体、动作两类；关系用 ModelLink 表达。条件、状态、约束是节点属性 |
| D03 | 数据库用本机 **PostgreSQL 17**。业务库 `testagent`，测试库 `testagent_test`。连接串只从被 git 忽略的 `.env` 读取，变量名为 `TESTAGENT_DATABASE_URL` 和 `TESTAGENT_TEST_DATABASE_URL`。**文档、代码和日志里都不能出现密码** |
| D04 | 本体用关系表存储：节点表 + 边表 + JSONB 属性，用 Pydantic 校验，用递归 CTE 遍历。v1 不用 RDF/SHACL |
| D05 | 平台内置简单的 API 注册表，关联方式为“动作 → API → 代码位置”。外部 API 平台对接放 M2 |
| D06 | 代码位置就是普通链接或文本，怎么打开不重要。目前没有被测系统源码，v1 只登记位置，不解析代码 |
| D07 | 自动化用例代码用 Python + pytest-playwright，提交到本地 git 仓。推送远程放 M2 |
| D08 | v1 只做 Web 功能测试。性能、可靠性等类型只打标签，不执行 |
| D09 | 缺陷由人或 Agent 查看失败的执行后创建。v1 只做简单的缺陷管理和人员管理，外部缺陷系统对接放 M2 |
| D10 | **以需求为中心追责**：每条需求挂真实的责任人和角色（需求负责人/设计 owner、开发 developer、测试 tester）。缺陷归属到需求，默认从用例关联的需求推断，可以修改；再追溯到责任人，统计谁的问题最多、最严重（按数量和严重度加权）。**分组只作为节点的可选归类**，用于看图和筛选，不用于追责 |
| D11 | 大模型用 OpenAI 兼容接口，可配置 base_url、key、model、temperature 等 |
| D12 | 原始纠错先保存，再由 Agent 自动整理成记忆或提示词，无需审核。记忆可以查看和停用 |
| D13 | 每个被测系统各有一个活模型；该系统版本的需求冻结时生成模型快照，系统之间不共用活模型 |
| D14 | 前端用 React + Vite + AntD + React Flow。账号会话登录；本机启动器用一次性 ticket 换会话，替代共享 token（0022） |
| D15 | Agent 用 LangGraph 实现 ReAct 结构，检查点用 Postgres checkpointer |
| D16 | 本地优先、单实例运行；已扩展账号登录及 Docker/Caddy 可选部署。默认回环监听；服务器模式按部署文档配置，不等于已具备团队隔离/多实例能力 |
| D17 | （2026-11-01 用户决定）实体有**结构化字段表**（独立的 entity_attribute 表：名称、显示名、类型、单位、约束），需求条目通过关联表引用“实体.字段”；冻结快照包含字段；原 data_schema JSON 迁移为字段行（原 JSON 保留）。界面上称“字段”，与节点的条件/状态/约束“属性”区分 |
| D18 | （2026-11-01 用户决定）AI 生成用例时**默认**同时为每个用例生成自动化脚本（含自检），作为后台任务执行并显示进度；可在 Agent 配置或单次生成时关闭；另提供“为可执行用例批量 AI 自动化” |
| D19 | API 注册表登记请求/响应 schema，可从被测系统的 OpenAPI（`{base_url}/openapi.json`）导入；用例生成和自动化必须按 schema 构造请求 |
| D21 | （2026-11-01 用户反馈 t16u）**动作和 API 都要写清楚用途、输入、输入格式、输出、输出格式**：动作节点有“用途说明”（description）、结构化的输入/输出参数表（名称、显示名、类型、必填、位置、格式、示例、枚举取值、说明，可对应“实体.字段”）和输入/输出格式；API 注册表有用途说明、请求/响应内容类型，参数、请求体字段和成功响应字段以表格显示和编辑（写回 JSON schema）；动作绑定 API 后可继承其输入/输出。**实体字段的类型必填**，类型含 枚举（须填取值）和 引用实体（须选目标实体），另有必填、格式、示例 |
| D22 | （2026-11-01 用户反馈 t17u）**实体字段名与代码实体/接口字段名一致**（代码接口和数据库字段一般不同，但代码里的实体字段一般与接口字段相同）：以接口字段名为准（如 amount_minor、state），数据库列名不同时记在字段的“数据库列名”（storage_name）里，只作说明 |
| D23 | （2026-11-01 用户反馈 t18u）**执行前先检查被测系统环境**：环境连不上时立即用中文提示（“被测系统环境 … 无法连接，请先启动…”），不消耗自检次数、不把脚本标成“需修复”，用例标“环境不可用”（可重试）。环境可填“启动命令”，启动器启动时自动拉起、界面可一键“启动”；内置演示系统默认带启动命令。用例清单逐条显示自动化状态（排队中/生成中/已绑定/需修复/环境不可用/未自动化，带原因） |
| D24 | （2026-11-01 用户决定 t19u，参照 Palantir 的 link type）**关系是实体之间的“关系类型”，不再是节点**：每条关系有两端读法（正向/反向名称，用介词或动词，如 采购单 属于 供应商 ／ 供应商 提供 采购单；付款记录 支付 采购单 ／ 采购单 收到 付款记录）、两端 API 名（如 supplier / purchaseOrders）、基数、外键字段、是否必填和说明。原有关系节点迁移为关系后归档（软删除），需求关联随之迁移 |
| D25 | （t19u）**基数现在就支持 1:1、N:1、1:N、M:N**；M:N 可以由中间实体承载（关系记录中间实体及其指向两端的两个外键字段）。外键字段名与接口/代码字段名一致（如 supplier_id、order_id，见 D22） |
| D26 | （t19u，参照 Palantir 的 action type：submission criteria + rules）**动作有结构化的前置条件和影响**：前置条件是“实体.字段 运算符 取值”（如 采购单.state == pending，可带不满足时的提示，也可写文字条件）；影响是执行后哪些字段变成什么值（如 采购单.state → approved | rejected，可注明何时）、创建/删除哪类对象、建立/解除哪条关系。用例生成和自动化据此覆盖满足/不满足前置条件、断言影响和基数边界 |
| D27 | （t19u）**关系由平台自动建议、人工采纳**：实体新增“引用实体”类型或名为 `<资源>_id` 的字段、以及 OpenAPI 导入后，平台生成“关系建议”（默认 属于/拥有、N:1，带外键）；AI 也可提出关系和前置条件/影响建议。采纳时可修改两端读法、API 名和基数。需求结构条目可关联关系 |
| D28 | （2026-11-02 用户反馈 #3：模型/版本/测试策略/任务/用例之间跳转生硬、不好找）**主流程步骤条**：选中被测系统后，页面顶部常驻主流程步骤条 被测系统 → 模型 → 版本/需求 → 测试策略 → 任务 → 用例 → 执行 → 缺陷/报告，按当前被测系统/版本显示每步完成状态（已完成/进行中/未开始）和一句摘要，给出“下一步”建议按钮；每一步可点击跳转 |
| D29 | （反馈 #3）**面包屑与互链**：所有详情页显示面包屑 被测系统 / 版本 / 需求 / 测试策略与任务 / 任务 / 执行批次 / 用例 / 执行；相关对象之间一律用“名称 (编号)”可点击链接互链（需求 ↔ 模型节点/字段/关系，用例 ↔ 需求/脚本/执行，任务 ↔ 策略/用例，缺陷 ↔ 用例/执行/批次）。顶部有全局“当前被测系统 / 当前版本”选择器，上下文保存在 URL（详情页从对象本身推出，列表页用 sut_id/version_id 查询参数），刷新和分享链接不丢 |
| D30 | （2026-11-02 用户反馈 #4：不理解“被测系统”所以没法审阅模型）**被测系统说明与空状态**：被测系统列表和概览页用一段白话解释“被测系统 = 你要测试的那个系统，它有环境、模型、版本和本地测试仓”，概览页显示本地测试仓的**绝对路径**（可复制）和“上手清单”（每步为什么要做 + 按钮）；每个列表页为空时给出说明和主操作按钮 |
| D31 | （反馈 #4）**模型审阅视图**：被测系统有只读的“模型审阅”页：实体及字段（类型、必填、API 名）、关系两个方向的读法和基数、动作的用途/输入输出/前置条件/影响/绑定接口；每个元素显示被哪些需求和用例覆盖，未覆盖的高亮；显示待审模型建议数；审阅清单可逐项标记“已审阅”（持久保存，元素修改后提示“审阅后已变更”）；可导出 Markdown、可打印。“已审阅”只是审阅辅助记号，不等于采纳建议（C01 不变） |
| D32 | （2026-11-21）**示例被测系统是供应链执行**：`examples/supply_chain`，系统代码 `supply-chain`，中文名「供应链执行（演示）」，地址 127.0.0.1:8766。示例应用是已经开发完成的 v2（质检、超收容差、合格供应商才能下达）。平台种子有 v1.0（已封板，REQ-001～REQ-012，含正文和结构）与 v2.0（复制模型后只登记 REQ-007～REQ-009 和 REQ-013～REQ-016，含正文，不含结构化引用）。`POST /sample/reset` 重置示例业务数据；`ops/restore_supply_chain.py` 还原平台里的该系统。 |
| D20 | Agent 运行绑定被测系统时，工具默认且只作用于当前被测系统；工具参数接受编号（REQ-001、TC-002、系统代码）和 UUID；界面上一律显示名称 + 编号，不显示裸 UUID |
| C01 | AI 只能起草。需求确认、版本冻结、用例设为可执行、缺陷关闭、缺陷原因类别的最终确定，都由人操作 |
| C03 | 每个被测系统一个本地测试仓，默认放在 `runtime/repos/<sut_code>/`，也可以指定已有的仓 |
| C04 | 任务内某个用例出错时，继续执行后面的用例 |
| C05 | 缺陷密度 = 缺陷数 ÷ 范围内已执行的用例数 |
| C06 | API key 存在本地密钥文件 `runtime/secrets.json`（Windows 用 DPAPI 加密），不进数据库 |
| C07 | 技能/MCP 在 M1 只做登记和停用，不加载执行。Agent 的浏览器能力用平台自己封装的 Python Playwright 工具 |
| C08 | 周期调度只在平台运行期间生效，错过的周期不补跑 |
| C09 | 纠错提交后立即在后台整理，也可以手动重新整理 |
| C11 | 由人执行的用例不阻塞后续用例。run 结束时仍未执行的，在报告里计入“未执行” |
| C10 | 在 `D:\CodeWork\TestAgent` 整个目录层面整理旧文件，不需要的归档。目标布局见 design/architecture.md §1.1；整理本身是规格确认后的单独任务 |

## 2 范围

### 2.1 M1 范围
- 被测系统、环境、可选分组、人员管理（含人员统计）。
- 本体模型（图 + 列表）和 API 注册表。
- 版本与需求：结构化、责任人。
- 测试策略与任务、测试用例（手动/自动化）、覆盖报告。
- 执行：Agent 用浏览器执行、自动化代码执行、人工执行、单用例调试。
- 任务串行执行和调度（一次/周期）。
- 缺陷：归属需求，归因到人。
- 报告：任务级、版本级，含人员排行。
- Agent 配置、提示词、记忆、纠错。
- 扩展点骨架。

### 2.2 非目标（M1 不做）
- 按被测系统的成员授权、并发编辑冲突处理、完整团队协作（基础 admin/member 账号已实现）。
- 多实例高可用、远程 Runner 和并行执行（已有单实例 Docker/HTTPS 部署配置；线上运行状态须另行验收）。
- 推送远程 git 仓。
- 对接外部缺陷系统或 API 平台。
- 性能/可靠性测试的执行。
- 移动端或桌面端测试。
- 用例失败后的自动修复。
- 跨版本趋势图（人员统计支持按版本范围筛选，但不画趋势）。
- RDF/OWL 导入导出。
- MCP/技能的加载执行。
- 解析被测系统代码。

## 3 角色
本地单人仍为首要场景，也支持受信任使用者通过账号访问同一实例。admin/member 是平台操作角色；下面的业务角色可以由同一人兼任。Person 责任人不自动等同登录账号，也尚无按被测系统隔离的成员权限。
- **设计人员**：建立和维护被测系统模型。
- **测试人员**：补全需求、审阅策略和用例、执行测试、纠错。
- **版本管理员**：确认版本的需求已经整理完毕（冻结）。
- **需求责任人**：一条 Person 数据，以角色挂在需求上（owner、developer、tester），用于缺陷归因和报告统计。
- **Agent**：执行受控工具，只能通过 `submit_result` 写入它被允许写的对象。

## 4 用户故事与验收

| 编号 | 用户故事 | 验收（可观察） |
|---|---|---|
| US-01 | 作为设计人员，我能登记被测系统、环境和可选的分组 | AC-01：新建被测系统“采购审批”并加一个环境（base_url），列表页能看到；重启后数据还在 |
| US-02 | 作为设计人员，我能维护实体、动作、字段和关系类型 | AC-02：建 ≥10 个实体/动作节点及 ≥2 条 ModelLink，维护字段及条件/状态/约束；图与列表来自同一结构化模型；关系两端为同系统实体，禁止新建 relation 节点（D24） |
| US-03 | 作为设计/开发人员，我能登记 API，并把动作节点关联到 API 和代码位置链接 | AC-03：登记 `POST /orders`，代码位置填一段链接或文本，关联到动作“创建采购单”；节点详情页能看到 |
| US-04 | 作为测试人员，我能录入需求，并给需求挂上责任人和角色 | AC-04：一条需求有 1 个 owner，以及开发、测试各 ≥1 人；人员页能看到每个人参与的需求和角色；没有 owner 的需求不能确认 |
| US-05 | 作为测试人员，我能让 AI 把需求结构化为“谁/条件/动作/结果/约束”并关联节点 | AC-05：AI 返回结构化草稿，各部分关联到已有节点或标“缺失”；我修改后确认，需求页能看到关联节点 |
| US-06 | 作为测试人员，我能采纳 AI 提出的模型补全建议 | AC-06：缺失的节点或属性以建议列表给出，逐条采纳后写入模型并回填需求的关联；拒绝的建议保留记录 |
| US-07 | 作为版本管理员，我能冻结版本需求 | AC-07：所有需求都确认后才能冻结；冻结时生成模型快照；冻结后需求不能修改，除非先解冻（解冻要写理由并留下记录） |
| US-08 | 作为测试人员，我能让 AI 制定测试策略和任务集，并能手动修改 | AC-08：AI 给出范围、类型标签、强度和任务列表；我修改后确认；策略页能看到覆盖度和等级分布 |
| US-09 | 作为测试人员，我能让 AI 按需求生成多个用例，也能手写用例；同时得到用例清单和覆盖报告 | AC-09：3 条需求生成 ≥9 个用例，字段齐全（测试点、步骤、数据、预期、等级、关联需求和节点）；覆盖报告列出没有用例的需求和动作节点 |
| US-10 | 作为测试人员，我能把用例关联到任务；任务可以先于用例创建 | AC-10：先建空任务，再挂用例并排序；也可以建任务时直接选用例 |
| US-11 | 作为测试人员，我能让 Agent 用浏览器执行手动用例，执行步骤会结构化保存 | AC-11：在采购演示系统上执行一个用例，记录每一步（动作、目标、值、截图）和结果；断言失败时记录失败断言和测试数据 |
| US-12 | 作为测试人员，我能让 AI 把用例生成为 pytest-playwright 代码并提交到本地仓，还能单独调试 | AC-12：仓里出现 `tests/<req_code>/test_<case_code>.py` 并有 commit；调试能拿到 pass/fail 和失败断言；用例记录了 code_path 和 commit |
| US-13 | 作为测试人员，我能执行一个任务（串行），也能设置定时或周期执行 | AC-13：执行一个含 5 个用例的任务，能看到进度；取消后不再启动新的用例；设一个 cron 周期，平台运行期间会按时触发 |
| US-14 | 作为测试人员，我能人工执行用例并记录结果 | AC-14：填写结果、实际数据和附件后保存，结果计入报告 |
| US-15 | 作为测试人员或 Agent，我能从失败的执行创建缺陷，缺陷自动归属到需求和责任人 | AC-15：一键建缺陷，自动带出该用例关联的需求（可以增删）、节点和 API；选择原因类别后，默认归因人从需求对应角色中带出，可以修改；Agent 创建的缺陷附原因分析和建议的原因类别 |
| US-16 | 作为测试人员，任务执行完后自动得到报告，也能生成版本报告 | AC-16：报告包含通过率、失败明细、按需求统计（缺陷数、密度、加权分）、人员排行（归因数和加权分，以及关联数）、关联的需求和代码（API）、AI 总结；报告生成后不可修改 |
| US-17 | 作为测试负责人，我能按范围查看谁的问题最多、最严重 | AC-17：人员统计页按版本或时间范围，列出每个人的归因缺陷数、加权严重度分、按角色拆分、涉及的需求；可以排序并下钻到具体缺陷 |
| US-18 | 作为测试人员，我能指出用例、策略、报告中的问题，Agent 会整理并在后续生效 | AC-18：纠错原文保存；Agent 自动整理成记忆或新版本提示词；再次生成用例时会注入这些记忆（轨迹里可以看到）；记忆可以停用 |
| US-19 | 作为使用者，我能配置大模型并测试连接 | AC-19：base_url、key、model、temperature 配置后测试连接成功；key 脱敏显示，不进数据库、日志和导出；没配置时 AI 按钮不可用并给出提示 |
| US-20 | 作为使用者，双击启动器就能自动登录工作台 | AC-20：启动器启动服务并打开浏览器后自动登录；跨 Origin 请求、未登录的受保护接口请求及缺少有效 CSRF 的写请求被拒绝；ticket 只能使用一次；账号退出后旧会话失效 |

## 5 领域模型

### 5.1 实体
| 实体 | 关键字段 | 说明 |
|---|---|---|
| Person | name, title, email, active | 职务只作描述，具体角色挂在需求上 |
| SystemUnderTest (SUT) | code, name, description, test_repo_path | 被测系统 |
| Environment | sut_id, name, base_url, credential_ref | 凭据只存引用 |
| Module | sut_id, name, description | **可选**的节点分组，只用于看图和筛选，没有负责人 |
| ModelNode | sut_id, module_id?, kind, name, description, data_schema, attributes{conditions[], states[], constraints[]}, code_ref, inputs[], outputs[], input_format, output_format, preconditions[], effects[] | 新建 kind ∈ entity/action（relation 只存在于 t19u 之前的历史数据，已迁移并归档，D24）；data_schema 为旧格式，已迁移为 EntityAttribute；动作的 description 即“用途说明”，inputs/outputs、preconditions/effects 只属于动作（D21、D26） |
| ModelLink（关系类型） | sut_id, from_node_id, to_node_id, forward_name, reverse_name, forward_api_name?, reverse_api_name?, cardinality, fk_attribute_id?, via_node_id?, via_from_attribute_id?, via_to_attribute_id?, required, description, legacy_node_id?, deleted_at | 两端都是实体；cardinality ∈ one_to_one/many_to_one/one_to_many/many_to_many；外键在“多”的一端（N:1 在起点、1:N 在终点，1:1 任一端），M:N 不用外键、可用中间实体；同一对实体下正向名称唯一；同一实体上 API 名唯一；软删除（D24、D25） |
| Precondition（动作前置条件，JSON 内嵌） | field?/attribute_id?, op, value, text?, message? | op ∈ eq/ne/in/not_in/gt/gte/lt/lte/is_null/not_null；field 为“实体.字段”，保存时解析为 attribute_id；枚举字段的取值必须在枚举内；不涉及字段时只写 text（D26） |
| Effect（动作影响，JSON 内嵌） | kind, field?/attribute_id?, values[], node_id?/entity?, link_id?, when?, text? | kind ∈ set_field（字段可能的新值）/create_object/delete_object（实体）/create_link/delete_link（关系）；when 说明在什么情况下（D26） |
| RequirementLinkRef | requirement_id, link_id, role | 需求条目关联的关系（role 同 RequirementNodeLink） |
| IoParam（动作/接口参数，JSON 内嵌） | name, display_name?, data_type, required, location?(path/query/header/body/form/response/ui), format?, example?, enum_values[], description?, field?/attribute_id? | data_type 必填，取值同字段类型；enum 必须有取值；同一列表内（位置 + 名称）唯一；field 为“实体.字段”，保存时解析为 attribute_id（不存在则拒绝） |
| EntityAttribute（字段） | sut_id, node_id, name, display_name, data_type, unit, required, format, example, enum_values[], ref_node_id?, storage_name?, constraints[], description, position, deleted_at | 只属于实体节点；data_type **必填** ∈ string/integer/number/decimal/money/boolean/date/datetime/enum/reference/object/array；enum 须有取值，reference 须指向同系统的实体；同一实体内名称唯一（不区分大小写），软删除 |
| RequirementAttributeLink / CaseAttributeLink | requirement_id 或 case_id, attribute_id（需求带 role） | 需求条目、用例与字段的关联，用于字段覆盖 |
| ModelEdge | sut_id, source_node_id, target_node_id, role | 动作的参与实体（actor/object）；role=source/target 只出现在已归档的旧关系节点上 |
| ApiEndpoint | sut_id, method, path, name, description, code_ref, request_schema, response_schema, request_content_type, response_content_type, operation_id, schema_source | description 即“用途说明”；code_ref 是普通链接或文本；schema 手工填写（JSON 或字段表）或从 OpenAPI 导入（schema_source=manual/openapi）；接口返回时附带由 schema 生成的 io{inputs, outputs, input_format, output_format} |
| NodeApiLink | node_id, api_id | 动作和 API 是 N:M |
| Version | sut_id, name, status, frozen_at, model_snapshot_id | |
| ModelSnapshot | sut_id, version_id, content, digest | 不可变 |
| Requirement | version_id, code, title, raw_text, structured, priority, status | 主线对象 |
| RequirementPerson | requirement_id, person_id, role | role ∈ owner/developer/tester，每种角色可以多人；确认需求时至少要有 1 个 owner |
| RequirementNodeLink | requirement_id, node_id, role | role ∈ actor/condition/action/result/constraint |
| ModelSuggestion | sut_id, requirement_id?, agent_run_id, payload, status | 模型补全建议；kind ∈ node/attribute/field/io/link/rules（io = 为已有动作补用途和输入/输出；link = 新关系；rules = 为已有动作补前置条件/影响） |
| TestStrategy | version_id, scope, test_types[], intensity, notes, status, revision, snapshot_id | 一个版本一份当前策略 |
| TestTask | version_id, strategy_id?, name, kind, executor, environment_id, schedule, status, next_run_at | |
| TaskCase | task_id, case_id, seq, source, reason, added_at | 来源 rule/manual，人工排除保存在 TaskCaseExclusion（D37） |
| TestCase | sut_id, origin_version_id, code, title, test_point, priority, type_tag, mode, preconditions, steps[], test_data, expected, code_path, code_commit, automation_status, automation_note, automation_draft_path, automation_draft_commit, source, status, revision | 持久自动化状态包括 ok/needs_fix/env_unavailable/sut_mismatch；排队/生成中还需结合后台作业状态展示 |
| CaseRequirementLink / CaseNodeLink | | 用例和需求、节点的 N:M 关联 |
| CaseRevision | case_id, revision, content, author | 用例修订历史 |
| CoverageReport | version_id, content | |
| TaskRun | task_id, trigger, status, started_at, ended_at, cancel_requested | |
| CaseExecution | task_run_id?, case_id, executor, status, result, failed_assertion, test_data, steps_recorded[], artifacts[], duration_ms, error | task_run_id 为空表示单用例调试 |
| Defect | sut_id, version_id, execution_id?, case_id?, title, description, severity, status, cause_category, created_by, analysis | severity ∈ critical/major/minor/trivial；cause_category ∈ requirement/design/development/test/environment/unknown |
| DefectRequirement | defect_id, requirement_id, inferred | 缺陷归属的需求，可以多条 |
| DefectResponsible | defect_id, person_id, role, inferred | 缺陷归因的人 |
| SeverityWeight | severity, weight | 默认 critical=10、major=3、minor=1、trivial=0.1，可以修改（用户决定，2026-10-31） |
| Report | scope_type(task_run/version), scope_id, content, ai_summary, weights_used | 不可变 |
| Correction | target_type, target_id, content, author, status, processed_at | 纠错原文 |
| AgentConfig | base_url, model, temperature, max_tokens, timeout_s, max_steps | 单例；key 存在密钥文件里（C06） |
| PromptTemplate | name, version, content, active, source_correction_ids[] | 有版本，可以回滚 |
| AgentMemory | scope(global/sut), sut_id?, content, tags[], enabled, source_correction_ids[] | 可以停用 |
| Skill / McpServer | name, description, content/command, enabled | M1 只登记（C07） |
| AgentRun | purpose, input_refs, status, steps, token_usage, error | 运行轨迹 |
| ModelReviewMark（模型审阅记号） | sut_id, target_type, target_id, reviewed, digest, note, reviewed_by, reviewed_at | target_type ∈ entity/action/link；同一元素一条（唯一）；digest 是标记时元素内容的摘要，内容变了即“审阅后已变更”；只是界面辅助，不影响建议和任何人工关口（D31、BR-30） |

### 5.2 关系概要
- SUT 1:N Environment / Module / ModelNode / ApiEndpoint / Version / TestCase。
- Module 1:N ModelNode（可选）。
- Version 1:N Requirement / TestTask，1:1 TestStrategy。
- **Requirement N:M Person（带角色）**；Requirement N:M ModelNode、ModelLink；TestCase N:M Requirement、ModelNode。
- **ModelLink**：实体 ↔ 实体（两端读法 + 基数 + 外键/中间实体，D24–D25）。
- TestTask N:M TestCase（有顺序）；TaskRun 1:N CaseExecution；CaseExecution 0:N Defect。
- **Defect N:M Requirement；Defect N:M Person（归因）**。

追溯链：缺陷 → 需求 → 责任人；缺陷 → 用例 → 节点 → API → 代码位置。

### 5.3 状态机
- **Version**：`planning → requirements_frozen → testing → closed`。允许 `requirements_frozen → planning`（解冻，必须写理由）。首次执行任务时自动进入 `testing`；关闭后只读。
- **Requirement**：`draft → structured → confirmed`。确认需要至少 1 个 owner。确认后再编辑会回到 `structured`。版本冻结后不能编辑。
- **TestStrategy**：`draft → confirmed`。确认后再编辑会回到 `draft`，revision+1。
- **TestTask**：`draft → ready → running → done`；`running → cancelled`；draft/ready/done/cancelled可归档，running不可直接归档；周期任务完成后回到ready。
- **TestCase**：`draft → ready → deprecated`，ready也可退回draft。只有ready的用例会被任务执行。
- **TaskRun**：`queued → running → passed | failed | error | cancelled | not_executed`；queued 也可进入 cancelled/error。零实际执行不能判 passed（BR-42）。
- **CaseExecution**：`queued → running → passed | failed | error | blocked | skipped`。人工执行的用例记为 `blocked(awaiting_human)`。
- **Defect**：`open → in_progress → resolved → closed`；`open/in_progress → rejected`；`resolved → open`（重新打开）。

## 6 页面清单
| 页面 | 对应 PRD | M1 深度 |
|---|---|---|
| P01 被测系统列表 | 测试系统列表页 | 完整 |
| P02 被测系统模型页（图 + 列表、版本清单、环境、可选分组） | 测试系统模型页 | 完整 |
| P03 模型节点详情（动作：用途说明、绑定 API、输入/输出表与格式；实体：字段表——类型、必填、格式、枚举/引用） | 模型细节页 | 完整 |
| P04 API 注册表（用途说明、输入/输出格式、参数/请求体/响应字段表，可编辑） | 业务规则：API 注册 | 完整 |
| P05 版本明细 | 版本明细页 | 完整 |
| P06 需求管理（结构化、**责任人**、关联用例/节点/代码、缺陷数） | 需求管理页 | 完整 |
| P07 测试策略 | 测试策略页 | 完整 |
| P08 测试任务 | 测试任务页 | 完整 |
| P09 测试用例详情 | 测试用例详情页 | 完整 |
| P10 执行详情 | 隐含于执行流程 | 完整 |
| P11 测试报告（任务/版本） | 测试报告页 | 完整 |
| P12 缺陷列表/详情（需求、原因类别、归因人） | 缺陷（澄清 6） | 简单 |
| P13 人员管理 + 人员统计（参与的需求和角色、归因/关联排行） | 人员（澄清 6、A13） | 完整 |
| P14 Agent 配置 | Agent 配置与设置页 | 完整 |
| P15 Agent 工具管理（提示词、记忆、纠错、技能/MCP 登记、轨迹） | Agent 工具管理页 | 部分（技能/MCP 只登记） |
| P16 模型审阅（只读：实体/字段、关系双向读法、动作规则、覆盖、审阅清单、导出 Markdown/打印） | 用户反馈 #4（批次 2） | 完整 |
| 全局：主流程步骤条、面包屑、当前被测系统/版本选择器、各列表页空状态 | 用户反馈 #3（批次 2） | 完整 |

## 7 业务规则
- **BR-01**：关系使用 ModelLink（D24、BR-22），两端必须是同系统实体；删除节点前列出引用方，确认后软删除。旧 relation 节点仅供迁移历史，不接受新建。
- **BR-02**：冻结版本前，版本内所有需求都必须是 confirmed。冻结时生成快照，之后产生的策略、用例、报告都记录快照 ID。
- **BR-03**：AI 写入的对象都带 `source=agent` 和 agent_run_id。C01 中列出的动作只能由人执行。
- **BR-04**：每条需求默认按“正常/边界/异常”生成 ≥3 个用例。覆盖报告列出需求覆盖、动作节点覆盖、字段覆盖（需求引用的字段是否有用例关联或在测试数据中出现）、等级分布和类型分布。
- **BR-05**：执行结果只来自执行器回执或人工提交，Agent 自报的“通过”无效。
- **BR-06**：任务内用例串行执行，出错后继续执行后续用例（C04）。非功能类型的用例记为 skipped。
- **BR-07（缺陷归属）**：
  - 缺陷所属需求默认等于该用例关联的全部需求（inferred=true），可以增删。
  - 归因人由原因类别决定：requirement/design → owner，development → developer，test → tester。默认从所属需求的对应角色人员中带出（inferred=true），可以修改（修改后 inferred=false）。
  - environment/unknown 不归因到任何人。
  - Agent 只能建议原因类别，最终由人确定（C01）。原因类别为空时视为 unknown。
- **BR-08（统计口径）**：
  - 需求维度：缺陷数、加权分（Σ 严重度权重）、缺陷密度（缺陷数 ÷ 范围内该需求已执行的用例数，C05）。
  - 人员维度：
    - **归因**：DefectResponsible 指向此人的缺陷数和加权分，按角色拆分。
    - **关联**：此人在缺陷所属需求上有任意角色的缺陷数。
    - 排行默认按归因加权分排序。
  - rejected 状态的缺陷不计入统计。报告会记录生成时使用的权重。
- **BR-09**：报告是不可变快照。纠正报告会生成一条 Correction，并可以生成一份新报告。
- **BR-10**：纠错的整理结果直接生效，不需要审核。停用的记忆不注入。每条记忆可以追溯到来源纠错。
- **BR-11**：自动化代码只写入测试仓的 `tests/` 目录。
- **BR-12**：任何时候都不能把数据库连接串或密码写进仓库、日志、报告、模型上下文或导出文件。
- **BR-13（自动化绑定）**：自动绑定要求最后一次自检（run_pytest）通过。自检出现有需求/用例依据的断言不一致时，可标记 sut_mismatch，由人明确选择绑定并记录失败、只记失败或退回脚本问题（BR-44）；不能为了自检通过而改弱预期。环境不可达按 BR-20 标记 env_unavailable，其他未验证或脚本失败保留草稿并标 needs_fix，不自动绑定。自检次数上限可配置，默认 5。Agent 只能写该用例的目标测试文件，不能写探测（probe）等其他文件。
- **BR-14（接口用例）**：步骤以 `METHOD /path` 描述接口调用、或类型为 api 的手工用例，由 agent_api 执行器用 HTTP 请求执行，判定同样只认断言回执（BR-05），不使用浏览器。
- **BR-15（按 schema 构造请求）**：生成用例时，引用已登记 schema 的接口的请求体不得含未知字段、不得缺少必填字段，否则退回模型重写。
- **BR-16（节点去重）**：AI 新建节点前先按名称归一（去括号注释、空白、标点）匹配已有节点，相同或包含关系时关联已有节点，不新建。
- **BR-17（动作继承接口的输入/输出）**：动作绑定 API 时，若动作还没有输入和输出，自动按接口 schema 带出：输入 = 路径/查询/请求头参数 + 请求体字段，输出 = 第一个 2xx 响应的字段；同名参数自动对应字段（动作有“对象”实体时只在这些实体里找，否则要求全系统唯一）；用途说明和格式为空时一并带出。已有内容不覆盖；“从绑定 API 带出”合并、“按 API 重建”替换。
- **BR-19（字段名对齐接口）**：从 OpenAPI 导入后，平台按“动作的对象实体 ↔ 该动作绑定接口返回的实体字段”比对：实体缺少的接口字段生成“新增字段”建议；实体已有名称不同但对应的字段（如 amount ↔ amount_minor、status ↔ state）生成“改名”建议，采纳时原字段改名，需求/用例关联保持不变。AI 补全遵循同一规则（rename_from）。建议仍需人工采纳。
- **BR-20（环境预检）**：AI 自动化（单个或后台任务）、调试执行、手动执行（非人工执行器）开始前，对环境 base_url 做 TCP 连接检查（2 秒）。不可达时：调试/手动执行返回 503 ENV_UNREACHABLE 和中文提示；AI 自动化不调用模型、不计自检次数，未绑定的用例标“环境不可用”（automation_status=env_unavailable，带原因），已绑定的不变；自检过程中环境掉线同样处理（草稿保留）；定时/批次执行的运行记为 error，原因写明环境不可达。“AI 自动化未自动化的用例”会重新排队“需修复”和“环境不可用”的用例（含草稿）。
- **BR-21（环境启动命令）**：环境可选填启动命令（在代码仓根目录用系统 shell 执行，输出写 `runtime/logs/env-<id>.log`）。启动器启动时对不可达且有启动命令的环境自动启动（`--no-env-start` 关闭），服务退出时结束由平台启动的进程；界面在环境列表和用例页显示“可连接/无法连接”并提供“启动”按钮。平台不会结束不是自己启动的进程。
- **BR-22（关系类型）**：关系的两端必须是同一被测系统内未删除的实体；正向/反向名称必填（1–50 字），界面同时显示两个读法和基数（1:1、N:1、1:N、M:N）；API 名小写字母开头、只含字母数字下划线，同一实体上不重复；同一对实体下正向名称不重复。不再能新建 kind=relation 的节点或 source/target 边（返回 422，提示改用关系）。删除实体会一并归档它的关系；删除被引用的关系需要确认。
- **BR-23（外键与中间实体）**：非 M:N 关系的外键字段必须在“多”的一端（N:1 在起点，1:N 在终点，1:1 任一端）；未指定时自动选该端唯一一个“引用实体”指向另一端的字段。M:N 不能有外键；指定中间实体时须给出（或能自动找到）中间实体上分别指向两端的两个外键字段。字段改名后关系里显示的“实体.字段”同步更新；字段删除时关系的外键置空。
- **BR-24（前置条件与影响）**：动作保存前置条件/影响时逐条校验：字段必须存在（按“实体.字段”或 id 解析），枚举字段的取值必须在枚举内，in/not_in 必须给出列表，对象/关系必须存在；不合格时整体拒绝（AI 建议则丢弃不合格的条目）。字段改名后同步显示名。删除被前置条件/影响引用的字段需要确认。
- **BR-25（关系建议）**：实体字段为“引用实体”类型、或名为 `<资源>_id` 且 `<资源>` 对应某个绑定接口的资源名（如 /orders → order → 采购单）时，生成关系建议（N:1，默认 属于/拥有，外键为该字段，API 名为资源名/对方复数），已用作外键或已有关系的实体对不再建议。OpenAPI 导入后同样生成。建议只有人工采纳才落地（C01）。
- **BR-26（AI 使用关系与规则）**：模型目录、节点详情和 list_links 工具向 Agent 提供关系的两端读法、基数、外键和动作的前置条件/影响；用例生成须覆盖前置条件满足与不满足两种情况、断言影响（字段新值、创建的对象和关系）以及基数边界（如 N:1 的必填外键、同一采购单只接受一次付款）；自动化脚本按前置条件准备数据并断言影响。
- **BR-27（主流程进度）**：步骤状态按当前被测系统和版本（未指定时取最近一个未关闭的版本）计算：被测系统=有环境；模型=有实体和动作（有实体但没有动作为进行中）；版本/需求=版本已冻结（有需求但未全部确认或未冻结为进行中）；测试策略=已确认（草稿为进行中）；任务=有就绪或已执行的任务；用例=有可执行用例；执行=有执行批次（最近一次排队/运行中为进行中）；缺陷/报告=有报告且没有未关闭缺陷（有未关闭缺陷为进行中）。“下一步”指向第一个未完成的步骤及其操作。任何写操作后步骤条自动刷新。
- **BR-28（面包屑与上下文）**：详情页的面包屑和当前被测系统/版本由后端 `GET /nav/context?kind&id` 按对象推出（用例取来源版本或所关联需求的版本，否则归到“用例库”）；标签一律“名称 (编号)”，执行批次为“执行批次 月-日 时:分”。列表页的上下文放在 URL 查询参数里；切换版本只改查询参数，不丢当前页面。
- **BR-29（路径显示）**：凡显示本地测试仓或脚本路径，一律显示绝对路径并带“复制”按钮（相对路径只作补充）。
- **BR-30（模型审阅记号）**：任何人可对实体、动作、关系标记/取消“已审阅”并写备注（≤500 字）；标记时记录元素内容摘要（不含覆盖信息），之后元素被修改则显示“审阅后已变更，请重新审阅”，不计入已审阅数。标记不改变模型、不采纳也不拒绝任何建议，不影响冻结等人工关口（C01）。审阅页和 Markdown 导出的“未覆盖”= 没有任何需求或未废弃用例关联该元素（实体的任一字段被关联即算覆盖）。
- **BR-31（被测系统重置）**：`ops/reset_sut_data.py --sut <code>` 默认演练（只读，列出将删除和保留的行数及其他被测系统）；`--apply` 在一个事务内删除该系统的模型（节点、字段、关系、边、接口绑定、分组）、接口、建议、审阅记号、版本与快照、需求及关联、策略、任务、用例及关联、执行与批次、缺陷、报告、覆盖报告、纠错、该系统的 Agent 运行（被记忆或提示词版本引用的除外）以及指向这些对象的后台任务；保留被测系统、环境、人员、Agent 配置、提示词版本、记忆、严重度权重、变更日志和其他被测系统。有排队/运行中的执行或后台任务时拒绝执行。报告和快照的不可变保护只在该事务内临时解除。本地测试仓移到 `--repo-archive`（已存在则拒绝，不覆盖、不删除），再按新建被测系统的方式初始化空仓。执行前必须先做全量备份（pg_dump）。
- **BR-18（类型必填）**：实体字段、动作参数、接口字段都必须有类型；枚举必须给出取值，引用实体必须选目标实体。OpenAPI 导入时，人工填写的名称和用途说明优先，只替换空值和 FastAPI 自动生成的摘要名（如 “Create Order”）。

## 8 非功能需求
- **NFR-01 运行环境**：Windows 11 优先，也兼容 Linux（开发测试用）。Python 3.12 + uv；Node 用于前端开发/构建，部署运行时前端由 Python 服务托管；PostgreSQL 17。默认回环监听，单实例服务器部署见 D16。
- **NFR-02**：中文界面仍是原始目标；发布仓目前为英文界面，Agent 输出语言可配置。界面 i18n 尚未交付，列入后续任务，不能用 Agent 中文输出代替验收。主要操作应可键盘完成，现有部分交互已有验证。
- **NFR-03 性能**：500 个节点、2000 个用例、5000 条执行记录规模下，列表、详情和统计页 p95 ≤ 1 秒。
- **NFR-04 安全**：凭据见 D03、C06、BR-12。受保护写接口校验账号会话及 CSRF；提供 Origin 时必须同源。匿名登录、健康和本机 ticket 入口有独立边界；详情见当前架构 §9。
- **NFR-05 可观测**：完整保存 Agent 轨迹；执行保存截图和 trace。
- **NFR-06 可恢复**：重启后，遗留 queued/running 作业、执行和 Agent 运行改为 error，并记录 INTERRUPTED 原因；不是新增一个 INTERRUPTED 终态，不自动重跑。
- **NFR-07 预算**：Agent 默认最多 30 步、超时 10 分钟，都可以配置，并且可以取消。
- **NFR-08 测试**：后端测试连接 `testagent_test`，每次测试运行彼此隔离；service 层覆盖率 ≥ 80%；每个工作包都有 API 级测试；有一条端到端冒烟测试。

## 9 扩展点
| 编号 | 扩展点 | M1 实现 |
|---|---|---|
| EP-01 | 流程阶段注册表（目标：主流程可以改变） | 已有StageRegistry骨架，默认占位；未接入可替换的完整生产主链 |
| EP-02 | 事件钩子：`requirement.confirmed`、`version.frozen`、`case.created`、`execution.finished`、`defect.created`、`report.generated` 等 | 进程内总线 |
| EP-03 | 执行器接口：agent_browser / agent_api / pytest / manual | 四个实现 |
| EP-04 | 缺陷系统对接器 | 规划扩展边界，未实现可用适配器 |
| EP-05 | API 平台对接器 | OpenAPI 导入（从被测系统读取 openapi.json：摘要/说明、内容类型、参数、请求体与响应 schema，保留字段顺序）；其他平台只有接口 |
| EP-06 | 代码仓远程推送 | 规划扩展边界，未实现远程推送 |
| EP-07 | Agent 工具注册 | 实现 |
| EP-08 | 模型导出（RDF 等） | 规划扩展边界，未实现RDF/OWL导出 |
| EP-09 | 归因规则：原因类别到角色的映射可以配置或替换 | 默认实现 |

## 10 M1 完成定义
以供应链执行演示系统（`examples/supply_chain`）为被测系统，走通 US-01 到 US-20，每条 AC 都有自动化测试或手工记录的证据；端到端脚本跑通主链路，并展示需求和人员排行。

## 11 原假设的处理结果（2026-10-31 用户审阅）
- A01、A03–A09、A11：接受，改为确认决策 C01、C03–C09、C11。
- A02 → D03（PostgreSQL 17）。
- A10 → C10（在整个目录层面整理）。
- A12 → D06（代码位置用普通链接）。
- A13 → D10（以需求为中心追责）。

当前没有未确认的假设。

## 批次 t24u 补充（用户反馈 t24u，2026-11-02）
| 编号 | 决策 |
|---|---|
| D33 | 自动化脚本的执行结果以结构化报告呈现：步骤、接口请求、页面动作、断言（期望/实际）、测试数据、中文失败解释；原始输出保留但折叠。报告由平台自带的 pytest 插件生成，旧脚本无需修改 |
| D34 | 手工新建的用例也可以让 AI 补全；AI 只给建议，采纳由人逐项决定（C01） |

- **BR-32**：pytest 执行（调试和任务执行）保存结构化报告 `case_execution.report`；断言失败时显示“期望 … 实际 …”的中文说明；没有报告的旧记录显示原始输出。
- **BR-33**：覆盖要列明细：用例清单、用例详情、版本覆盖和需求详情都按名称列出覆盖的动作、实体、字段、关系，并能跳到模型和用例。
- **BR-34**：AI 补全写入建议（不产生修订）；只有人能采纳，采纳生成新修订，用例状态不变；已有的需求/节点/字段关联不会被建议删除。
- **BR-35**：页头有“返回”；用例、需求、任务、缺陷列表支持勾选后批量操作，逐条处理并汇报成功/跳过/失败；设为可执行仍是人的操作。
- **BR-36**：日志和 Agent 轨迹里的对象引用显示为“类别「名称 (编号)」”，不只显示 ID。
- 任务与用例的打通（任务按规则引用用例、任务分类 需求验证/通用质量/回归）见 `design/task-case-binding-proposal-t24u.md`；用户已在 t25 决定，见“批次 t25 补充”。

## 批次 t25 补充（用户决定 t25，2026-11-02）
| 编号 | 决策 |
|---|---|
| D35 | 任务只引用已有用例，不自己生成用例；没有可执行用例的需求列为“缺口”，可一键让 AI 生成草稿用例（只生成草稿，由人设为可执行） |
| D36 | 用例分三类：需求验证（需求里的业务规则，正常/边界/异常，**含输入校验和错误码**）、通用质量（幂等、并发/重复提交、可重复与数据重置等）、回归冒烟；任务类型与之对应：每条需求一个需求验证任务、一个通用质量任务、一个回归/冒烟任务 |
| D37 | 用例变为可执行后自动加入所有规则匹配的任务（单个和批量都一样），并记录原因；手工加入/移出优先，手工移出的用例不会被规则加回 |
| D38 | 边界、异常是用例设计方法（场景），不是非功能类型：照常执行；只有性能、安全等真正的非功能类型记为跳过。跳过永远不算通过，通过率 = 通过 ÷ 已执行，跳过/待人工/未执行单列 |

- **BR-37**：任务可带“选用例规则”（需求、分类、等级、场景、类型、质量属性，列表之间是“且”、列表内是“或”），只选可执行用例；任务里的每个用例标明来源（规则/手工）和原因。
- **BR-38**：用例设为可执行、修改或退回草稿/废弃时，平台按规则对所有未运行、未归档、版本未关闭的任务做调整：匹配则加入（原因“用例变为可执行，自动加入（规则匹配：…）”），不再匹配则移出“规则加入”的那一行；手工加入的行永不被规则移走；手工移出记入排除名单。
- **BR-39**：AI 生成用例和 AI 补全给出分类（补全只在分类看起来不对时建议，仍由人采纳）；分类不确定的存量用例只写“分类建议”，由人在用例页“采纳/保持现状”。
- **BR-40**：AI 生成策略时读取已有用例，按规则建任务（不再写自由文本的用例提纲），已有的规则任务不重复创建；策略页列出需求缺口，任务列表可“按分类补齐任务”。
- **BR-41**：报告按用例分类分别统计通过率。


## 12 当前实现补充（2026-11-09）

以下约束对应已落地能力；未覆盖的原 NFR 与 AC 仍保留验收义务。

- **BR-42 结果可信度**：空批次、全跳过或全待人工均不得显示通过；完成聚合时有 failed/error 回执则批次 failed，无 passed 且无失败回执则 not_executed，否则 passed。取消、环境/编排中断另按其流程终结。通过率 = passed / (passed + failed + error)，分母为零显示不可计算；skipped、blocked、尚未执行单列。旧不可变报告不因修复原地重写。
- **BR-43 执行版本**：已绑定脚本按 code_commit 的独立完整仓库检出执行，包括其 fixture/helper；执行记录写同一个完整 SHA。旧未绑定版本只允许在开始时固定 HEAD 并记录；绑定不可取回时明确失败，不静默换 HEAD，不改用户工作区。
- **BR-44 自检与失败分析**：失败类型与疑似原因分开记录；只有人最终确认缺陷原因。sut_mismatch 的人工处理保留草稿版本、断言与记录；无脚本在自动化任务中为 skipped/no_script。任务就绪/启动前展示缺口并允许生成脚本、改 Agent 任务或明确继续，定时运行记录跳过。
- **BR-45 建议依据**：来源区分需求原文、OpenAPI、模型规则和 AI 推断；引用的原文须可核实。AI 推断和关系建议不默认勾选，采纳 AI 推断须填写依据；按已有节点、API、同批、待审/已拒建议去重。拒绝撤销和 missing model 一键补建尚未实现，不能冒充现有能力。
- **BR-46 任务反馈**：Ready 操作后说明实际加入的任务、版本、来源和未加入原因；Ready 本身不启动运行。事件同步失败保留已保存状态并提示检查，不把理论匹配当实际关联。运行中/归档任务和人工排除保持原有规则。任务列表可进入最近运行，并提示排队/运行状态和刷新失败。
- **BR-47 列表与阅读**：显示当前范围结果数量；筛选数/总数有相同范围，有上限的接口标“最近已加载”及上限。未知/失败不可伪装成零；保留重试。分页、区域滚动不丢记录标识，报告/审阅打印保留所有行。系统/版本过滤先于报告与最近运行的 LIMIT。
- **BR-48 抽屉与描述**：需求、模型节点、Agent 详情支持响应式宽度、鼠标/键盘调整、分别记忆；窄屏全宽。存储不可用仍可操作，取消拖动不保存。长模型描述可展开/悬停全文，详情原文自动增高；调整布局不提交或丢失未保存文本。

### 后续范围与保留目标

显示名称/长标题、需求优先路径、建议恢复/缺失模型补建、M:N 覆盖修正见 plan 和 tasks。远程测试仓/PR review、外部缺陷平台、Runner、协作授权与冲突检测仍为后续设计，不因平台源码已推 GitHub 而算作测试代码仓远程能力。

NFR-03（规模与 p95）和 NFR-08（service 覆盖率 ≥80%）尚未找到达标测量报告；本轮不降低阈值，安排独立验收。技能/MCP 仍只登记，EP-01 只有注册表骨架；没有可配置的完整业务流水线。早期 OWL/RDF 和官方 Playwright Test Agents 复用属于历史研究方向，当前架构没有 Java/OWL reasoner 或官方三 Agent 的运行依赖。
