# 批次 2「结果可信度」设计方案（历史提案）

> 2026-11-09维护说明：主要能力已在0023/0024及406a21e、65e544c等提交落地；DEMO-FIX-001进一步覆盖所有零执行批次。下方草案和待确认问题保留设计背景，不再表示等待开发。当前契约以architecture/detailed-design及spec BR-42–45为准。

> 原撰写时为草案；当前实现状态见上方维护说明。
> 依据：发布仓 `D:\CodeWork\TestAgent\release\testagent`，分支 `develop`，HEAD `b841518`（逐个读过下面引用的源码）；问题来源：`D:\CodeWork\TestAgent\TODO.md` 批次 A、`D:\CodeWork\TestAgent\release\demo-run-2026-11-03\demo-run-2026-11-03.zh.md` 第 2 节。
> 范围：TODO 批次 A 的六项全部放在这一批：#9 + #15（失败分类和可读摘要）、#18（自动化任务里没有脚本的用例）、#13（Start testing / Next 真的能运行任务）、#6（模型建议标来源）、#4（补全去重、名称必填）。#6、#4 是**可选子项**，可以拆到下一批（见第 8 节决策 D10）。
> 约定：只提已公开的审批阈值边界那一个预埋 bug（TC-002），其余不描述。文中不出现任何口令或密钥。
> 迁移编号：现有最后一个是 `0022_users_sessions.sql`，本批新增 **`src\testagent\migrations\0023_result_trust.sql`**（一个文件，包含下面所有表结构改动）。

---

## 0. 一页总览

| 项 | 要解决的问题 | 核心做法 | 估算 |
|---|---|---|---|
| #9 + #15 | 自检失败只显示 Needs fix，分不清"脚本错了"还是"系统错了"；报错是原始 pytest 文本 | 平台先按报错类型**确定性分类**（断言 / 定位 / 超时 / 脚本错误 / 环境 / 平台配置），断言失败再让 Agent 给出判断；新增"疑似系统问题"状态；统一生成"期望 / 实际 / 对应需求"的一句话摘要，原始报错折叠 | 3.5 天 |
| #18 | 自动化任务里混进没脚本的用例（TC-019），运行时记成 error | 运行前检查并提示（生成脚本 / 改 Agent 执行 / 跳过继续）；运行时记成 **skipped（原因：缺脚本）**，不算 error，不进通过率分母；报告单独列出 | 1.5 天 |
| #13 | Start testing 只改版本状态；Next "Run task" 只是跳转 | 新增"运行版本任务"接口和弹窗；Start testing、Next、任务列表"全部运行"都走它 | 1.5 天 |
| #6（可选） | 模型建议不显示来源，AI 猜测的约束容易被全盘接受 | `model_suggestion` 加 `source` 和 `evidence`；AI 推断默认不勾选；新增批量接受，默认排除 AI 推断 | 2 天 |
| #4（可选） | AI 补全产生重复动作和"空壳"节点 | 同批去重 + 按绑定 API 去重 + 和待处理建议做相似度去重；节点名称和动作说明必填，不合格的直接丢弃并计数 | 1.5 天 |
| 合计 | | | **约 10 人天**（只做 #9/#15/#18/#13 约 6.5 天） |

---

## 1. 共用的基础：失败分类模型

#9、#15、#18 都依赖同一套"失败是什么、像谁的问题"的分类，先统一定义。

### 1.1 两个维度

**failure_kind（发生了什么，平台确定性判断，不靠大模型）**

| 值 | 含义 | 判定来源 |
|---|---|---|
| `assertion` | 断言不成立（期望 ≠ 实际） | pytest `AssertionError` / `check()` 失败；Agent 执行器的 assert 回执失败 |
| `locator` | 页面元素找不到 | Playwright 报错里含 locator / waiting for，且非纯超时 |
| `timeout` | 操作或用例超时 | `TimeoutError`、pytest 超时被杀 |
| `script_error` | 脚本自身错误：语法、导入、`KeyError`、`TypeError` 等 | `explain_error()` 里除连接错误以外的分支；收集阶段失败（`no tests collected`） |
| `http_error` | 被测系统返回 5xx 或非 JSON | 报告里请求事件状态码 ≥ 500 或 JSON 解析失败 |
| `env_unreachable` | 被测系统连不上 | `ENV_UNREACHABLE`、`ECONNREFUSED` |
| `platform` | 平台或配置问题：没有环境、测试仓没配置、模型不可用、代码文件不存在、仓库脏 | `AppError` 的 `NO_ENVIRONMENT` / `CONFIG_MISSING` / `MODEL_UNAVAILABLE` / `NOT_FOUND`（code_path）/ `REPO_DIRTY` |
| `agent_error` | Agent 执行器没跑完（中途出错 / 取消 / 超预算） | `agent_run.status in (error, cancelled)` |
| `no_script` | 自动化任务里的用例没有脚本 | `select_executor()` 返回 forced error 的那个分支（#18） |
| `non_functional` | 本版本不执行的非功能类型 | 现有 forced skipped |
| `unknown` | 以上都不是 | 兜底 |

**suspected_cause（更像谁的问题，给人看的初判）**，取值和缺陷的 `cause_category` 对齐，便于一键带入缺陷：

| 值 | 显示 | 对应缺陷原因 |
|---|---|---|
| `sut` | 疑似系统问题 | requirement / design / development（细分仍交给 `analyze_failure` 和人） |
| `script` | 疑似脚本 / 用例问题 | test |
| `environment` | 环境问题 | environment |
| `platform` | 平台或配置问题 | （不建缺陷，提示去修配置） |
| `unknown` | 无法判断 | unknown |

