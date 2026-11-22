# 供应链执行（演示）

被测系统示例，不是 TestAgent 平台本身。系统代码 `supply-chain`，中文名「供应链执行（演示）」。

示例应用实现的是已经开发完成的 v2：需要质检的物料必须质检合格才能过账，下达订单时供应商必须合格，收货不得超过订购数量 ×（1 + 超收容差）。容差是小数，`0.1` 表示允许超收 10%。

平台种子里有两个版本：

- **v1.0**：申请 → 订单 → 收货过账即入库。模型里没有质检，也没有超收容差。
- **v2.0**：从 v1.0 复制后再加上质检单、物料「需要质检」、超收容差，以及供应商必须合格才能下达。

平台里 v1.0 已封板，需求是 REQ-001～REQ-012。v2.0 只登记 REQ-007～REQ-009 和 REQ-013～REQ-016。正文和还原命令见 [docs/demo-supply-chain.md](../../docs/demo-supply-chain.md)。

## 启动

```bash
uv run uvicorn examples.supply_chain.api:create_app --factory --host 127.0.0.1 --port 8766
```

界面：<http://127.0.0.1:8766/> 。OpenAPI：<http://127.0.0.1:8766/docs> 。

重置业务数据：`POST /sample/reset`。

平台侧还原见 [docs/demo-supply-chain.md](../../docs/demo-supply-chain.md)。本机示例：

```powershell
uv run python ops/restore_supply_chain.py --apply --keep-repo --demo-url http://127.0.0.1:8766
```
