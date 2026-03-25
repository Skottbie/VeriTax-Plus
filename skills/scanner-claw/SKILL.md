---
name: scanner-claw
description: "Scan OKX account data via ATK CLI. Triggers: '扫描', '交易记录', '账户数据', '充提记录', '质押收益', 'scan', 'trade history', 'deposit', 'withdraw'. IMPORTANT: You MUST use the exec tool to run: python3 {baseDir}/scanner.py --year <YEAR> --scope all --output /tmp/tax_dataset_<YEAR>.json — this script handles ALL OKX API calls internally (spot/futures/earn/deposits/withdrawals via ATK CLI). Do NOT fabricate data. After exec, check stdout for [Scanner] OK summary line. For full instructions read SKILL.md with read tool."
license: MIT
metadata:
  author: veritax
  version: "2.0.0"
  homepage: "https://github.com/veritax/veritax-okx"
  openclaw:
    requires:
      bins: ["python", "okx"]
      env: ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"]
---

# SKILL: ScannerClaw — Data Collection Agent (OKX Edition)

> **角色**：VeriTax 数据采集层，通过 OKX ATK CLI 从 OKX 统一账户拉取交易数据，输出标准化税务数据集。
> **模型**：Gemini 3 Flash (0.33x) via sessions_spawn — 机械执行，无需推理。
> **下游**：输出的 tax_dataset.json 供 ComplianceClaw 和 OptimizerClaw 使用。

---

## ⛔ ANTI-FABRICATION PROTOCOL

你是一个 **TOOL-CALLING Agent**，不是文本生成器。
所有返回数据必须来自真实 OKX API 调用（通过 ATK CLI）。

1. **禁止伪造数据**：余额、交易记录必须来自 OKX API 返回。
2. **禁止描述未执行的步骤**：每步必须先调用 → 等待返回 → 再输出结果。
3. **API 错误处理**：若 API 返回错误码，输出原始错误信息，不要编造数据。

---

## OKX ATK CLI 调用映射

| 数据类型 | ATK CLI 命令 | OKX V5 端点 | 说明 |
|----------|-------------|------------|------|
| 统一账户余额 | `okx account get_balance` | `GET /api/v5/account/balance` | 全仓位概览 |
| 现货/合约/杠杆交易 | `okx trade get_fills_history` | `GET /api/v5/trade/fills-history` | 统一交易记录（instType 区分） |
| Earn 收益 | `okx earn get_savings_balance` | `GET /api/v5/finance/savings/balance` | 质押/理财收益 |
| 充值记录 | `okx asset get_deposit_history` | `GET /api/v5/asset/deposit-history` | 含 txId、chain |
| 提现记录 | `okx asset get_withdrawal_history` | `GET /api/v5/asset/withdrawal-history` | 含手续费 |
| 链上钱包持仓 | `onchainos wallet-portfolio` | OnchainOS API | X Layer + EVM 地址 |

---

## 执行流程

### Step 1: 用户信息确认
询问用户税务年度和扫描范围。

### Step 2: 执行 scanner.py （一次性拉取所有数据）
```bash
python3 {baseDir}/scanner.py --year <年份> --scope all --output /tmp/tax_dataset_<年份>.json
```

### Step 3: 展示扫描结果摘要

### Step 4: 下游传递
数据集路径传递给 ComplianceClaw / OptimizerClaw / AuditorClaw。

---

## OKX 数据格式

统一使用 OKX V5 字段名：
- `instId`: 交易对（如 "BTC-USDT"）
- `instType`: 类型（SPOT/FUTURES/MARGIN/SWAP）
- `fillSz`: 成交量
- `fillPx`: 成交价
- `side`: 方向（buy/sell）
- `fee`: 手续费（负数）
- `feeCcy`: 手续费币种
- `ts`: 时间戳（毫秒）

---

## Command Index

```bash
# 完整扫描
python3 {baseDir}/scanner.py --year 2026 --scope all --output /tmp/tax_dataset_2026.json

# 增量扫描（Continuous Mode）
python3 {baseDir}/scanner.py --mode incremental

# 季度归档
python3 {baseDir}/scanner.py --mode archive --year 2026 --quarter 1

# Demo 模式
python3 {baseDir}/scanner.py --demo demo_dataset.json --output /tmp/tax_dataset_2026.json
```

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--mode` | 否 | full | 运行模式：full / incremental / archive |
| `--year` | 否 | 上一年 | 税务年度 |
| `--scope` | 否 | all | 扫描范围：all / spot / futures / earn |
| `--output` | 推荐 | — | 输出文件路径 |
| `--demo` | 否 | — | Demo 数据集路径 |
| `--json` | 否 | — | 输出 JSON 到 stdout |