默认映射（确定性部分）：

| failure_kind | 默认 suspected_cause |
|---|---|
| `script_error`、`locator` | `script` |
| `timeout` | `unknown`（页面慢和定位写错都有可能） |
| `http_error` | `sut` |
| `env_unreachable` | `environment` |
| `platform`、`no_script`、`agent_error` | `platform` |
| `assertion` | 见 1.2，需要再判断 |

### 1.2 断言失败时的判断

断言失败是唯一"分不清"的情况，分两种场景：

1. **AI 自动化自检阶段**（`automation.py` 的 `automate()`）：脚本还没被验证过。让 Agent 在 `submit_result` 时多交一个结构化判断（见 2.2），平台再做一致性校验：
   - Agent 判断 `sut_mismatch` 且断言的期望值能在用例 `expected` 或关联需求里找到依据 → `suspected_cause=sut`；
   - Agent 判断 `script_issue`，或期望值在用例 / 需求里找不到 → `script`；
   - 其他 → `unknown`。
2. **任务运行阶段**（已绑定、自检通过过的脚本）：脚本当初是在同一套系统上跑通过的，现在断言失败，**更像系统行为变了**。规则：`code_commit` 和绑定时一致 → `sut`；脚本在绑定后被改过 → `unknown`。不额外调用大模型（省钱、可复现）；需要细分时仍用现有的 `AI analyse cause`。
3. **Agent 执行器**（agent_browser / agent_api）：平台只认断言回执，回执失败 → `sut`（Agent 没写脚本，不存在"脚本写错"）；但若失败的回执在用例 `expected` 里找不到对应 → `unknown`。

> 这只是初判，界面上一律写"疑似"，最终结论仍由人确认（和现有 C01 原则一致：AI 只给建议）。

### 1.3 可读摘要（#15）的统一结构

所有执行记录和自检结果统一产出一个 `summary` 对象（JSON），前端按模板渲染，原始报错放折叠区：

```json
{
  "headline": "金额正好等于审批阈值时，状态应为 pending，实际是 approved",
  "kind": "assertion",
  "cause": "sut",
  "expected": "'pending'",
  "actual": "'approved'",
  "subject": "order['state']",
  "check": "state is pending approval",
  "step": "Step 2: submit order at the threshold",
  "requirement_refs": [{"code": "REQ-003", "rule": "金额 ≥ 阈值需要审批"}],
  "evidence": "用例期望结果第 2 条；需求 REQ-003 规则 1",
  "next_actions": ["record_failed", "create_defect", "bind_draft"],
  "agent_note": "系统行为和需求不一致，保留断言"
}
```

- `expected` / `actual` / `subject` / `check` / `step`：直接取自 `pytest_report.py` 已经记录的 `check()` 事件和断言事件（现有 `assertion_event()`、`_explain_compare()` 已经拿到了这些值，只是最后被拼成了一段英文字符串）。
- `requirement_refs`：用例关联的需求（`case_requirement_link`）+ Agent 指出的具体规则；平台校验编号存在，不存在的丢弃。
- `headline`：确定性模板生成（期望 X，实际 Y）；Agent 有判断时用 Agent 写的一句话（按 `TESTAGENT_AGENT_LANGUAGE` 输出），平台校验长度 ≤ 200。
- `next_actions`：由 kind + cause 决定，前端据此显示按钮（见 2.4）。

---

## 2. #9 + #15：自检失败分类和可读的报错摘要

### 2.1 现状

| 位置 | 行为 |
|---|---|
| `src\testagent\services\automation.py` `AutomationService.automate()` | 自检最后一次没通过 → `_needs_fix()`，`automation_status='needs_fix'`，`automation_note` = `failed_assertion` 或 `error` 原文（≤4000 字）。**不区分是系统问题还是脚本问题** |
| 同文件 `automate_entry()` 的 instructions | 已经告诉 Agent："系统本身和期望不一致时保留断言并在 summary 里说明"。但 `AutomateOut` 只有自由文本 `summary`，平台没有读它，界面也不显示 |
| 同文件 `run_pytest_tool()` | 每次自检只保留 `status / failed_assertion / error` 三个字段到 `last_check`，报告里的结构化 `failure`（含 expected/actual）被丢掉 |
| `src\testagent\integrations\pytest_report.py` `explain_assert()` / `explain_error()` | 已能把断言翻译成 "expected … equals …, got …"、把常见异常翻译成一句话，但只输出英文字符串，没有类型字段 |
| `src\testagent\services\executions.py` `ExecutionService._pytest()` | 把 `explain` 和原始 `failed_assertion` / `error` 拼成一个字符串存进 `case_execution.failed_assertion` / `error` |
| 同文件 `execute_case()` | 所有 `AppError` 和异常都变成 `status='error'`、`error="CODE: message"`，不区分平台配置问题和执行问题 |
| `src\testagent\services\failure_analysis.py` | 已有 `analyze_failure` 入口，可按需给出 `suggested_cause`（requirement/design/development/test/environment/unknown），但只能手动触发、只对执行记录，不对自检 |
| `web\src\components\CaseExecutionPanel.tsx`（约 217–240 行） | needs_fix 一律显示黄色提示 "Automation needs fix: the last self-check failed…" 和 "Reason: …原文"，建议操作固定为"改用例重新生成 / 手动改草稿再绑定" ——**正好把人引向"去修脚本迁就系统"** |
| `web\src\components\AutomationTag.tsx`、`AutomationProgress.tsx` | 只有 needs_fix / env_unavailable 两种标签 |
| `web\src\pages\ExecutionPage.tsx`（约 210–213 行）、`web\src\components\RunReport.tsx` | 显示 "Unmet assertions" 和 "Execution error" 的原文 `<pre>`；报告视图里有 `failure.explain` |

