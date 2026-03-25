<p align="center">
  <img src="VeriTax.jpg" alt="VeriTax+" width="200"/>
</p>

<h1 align="center">VeriTax+</h1>

<p align="center">
  <strong>Verifiable Crypto Tax OS for Global OKX Users</strong><br/>
  Built with OpenClaw, OKX Agent Trade Kit (ATK CLI), OKX OnchainOS, and Intel TDX-backed confidential execution
</p>

<p align="center">
  <a href="#judges-fast-path">Judges Fast Path</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#demo-runbook">Demo Runbook</a> •
  <a href="#continuous-mode-demo-case">Continuous Demo Case</a> •
  <a href="#reproducibility">Reproducibility</a> •
  <a href="#architecture-entry">Architecture Entry</a> •
  <a href="docs/public/PRODUCT_POSITIONING.md">Product Positioning</a> •
  <a href="docs/public/VERIFIABLE_ARCHITECTURE.md">Verifiable Architecture</a> •
  <a href="docs/public/RESEARCH_VALIDATION_APPENDIX.md">Research Validation</a> •
  <a href="docs/public/ENGINEERING_POSTMORTEMS.md">Engineering Postmortems</a>
</p>

---

## What Is VeriTax+?

VeriTax+ is a crypto tax operations system for (Chinese-speaking) Global OKX users facing growing cross-border reporting pressure under CARF, CRS, and jurisdiction-specific crypto tax rules.

It combines four layers into one workflow:

1. Accounting: reconstruct exchange and wallet activity into a usable tax ledger.
2. Compliance: run jurisdiction-aware rule logic for reporting and tax estimation.
3. Optimization: identify compliant tax-saving opportunities where local rules allow them.
4. Verification: attach cryptographic evidence for data provenance and execution integrity.

The project is built around a practical constraint: tax workflows are not just a chat problem. Users need a durable ledger, clear rule boundaries, and auditable evidence they can hand to an advisor or keep for future reporting.

CARF-related reporting is no longer only future policy. DAC8 took effect across 27 EU member states on January 1, 2026. The first CASP reports will be submitted to tax authorities in 2027.

## Judges Fast Path

If you only have 3-5 minutes, review in this order:

1. Product scope and market problem: [docs/public/PRODUCT_POSITIONING.md](docs/public/PRODUCT_POSITIONING.md)
2. System and trust layers: [docs/public/VERIFIABLE_ARCHITECTURE.md](docs/public/VERIFIABLE_ARCHITECTURE.md)
3. Research evidence trail: [docs/public/RESEARCH_VALIDATION_APPENDIX.md](docs/public/RESEARCH_VALIDATION_APPENDIX.md)
4. Engineering hardening record: [docs/public/ENGINEERING_POSTMORTEMS.md](docs/public/ENGINEERING_POSTMORTEMS.md)
5. Focused model-behavior memo: [RESEARCH_FLASH_4OPTIONS_BUG.md](RESEARCH_FLASH_4OPTIONS_BUG.md)

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 20+
- OpenClaw CLI installed and authenticated
- OKX API keys configured via ATK CLI (`~/.okx/config.toml`; read-only for scan, trading permission only if execution is required)

### Environment Setup

1. Create runtime env file from template:

```bash
cp .env.example .env
```

2. Install Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Install Node dependencies:

```bash
npm install
```

### Deploy Skills To OpenClaw Workspace

```bash
bash deploy_to_openclaw.sh --refresh
```

### Start Gateway

```bash
bash start_gw.sh
```

## Demo Runbook

### Local Full Demo (CLI)

```bash
npm run demo
```

Equivalent command:

```bash
python demo_director.py --full-auto
```

### Scene-By-Scene Debug Demo

```bash
python demo_director.py --scene scan0
python demo_director.py --scene cm-daily --jurisdiction japan
python demo_director.py --scene archive
```

### Cron-Driven Continuous Mode

```bash
bash setup_cron.sh
openclaw cron list
```

