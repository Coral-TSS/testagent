# 关系建模优化方案（对照 Palantir Foundry Ontology，t18u，待决定，未实施）

> 2026-11-09维护说明：关系类型与动作规则已按D24–D27及0018实现；下文方案比较是历史背景，当前实体/动作节点+ModelLink为准。M:N中间字段覆盖仍需MODEL-014。

日期：2026-11-01。状态：提案，等待用户决定后再实施。

## 1. Palantir Ontology 要点（官方文档）
| 概念 | 含义 | 对我们的启发 |
|---|---|---|
| Object type / Property | 实体（或事件）的 schema；属性有类型，主键唯一 | 对应我们的“实体”节点 + 字段（entity_attribute），已基本一致 |
| **Link type** | 两个 object type 之间关系的 schema；**一条 link type 有两侧（side）**，每侧有自己的显示名和 API 名，双向可遍历，不需要再建反向关系；同一对类型之间可以有多条不同含义的 link type | 关系应是“边上的定义”，不是第三类节点；两侧名称就是“介词/动词短语” |
| 基数（cardinality） | 一对一、一对多、多对一、多对多（一对一只是提示，不强制） | 关系要记录基数 |
| 关系的承载方式 | 一对一/多对一：**外键**（一侧的属性 = 另一侧主键，如 Flight.tail_number → Aircraft.tail_number）；多对多：**关联表**；**对象承载的关系**：中间对象可带额外属性（如 Flight Manifest） | 关系要指向具体字段，如 付款记录.order_id → 采购单.id |
| Action type | 一次事务性的修改：**参数**（parameters）、**规则**（rules：创建/修改/删除对象、创建/删除多对多关系、函数、通知、Webhook）、**提交条件**（submission criteria：当前用户/参数/执行上下文的条件 + 失败提示） | 我们的动作已有用途、输入/输出、对象/执行者边；缺“影响哪些对象/字段/关系”（规则）和“前置条件”（提交条件）——这正是测试最需要的断言来源 |
| Interface | 抽象“形状”，多个 object type 实现同一接口（属性、link 约束、action 约束） | M2 再考虑（例如“可审批单据”） |
| Function | 以对象为输入的代码逻辑，可被 action 使用 | 对应我们的“代码引用”，暂不需要单独建模 |

## 2. 我们现在的模型与问题
- 节点三类：entity / action / **relation**。关系是一个节点（如“采购单-供应商”），用 source/target 两条边连接实体。
- 正式库现状：`采购单-供应商`（采购单 → 供应商）、`付款记录-采购单`（付款记录 → 采购单），都没有说明、没有基数、没有外键字段；名称只是两个实体名拼接，看不出“谁对谁是什么关系”。
- 问题：①关系没有语义（介词/动词），AI 和人读模型都要猜；②没有基数，生成用例时想不到“一个采购单多笔付款”“付款引用不存在的采购单”等边界；③没有和字段关联（付款记录.order_id 已是“引用实体”类型字段，但关系不知道）；④关系作为节点会出现在节点列表、需求关联里，和实体/动作混在一起。

## 3. 方案
### 方案 A（推荐）：关系改为一等的“关系类型”（link type），不再是节点
新表 `model_link`（每个被测系统）：
| 列 | 说明 | 例 |
|---|---|---|
| from_node_id / to_node_id | 两侧实体 | 采购单 / 供应商 |
| forward_name / forward_api_name | 从 from 看 to 的名称（介词/动词短语） | 属于 / supplier |
| reverse_name / reverse_api_name | 从 to 看 from 的名称 | 提供 / purchaseOrders |
| cardinality | one_to_one / many_to_one / one_to_many / many_to_many | many_to_one |
| fk_attribute_id | 外键字段（多对一时在“多”的一侧） | 采购单.supplier_id |
| target_key_attribute_id | 被引用的主键字段（默认 id） | 供应商.id |
| join_table / via_node_id | 多对多时的关联表名，或承载关系的中间实体 | — |
| required | 外键是否必填（0..1 vs 1） | true |
| description | 业务说明 | 每张采购单只对应一个供应商 |
| archived_at | 归档 | |
显示：图上画成一条带两侧名称的边，“采购单 →属于→ 供应商”、“供应商 →提供→ 采购单”；“付款记录 →支付→ 采购单（多对一，外键 付款记录.order_id）”、“采购单 →收到→ 付款记录（一对多）”。
联动：字段类型为“引用实体”时自动建议一条关系（外键 = 该字段）；OpenAPI 导入看到 `xxx_id` 字段时同样给出建议；需求条目/用例可以关联关系；冻结快照、Agent 模型目录、覆盖报告都带关系；生成用例时按基数和外键提示边界（外键不存在、重复关联、一对多聚合）。