### 2.2 后端改动

**数据模型（0023）**

```sql
-- 执行记录：分类 + 可读摘要
ALTER TABLE case_execution
  ADD COLUMN failure_kind text CHECK (failure_kind IS NULL OR failure_kind IN
    ('assertion','locator','timeout','script_error','http_error','env_unreachable',
     'platform','agent_error','no_script','non_functional','unknown')),
  ADD COLUMN suspected_cause text CHECK (suspected_cause IS NULL OR suspected_cause IN
    ('sut','script','environment','platform','unknown')),
  ADD COLUMN summary jsonb;

-- 用例的自动化状态：新增"疑似系统问题"
ALTER TABLE test_case DROP CONSTRAINT IF EXISTS test_case_automation_status_check;
ALTER TABLE test_case ADD CONSTRAINT test_case_automation_status_check CHECK
  (automation_status IS NULL OR automation_status IN ('ok','needs_fix','env_unavailable','sut_mismatch'));
ALTER TABLE test_case ADD COLUMN automation_failure jsonb;  -- 最近一次自检的 summary（同 1.3 结构）
```

- 旧数据回填：`case_execution` 中 `status in ('failed','error')` 的行按 `error` 前缀做一次粗分类（`ENV_UNREACHABLE` → env_unreachable/environment；`NO_ENVIRONMENT`/`CONFIG_MISSING`/`MODEL_UNAVAILABLE` → platform；FORCED_REASON 那句 → no_script/platform；其余 failed → assertion/unknown）。`summary` 旧行留空，前端回退到显示原文。
- `test_case.automation_status='needs_fix'` 的旧行不动（重新跑一次 AI automation 会得到新分类）。

**代码**

1. 新文件 `src\testagent\services\failure_classify.py`：纯函数 `classify(executor, status, error_code, error, report, *, phase, bound_commit=None, code_commit=None, agent_verdict=None, case=None, requirements=None) -> {"failure_kind", "suspected_cause", "summary"}`，实现第 1 节的规则。纯函数，便于单测。
2. `pytest_report.py`：`test.failure` 增加 `kind`（assertion / locator / timeout / script_error / http_error / env_unreachable）和结构化字段 `expected / actual / subject / check / step`；`explain_error()` 改为返回 `(kind, text)`（保留原函数做兼容包装）。现有 `explain` 字符串不变，旧前端照常可用。
3. `pytest_runner.py`：收集失败、超时被杀、无报告时补 `kind`（script_error / timeout）。
4. `executions.py`：
   - `_pytest()` / `_agent_browser()` / `_agent_api()` 返回值加上 `classify()` 结果；`failed_assertion` / `error` **继续保存原文**（兼容、可追溯），可读信息只放 `summary`。
   - `execute_case()` 的 `except AppError` 按 `exc.code` 映射到 platform / env_unreachable。
   - `record_forced()` 写入 `failure_kind`（no_script / non_functional）。
   - `get()` / `list_for_case()` 返回新字段。
5. `automation.py`：
   - `AutomateOut` 加可选的结构化判断（旧模型输出不带也能通过校验）：
     ```python
     class SelfCheckVerdict(BaseModel):
         verdict: Literal["passed", "sut_mismatch", "script_issue", "unclear"]
         expected: str | None; actual: str | None
         requirement_code: str | None; rule: str | None
         explanation: str = Field(max_length=1000)
     class AutomateOut(BaseModel):
         summary: str
         verdict: SelfCheckVerdict | None = None
     ```
   - instructions 增加一句："最后一次自检断言失败时，必须填写 verdict：期望值有用例或需求依据而系统返回不同 → sut_mismatch；字段名、路径、步骤或数据写错 → script_issue；分不清 → unclear。不要为了通过而改断言。"
   - `run_pytest_tool()` 的 `last_check` 保存完整 `failure`（含 kind / expected / actual）。
   - 自检失败分支：`classify(phase="self_check", agent_verdict=...)`；`suspected_cause=='sut'` 时写 `automation_status='sut_mismatch'`，否则 `needs_fix`；两种情况都写 `automation_failure`，`automation_note` 改为 `headline`（兼容旧前端）。
   - 环境不可达分支保持现状（已有 `env_unavailable`）。
6. 新接口（`src\testagent\api\executions.py`）：
   - `POST /api/v1/cases/{case_id}/automation/confirm-sut-issue`  body `{action: "bind_and_record" | "record_only", create_defect: bool}`（仅 human，`ensure_human`）：
     - `bind_and_record`（推荐默认）：把草稿脚本绑定到用例（复用 `_bind()`，`mode=automated`，`automation_status='ok'`），同时用最近一次自检结果写一条 `status='failed'` 的执行记录（`executor='pytest'`，`task_run_id=NULL`，带 report / summary / `code_commit`）。之后任务运行会持续失败，直到系统修好 —— 这才是回归测试该有的样子。
     - `record_only`：不绑定，只写那条 failed 执行记录，用例保持 `sut_mismatch`。
     - `create_defect=true`：再调用现有 `DefectService` 从这条执行记录建缺陷，`suggested_cause='development'`，`cause_category` 仍留 `unknown`（C01）。
   - `POST /api/v1/cases/{case_id}/automation/mark-script-issue`：人认为其实是脚本问题，把 `sut_mismatch` 改回 `needs_fix`（记 change log）。
   - 执行记录和运行详情接口（`GET /executions/{id}`、`GET /runs/{id}`）返回 `failure_kind / suspected_cause / summary`。
