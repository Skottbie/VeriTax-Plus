<p align="center">
  <img src="../../VeriTax.jpg" alt="VeriTax+" width="180"/>
</p>

# VeriTax+ Research Validation Appendix

This document records the main research trail behind VeriTax+, including the points where early assumptions were corrected after deeper checking.

## Public Source Ledger Already Normalized

The repository already preserves several exact documentation URLs used during architecture and model-behavior research:

- GitHub Copilot model comparison:
  https://docs.github.com/en/copilot/reference/ai-models/model-comparison
- GitHub Copilot premium requests:
  https://docs.github.com/en/copilot/managing-copilot/monitoring-usage-and-entitlements/about-premium-requests
- OpenClaw multi-agent routing:
  https://docs.openclaw.ai/concepts/multi-agent
- OpenClaw session tools:
  https://docs.openclaw.ai/concepts/session-tool
- OpenClaw sessions_spawn:
  https://docs.openclaw.ai/concepts/session-tool#sessions_spawn

Additional key URLs used in engineering and runtime reliability research:

- Node.js Happy Eyeballs timeout behavior in mixed IPv4/IPv6 environments:
  https://github.com/nodejs/node/issues/48145
- Node.js autoSelectFamily related timeout behavior:
  https://github.com/nodejs/node/issues/54359
- Telegram bot timeout symptoms in Node runtime:
  https://github.com/telegraf/telegraf/issues/1981
- OpenClaw WSL2 networking issue tracking:
  https://github.com/openclaw/openclaw/issues/21909
- OpenClaw WSL2 fix merge reference:
  https://github.com/openclaw/openclaw/pull/21916

Additional prompt and tooling references cited in model-behavior research:

- OpenClaw skills concept:
  https://docs.openclaw.ai/tools/skills
- OpenClaw system prompt concept:
  https://docs.openclaw.ai/concepts/system-prompt
- OpenClaw agent loop concept:
  https://docs.openclaw.ai/concepts/agent-loop


These URLs matter because they support concrete implementation decisions, not just product storytelling.

## A. Regulatory and Market Validation

### A1. CARF / DAC8 Timing Pressure

**Why it matters**

VeriTax+'s timing argument depends on crypto reporting moving from abstract policy discussion into operational reality.

**Working conclusion**

- The "future problem" framing is too weak.
- The product should be positioned as preparation for reporting infrastructure that is already rolling forward.

**Repository evidence trail**

- [design.md](../../design.md) frames the project around CARF-era reporting pressure.
- VeriTax+ treats reporting pressure as an active rollout trend, not a distant future event.

**Source trail**

| Topic | Repository evidence | Source status |
|------|---------------------|---------------|
| DAC8 / EU effective timing | This appendix preserves the corrected implementation-era framing | Source title and timeline statement are documented in repository research notes |
| CARF operational impact | VeriTax+ treats reporting as operational rollout, not only future policy risk | Derived from internal synthesis of CARF timeline notes |

### A2. Singapore Narrative Correction

**Initial hypothesis**

The early draft leaned heavily on retail users in Singapore being at high immediate risk of being classified as "traders" for tax purposes.

**Changed after review**

That framing was too aggressive. The reviewed conclusion preserved here is that retail enforcement appears much rarer in practice than the original story implied.

**What survived the review**

- Singapore still matters because taxable income categories remain relevant.
- CARF or CRS adjacency still supports a forward-looking compliance angle.
- The user value is record readiness and category handling, not panic messaging.

**Source trail**

| Topic | Repository evidence | Source status |
|------|---------------------|---------------|
| Retail treatment is often non-taxable | Public summary preserves the reassessment that retail trader-classification fear should not be the main hook | Source quote and conclusion are documented in repository research notes |
| Value should pivot to taxable income categories | VeriTax+ centers this market on income categories and forward compliance readiness | Fully preserved in current docs |

### A3. Japan Tax Reform and Priority Re-ranking

**Why it matters**

Japan was one of the strongest early storylines, but later research changed the shape of that story.

**Changed after review**

- The original "55% high-tax pain" framing was no longer sufficient.
- Later notes record a reform scenario centered on 20% separate taxation, loss carryforward, and classification complexity.

**What survived the review**

- Japan remains operationally important.
- The value shifts from raw fear or headline tax rate toward classification, event-level calculation, and exchange-report readiness.

**Repository evidence trail**

- VeriTax+ preserves the updated conclusion: Japan remains strategically relevant, but the value thesis depends more on classification and reporting complexity than on a single headline tax rate.

**Source trail**

| Topic | Repository evidence | Source status |
|------|---------------------|---------------|
| 2025-12-26 reform claim | Public appendix records the cited source title 日本财务省「令和8年度税制改正の大綱」 | Source title and cited date are documented in repository research notes |
| New priority and TLH implications | The current product docs preserve the post-reform reprioritization | Fully preserved in current docs |