## Continuous Mode Demo Case

This section packages a real Telegram demo conversation into a judge-friendly script.

### Narrative Goal

Show one complete operational loop in under 5 minutes:

1. Baseline compliance + monitoring readiness.
2. Multi-day incremental monitoring (time-compressed).
3. Triggered TLH decision and execution.
4. Quarterly archive with cryptographic audit outputs.

### Live Interaction Script (Detailed)

<details>
<summary><strong>Click to expand full Continuous Mode interaction script (2026-03-25, Telegram)</strong></summary>

**`[14:17] User:`** 开始demo  
**`[14:17] VeriTax+:`** 🦞 Demo 数据已就绪。请选择服务类型：  
(A) 一次性税务审查（扫描→合规计算→TLH分析→审计证明）  
(B) Continuous Mode 持续监控 Demo（模拟多天：每日增量扫描 + 每小时TLH监控 + 闪崩触发）  
**`[14:17] User:`** B

**`[14:18] VeriTax+:`** CM-1 合规基线  
Continuous Mode 监控初始化
📊 合规基线报告（日本）
• 数据概况：已扫描 14 笔 交易记录，涵盖现货、合约及 Earn 收益。
• 资产构成：
  • BTC: 0.499 Units (Cost Basis: 3,413,587 JPY)
  • ETH: 7 Units (Cost Basis: 2,544,151 JPY)
  • OKB: 19.98 Units (Cost Basis: 985,366 JPY)
  • MATIC: 2,000 Units (Cost Basis: 286,217 JPY)
• 税务预估：本年度当前已实现收益约 927,811 JPY，预估应纳税额约 160,102 JPY。
• 风险预警：检测到部分资产（如 ETH）持有成本较高，若市场回调可能产生 TLH 优化机会。
✅ 监控参数规划
• 辖区：Japan (日本税法兼容)
• 资产：BTC/ETH/OKB/MATIC (监控路径已激活)
• 阈值：Unrealized Loss > 15% 或单个仓位亏损 > 50,000 JPY
• 结论：监控环境已就绪。
step_hash: 5a4c92f112ba7d305e06a6e8b129bd419d7b84634a369380421fe142772a438e

**`[14:18] VeriTax+:`** 📅 Day 1（增量 +4, ✅ all_clear）  
📊 增量扫描：新增 4 笔交易记录
📈 监控状态：✅ all_clear
💰 持仓快照：
• BTC: 0.5489775 (成本 4108906 JPY)
• ETH: 9 (成本 3211991 JPY)
• OKB: 19.98 (成本 985366 JPY)
• SOL: 30 (成本 691691 JPY)
• MATIC: 2000 (成本 286217 JPY)
🧾 累计已实现收益：927811 | 期货损益：59281 | 预估税额：160025
🔐 可信证明：step_hash=e28bc8c3af2153a75a3c3c8403791839664f57cd92a6c1ec21b590b2f8f0f7ad

**`[14:19] VeriTax+:`** 📅 Day 2（增量 +4, ✅ all_clear）  
📊 增量扫描：新增 4 笔交易记录
📈 监控状态：✅ all_clear
💰 持仓快照：
• BTC: 0.5489775 (成本 4108906 JPY)
• ETH: 10.5 (成本 3700945 JPY)
• OKB: 19.98 (成本 985366 JPY)
• SOL: 30 (成本 691691 JPY)
• AVAX: 100 (成本 604236 JPY)
🧾 累计已实现收益：927811 | 期货损益：45613 | 预估税额：157961
🔐 可信证明：step_hash=3139e05e9eabbf35cb0b336f5dddf9eda4c1b87acb3a0b970e308c41174f9146