7. `failure_analysis.py`：`analyze()` 的输入加上 `summary`，提示词里说明"平台初判是 X"，减少重复推理。

### 2.3 前端改动

| 文件 | 改动 |
|---|---|
| `web\src\api\types.ts`、`schema.d.ts` | 新字段类型；`AutomationStatus` 加 `sut_mismatch` |
| 新组件 `web\src\components\FailureSummary.tsx` | 统一渲染 1.3 的 summary：第一行原因标签（疑似系统问题 = 红 / 疑似脚本问题 = 橙 / 环境 = 蓝 / 平台配置 = 灰）+ headline；下面"期望 / 实际 / 对应需求（可点击跳到需求）/ 步骤"四行；最后"原始报错"放 `Collapse`，默认收起 |
| `CaseExecutionPanel.tsx` | `sut_mismatch`：红色提示"自检时发现系统行为和期望不一致（疑似系统问题），脚本未绑定"，按钮：**绑定脚本并记录失败**（主按钮）/ 只记录失败 / 记录并创建缺陷 / 其实是脚本问题；明确写"不要为了让测试通过去改断言"。`needs_fix`：按 failure_kind 给针对性建议（定位失败 → 检查页面选择器 / 用例步骤；脚本错误 → 重新生成；超时 → 检查环境速度后重试） |
| `AutomationTag.tsx`、`AutomationProgress.tsx` | 新标签 "Suspected SUT issue"；批量自动化进度里把 sut_mismatch 和 needs_fix 分两组列出 |
| `ExecutionPage.tsx`、`RunReport.tsx` | 顶部用 `FailureSummary` 替换现在的两个原文 Alert；`DefectActions` 在 cause=sut 时高亮"创建缺陷"，cause=platform 时改为"去修配置"链接 |
| `RunPage.tsx` | 用例行加"原因"列（标签）；运行汇总加"按原因"小计：系统 N / 脚本 N / 环境 N / 平台 N |
| `CaseList.tsx`、版本页用例表 | Automated 列显示新标签，可按"疑似系统问题"筛选 |

### 2.4 对通过率和统计的影响

- 通过率公式**不变**：`passed / (passed + failed + error)`（`services\reports.py` `_summary()`）。
- 报告 `content.summary` 新增 `by_cause: {sut, script, environment, platform, unknown}`、`by_kind`；`summarize_report` 提示词加一句"失败按原因分开说，平台 / 环境原因的失败不是系统缺陷"。
- `sut_mismatch` 的自检本身不产生执行记录，不进通过率；用户点"记录失败"后才产生一条 failed（task_run 为空，只进版本报告 / 用例历史，不进任务运行报告）。
- 缺陷密度（`v_defect_by_requirement`、`stats.py` 的 `EXECUTED`）不变。
- 是否把平台 / 环境原因的 error 从分母里去掉：见决策 D3（推荐**不去掉**，只单独展示）。

### 2.5 测试

- `tests\integrations\test_pytest_report.py`：每种异常的 `kind` 和 expected/actual 提取（`check()`、裸 `assert`、`.status` 比较、`KeyError`、Timeout、ECONNREFUSED、语法错误收集失败）。
- 新 `tests\unit\test_failure_classify.py`：第 1 节映射表逐行；断言三种场景（自检 + 各 verdict、任务运行同 commit / 改过 commit、Agent 执行器回执）。
- `tests\api\test_executions_api.py`：执行记录返回 summary；`AppError` → platform；confirm-sut-issue 两种 action（绑定后 `mode=automated`、生成 failed 执行、可建缺陷且 `cause_category='unknown'`）；mark-script-issue；非人类 actor 调用返回 403。
- `tests\api\test_readable_runs_api.py`：报告 `by_cause`。
- 自动化：用 fake runtime 让 Agent 交 `sut_mismatch` → 用例变 `sut_mismatch`；交 `script_issue` → `needs_fix`；不交 verdict（旧模型）→ 回退到确定性分类。
- `tests\samples\test_procurement.py`（Docker 演示样例）：阈值用例（TC-002 对应的那条）自检后应为 `sut_mismatch`，**只断言状态，不在测试名或注释里描述其他预埋 bug**。
- 前端 vitest：`FailureSummary.test.tsx`（四种 cause、折叠原文、需求链接）；`CaseExecutionPanel.test.tsx` 加 sut_mismatch 按钮和确认流程；`ExecutionPage.test.tsx`、`RunPage.test.tsx` 原因列和小计。

---

## 3. #18：自动化任务里没有脚本的用例

### 3.1 现状

| 位置 | 行为 |
|---|---|
| `src\testagent\services\executions.py` `select_executor()` 最后一行 | `executor='automation'` 的任务里，`mode!='automated'` 或 `code_path` 为空的功能用例 → `("manual", "error")` |
| `src\testagent\services\runs.py` `FORCED_REASON["error"]` + `_loop()` | 记成 `status='error'`，原因 "A case in the automated task has no automation code yet (code_path)"；`_loop()` 最后 `failed/error` 任一存在 → 整个运行 `failed` |
| `src\testagent\services\task_binding.py` `match()` / `sync_task()` | 规则只看 `status='ready'` 和分类，不看有没有脚本；`Add to task` 和手动添加同样不看 |
| `src\testagent\services\tasks.py` `set_status('ready')` | 只检查任务里至少有一个用例 |
| `RunService.start()` | 只检查任务状态和环境，不检查脚本 |
| `services\reports.py` `_summary()` | error 进分母 → TC-019 拉低通过率，看起来像"第二个发现" |

