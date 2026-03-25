<p align="center">
  <img src="../../VeriTax.jpg" alt="VeriTax+" width="180"/>
</p>

# VeriTax+ Engineering Postmortems

This document records the engineering failures and debugging results that materially changed VeriTax+'s architecture, runtime configuration, or prompt strategy.

## 1. Continuous Mode Control Could Not Stay in Prompt Text Alone

### Resolution Status

Resolved.

### Problem

In Continuous Mode, the main agent merged multiple day-level outputs into a single turn, skipped required pacing, and sometimes failed to advance the workflow correctly.

### Why It Mattered

This was not just a formatting issue. It broke the product contract for day-by-day reporting.

### Useful Lesson

Deterministic control flow should move from prompt instruction into code whenever possible.

### Repository evidence trail

- This appendix preserves the design rule that came out of the CM-2 and formatting failures: move control flow into code, keep tool actions atomic, and use prompt constraints only as a secondary guardrail.

### Reusable conclusion

For any agent workflow where order matters, prompt wording is not enough. Atomic tool design and stateful progression win over increasingly elaborate natural-language constraints.

### Current State

Continuous Mode orchestration now uses code-level state progression and atomic step boundaries as the primary control mechanism.

## 2. WSL2 Telegram Timeouts Produced a Real Runtime Configuration Change

### Resolution Status

Resolved.

### Problem

Telegram-related networking in WSL2 showed intermittent timeouts and slow recovery behavior even when direct command-line checks looked healthy.

### Investigated root cause

The notes record a plausible interaction between WSL2 networking, IPv6 reachability issues, and Node's family-selection behavior.

### Resulting engineering action

- network family handling was forced into a safer mode
- gateway startup behavior was hardened
- runtime persistence concerns were documented instead of treated as random flakiness

### Why This Is Worth Keeping Public

This class of issue is transferable. It helps anyone running OpenClaw- or Telegram-style bots in WSL2 understand that successful curl checks do not guarantee healthy Node runtime behavior.

### Repository evidence trail

- Publicly preserved reference set for this class of issue includes:
  - nodejs/node#48145
  - nodejs/node#54359
  - telegraf/telegraf#1981
  - openclaw/openclaw#21909
  - openclaw/openclaw#21916

### Current State

Gateway networking now runs with hardened startup and family-selection safeguards that removed the observed intermittent timeout behavior in the verified runtime path.

## 3. Flash Demo Menu Fabrication Was a Product-Correctness Bug, Not Just a Prompt Quirk

### Resolution Status

Resolved.

### Problem

The Flash model fabricated a four-option demo menu when the product required a strict two-option menu.

### Why It Mattered

This was a direct product-behavior failure. The system looked like it supported flows that did not exist.

### Core finding

The issue was tied to the difference between:

- instructions visible in the active prompt context
- instructions stored in skill bodies and loaded on demand
- tasks that a model believed it could answer without calling tools

### Engineering takeaway

If a task can be "answered from vibes," the model may bypass the very mechanism that contains the real constraints. When correctness matters, force the workflow through a tool or equivalent hard boundary.

### Repository evidence trail

- This public postmortem keeps the architectural conclusion: if a correctness-critical step can be answered without a tool, the model may bypass the only place where the real constraints live.

### Current State

Demo menu generation now uses explicit constrained prompt design plus a deterministic tool fallback, and the two-option output contract is enforced in the current flow.

## 4. Debugging Outcomes Preserved in This Repository

The debugging record kept here focuses on failures that changed the system in one of three ways:

1. user-visible behavior was corrected
2. deployment configuration was hardened
3. prompt logic was replaced or reinforced by code-level controls

All incidents documented in this file are closed with implemented fixes and are retained as engineering evidence, not as unresolved backlog items.