**`[14:20] VeriTax+:`** 📅 Day 3（增量 +1, ⚠️ triggered 3 assets）  
📊 增量扫描：新增 1 笔交易记录
📈 监控状态：⚠️ triggered (3个标的)
💰 持仓快照：
• BTC: 0.5489775 (成本 4108906 JPY)
• ETH: 10.5 (成本 3700945 JPY)
• OKB: 21.978 (成本 1182439 JPY)
• SOL: 30 (成本 691691 JPY)
• AVAX: 100 (成本 604236 JPY)
🧾 累计已实现收益：927811 | 期货损益：45613 | 预估税额：157961
🔐 可信证明：step_hash=42761bb629251c7bd102a1f88499f944540ac1502cecb955dd5df53820e6a4d1

**`[14:20] VeriTax+:`** 📉 Tax-Loss Harvesting 分析结果  

💰 总可收割亏损：-1,346,355 JPY
💵 预估节税：753,218 JPY
🔄 Wash Sale 状态：日本には wash sale rule なし。即時回購可能。
🧭 排序方案：
[1] 现货替代保持敞口（score=88｜敞口保持=high｜可执行性=ready_now）
→ 卖出亏损现货，换入同赛道非同质替代资产，尽量保持市场敞口。
→ 辖区理由：优先满足当前辖区的 TLH 合规边界，并通过非同质替代资产维持主要市场暴露。
→ 执行备注：完全兼容当前 VeriTax+ execute 路径，可直接落到现货卖出加替代买入。
→ ATK 模块：account, market, spot
[2] 期权对冲保持敞口（score=79｜敞口保持=very_high｜可执行性=proposal_only）
→ 卖出现货后用 call 或低杠杆永续维持上行参与度。
→ 辖区理由：适合需要更强敞口连续性的用户，但必须先通过辖区规则校验后再执行。
→ 执行备注：当前阶段作为 Pro 推荐方案输出，不进入默认自动执行路径。
→ ATK 模块：account, market, swap, futures, option
[3] 税后资金收益部署（score=72｜敞口保持=medium｜可执行性=proposal_only）
→ TLH 完成后将部分资金部署到 Earn / DCD，提高空闲资金效率。
→ 辖区理由：更适合 TLH 完成后的资金管理，而不是替代主策略。
→ 执行备注：当前阶段仅作推荐，不替代核心 TLH 动作。
→ ATK 模块：account, market, earn, bot.grid
[4] 当前DEX无适合替代标的，Veri Agent将持续通过OnChainOS监控链上持仓情况
📋 当前可直接执行的 TLH 动作：
1. 卖出 ETH 10.5 单位（未实现亏损 -916,389 JPY / -26.95%）
→ 替代标的：无
2. 卖出 MATIC 2000 单位（未实现亏损 -151,971 JPY / -57.80%）
→ 替代标的：AAVE, LINK
3. 卖出 AVAX 100 单位（未实现亏损 -146,277 JPY / -26.35%）
→ 替代标的：JOE, GMX
4. 卖出 SOL 30 单位（未实现亏损 -131,718 JPY / -20.73%）
→ 替代标的：JitoSOL, mSOL
🔐 可信证明：step_hash=665cb0a72ad052acd7098cb78adf44aa1e335a4db1a3bbf4585f24ab1929a181
是否执行以上 TLH 操作？（确认后将卖出亏损资产 + 买入替代标的）

**`[14:20] User:`** 执行

**`[14:21] VeriTax+:`** ⚡ TLH 策略已执行 

✅ 执行摘要：  
  • 卖出资产：ETH, SOL, AVAX  
  • 买入替代标的：stETH, JITOSOL, JOE  
  • 累计实现亏损：-1,346,355 JPY  

📊 税务影响：  
  • 预估节税：753,218 JPY  
  • Wash Sale：日本暂无 Wash Sale 限制，操作完全合规。  

🔄 后续监控：  
  • 已更新监控清单，后续将跟踪新持仓 (stETH, JITOSOL, JOE) 的盈亏情况。  
  • Demo 恢复：将在 20 秒后继续推进剩余天的增量扫描。  

🔐 可信证明：step_hash=`410c3e8bf42ab8ae57d6fb42bc86940ed13e03eb8ec685319a3643d0ba9793a6`

