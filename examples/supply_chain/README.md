# 供应链执行（演示）

被测系统示例，不是 TestAgent 平台本身。系统代码 `supply-chain`，中文名「供应链执行（演示）」。

示例应用实现的是已经开发完成的 v2：需要质检的物料必须质检合格才能过账，下达订单时供应商必须合格，
收货不得超过 `订购数量 ×（1 + 超收容差）`。容差是小数，`0.1` 表示允许超收 10%。

平台种子里有两个版本：

- **v1.0**：申请 → 订单 → 收货过账即入库。模型里没有质检，也没有超收容差。
- **v2.0**：从 v1.0 复制后再加上质检单、物料「需要质检」、超收容差，以及供应商必须合格才能下达。

固定需求是 REQ-001～REQ-012；v2.0 另有 REQ-013～REQ-016。正文以种子为准。

## 启动

```bash
uv run uvicorn examples.supply_chain.api:create_app --factory --host 127.0.0.1 --port 8766
```

界面：<http://127.0.0.1:8766/> 。OpenAPI：<http://127.0.0.1:8766/docs> 。

重置业务数据：`POST /sample/reset`。

平台里的系统、版本、模型和需求用 `uv run python ops/restore_supply_chain.py --apply --keep-repo` 还原。
加上 `--demo-url http://127.0.0.1:8766` 会同时重置示例应用里的业务数据。