### 3.2 方案

原则：**能提前拦就提前提示，运行时不记成失败**。

1. **记录方式**：运行时缺脚本的用例记成 `status='skipped'`，`failure_kind='no_script'`，`result`（现有 skipped 原因字段）写"自动化任务中该用例还没有绑定脚本，未执行"。（是否新增独立状态 `not_executable` 见决策 D4，推荐复用 skipped。）`_loop()` 的运行结论只看 failed/error，所以全部其他用例通过时运行就是 `passed`（带"N 条未执行"提示）。
2. **提前检查**（不阻断数据，只在动作前提示）：
   - 新函数 `task_binding.script_gaps(cur, task_id) -> list[{case_id, code, title, automation_status}]`：`executor='automation'` 的任务里、ready、功能类型、`mode!='automated' or code_path is null` 的用例。
   - `GET /api/v1/tasks/{task_id}` 的详情和 `GET /versions/{id}/tasks` 列表增加 `script_gaps`（列表只给数量）。
   - `POST /tasks/{id}/status`（ready）和 `POST /tasks/{id}/run`：有缺口且请求没带 `allow_missing_scripts=true` → `409 MISSING_SCRIPTS`，`related` 列出用例编号。前端据此弹窗；定时运行（`trigger='schedule'`）不弹窗，直接按第 1 条记 skipped。
3. **弹窗的三个选项**（前端，复用现有接口）：
   - **生成脚本**：调用现有 `POST /versions/{version_id}/automate`（批量 AI 自动化），只传缺口里的用例（给该接口加可选 `case_ids` 参数）；完成后回到任务页再运行。
   - **移到 Agent 执行的任务**：把这些用例从本任务移除（写 `task_case_exclusion`，规则不会再加回来）并加入同版本 `executor='agent'` 的同类任务；没有同类任务时提供"新建 Agent 任务"。
   - **跳过这些用例，继续**：带 `allow_missing_scripts=true` 运行，缺脚本的记 skipped。
4. **规则同步**：不改变规则匹配（避免用例在任务里"消失"让人更困惑），但任务页用例表加"缺脚本"标签，任务列表显示"N 条缺脚本"。是否改成规则不自动加入缺脚本用例，见决策 D5。
5. **脚本在运行时才发现丢失**（`code_path` 有值但文件不在仓库里）：保持 error，但 `failure_kind='platform'`、`suspected_cause='platform'`，摘要写"绑定的脚本文件在测试仓里找不到"。

### 3.3 前端改动

| 文件 | 改动 |
|---|---|
| `web\src\pages\TaskPage.tsx` | Run now、Set ready 遇到 `MISSING_SCRIPTS` 弹出新组件 `MissingScriptsModal`（列出用例、三个选项）；用例表加"缺脚本"标签 |
| `web\src\components\StrategyTab.tsx` | 任务列表加"缺脚本 N"徽标 |
| `web\src\pages\RunPage.tsx`、`RunReport.tsx`、`ReportPage.tsx` | 单独一块"未执行（缺脚本）N 条"，可点进用例；不再显示为红色 error |

### 3.4 对通过率和统计的影响

- 缺脚本的用例从 error 变成 skipped：**不再进通过率分母**，报告里在"skipped"下细分 `skipped_no_script` 和 `skipped_non_functional`（`_summary()` 增加这两个字段，`passRateNote()` 文案相应补一句"N 条缺脚本未执行"）。
- 历史数据：已有的那类 error 记录**不改状态**（决策 D6，推荐保持历史不变，只回填 `failure_kind='no_script'` 让界面显示正确原因）。如果选择改，演示那次的版本报告需要重新生成。
- 缺陷密度的"已执行用例数"不变（skipped 本来就不算）。

### 3.5 测试

- `tests\api\test_runs_api.py`：自动化任务含缺脚本用例 → 该用例 skipped + `failure_kind='no_script'`；其余通过时运行结论 `passed`；`/run` 不带参数返回 409 `MISSING_SCRIPTS` 并列出编号；带 `allow_missing_scripts` 能启动；`trigger='schedule'` 不拦。
- `tests\api\test_task_binding_api.py`：`script_gaps` 只统计 automation 任务、ready、功能类型；移到 Agent 任务后写入 exclusion，规则同步不加回来。
- `tests\api\test_stats_reports_api.py`：通过率分母不含 no_script；`skipped_no_script` 计数。
- `tests\api\test_strategy_tasks_api.py`：Set ready 的 409 和 allow 参数。
- 前端：`MissingScriptsModal.test.tsx`（三个选项分别调用的接口）；`passRate.test.ts` 新文案；`RunPage.test.tsx` 未执行分组。

---

## 4. #13：Start testing / Next 真的能运行任务

### 4.1 现状

| 位置 | 行为 |
|---|---|
| `web\src\pages\VersionPage.tsx`（约 127 行） | Start testing → `setStatus.mutate("testing")`，即 `POST /versions/{id}/status`（`src\testagent\api\requirements.py` 137 行 → `VersionService.set_status()`），只改状态 |
| `src\testagent\services\navigation.py` `progress()`（约 344 行） | 没有运行记录时，Next 的 action 是 `{"label": "Run task", "path": spath}`，`spath` = 版本页 `?tab=strategy` |
| `web\src\components\FlowSteps.tsx` | Next 按钮只 `navigate(progress.next.path)`；已经在该页时看上去毫无反应 |
| `web\src\pages\TaskPage.tsx` | 只有单个任务的 Run now（`POST /tasks/{id}/run`） |
| `RunService._enter_testing()` | 第一次运行时会自动把版本从 requirements_frozen 改成 testing，所以"先运行任务"本来就会改状态 |