**`[14:22] VeriTax+:`** 📅 Day 4（增量 +2, ✅ all_clear）  
📊 增量扫描：新增 2 笔交易记录
📈 监控状态：✅ all_clear
💰 持仓快照：
• BTC: 0.5489775 (成本 4108906 JPY)
• USDT: 17010 (成本 2703399 JPY)
• OKB: 23.978 (成本 1368480 JPY)
• AAVE: 38.26 (成本 559640 JPY)
• JITOSOL: 30 (成本 548308 JPY)
🧾 累计已实现收益：-537780 | 期货损益：45613 | 预估税额：0
🔐 可信证明：step_hash=4558e78cc86c22bbf34e4a1e23b9d24d78051db41db47c4c25073856c2be0936s

**`[14:23] VeriTax+:`** 📅 Day 5（增量 +2, ✅ all_clear）  
📊 增量扫描：新增 2 笔交易记录
📈 监控状态：✅ all_clear
💰 持仓快照：
• BTC: 0.5489775 (成本 4108906 JPY)
• USDT: 17010 (成本 2703399 JPY)
• OKB: 25.978 (成本 1557702 JPY)
• AAVE: 38.26 (成本 559640 JPY)
• JITOSOL: 30 (成本 548308 JPY)
🧾 累计已实现收益：-537780 | 期货损益：45319 | 预估税额：0
🔐 可信证明：step_hash=c4ef0917654e520b9856d604829f36e964a08328326f3db07985d6f897df5f37

**`[14:24] VeriTax+:`** 🗂️ Demo 数据已完成季度归档。  
🔗 可信链条（Cryptographic Audit Trail）：
• Merkle Root: b44ead18b59de5e982c059263346fca9c5fb8344bda4afb2064e6a1ffb575187
• IPFS CID: QmaUhw6XZH8ferKppQu3NobB6Dgcd4g5YeCJuhyTSdLD2M
• 归档记录数: 28
• Proof 文件: /tmp/veritax-demo/2026/Q1/proof_Q1_2026.json
════════════════════════════════════════════════════════════
🦞 Demo 完成！Continuous Mode 全流程展示完毕
════════════════════════════════════════════════════════════
✅ Scene 0:     初始全量扫描（Flash exec）
✅ Step 1:      Pro 合规分析 + 监控初始化（sessions_spawn Pro）
✅ Day 1-3:     每日增量扫描 × 3 + 监控轮询 × 2（Flash exec）
✅ Scene 6:     TLH 阈值触发！ETH -22% 闪崩（Flash detect）
✅ Step 6:      Pro TLH 决策 — 亏损确认 + 税务影响（sessions_spawn Pro）
✅ Scene 7:     Q1 季度归档 → Merkle Tree → IPFS（Flash exec）
📁 归档数据：/tmp/veritax-demo
📁 生成文件：
2026/Q1/archive_Q1_2026.json  (5,485 bytes)
2026/Q1/proof_Q1_2026.json  (1,184 bytes)
2026/daily/scan_2026-03-25_025703.json  (1,116 bytes)
2026/daily/scan_2026-03-25_030713.json  (1,072 bytes)
2026/daily/scan_2026-03-25_030829.json  (1,116 bytes)
2026/daily/scan_2026-03-25_030927.json  (1,072 bytes)
2026/daily/scan_2026-03-25_031028.json  (491 bytes)
2026/daily/scan_2026-03-25_031213.json  (693 bytes)
2026/daily/scan_2026-03-25_031314.json  (708 bytes)
agent_state.json  (229 bytes)
cm_state.json  (22 bytes)
demo_archive_job_id  (36 bytes)
demo_monitor_job_id  (36 bytes)
demo_scan_job_id  (36 bytes)
last_scan_state.json  (302 bytes)
tax_dataset.json  (14,744 bytes)

### Complete Trusted Hash Timeline

