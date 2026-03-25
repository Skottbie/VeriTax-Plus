---
name: optimizer-claw
description: "TLH tax-loss harvesting optimization (OKX Edition). Triggers: 'TLH', 'tax-loss', '亏损抵扣', '省税', '优化', 'harvest', 'wash sale', 'Jumpstart'. IMPORTANT: You MUST use the exec tool to run: python3 {baseDir}/optimizer.py --dataset /tmp/tax_dataset_<YEAR>.json --jurisdiction <JURISDICTION> — identifies unrealized losses and recommends substitute assets. Do NOT fabricate savings amounts. For monitor mode: python3 {baseDir}/optimizer.py --mode monitor. After exec, present TLH opportunities to user. For full instructions read SKILL.md with read tool."
license: MIT
metadata:
  author: veritax
  version: "2.0.0"
  homepage: "https://github.com/veritax/veritax"
  openclaw:
    requires:
      bins: ["python"]
      env: ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"]
---

# SKILL: OptimizerClaw — TLH Strategy Engine (OKX Edition)

> **角色**：VeriTax 税务优化层，识别 TLH（Tax-Loss Harvesting）机会，审计替代标的安全性，执行卖出+回购操作。
> **模型**：Gemini 3.1 Pro (1x) via sessions_spawn — 需要推理能力做策略分析。
> **适用辖区**：日本（3年损失结转）、澳洲（CGT offset）、加拿大（capital loss deduction）。
> **不适用**：台湾（无资本利得税）、新加坡（个人免税）。

---

## OKX Skills 调用映射

| OKX Skill / ATK CLI | 用途 |
|---------------------|------|
| `okx-security` token-scan | 替代标的合约安全审计（过滤 rug pull） |
| `okx-dex-token` detail | 替代标的流动性/持有人分布评估 |
| `okx-dex-signal` alerts | smart money 信号 → 最佳执行时机 |
| `okx-dex-token` trending | 替代标的市场热度过滤 |
| ATK CLI `okx spot place-order` | TLH 订单执行 |
| ATK CLI `okx account balance` | 实时持仓余额查询 |
| ATK CLI `okx market ticker` | 实时行情价格获取 |
| ATK CLI `okx trade get-fills` | 近期成交查询（wash sale 检查） |

### TLH 规划可用的 ATK 能力清单

以下能力是 TLH 方案规划阶段可考虑的 ATK 能力族。它们不等于当前执行链路已经全部调用，但会作为规划候选集合供 Pro 模型选择：

| 能力族 | 规划用途 |
|--------|----------|
| `account.balance` | 持仓与可用余额盘点 |
| `account.bills` | 交易、充提、资金流重建 |
| `account.fees` | 手续费与执行成本评估 |
| `spot.fills` | 现货成交与历史执行回溯 |
| `spot.place-order` | 卖出亏损仓位、买入替代标的 |
| `trade.get-fills` | 近期成交与 wash sale 检查 |
| `market.ticker` | 实时定价、触发阈值判断 |
| `earn.savings.balance` | 资金闲置期的收益部署判断 |
| `swap.*` | 现货/替代买入的链路规划与执行备选 |
| `futures.*` | 方向性对冲或保持敞口的备选方案 |
| `option.*` | 在洗售窗口或强约束辖区下的替代敞口方案 |
| `bot.grid` | 作为收益部署或波动区间策略的备选 |

### TLH 规划可用的 ATK 模块清单

TLH 方案规划阶段可以把 ATK 视为以下模块集合：

| 模块 | 规划可用能力 |
|------|--------------|
| `market` | ticker / tickers / orderbook / candles / history candles / index ticker / index candles / price limit / funding rate / mark price / open interest / trades / stock tokens / indicators |
| `spot` | orders / get / fills / place / cancel / amend / batch orders / algo orders / trailing stop / OCO / order history / archive history |
| `swap` | positions / orders / get / fills / place / cancel / amend / batch orders / close / leverage / algo orders / trailing stop / OCO |
| `futures` | orders / positions / fills / place / cancel / amend / get / close / leverage / batch orders / algo orders / trailing stop / OCO |
| `option` | orders / positions / fills / place / cancel / amend / batch cancel / option chain / Greeks / IV |
| `account` | balance / asset balance / positions / positions history / bills / bills archive / fee rates / config / position mode / max size / max withdrawal / leverage / trade fee / audit |
| `earn.savings` | balance / purchase / redeem / rate history / lending history / rate summary |
| `earn.onchain` | offers / orders / history / purchase / redeem / protocol filtering |
| `earn.dcd` | pairs / products / quote-and-buy / orders / redeem / order state |
| `bot.grid` | grid orders / details / sub-orders / create / stop |
| `bot.dca` | DCA orders / details / sub-orders / create / stop |

> 说明：当前实现中，TLH 默认主链路优先使用已落地的 ATK 能力；上表用于扩展规划空间，便于 Pro 在需要时组合更广的能力集。

---

## 执行流程

