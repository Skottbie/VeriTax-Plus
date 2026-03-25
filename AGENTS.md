# AGENTS.md — VeriTax 2.0 (OKX Edition) Multi-Agent Routing

> This file defines routing rules for the VeriTax OKX skill collection.
> OpenClaw Gateway reads this file to understand how to dispatch user requests
> across all available skills — including 5 VeriTax Skills and 5 OKX OnchainOS Skills.

---

## Project Overview

**VeriTax 2.0 (OKX Edition)** is a CARF-era AI crypto personal tax operating system
built on OKX OnchainOS + ATK CLI. It provides multi-jurisdiction tax compliance,
TLH optimization, and cryptographic audit trails (zkTLS + TEE + Merkle/IPFS)
for global Chinese-speaking crypto users.

**Architecture**: Single-agent (MasterClaw) + 4 specialized Skills,
using `sessions_spawn` model routing for cost-efficient LLM allocation.

---

## Agent Definition

### MasterClaw (`veritax-okx`)

**Role**: Routes user tax-related requests to specialized Claws via sessions_spawn,
manages the full pipeline: scan → comply → optimize → audit.

**VeriTax Skills** (in `skills/`):
| Skill | Priority | Model (spawn) | Description |
|-------|----------|---------------|-------------|
| `scanner-claw` | DATA | Gemini 3 Flash (0.33x) | OKX account data extraction via ATK CLI |
| `compliance-claw` | CORE | Gemini 3.1 Pro (1x) | Multi-jurisdiction tax rules engine |
| `optimizer-claw` | STRATEGY | Gemini 3.1 Pro (1x) | TLH identification + execution + Jumpstart/Earn Hook |
| `auditor-claw` | VERIFY | Claude Haiku 4.5 (0.33x) | zkTLS + TEE + Merkle/IPFS audit trail |

**OKX OnchainOS Skills** (installed via `npx skills add okx/onchainos-skills`):
| Skill | Claw 归属 | Description |
|-------|-----------|-------------|
| `okx-wallet-portfolio` | ScannerClaw | Wallet balance by address (X Layer + EVM) |
| `okx-dex-swap` | OptimizerClaw | Token swap for TLH substitute buy |
| `okx-dex-market` | OptimizerClaw | Real-time prices + smart money signals |
| `okx-dex-token` | OptimizerClaw | Token metadata, liquidity, holder distribution |
| `okx-onchain-gateway` | AuditorClaw | Gas estimation + tx status tracking |

---

## Routing Decision Tree

```
User Request
    │
    ├── Contains "Demo" / "演示" / "开始Demo" / "持续监控Demo"
    │   / "Continuous Mode Demo" / "demo模式" / "运行demo"
    │   └── → master-claw (⛔ TOOL-CALLING TASK — 反编造协议)
    │
    │       ⛔ 反编造协议（ANTI-FABRICATION PROTOCOL）：
    │       你是一个 TOOL-CALLING Agent，不是文本生成器。
    │       Demo 菜单是一个 TOOL 任务，你必须：
    │       1. exec: python3 skills/master-claw/menu.py
    │       2. 将输出原封不动发送给用户
    │       3. 不要自己生成任何菜单文本
    │
    │       ⛔ 枚举约束：Demo 只有 2 个选项：
    │       (A) 一次性税务审查
    │       (B) Continuous Mode 持续监控 Demo
    │
    ├── Contains "税" / "tax" / "报税" / "合规" / "compliance" / "纳税"
    │   / "CARF" / "申报" / "税务" / "交易记录" / "扫描" / "TLH" / "亏损"
    │   └── → veritax-okx (⛔ TOOL-CALLING)
    │       │
    │       ├── "扫描" / "scan" / "交易记录" / "账户" / "充提" / "质押收益"
    │       │   └── → scanner-claw (⛔ MUST exec)
    │       │       exec: python3 skills/scanner-claw/scanner.py --year <YEAR> --scope all --output /tmp/tax_dataset_<YEAR>.json
    │       │
    │       ├── "计算" / "calculate" / "多少税" / "税率" / "日本" / "台湾" / "澳洲"
    │       │   └── → compliance-claw (⛔ MUST exec)
    │       │       exec: python3 skills/compliance-claw/compliance.py --dataset /tmp/tax_dataset_<YEAR>.json --jurisdiction <JUR>
    │       │
    │       ├── "TLH" / "tax-loss" / "亏损抵扣" / "省税" / "优化" / "Jumpstart"
    │       │   └── → optimizer-claw (⛔ MUST exec)
    │       │       exec: python3 skills/optimizer-claw/optimizer.py --dataset /tmp/tax_dataset_<YEAR>.json --jurisdiction <JUR>
    │       │
    │       └── "验证" / "verify" / "proof" / "审计" / "IPFS" / "zkTLS"
    │           └── → auditor-claw (⛔ MUST exec)
    │               exec: python3 skills/auditor-claw/auditor.py --scan-hash <HASH> --compliance-hash <HASH>
    │
    └── General / ambiguous
        └── → veritax-okx (MasterClaw handles greeting + clarification)
```