### A4. Taiwan Opportunity Thesis

**Why it matters**

Taiwan became stronger over time not because final tax treatment is already settled, but because record-preparation demand can emerge before full tax-law clarity.

**Working conclusion**

- The product should not overclaim current taxation certainty.
- The product can credibly claim value in self-check workflows, record preparation, and forward compliance readiness.

**Source trail**

| Topic | Repository evidence | Source status |
|------|---------------------|---------------|
| VASP / regulatory acceleration | Public appendix preserves the logic of regulatory acceleration and record-preparation demand before full tax-law certainty | Source titles and regulatory sequence are documented in repository research notes |
| Taiwan reprioritization | The current product docs reflect the later move toward higher strategic priority | Fully preserved in current docs |

## B. Technical Validation Trail

### B1. Why SHA-256 + HMAC-SHA256 Was Chosen Over zkTLS

**Design need**

The project needed a stronger story than "user uploaded a CSV and we trusted it."

**Evaluated alternative: zkTLS / Reclaim**

The initial design considered zkTLS (Reclaim Protocol) for data provenance — proving that fetched records came from the intended source channel via TLS session attestation. However, after adopting OKX ATK CLI as the primary data interface, this approach was reconsidered.

**Why VeriTax+ chose SHA-256 instead**

OKX ATK CLI authenticates every API request locally using **HMAC-SHA256 signatures** derived from the user's API credentials stored in `~/.okx/config.toml`. This provides **native source authenticity** through the cryptographic API authentication itself — the data provenance is inherent in the API authentication layer, not bolted on after the fact.

- **HMAC-SHA256 API authentication**: Every ATK CLI request is signed with the user's secret key, proving the data was fetched from OKX's authenticated API endpoint.
- **SHA-256 data integrity hashing**: VeriTax+ hashes every API response (6 data sources) via SHA-256, creating a tamper-evident audit trail from source to archive.
- **No browser dependency**: Unlike zkTLS which requires browser-mediated TLS sessions, ATK CLI operates as a direct API client — simpler, more reliable, and equally provenant.

**Working conclusion**

For CLI-based API integrations with built-in cryptographic authentication (like OKX ATK), SHA-256 data integrity hashing is a more natural and reliable provenance layer than zkTLS. The latter remains valuable for browser-mediated data sources where no API authentication exists.

**Repository evidence trail**

- The architecture documents preserve the SHA-256 provenance role and the rationale for not using zkTLS.
- `lib/atk_client.py` implements credential-isolated CLI calls; `skills/auditor-claw/auditor.py` implements SHA-256 hashing of all API responses.

**Source trail**

| Topic | Repository evidence | Source status |
|------|---------------------|---------------|
| SHA-256 + HMAC-SHA256 provenance rationale | Architecture docs and README explain the native API authentication advantage | Fully preserved in current docs |
| zkTLS evaluation and decision not to use | This appendix documents the design tradeoff | Decision rationale documented here |

### B2. Why TEE / Phala Was Chosen

**Design need**

The project needed a clearer answer to "why should anyone trust the execution environment for sensitive tax computation?"

**Working conclusion**

TEE-backed execution and attestation do not solve every legal trust problem, but they materially improve the technical evidence story compared with plain server-side processing.

**Repository evidence trail**

- The architecture docs preserve the attestation role, execution-boundary caveat, and deployment rationale.

**Source trail**

| Topic | Repository evidence | Source status |
|------|---------------------|---------------|
| Phala / dStack fit for attested execution | The architecture docs preserve the role of attested confidential execution | Source title and implementation notes are documented in repository research notes |

### B3. Why Deterministic Rules Were Treated as Mandatory

**Design need**

Tax calculation is a low-tolerance domain. A persuasive model answer is not enough.

**Working conclusion**

- LLMs should explain and route.
- A deterministic rules engine should own final arithmetic and tax logic.

**Repository evidence trail**

- [design.md](../../design.md) and [VERIFIABLE_ARCHITECTURE.md](VERIFIABLE_ARCHITECTURE.md) both preserve this decision.

## C. Research Process

The research process behind VeriTax+ followed this sequence:

1. initial product framing
2. challenge to assumptions
3. jurisdiction-specific rechecks
4. revised positioning
5. implementation-oriented technical validation
6. later engineering postmortems

That sequence matters because several of the product's strongest decisions only emerged after the original assumptions were challenged and revised.

## D. Source Ledger Already Present in Repository Notes

The repository already contains explicit source URLs for several engineering and model-behavior research items, including:

- GitHub Copilot model comparison and premium request documentation
- OpenClaw multi-agent and session tool documentation
- OpenAI function-calling and structured-output references quoted in notes
- Anthropic prompting and agent-system references quoted in notes

Those normalized public references remain visible in this appendix and in the focused memo [RESEARCH_FLASH_4OPTIONS_BUG.md](../../RESEARCH_FLASH_4OPTIONS_BUG.md).

