---
name: compliance-claw
description: "Calculate taxes by jurisdiction. Triggers: '计算', '多少税', '税率', '合规报告', '自查报告', 'CGT', 'ACB', '日本', '台湾', '澳洲', '加拿大', '新加坡'. IMPORTANT: You MUST use the exec tool to run: python3 {baseDir}/compliance.py --dataset /tmp/tax_dataset_<YEAR>.json --jurisdiction <JURISDICTION> — the rules engine computes all tax amounts deterministically. Do NOT fabricate tax numbers. Jurisdictions: japan, taiwan, australia, canada, singapore. After exec, present the tax report to user with disclaimer. For JSON output add --json. For full instructions read SKILL.md with read tool."
license: MIT
metadata:
  author: veritax
  version: "2.0.0"
  homepage: "https://github.com/veritax/veritax-okx"
  openclaw:
    requires:
      bins: ["python"]
---

# SKILL: ComplianceClaw — Tax Rules Engine (OKX Edition)

> **角色**：VeriTax 税规引擎，接收 ScannerClaw 的标准化税务数据集（OKX V5 格式），按用户所在辖区运行确定性规则计算，输出税额 + 自然语言报告。
> **模型**：Gemini 3.1 Pro (1x) via sessions_spawn — 需要推理能力解释复杂税规。
> **核心原则**：税务计算由 JSON 规则引擎确定性运行，LLM 只负责解释和呈现结果，不生成数字。

---

## ⛔ ANTI-FABRICATION PROTOCOL

1. **禁止伪造税额**：所有数字必须来自规则引擎计算结果，LLM 不得自行推算。
2. **禁止跳过规则引擎**：即使 LLM "知道"税率，也必须通过规则引擎执行后输出。
3. **辖区未覆盖时诚实声明**：若用户辖区不在已实现范围内，明确告知而非猜测。
4. **免责条款必须附加**：每份报告末尾必须包含：「本工具提供合规参考建议，最终税务申报请咨询持牌税务师。」

---

## 辖区模式

| 辖区 | 模式名 | 核心计算逻辑 | 规则文件 |
|------|--------|-------------|---------|
| 🇯🇵 日本 | `japan` | 双轨分类（特定暗号資産20%分离 vs 非特定55%综合）+ 币币逐笔日元计价 + 3年损失结转 | `rules/japan.json` |
| 🇹🇼 台湾 | `taiwan` | 自查报告生成 + 应税所得分类（质押/营业行为判定）| `rules/taiwan.json` |
| 🇦🇺 澳洲 | `australia` | CGT + 12个月50%折扣 + lot-level 成本基础 | `rules/australia.json` |
| 🇨🇦 加拿大 | `canada` | ACB + 50%inclusion rate + superficial loss rule 30天 | `rules/canada.json` |
| 🇸🇬 新加坡 | `singapore` | 所得类型自动分类（质押>$300SGD/借贷利息/Jumpstart）| `rules/singapore.json` |

---

## 数据格式（OKX V5）

输入数据集字段（来自 ScannerClaw）:
- `trades[]` — 统一交易记录（SPOT/SWAP/FUTURES/MARGIN），字段: instId, instType, side, fillSz, fillPx, fee, feeCcy, ts, pnl, billSubType
- `earn_records[]` — 理财收益记录，字段: amt, ccy, ts, product, type
- `deposits[]` / `withdrawals[]` — 充提记录

## 执行流程

```
MasterClaw → sessions_spawn(model="pro") → ComplianceClaw
  1. load_dataset(scanner_output.json)
  2. load_rule(rules/{jurisdiction}.json)
  3. fetch_fx_rate(year, currency) — USD→本地货币汇率
  4. convert_dataset(data, fx_rate) — USDT→本地货币
  5. aggregate_metrics(data, cost_basis_method) — 成本基础计算
  6. calculate_tax(rule, metrics) — 税额计算
  7. build_report() — 生成报告
  8. Output JSON with step_hash for audit chain
```

## 命令行用法

```bash
# 完整分析
python3 compliance.py --dataset /tmp/tax_dataset_2026.json --jurisdiction japan --json

# 每日简报 (Continuous Mode)
python3 compliance.py --dataset /tmp/tax_dataset_2026.json --jurisdiction japan --mode daily-digest --json
```