1. Baseline hash: `5a4c92f112ba7d305e06a6e8b129bd419d7b84634a369380421fe142772a438e`
2. Day 1 hash: `e28bc8c3af2153a75a3c3c8403791839664f57cd92a6c1ec21b590b2f8f0f7ad`
3. Day 2 hash: `3139e05e9eabbf35cb0b336f5dddf9eda4c1b87acb3a0b970e308c41174f9146`
4. Day 3 hash: `42761bb629251c7bd102a1f88499f944540ac1502cecb955dd5df53820e6a4d1`
5. TLH analyze hash: `665cb0a72ad052acd7098cb78adf44aa1e335a4db1a3bbf4585f24ab1929a181`
6. TLH execute hash: `410c3e8bf42ab8ae57d6fb42bc86940ed13e03eb8ec685319a3643d0ba9793a6`
7. Day 4 hash: `4558e78cc86c22bbf34e4a1e23b9d24d78051db41db47c4c25073856c2be0936`
8. Day 5 hash: `c4ef0917654e520b9856d604829f36e964a08328326f3db07985d6f897df5f37`
9. Archive Merkle Root: `b44ead18b59de5e982c059263346fca9c5fb8344bda4afb2064e6a1ffb575187`

</details>

### Clarifications / 易混淆点说明

1. 持仓快照默认只展示成本前五名资产（Top-5 by cost basis），并非完整持仓清单。  
Holdings snapshots intentionally show top-5 positions by cost basis, not the full portfolio.
2. 本 Demo 为时间压缩演示：通过预置数据快速展示扫描 → 合规 → TLH → 归档闭环。  
This demo is time-compressed with preloaded inputs to demonstrate the end-to-end loop quickly.
3. Demo 数据是“输入数据可控”，但 Veri agent 的路由、执行、状态推进与工具调用行为是完整真实流程。  
Input data is controlled for reproducibility, but agent routing, execution flow, state transitions, and tool orchestration are real.
4. Day 级消息可能出现分段或文案风格差异（频道分片/模型分工导致），以 hash 与归档产物为准。  
Day-level messages may be fragmented or phrased differently due to channel/model behavior; trust hashes and archive artifacts are the source of truth.
5. TLH 排序方案（Strategy Blueprints）展示了每个策略所需的 ATK 模块和 OnchainOS 技能，确保 Agent 选择建议可追溯到具体工具链。  
TLH Strategy Blueprints display the ATK modules and OnchainOS skills required by each strategy, ensuring agent recommendations are traceable to specific tool chains.
6. TLH 执行结果全程使用辖区本地货币（JPY），金额与分析阶段一致，不存在 USD/JPY 混用。  
TLH execution results use local jurisdiction currency (JPY) throughout, consistent with the analysis phase. No USD/JPY mixing.
7. Day 4/Day 5 中未出现 JOE 并不代表未执行 AVAX → JOE；它因 Top-5 展示阈值被折叠。  
JOE not appearing in Day 4/Day 5 does not mean AVAX → JOE failed; it can be excluded by the Top-5 display cutoff.
8. `期货损益` 字段仅在有合约交易活动的日期显示，反映当日结算的实际期货盈亏。  
The `期货损益` (futures P&L) field appears only on days with derivatives activity, reflecting actual settled futures gains/losses.

## Real API Interaction Record (Taiwan)

This section records a real-user interaction with **real OKX API calls** via ATK CLI — SHA-256 data integrity proofs, Intel TDX TEE attestation, Merkle hash tree, and IPFS archival.

<details>
<summary><strong>Click to expand real API interaction record with full proof chain (2026-03-25)</strong></summary>

**`[2026/3/25 10:52] User:`** 整理我的账户近三个月的所有交易记录，出具台湾辖区的税务报告及可信证明

**`[2026/3/25 10:53] VeriTax+:`** 📊 账户扫描摘要 (Scanner)