### 4.2 后端改动（无表结构改动）

1. `RunService.runnable(version_id) -> list[dict]`：版本下每个任务的 `id, name, executor, status, environment_name, ready_cases, script_gaps, active_run_id, runnable: bool, reason`（reason 取值：`not_ready`（任务是 draft）/ `no_environment` / `no_cases` / `running` / `archived`）。
2. 新接口（`src\testagent\api\runs.py`）：
   - `GET /api/v1/versions/{version_id}/runnable-tasks` → 上面的列表。
   - `POST /api/v1/versions/{version_id}/run-tasks`  body `{task_ids: [uuid] | null, allow_missing_scripts: bool = false, start_testing: bool = true}`：
     - `start_testing=true` 且版本是 `requirements_frozen` → 先改为 testing（复用 `set_status`）；
     - 逐个任务调用 `RunService.start()`，**每个任务独立事务**，一个失败不影响其他；环境不可达（`ENV_UNREACHABLE`）、缺脚本（`MISSING_SCRIPTS`，未允许时）、已有运行等记入 `skipped`；
     - 返回 `{started: [{task_id, run_id}], skipped: [{task_id, name, code, message}]}`。
     - 平台只启动一个 Worker（`api\app.py` 创建，`core\worker.py`），任务按队列依次执行，多个任务会依次执行，在返回里说明"已排队 N 个"。
   - `draft` 状态的任务：不自动改成 ready（见决策 D7，推荐弹窗里可勾选"同时设为 ready"，后端按 `set_status('ready')` 的规则校验）。
3. `navigation.py`：没有运行记录且有可运行任务时，Next 的 action 改为 `{"label": "Run tasks", "path": spath, "kind": "run_tasks", "version_id": vid}`；没有可运行任务时 label 改为具体原因，例如 "Set tasks ready" / "Choose an environment for tasks"，path 指向任务页，避免按钮名和行为不符。

### 4.3 前端改动

| 文件 | 改动 |
|---|---|
| 新组件 `web\src\components\RunTasksModal.tsx` | 列出可运行任务（默认勾选可运行的，显示执行方式、环境、用例数、缺脚本数），不可运行的灰显并写原因；底部"同时设为 ready"开关；缺脚本处理复用 #18 的三个选项（汇总一次，不逐个弹）；确定后调用 `run-tasks`，结果用通知显示"已开始 N 个，跳过 M 个（原因）"，提供"查看运行"链接 |
| `VersionPage.tsx` | Start testing 打开 `RunTasksModal`（标题"开始测试"），里面提供"只改状态，不运行"的次要按钮，保留原有能力 |
| `FlowSteps.tsx` | `next.kind === "run_tasks"` 时打开 `RunTasksModal`，不跳转；普通跳转若目标就是当前页面，则滚动到对应区域并闪烁高亮（给目标区块加 `data-flow-anchor`） |
| `StrategyTab.tsx` | 任务列表上方加"运行全部可运行任务"按钮（同一个弹窗） |
| `navContext.ts`、`types.ts` | `NextAction` 加 `kind?`、`version_id?` |

### 4.4 对通过率和统计的影响

无直接影响。运行入口变多但每次仍是普通 task_run，报告按运行生成，规则不变。

### 4.5 测试

- `tests\api\test_runs_api.py`：`runnable-tasks` 各种 reason；`run-tasks` 部分成功（一个环境不可达、一个正常）；`start_testing` 改状态；重复调用不会给运行中的任务再排队；非 human 调用的权限与现有 `/tasks/{id}/run` 一致。
- `tests\api\test_navigation_api.py`：无运行记录时 `next.kind == "run_tasks"`；无可运行任务时 label 写原因。
- 前端：`RunTasksModal.test.tsx`（默认勾选、灰显原因、提交参数、结果提示）；`navigation.test.tsx` 中 FlowSteps 打开弹窗而不是跳转、同页时高亮；`VersionPage` 的 Start testing 打开弹窗。

---

## 5. #6（可选）：模型建议标来源，AI 推断默认不勾选

### 5.1 现状

| 位置 | 行为 |
|---|---|
| `model_suggestion` 表（`0001_init.sql`、`0004_requirements.sql`） | 有 `requirement_id`、`agent_run_id`、`payload`（内含可选 `reason`）、`kind`、`dedup_key`；**没有来源字段** |
| 产生建议的四个地方 | `field_align.suggest_alignment()`（来自 OpenAPI 响应字段，无 agent_run）；`links.py` `link_suggestions()`（来自外键字段的规则推断，无 agent_run）；`ai_tasks.structure_requirement()`（带 requirement_id）；`ai_tasks.complete_model()`（Agent 自由补全，`requirement_id` 可有可无） |
| `web\src\components\SuggestionList.tsx` | 每条只有 Accept / Reject，显示 `requirement_code` 标签；**没有批量接受**，也没有勾选框 |

### 5.2 方案

**数据模型（0023）**

```sql
ALTER TABLE model_suggestion
  ADD COLUMN source text NOT NULL DEFAULT 'ai_inferred'
    CHECK (source IN ('requirement','openapi','model_rule','ai_inferred')),
  ADD COLUMN evidence text;  -- 依据：需求原文片段 / API 路径和字段 / 规则说明
-- 回填：有 requirement_id → requirement；kind='field' 且 agent_run_id IS NULL → openapi；
-- kind='link' 且 agent_run_id IS NULL → model_rule；其余保持 ai_inferred
```

**后端**