### Step 1: 亏损仓位扫描
从 ScannerClaw 的 tax_dataset 中识别当前持仓中未实现亏损 > 阈值的仓位。
按亏损金额降序排列，输出候选列表。

### Step 2: 替代标的筛选
对每个亏损仓位：
- `okx-dex-token` trending → 同赛道 Token 热度排名
- `okx-dex-token` detail → 流动性/持有人分布评估
- `okx-security` token-scan → 合约安全审计（过滤 rug pull）
- 输出安全替代标的推荐列表

### Step 2.5: 多方案排序
在替代标的列表之上，再输出按辖区约束排序的候选方案：
- 现货替代保持敞口
- 衍生品对冲保持敞口
- TLH 后收益部署

排序原则：先满足辖区合规，再尽量保持市场敞口，最后比较收益增强空间。

### Step 3: 执行时机判断
- `okx-dex-signal` → smart money / whale 信号分析
- 判断当前是否适合执行（避开大幅波动期）

### Step 4: Wash Sale / Superficial Loss 检查
- 日本：无 wash sale rule（可立即回购同资产）
- 澳洲：same asset repurchase 需注意 ATO 实质重于形式原则
- 加拿大：30 天 superficial loss rule → 必须等 30 天或用替代标的

### Step 5: 用户确认 + 执行（需用户明确同意）
⛔ **禁止自动执行交易**。必须展示行动计划 → 等待用户确认 → 再通过 OKX Spot API 下单。

### Step 6: Jumpstart / On-chain Earn Hook（可选）
省下的税金 → 推荐质押进 OKX Jumpstart 或 On-chain Earn。
> "🦞 税局没拿走的钱，让 OKX 帮您生钱。"

---

## Command Index

```bash
# 扫描 TLH 机会（一次性分析）
python {baseDir}/optimizer.py --dataset <tax_dataset.json> --jurisdiction japan

# JSON 输出
python {baseDir}/optimizer.py --dataset <tax_dataset.json> --jurisdiction australia --json

# TLH 执行 — Dry Run（默认，仅模拟，不下单）
python {baseDir}/optimizer.py --mode execute --dataset <tax_dataset.json> --jurisdiction japan --json

# TLH 执行 — 实际下单（通过 OKX Spot API）
python {baseDir}/optimizer.py --mode execute --dataset <tax_dataset.json> --jurisdiction japan --confirm --json

# TLH 执行 — Demo trading 下单（安全测试）
python {baseDir}/optimizer.py --mode execute --dataset <tax_dataset.json> --jurisdiction japan --confirm --testnet --json

# 指定执行标的（从 analyze 输出中筛选）
python {baseDir}/optimizer.py --mode execute --dataset <tax_dataset.json> --jurisdiction japan --actions '["ETH","AVAX"]' --confirm --json

# ---- Continuous Mode (v1.1) ----

# TLH 监控模式（cron 每小时触发）
python {baseDir}/optimizer.py --mode monitor --config <monitor_config.json> --jurisdiction japan
```

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--mode` | 否 | analyze | 运行模式：analyze / monitor / execute |
| `--dataset` | analyze/execute 时必填 | — | ScannerClaw 输出的税务数据集路径 |
| `--jurisdiction` | 是 | — | 辖区：japan / australia / canada |
| `--config` | monitor 时必填 | — | monitor_config.json 路径 |
| `--threshold` | 否 | 100 USD | 最小亏损金额阈值 |
| `--actions` | 否 | — | execute 模式白名单（JSON array，如 `'["ETH"]'`） |
| `--confirm` | 否 | — | execute 模式实际下单（无此flag=dry run） |
| `--testnet` | 否 | — | 使用 OKX Demo Trading 模式下单 |
| `--json` | 否 | — | 输出原始 JSON |

---

## Continuous Mode — TLH 监控（v1.1）

### 监控模式（`--mode monitor`）
由 cron job `veritax-monitor` 每小时触发，双层模型架构：

**Flash 层（0.33x，每小时运行）**：
1. `monitor_check()` — 读取 `monitor_config.json` 中的 `positions_watch`
2. 获取实时现货余额 + 行情价格（via ATK CLI）
3. 计算未实现盈亏，与 `loss_threshold_pct` 阈值比较
4. **未触发** → stdout 输出 `[Monitor] no_trigger` → 结束
5. **触发** → stdout 输出 `[Monitor] TRIGGERED asset=X loss_pct=Y`

**Pro 层（1x，仅触发时调用）**：
6. `tlh_decision()` — 验证持续性 → wash sale 检查 → 替代标的审计 → 税务节省估算
7. 返回 `action=recommend_sell` 或 `action=skip`（含原因）
8. 若推荐执行 → `execute_tlh()` 写入 monitor_config + TG 通知

### monitor_config.json 结构
```json
{
  "positions_watch": [
    { "asset": "ETH", "cost_basis_usd": 3200, "qty": 1.5,
      "loss_threshold_pct": -10, "sector": "L1" }
  ],
  "executed_tlh": [],
  "wash_sale_cooldowns": {}
}
```