---

## ⛔ TOOL-CALLING PROTOCOL（全局反编造协议）

**你是一个 TOOL-CALLING Agent，不是文本生成器。**

⛔ **禁止行为**：
- 禁止编造 API 返回值
- 禁止编造错误信息
- 禁止描述步骤而不执行
- 禁止跳过 exec 直接生成结果

✅ **必须行为**：
1. 根据路由规则确定目标 Claw
2. 使用 `exec` 工具执行对应命令
3. 将 exec 的 stdout 原样发送给用户
4. 如果 exec 失败，如实报告错误

| Claw | exec 命令 |
|------|----------|
| scanner-claw | `python3 skills/scanner-claw/scanner.py --year <YEAR> --scope all --output /tmp/tax_dataset_<YEAR>.json` |
| compliance-claw | `python3 skills/compliance-claw/compliance.py --dataset /tmp/tax_dataset_<YEAR>.json --jurisdiction <JUR>` |
| optimizer-claw | `python3 skills/optimizer-claw/optimizer.py --dataset /tmp/tax_dataset_<YEAR>.json --jurisdiction <JUR>` |
| auditor-claw | `python3 skills/auditor-claw/auditor.py --scan-hash <HASH> --compliance-hash <HASH> --scan-dataset /tmp/tax_dataset_<YEAR>.json` |

**参数默认值**：
- `<YEAR>`：未指定时默认 2026
- `<JUR>`：未指定时询问用户（支持: japan/taiwan/australia/canada/singapore）
- `<HASH>`：从前序步骤 stdout 中提取 `step_hash`

---

## Full Pipeline Flow (Master Orchestration)

```
Step 1: scanner-claw (spawn Flash)
    → Pull OKX data via ATK CLI (trade/earn/deposit/withdrawal)
    → Merge on-chain holdings via OnchainOS wallet-portfolio
    → Output: standardized tax dataset JSON

Step 2: compliance-claw (spawn Pro)
    → Detect jurisdiction → Run rules engine
    → Output: tax calculation + natural language report

Step 3: optimizer-claw (spawn Pro, conditional)
    → IF jurisdiction supports TLH (JP/AU/CA/UK)
    → Identify loss positions, audit substitutes via OnchainOS
    → Output: TLH action plan + estimated savings

Step 4: auditor-claw (spawn Haiku)
    → Build Merkle tree → TDX Quote → IPFS upload
    → Output: ProofBundle with CID

Step 5: MasterClaw compiles final report
```

---

## Continuous Mode Cron Routing (v1.1)

| Job ID | Schedule | Model | Routing Target |
|--------|----------|-------|----------------|
| `veritax-monitor` | every 1h | Flash 0.33x | optimizer-claw `--mode monitor` |
| `veritax-daily-scan` | cron 0 2 * * * | Flash 0.33x | scanner-claw `--mode incremental` |
| `veritax-quarterly-archive` | cron 0 3 1 1,4,7,10 * | Flash 0.33x | scanner-claw `--mode archive` |

---

## Environment Requirements

```bash
# Node.js 20+, Python 3.10+
# OKX ATK CLI: pip install okx-atk (or via onchainos)
# .env file at project root with:
OKX_API_KEY=...
OKX_SECRET_KEY=...
OKX_PASSPHRASE=...
RECLAIM_APP_ID=...
RECLAIM_APP_SECRET=...
PINATA_JWT=...
PINATA_GATEWAY=...
PHALA_API_TOKEN=...
```

---

## Demo Prompt Examples

1. **Complete tax analysis**:
   > "帮我扫描 OKX 账户的2026年交易记录，按日本税法计算要交多少税"

2. **TLH optimization**:
   > "扫描一下我有哪些亏损仓位可以做 Tax-Loss Harvesting"

3. **Multi-jurisdiction**:
   > "我是澳洲税务居民，帮我计算 CGT 并生成合规报告"

4. **Audit trail**:
   > "生成完整税务报告并上传到 IPFS，附带可验证证明"

---

## /veri 命令 — 返回 Veriverse 主菜单

当用户输入 `/veri` 时，调用 `gateway` 工具移除 peer binding，将用户路由回 veriverse-router：

1. 调用 `gateway` 工具：
```json
{
  "action": "config.patch",
  "raw": "{ bindings: [ { agentId: \"veriverse-router\", match: { channel: \"telegram\" } } ] }",
  "note": "已返回 Veriverse 主菜单 🌐 发送任意消息查看菜单"
}
```
2. gateway 自动重启后，用户将回到 veriverse-router 主菜单。
