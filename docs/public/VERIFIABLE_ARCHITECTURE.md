<p align="center">
  <img src="../../VeriTax.jpg" alt="VeriTax+" width="180"/>
</p>

# VeriTax+ Verifiable Architecture

## Purpose

This document summarizes VeriTax+'s architecture and trust model for technical review and implementation alignment.

## System Goal

VeriTax+ is designed to turn exchange activity into a compliance workflow with stronger evidence properties than a conventional CSV-based tax tool.

The architecture is organized around five roles:

1. MasterClaw: routes user intent and orchestrates the workflow.
2. ScannerClaw: reconstructs account and transaction data.
3. ComplianceClaw: applies jurisdiction-aware deterministic rules.
4. OptimizerClaw: evaluates legally available optimization opportunities.
5. AuditorClaw: packages provenance, execution, and audit evidence.

## Architecture Summary

```text
User Request
   -> MasterClaw
      -> ScannerClaw
      -> ComplianceClaw
      -> OptimizerClaw
      -> AuditorClaw
```

The implementation is centered on OpenClaw skills and routing rules, with OKX Agent Trade Kit (ATK CLI) used as the primary structured CEX data interface and OKX OnchainOS used for on-chain capabilities.

## Data and Trust Layers

### 1. Source Data Layer

OKX ATK CLI modules are used to retrieve account snapshots, transfers, earn/staking yields, trading history, and other relevant activity needed to rebuild the user's ledger. OKX OnchainOS extends this to on-chain wallet portfolio queries and token metadata.

### 2. Deterministic Computation Layer

Tax calculations should be performed by a rule engine, not by free-form LLM generation. The model's job is explanation, routing, and human-readable summarization.

### 3. Provenance Layer

OKX ATK CLI authenticates every API request using HMAC-SHA256 signatures from the user's local credentials (`~/.okx/config.toml`). All API responses are SHA-256 hashed to produce a tamper-evident data integrity chain. This provides native source authenticity through the cryptographic API authentication itself.

### 4. Confidential Execution Layer

Phala-hosted confidential execution with Intel TDX attestation is used to support stronger claims about how sensitive computation was executed.

### 5. Audit Packaging Layer

Merkle-style hashing and IPFS-compatible packaging are used to persist auditable artifacts for later review or handoff.

## What the Verification Layer Does and Does Not Mean

The verification stack should be described carefully.

It is reasonable to claim that VeriTax+ is designed to provide:

- better evidence of data provenance than manual CSV workflows
- stronger evidence of execution context than plain server-side processing
- better audit traceability than opaque one-shot report generation

It is not reasonable to imply without qualification that:

- every authority will accept the output as legal proof by default
- the system eliminates all trust assumptions
- the computation is universally incontestable in every deployment mode

## Public Component Mapping

| Component | Public Role |
|------|-------------|
| [openclaw.json](../../openclaw.json) | Agent runtime configuration |
| [AGENTS.md](../../AGENTS.md) | Routing logic and execution policy |
| [skills/master-claw/SKILL.md](../../skills/master-claw/SKILL.md) | Top-level orchestration |
| [skills/scanner-claw/SKILL.md](../../skills/scanner-claw/SKILL.md) | Ledger reconstruction |
| [skills/compliance-claw/SKILL.md](../../skills/compliance-claw/SKILL.md) | Compliance analysis |
| [skills/optimizer-claw/SKILL.md](../../skills/optimizer-claw/SKILL.md) | Optimization planning |
| [skills/auditor-claw/SKILL.md](../../skills/auditor-claw/SKILL.md) | Evidence packaging |
| [lib/atk_client.py](../../lib/atk_client.py) | OKX ATK CLI unified wrapper |
| [skills/optimizer-claw/okx_onchain_utils.py](../../skills/optimizer-claw/okx_onchain_utils.py) | OKX OnchainOS integration layer |

## Design Principles

The public architecture should be read with these principles in mind:

1. Reuse platform-native integrations where possible.
2. Keep tax calculation deterministic and inspectable.
3. Treat provenance and attestation as layered evidence, not magic claims.
4. Prefer maintainable interfaces over demo-only complexity.