- `SuggestionService.add_many()` 增加 `source` 参数（每个调用方显式传入）；`complete_model()` 里：Agent 给了 `requirement_id` 且校验存在、并给出了 `evidence`（需求原文片段，平台检查它确实出现在该需求的文本里）→ `requirement`；否则 `ai_inferred`。
- `NodeSuggestion` / `AttributeSuggestion` / `FieldSuggestion` 等加 `evidence: str | None`；`complete_model` 提示词："只提出能在需求原文里找到依据的内容，并在 evidence 里引用原文；没有依据的内容不要提。"
- 新接口 `POST /api/v1/suts/{sut_id}/suggestions/accept-batch` body `{ids: [uuid], include_ai_inferred: bool=false}`：逐条接受（复用 `accept()`），`ai_inferred` 的条目在未显式允许时跳过；需要额外输入的条目（新节点要名称、link 要确认）跳过并返回原因。
- 接受 `ai_inferred` 的单条建议时要求填写"依据"（`AcceptIn.note`，≥ 5 字），写入 change log。

**前端（`SuggestionList.tsx`）**

- 每条显示来源标签：需求 REQ-xxx（蓝，可点）/ OpenAPI（绿，显示 `METHOD /path`）/ 模型规则（青）/ **AI 推断**（橙）；`evidence` 显示在标签悬停或展开区。
- 加勾选框和"接受所选"按钮；默认勾选：requirement、openapi、model_rule；AI 推断**默认不勾选**；顶部筛选"只看 AI 推断"。
- 接受 AI 推断时弹窗填依据。

**对统计的影响**：无（建议不影响执行统计）。可在模型审阅页 `model_review.py` 的 `pending_by_kind` 旁加 `pending_by_source`。

**测试**：`tests\api\test_requirements_api.py` / `test_field_align_api.py` / `test_links_api.py` 各自断言 source；回填迁移测试（`tests\db\test_db_foundation.py` 的迁移用例）；`complete_model` 证据校验（伪造的引用 → ai_inferred）；batch 接受默认跳过 ai_inferred；前端 `SuggestionList.test.tsx` 默认勾选和标签。

---

## 6. #4（可选）：AI 补全去重，名称必填

### 6.1 现状

- `SuggestionService.add_many()`：节点按 `find_similar_node()`（规范化名称相等或包含）和已有节点去重；`dedup_key = node:<kind>:<normalized name>`，只防"完全同名的待处理建议"。
- `model_catalog()` 已把已有节点（含绑定的 API）传给 Agent，提示词也写了"不要重复"，但没有平台侧强制。
- 漏掉的情况（演示中出现的 3 个重复动作 + 1 个空壳）：
  1. 名称写法不同但含义相同（例如中文名 vs 英文名、"Approve order" vs "Approve purchase order" 之外的同义改写），包含匹配抓不到；
  2. **同一批**建议之间互相重复（逐条插入时只和库里比，同批的两个不同名称都能进）；
  3. 新动作和已有动作绑定的是**同一个 API**；
  4. 节点只有名称、没有说明 / 输入输出，接受后在需求 Structure 里成了"空壳"（`Text` 只要求 `min_length=1`）。

### 6.2 方案

后端（`suggestions.py`、`ai_tasks.py`，无表结构改动；被丢弃的计数放在返回值里）：

1. `NodeSuggestion` 校验：`name` 去空白后 ≥ 2 字符；`node_kind='action'` 时 `description` 必填（≥ 5 字）；不满足 → 丢弃，计入 `dropped.invalid`。
2. 新字段 `api: str | None`（"METHOD /path"）：动作建议若声称对应某个 API，平台查 `api_endpoint`；该 API 已被某个动作节点绑定（`node_api_link`）→ 判为重复，丢弃并在返回里说"已有动作 X 绑定了该接口"。
3. 同批去重：`add_many()` 先在内存里按 `(node_kind, normalize_name)` 和 `(node_kind, api)` 合并同批条目。
4. 和**待处理**、**已拒绝**的建议比对相似度（复用 `find_similar_node` 的规则，扩展到 `model_suggestion.payload->>'name'`）：已拒绝过的同类建议不再提出（避免拒绝后又冒出来）。
5. `complete_model` 返回 `{created, skipped, dropped: {duplicate_node, duplicate_api, duplicate_in_batch, previously_rejected, invalid}}`；前端 `AiCompletion.tsx` 显示"新增 N 条，跳过 M 条（原因…）"。
6. 提示词补充：已有节点的绑定 API 已在 `model` 输入里；"新动作必须对应一个尚未被绑定的接口或需求里明确的操作"。
7. 语义级去重（中英文同义）不靠大模型额外调用：先靠第 2、4 条覆盖大部分；剩余的作为已知限制，见决策 D9。

前端：`AiCompletion.tsx` 显示丢弃统计；`SuggestionList.tsx` 新节点建议若和已有节点相似度高（后端返回 `similar_to`）显示"可能重复：X"。

统计影响：无。

测试：`tests\api\test_model_api.py` / `test_requirements_api.py`：同批重复只留一条；同 API 的新动作被丢弃；空说明动作被丢弃；已拒绝的建议不再出现；返回的 dropped 计数正确。前端 `AiCompletion` 显示丢弃统计。

---

## 7. 实施顺序和估算