### 方案 B：保留 relation 节点，只在节点上加字段
在 relation 节点上加 forward/reverse 名称、基数、外键字段。改动小（约一半工作量），但关系仍混在节点列表里，图上仍是“实体—关系节点—实体”三段，语义不如 A 清楚；以后做多对多/中间实体时还要再改。

### 动作补充（两种方案都建议，作为第二步）
给动作增加：①**影响**（规则）：创建/修改/删除哪个实体、改哪些字段（如 审批采购单：修改 采购单.state → approved/rejected），创建/删除哪条关系；②**前置条件**（提交条件）：如“采购单.state = pending_approval”“当前用户角色 = 审批人”，带失败提示；③执行者（已有 actor 边）。这些直接成为用例的前置条件和断言来源。

## 4. 已有数据迁移（方案 A）
1. 迁移 0018：建 `model_link`；把每个 relation 节点（source 边 → from，target 边 → to）转成一条 link，名称暂取原名，基数默认 many_to_one，外键字段在 from 实体里找“引用实体”且指向 to 的字段（付款记录.order_id → 采购单 会自动对上；采购单-供应商 若无 supplier_id 字段则留空并生成待审建议）。
2. 原 relation 节点和边**归档不删除**（archived_at），需求/用例上对 relation 节点的关联迁到 link 关联表；快照里旧版本保持原样（只读历史）。
3. AI 补全生成“关系命名”建议（forward/reverse 介词），人工采纳；正式库操作先备份。
4. 节点类型 relation 保留在 CHECK 中只读兼容一个版本，之后再去掉。

## 5. 工作量估计
| 项 | 方案 A | 方案 B |
|---|---|---|
| 迁移 + 服务 + API + 校验 | 1.5 天 | 0.5 天 |
| 前端（图上的边与两侧名称、关系表、字段联动） | 1.5 天 | 0.5 天 |
| Agent（快照/目录/结构化/补全建议/用例生成提示）+ 测试 | 1 天 | 0.5 天 |
| 正式库迁移脚本（备份/演练） | 0.5 天 | 0.25 天 |
| 动作“影响 + 前置条件”（第二步，可选） | +1.5 天 | +1.5 天 |
| 合计 | 约 4.5 天（+1.5） | 约 1.75 天（+1.5） |

## 6. 需要用户决定
1. 选方案 A（关系作为一等的关系类型，不再是节点）还是 B（保留关系节点只加属性）？
2. 关系名称用“介词/动词短语”两侧各一个（如 属于 / 提供）——是否同意？是否也要英文 API 名（用于生成代码，如 supplier / purchaseOrders）？
3. 基数是否需要“必填/可选”（1 vs 0..1）？
4. 多对多与“中间实体承载关系”（如 订单行）现在就支持，还是先只做一对一/多对一/一对多？
5. 动作的“影响 + 前置条件”是否作为同一批一起做？
6. 现有两条关系的名称：建议 采购单 →属于→ 供应商 / 供应商 →提供→ 采购单；付款记录 →支付→ 采购单 / 采购单 →收到→ 付款记录。是否这样命名？

## 参考（Palantir 官方文档）
- Core concepts：https://www.palantir.com/docs/foundry/ontology/core-concepts/
- Link types overview（两侧、方向、多条关系）：https://www.palantir.com/docs/foundry/object-link-types/link-types-overview/
- Create a link type（基数、外键、关联表、对象承载关系、两侧显示名/API 名）：https://www.palantir.com/docs/foundry/object-link-types/create-link-type/
- Action types overview：https://www.palantir.com/docs/foundry/action-types/overview/
- Action rules：https://www.palantir.com/docs/foundry/action-types/rules/
- Submission criteria：https://www.palantir.com/docs/foundry/action-types/submission-criteria/
- Interfaces：https://www.palantir.com/docs/foundry/interfaces/interface-overview/
