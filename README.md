# TestAgent

基于本体模型的 AI 测试开发平台。把被测系统写成实体、动作、关系和字段，需求挂在这份模型上，Agent 在需求划定的范围内起草用例和 Playwright 脚本。确认、冻结、设为就绪、接受建议这些关口由人来做。

界面是简体中文。部署和运维的英文说明在 [docs/deployment.md](docs/deployment.md)。

![license](https://img.shields.io/badge/license-Apache--2.0-blue)
![python](https://img.shields.io/badge/python-3.12-blue)
![postgres](https://img.shields.io/badge/PostgreSQL-17-336791)

## 能做什么

- **被测系统与版本**：一个系统下有多个版本。每个版本有自己的模型（节点、字段、关系、边、动作规则）。新建后续版本时复制来源版本，之后两边分开改。接口定义仍登记在系统上。
- **建模**：图谱把实体和它相关的实体、动作放在一起，节点可拖动，位置记在浏览器里。「重排」按当前关系重新布局并丢掉已拖动的位置。动作到实体的线是实心曲线：作用对象标「修改」，效果明确新建或删除该实体时标「新建」或「删除」，只读引用标「读取」，执行人标「执行人」。实体之间的关系是另一种颜色的实心曲线。另有列表、模型评审（可导出）和 API 注册表（可从 OpenAPI 导入）。
- **需求**：对照当前版本的模型来写。可以 AI 结构化，条目指向模型节点、字段和关系。确认后可冻结，并留下模型快照。
- **用例**：按单条需求生成。生成前要确认范围预览；生成后覆盖目标必须被用例打到，或由人确认放弃。一条动作的效果若满足下一条动作的前置条件，可以生成跨需求的端到端用例。用例设为就绪后才会进入自动执行。
- **执行**：pytest 与 Playwright 脚本、Agent 按步骤驱动浏览器或调用接口，以及手工记录结果。任务可以定时跑。
- **缺陷与报告**：失败执行可以建缺陷或做原因分析。报告按任务、版本汇总。
- **账号**：角色 `admin` / `member`。只有管理员能改 Agent 模型设置、环境启动命令和用户。

不配置大模型时，建模、手写用例、脚本执行、缺陷和报告仍然可用。Agent 的输出语言默认简体中文。

## 导航

左侧菜单：

- **全部被测系统**：系统列表。
- **当前系统**（进入某个系统后）：切换系统和版本，然后是概览、建模（模型图谱、模型评审、API 注册表）、版本与需求、策略、任务、用例、执行、缺陷。还没有版本时，建模和版本相关入口不可用。
- **跨系统**：执行、缺陷、测试报告。
- **人员**（人员、人员统计）、**Agent**（设置、运行、工具），管理员另有**用户**。

## 技术栈

- 后端：Python 3.12、FastAPI、PostgreSQL 17。Agent 运行时用 LangGraph，调用 OpenAI 兼容接口。
- 前端：React、Ant Design、Vite。
- 执行：pytest、Playwright（无头 Chromium）。生成的脚本在每个被测系统自己的 git 测试仓里。

## 仓库布局

| 路径 | 内容 |
|---|---|
| `src/testagent` | 平台 API、服务和 Agent |
| `web` | 前端 |
| `examples/supply_chain` | 供应链演示被测系统 |
| `ops` | 启动、种子、还原数据库 |
| `docs` | 部署说明和演示说明 |
| `specs/test-agent-platform` | 规格与设计 |
| `tests` | 后端与端到端测试 |

## 快速开始

### 本机（Windows）

需要 Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 20 或以上、PostgreSQL 17，以及配好的 `.env`（至少 `TESTAGENT_DATABASE_URL`）。

在 `D:\CodeWork\TestAgent\release\testagent` 双击 `ops\start.cmd`，或：

```powershell
cd D:\CodeWork\TestAgent\release\testagent
powershell -NoProfile -ExecutionPolicy Bypass -File ops\start.ps1
```

第一次会构建前端，然后启动平台并打开浏览器。`ops\start.cmd -Rebuild` 在改过前端之后重新构建。演示被测系统的地址是 `http://127.0.0.1:8766`。可选：`uv run python ops/seed_supply_chain.py` 写入演示系统（已有模型时不会覆盖）。

检查：

```powershell
uv run pytest -q
uv run ruff check . ; uv run ruff format --check .
cd web ; npm run lint ; npx tsc -b --noEmit ; npm test ; npm run build
```

### Docker Compose

```bash
cp .env.example .env
# 填写 POSTGRES_PASSWORD、TESTAGENT_ADMIN_USER、TESTAGENT_ADMIN_PASSWORD
docker compose up -d --build
```

浏览器打开 `http://localhost:8765`，用 `.env` 里的管理员登录。演示被测系统在 `http://localhost:8766`。服务是 `db`、`demo`、`testagent`；公网 HTTPS 另有 `proxy`（Caddy）。端口默认只绑在 `127.0.0.1`。

镜像里带无头 Chromium。升级已有部署后，若要换成当前仓库里的演示模型和需求，见下面的还原命令。不要删除 `caddy-data` 卷。

更完整的账号、HTTPS、备份和排错：[docs/deployment.md](docs/deployment.md)。

## 配置

写在 `.env`。模型的 Base URL、模型名和 API Key 在界面 **Agent → 设置** 里填写，密钥在 `runtime/secrets.json`，不进数据库。

| 变量 | 含义 |
|---|---|
| `TESTAGENT_AGENT_LANGUAGE` | Agent 写出的文字的语言。默认 `Simplified Chinese`。例如设为 `English` 则改成英文。 |
| `TESTAGENT_SEED_DEMO` | Docker 启动时是否尝试写入供应链演示。默认 `1`。系统里已经有模型时不会重写。 |
| `TESTAGENT_DEMO_URL` | 演示应用不在本机时的地址。Compose 里是 `http://demo:8766`。 |
| `TESTAGENT_ADMIN_USER` / `TESTAGENT_ADMIN_PASSWORD` | 还没有任何账号时创建的第一个管理员。密码至少 10 位。 |

## 供应链演示

系统代码 `supply-chain`，名称「供应链执行（演示）」。v1.0 是申请到收货过账直接入库，没有质检、没有超收容差。v2.0 在复制 v1 之后加上质检、`inspectionRequired`、超收容差（小数，`0.1` = 10%）和「合格供应商才能下达」。固定需求 REQ-001～REQ-016 的正文、两个版本的差别，以及还原命令，写在 [docs/demo-supply-chain.md](docs/demo-supply-chain.md)。示例应用说明：[examples/supply_chain/README.md](examples/supply_chain/README.md)。

还原（默认只演练；`--apply` 清掉该系统的平台数据后重建，并保留系统行和环境）：

```powershell
cd D:\CodeWork\TestAgent\release\testagent
uv run python ops/restore_supply_chain.py
uv run python ops/restore_supply_chain.py --apply --keep-repo --demo-url http://127.0.0.1:8766
```

```bash
cd ~/testagent
git pull && docker compose up -d --build
docker compose exec testagent python ops/restore_supply_chain.py
docker compose exec testagent python ops/restore_supply_chain.py --apply --keep-repo --demo-url http://demo:8766
```

容器里用 `python`，不要在宿主机上用 `uv`。不能直接跑 Docker 时在命令前加 `sudo`。

## 文档

- [供应链演示与还原](docs/demo-supply-chain.md)
- [部署](docs/deployment.md)
- [服务器升级（中文）](docs/server-upgrade.zh.md)
- [规格与设计](specs/test-agent-platform/README.md)
- [贡献](CONTRIBUTING.md) · [安全问题](SECURITY.md) · [第三方许可](docs/third-party-licenses.md)

## 许可

[Apache License 2.0](LICENSE)。Copyright 2026 Coral-Lee。
