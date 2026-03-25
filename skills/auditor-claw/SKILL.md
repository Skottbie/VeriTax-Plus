---
name: auditor-claw
description: "Generate cryptographic audit trail (zkTLS + TEE + IPFS). Triggers: '验证', 'verify', 'proof', '审计', 'IPFS', 'zkTLS', 'TEE', 'Merkle', '可信证明'. IMPORTANT: You MUST use the exec tool to run: python3 {baseDir}/auditor.py --scan-hash <HASH> --compliance-hash <HASH> [--scan-dataset <DATASET>] — generates ProofBundle with Merkle tree + TDX attestation + IPFS upload. Do NOT fabricate CIDs. For full instructions read SKILL.md with read tool."
license: MIT
metadata:
  author: veritax
  version: "2.0.0"
  homepage: "https://github.com/veritax/veritax-okx"
  openclaw:
    requires:
      bins: ["python", "node"]
      env: ["RECLAIM_APP_ID", "PINATA_JWT", "PHALA_API_TOKEN"]
---

# SKILL: AuditorClaw — Verifiable Audit Trail (OKX Edition)

> **角色**：VeriTax 可验证层，为税务计算流程生成密码学审计链。
> **模型**：Claude Haiku 4.5 (0.33x) via sessions_spawn — 执行，无需推理。

---

## 可验证三件套

| 层 | 技术 | 作用 |
|----|------|------|
| 数据来源证明 | Reclaim zkFetch (zkTLS) | 证明 OKX API 数据确实来自 OKX 服务器 |
| 计算完整性证明 | Phala dStack TDX Quote (TEE) | 证明税计算在可信执行环境中运行 |
| 审计链完整性 | merkletreejs + Pinata IPFS | Merkle Hash Chain + 不可变存储 |

---

## 执行流程

### Step 1: 收集各步骤哈希
- `scan_hash` = SHA256(tax_dataset.json)
- `compliance_hash` = SHA256(compliance_report.json)
- `optimizer_hash` = SHA256(tlh_plan.json)（如有）

### Step 2: 构建 Merkle Tree
### Step 3: 生成 TEE 证明（Phala dStack TDX Quote）
### Step 4: 上传到 IPFS（Pinata）

---

## Command Index

```bash
# 生成完整审计链
python3 {baseDir}/auditor.py --scan-hash <hash> --compliance-hash <hash> --scan-dataset /tmp/tax_dataset_<YEAR>.json

# 含 TLH 步骤
python3 {baseDir}/auditor.py --scan-hash <hash> --compliance-hash <hash> --optimizer-hash <hash> --scan-dataset /tmp/tax_dataset_<YEAR>.json

# JSON 输出
python3 {baseDir}/auditor.py --scan-hash <hash> --compliance-hash <hash> --scan-dataset /tmp/tax_dataset_<YEAR>.json --json
```

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--scan-hash` | 是 | — | ScannerClaw 输出的 SHA256 |
| `--compliance-hash` | 是 | — | ComplianceClaw 输出的 SHA256 |
| `--optimizer-hash` | 否 | — | OptimizerClaw 输出的 SHA256 |
| `--scan-dataset` | 否 | — | ScannerClaw 数据集路径 |
| `--json` | 否 | — | 输出 JSON ProofBundle |