每一步都按现有流程：先补规格到 `D:\CodeWork\TestAgent\specs\test-agent-platform\`，测试先行，最后在 Docker 里把演示从头跑一遍验证。

| 顺序 | 内容 | 估算 | 依赖 / 说明 |
|---|---|---|---|
| 1 | 迁移 0023（全部表结构）+ `failure_classify.py` + `pytest_report.py` 的 kind 和结构化字段 + 单测 | 1 天 | 后面所有项的基础 |
| 2 | #18 缺脚本：运行时记 skipped、`script_gaps`、409 和三个选项、报告细分 | 1.5 天 | 依赖 1（`failure_kind='no_script'`）；最快消除"假发现" |
| 3 | #9/#15 执行侧：执行记录分类和 summary、`FailureSummary` 组件、执行详情 / 运行页 / 报告按原因 | 1 天 | 依赖 1 |
| 4 | #9/#15 自检侧：`AutomateOut.verdict`、`sut_mismatch`、confirm-sut-issue / mark-script-issue、用例页按钮 | 1.5 天 | 依赖 1、3 |
| 5 | #13 运行入口：`runnable-tasks`、`run-tasks`、`RunTasksModal`、Start testing / Next / 全部运行 | 1.5 天 | 依赖 2（缺脚本提示复用） |
| 6 | #6 建议来源和批量接受 | 2 天 | 独立，可与 5 并行 |
| 7 | #4 补全去重和名称必填 | 1.5 天 | 依赖 6 的 `evidence` 字段（同一个 schema 改动） |
| 8 | CHANGELOG `[Unreleased]`、README / 演示手册里 Needs fix、Start testing 的说法同步；Docker 演示复跑 | 0.5 天 + 复跑 | 结论仍只写"找到 X / 3" |
| | **合计** | **约 10 人天**；只做 1–5 约 6.5 天 | |

建议按 1→2→3→4→5 做完先推一次 develop（结果可信度的核心），再做 6→7 推第二次。每次推送都在 CHANGELOG `[Unreleased]` 记一笔。

---

## 8. 需要你决定的问题（都给了推荐默认）

| 编号 | 问题 | 选项 | 推荐默认 |
|---|---|---|---|
| D1 | 自检时判断为"疑似系统问题"后，默认怎么处理那份草稿脚本？ | A. 绑定脚本并记一条 failed（之后每次运行都会失败直到系统修好）；B. 只记 failed，不绑定；C. 什么都不做，只换提示文案 | **A**（主按钮），B 作为次选；都需要人点确认，平台不自动做 |
| D2 | 断言失败时"更像谁的问题"由谁判断？ | A. 自检阶段让 Agent 交结构化判断 + 平台校验，任务运行阶段用确定性规则；B. 每次失败都自动调用 `analyze_failure`；C. 全部只用确定性规则 | **A**（不增加任务运行的模型调用和费用） |
| D3 | 平台 / 环境原因的 error 是否从通过率分母里去掉？ | A. 不去掉，报告里按原因单独展示；B. 去掉，另算"有效通过率" | **A**（保守、和现有口径一致；B 以后可以加） |
| D4 | 缺脚本的用例运行时记成什么？ | A. 复用 `skipped` + `failure_kind='no_script'`；B. 新增状态 `not_executable` | **A**（不改状态机和所有统计口径，skipped 本来就不算通过） |
| D5 | 自动化任务的规则同步要不要自动排除缺脚本的用例？ | A. 照常加入，标"缺脚本"，运行前提示；B. 不加入，等有脚本后再自动加入 | **A**（用例不会"凭空消失"，提示更直观） |
| D6 | 历史上已记成 error 的缺脚本记录（如演示里的 TC-019）要不要改成 skipped？ | A. 不改状态，只回填 `failure_kind='no_script'` 让界面显示正确原因；B. 改成 skipped 并重算报告 | **A**（历史记录保持原样，可追溯） |
| D7 | 一键运行时，处于 draft 的任务怎么办？ | A. 弹窗里提供"同时设为 ready"开关，默认关；B. 默认打开；C. 不处理，只运行已 ready 的 | **A** |
| D8 | Start testing 弹窗默认行为 | A. 默认勾选所有可运行任务，同时提供"只改状态"；B. 默认不勾选 | **A** |
| D9 | #4 语义级去重（中英文同义名）要不要额外调一次大模型判断？ | A. 先不调，靠同 API、同批、已拒绝、相似名四条规则 + 界面"可能重复"提示；B. 调用一次小模型做同义判断 | **A**（省钱、可复现；演示里的重复动作预计多数能被“同 API / 同批 / 相似名”规则拦住，实现后用演示数据验证） |
| D10 | #6、#4 放在这一批还是拆到下一批？ | A. 同一批，分两次推送；B. 拆到批次 D（建模流程）一起做 | **A**（TODO 批次 A 本来就包含，而且影响"模型以确认过的需求为准"这条结论） |
| D11 | 可读摘要用什么语言？ | A. 结构化字段由前端按模板渲染（界面目前是英文），Agent 写的那句判断按 `TESTAGENT_AGENT_LANGUAGE`；B. 全部按 Agent 语言生成 | **A**（等界面 i18n 时模板一起翻译） |
| D12 | 接受"AI 推断"的建议时是否强制填写依据？ | A. 强制（≥ 5 字）；B. 可选 | **A**（单条接受时填；批量接受默认就不包含 AI 推断） |

---

## 9. 不在本批范围

- 导航顶层页面、步骤条当前步可点、最近一次运行列（批次 B：#10/#11/#12/#14）。
- 列表总数、滚动、抽屉宽度等界面细节（批次 C）。
- 拒绝后撤销、missing model 一键建节点（#8，批次 D）。
- 外部缺陷系统对接、远程脚本仓库（批次 E / 路线图）。

确认方式：直接回复各决策的编号和选项（例如"D1 选 B，其余按推荐"），或者"全部按推荐"。确认后我按第 7 节顺序开始，先写规格和测试。