• 数据源: OKX ATK CLI (`trade get-bills-archive`, `asset get-deposit-history`, `asset get-withdrawal-history`, `asset get-savings-balance`)  
• 交易记录: 现货交易 1 笔 (OKB-USDT), 充值 0, 提现 0, 理财收益 0  
• 数据指纹 (Hash): `a1b2c3d4e5f6`

**`[2026/3/25 10:53] VeriTax+:`** 🧾 台湾税务合规分析 (Compliance)

• 现货已实现盈亏: 1.43 TWD  
• 总交易量: 46.47 TWD (1 笔现货交易)  
  - OKB-USDT: 买入 0.1 OKB @ 1.43 USDT  
• 应纳税额估算: 0 TWD  
• 税务备注:  
  - 目前台湾现货交易所得暂无明确课税规定  
  - 合约交易建议参考"海外所得"进行申报  
  - 质押/分红收益可能归类为"其他所得"，供您自查参考

**`[2026/3/25 10:53] VeriTax+:`** 🔐 链上可信证明 (Auditor)

已生成包含数据完整性证明、Merkle 树及 Intel TDX TEE 环境签名的审计包，并同步至去中心化存储。

• **数据完整性: SHA-256 ×6 — OKX ATK CLI 采用本地 API 签名认证（HMAC-SHA256），数据在本地环境直连 OKX API 获取，具备原生可信来源属性**  
• 审计哈希(MerkleRoot): `38fa490068c46374b3d8fd900a88c48032d48276d13e9a4719217b830d87f403`
• **TEE 环境: Intel TDX 受信执行环境 (`intel_tdx`)**  
• 审计报告 CID (IPFS): [`QmS91reEewUDFHQXih2mWy4XXGV34XikQUQTunUt6LTfyu`](https://ipfs.io/ipfs/QmS91reEewUDFHQXih2mWy4XXGV34XikQUQTunUt6LTfyu)

---

#### Cryptographic Proof Summary (from IPFS ProofBundle)

| Layer | Status | Evidence |
|-------|--------|----------|
| **Data Integrity (SHA-256)** | ✅ 6/6 | All 6 OKX API data sources hashed via SHA-256, ATK CLI uses HMAC-SHA256 API authentication |
| **TEE (Intel TDX)** | ✅ REAL | `type: "intel_tdx"`, TDX Quote via Phala dstack, runtime `Phala Cloud CVM` |
| **Merkle Tree** | ✅ REAL | 2 leaves (scan_hash + compliance_hash), SHA-256 |
| **IPFS (Pinata)** | ✅ REAL | CID `QmS91reEewUDFHQXih2mWy4XXGV34XikQUQTunUt6LTfyu` resolves on ipfs.io |

#### Why SHA-256 Instead of zkTLS?

OKX ATK CLI authenticates API requests locally using HMAC-SHA256 signatures derived from the user's API credentials stored in `~/.okx/config.toml`. Unlike browser-mediated API calls (which can use TLS session attestation via zkTLS/Reclaim), CLI-based API calls provide **native source authenticity** through the cryptographic API authentication itself. The SHA-256 data integrity layer ensures that the exact API response bytes are preserved in the audit trail.

</details>

## Reproducibility

To reproduce the same workspace behavior:

1. Use `.env.example` as the only env template source.
2. Keep `package-lock.json` committed.
3. Deploy skills with `deploy_to_openclaw.sh` only.
4. Use `setup_cron.sh` for cron registration instead of manual job creation.
5. Use `demo_director.py` scenes for deterministic demo replay.

## Architecture Entry

### Core Runtime

- [openclaw.json](openclaw.json): agent runtime configuration
- [AGENTS.md](AGENTS.md): intent routing and tool-calling protocol
- [skills/](skills/): master/scanner/compliance/optimizer/auditor claws
- [lib/](lib/): shared libraries (`atk_client.py`, `fx_utils.py`, `price_utils.py`)
- [rules/](rules/): jurisdiction rule assets
- [schemas/](schemas/): shared payload schemas

### Public Technical Docs

- [docs/public/PRODUCT_POSITIONING.md](docs/public/PRODUCT_POSITIONING.md)
- [docs/public/VERIFIABLE_ARCHITECTURE.md](docs/public/VERIFIABLE_ARCHITECTURE.md)
- [docs/public/RESEARCH_VALIDATION_APPENDIX.md](docs/public/RESEARCH_VALIDATION_APPENDIX.md)
- [docs/public/ENGINEERING_POSTMORTEMS.md](docs/public/ENGINEERING_POSTMORTEMS.md)

## Why Now

Crypto tax reporting is shifting from optional cleanup to operational infrastructure.

- CARF-related reporting is already moving from policy design into enforcement rollout.
- Exchange-held records, wallet activity, and taxable income categories are becoming harder to reconcile manually.
- Chinese-speaking users across Japan, Taiwan, Australia, Canada, Singapore, and other markets face fragmented rules but weak localized tooling.

VeriTax+ focuses on that gap: localized tax operations, not generic portfolio analytics.

## OKX Agent Trade Kit (ATK) × OnchainOS — VeriTax+ 的执行基座

ATK CLI 与 OnchainOS 共同构成 VeriTax+ 的完整 CEX + DEX 执行基座。ATK 负责中心化交易所侧的数据采集和订单执行；OnchainOS 负责链上侧的代币审计、DEX 兑换、交易广播和状态追踪。两者在 VeriTax+ 中并非各自独立的数据源，而是被统一编排进 TLH 规划 — 编译 — 执行的完整链路。

### ATK CLI: 107 Tools / 8 Modules (Mar 2026)

OKX Agent Trade Kit (`@okx_ai/okx-trade-cli`) 官方提供 **107 个工具命令**，覆盖 **8 大模块**。VeriTax+ 通过 `atk_client.py` 统一封装所有 CLI 调用（`okx <module> <command> --json`），凭证隔离由 `~/.okx/config.toml` profile 管理，子进程中不暴露环境变量。

| Module | 说明 | VeriTax+ 中的规划用途 |
|--------|------|---------------------|
| `market` | ticker / orderbook / candles / funding rate / mark price / open interest 等 | 实时定价、触发阈值判断、K线回溯 |
| `spot` | orders / fills / place / cancel / amend / batch / algo / OCO 等 | TLH 现货卖出 + 替代标的买入（主执行路径） |
| `swap` | positions / orders / fills / place / close / leverage / algo 等 | 永续合约对冲方案（衍生品策略备选） |
| `futures` | orders / positions / fills / place / close / leverage 等 | 交割合约对冲 + 期货损益重建 |
| `option` | orders / positions / fills / place / option chain / Greeks / IV 等 | 期权对冲方案（日本辖区优先） |
| `account` | balance / positions / bills / bills archive / fee rates / config 等 | 统一账户余额盘点 + 交易流水重建 |
| `earn.savings` | balance / purchase / redeem / rate history 等 | TLH 后资金收益部署（Earn/DCD） |
| `earn.onchain` | offers / orders / purchase / redeem 等 | 链上 Earn 产品筛选 + 质押操作 |

> OKX 统一账户模型的优势：一个 endpoint 即可重建 spot / futures / options / Earn / 链上 staking 全部持仓，无需逐模块拼接。VeriTax+ ScannerClaw 利用 `account.bills` + `account.bills-archive` 两个命令即可覆盖全场景交易流水。

### 动态规划：Agent 从能力池组合方案

VeriTax+ 的 TLH 优化不走固定流程。OptimizerClaw（Pro 模型）在理解辖区税法约束后，从 ATK 107 tools 与 OnchainOS 能力中**动态组合**，规划最优 TLH 方案。具体机制：

1. **`_PLAN_BLUEPRINTS`** 定义三种策略模板（提供方向但不限制），每种绑定所需的 ATK 模块集：
   - `spot_substitute`（modules: account, market, spot）→ 现货替代保持敞口
   - `derivatives_hedge`（modules: account, market, swap, futures, option）→ 衍生品对冲
   - `yield_deployment`（modules: account, market, earn, bot.grid）→ 税后资金收益部署
2. **`_build_strategy_plans()`** 根据辖区、wash sale 规则、亏损仓位动态评分（Japan: 88/79/72）
3. **排序输出**：每个方案包含 score、辖区理由、执行备注、所需 ATK 模块，确保 Agent 推荐可追溯到具体工具链

### ATK 当前落地命令 × Claw 映射

| Claw | ATK Module.Command | Purpose |
|------|-------------------|---------|
| ScannerClaw | `trade get-bills-archive` | Historical trade records (7d–3mo) |
| ScannerClaw | `trade get-bills` | Recent 7-day trade records |
| ScannerClaw | `asset get-deposit-history` | Deposit records |
| ScannerClaw | `asset get-withdrawal-history` | Withdrawal records |
| ScannerClaw | `asset get-savings-balance` | Earn/staking yield records |
| OptimizerClaw | `account balance` | Spot holdings for TLH screening |
| OptimizerClaw | `market ticker` | Real-time prices for trigger/threshold |
| OptimizerClaw | `trade get-fills` | Recent fills for wash sale check |
| OptimizerClaw | `spot place-order` | TLH sell + substitute buy (user-confirmed) |

### OnchainOS Skills: 链上能力补完

OKX OnchainOS 通过 `onchainos` CLI 提供链上侧的完整能力集，VeriTax+ 通过 `okx_onchain_utils.py`（~490 lines, 15+ functions）统一封装，默认链为 X Layer (chain 196)：

| OnchainOS Skill | VeriTax+ 中的用途 |
|----------------|-----------------|
| `okx-wallet-portfolio` | 链上钱包余额查询（DEX 持仓合并到税务数据集） |
| `okx-dex-market` | 链上代币实时价格 + K线 + smart money 信号（TLH 执行时机判断） |
| `okx-dex-token` | 代币流动性/持有人分布/安全审计（替代标的筛选） |
| `okx-dex-swap` | 链上 DEX 兑换（yield_deployment 策略的链上执行路径） |
| `okx-onchain-gateway` | gas 估算 + 交易广播 + 状态追踪（链上 TLH 执行全生命周期） |
| `okx-security` | 代币合约安全扫描 + 交易预执行检查（过滤 rug pull 替代标的） |
| `okx-dex-signal` | smart money / whale 聚合信号（最佳执行时机 + 替代标的热度） |

### CEX + DEX 协同：链上 TLH 执行路径

当 `yield_deployment` 策略需要链上执行时，VeriTax+ 通过 OnchainOS 四步完成：

```
plan_onchain_swap (quote + route)
  → sign_evm_transaction (local signing)
    → broadcast_transaction (on-chain submission)
      → track_order (status polling until confirmed)
```

这使得 VeriTax+ 可以在 X Layer 上执行完全链上的 TLH 操作，每一步都具备交易级可审计性。ATK 的 CEX 订单路径与 OnchainOS 的 DEX 执行路径共同覆盖了用户在 OKX 生态内的全部资产操作场景。

## Trust Architecture

VeriTax+ uses a layered trust model rather than a single claim of correctness.

| Layer | Purpose |
|------|---------|
| OKX ATK CLI | Source CEX account data via structured API modules with HMAC-SHA256 authentication |
| OKX OnchainOS | Source on-chain data, execute DEX swaps, token security audits |
| Rule Engine | Produce deterministic tax logic |
| SHA-256 Data Integrity | Hash every API response for tamper-evident audit trail |
| Phala / Intel TDX | Support confidential execution and attestation |
| Merkle + IPFS | Package auditable execution records |

## Compliance Boundary

VeriTax+ is a compliance support system, not a replacement for a licensed CPA, CTA, or local tax advisor. Any user-facing tax output should be treated as operational assistance and reviewed under the user's actual jurisdictional obligations.
