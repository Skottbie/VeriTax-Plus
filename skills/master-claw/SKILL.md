---
name: master-claw
description: "MANDATORY: You MUST read this SKILL.md file with the read tool BEFORE responding to the user. Never answer without reading the full instructions first. This skill should be used when the user asks for complete tax analysis, mentions '帮我报税', '税务全流程', 'full tax report', '完整税务分析', or expects the end-to-end pipeline. Also use when the user says '开始Demo', '演示', '运行demo', 'demo模式' — IMPORTANT: For demo, you MUST first read SKILL.md, then exec menu.py to get the exact menu text, then send that text verbatim to user. Demo has exactly 2 options: (A) 一次性税务审查 and (B) Continuous Mode. Do NOT invent additional options. Do NOT use when the user only wants data extraction (use scanner-claw), only tax calculation (use compliance-claw), only TLH (use optimizer-claw), or only audit (use auditor-claw)."
license: MIT
metadata:
  author: veritax
  version: "2.0.0"
  homepage: "https://github.com/veritax/veritax-okx"
  openclaw:
    requires:
      bins: ["python"]
      env: ["OKX_API_KEY"]
---

# SKILL: MasterClaw — VeriTax 总控路由

> **角色**：VeriTax 顶层编排技能，串联 4 个子 Claw（Scanner → Compliance → Optimizer → Auditor）完成端到端税务合规流程。
> **这是 VeriTax 的入口点**：用户只需说出税务年度和辖区，本技能自动调度全流程。
> **模型路由**：MasterClaw 本身运行在 Gemini 3 Flash (0.33x)，通过 `sessions_spawn` 按需调用推理模型执行子 Claw。

---

## 模型路由映射

| 子 Claw | 模型 | 倍率 | 调用方式 |
|---------|------|------|---------|
| ScannerClaw | Flash | 0.33x | MasterClaw 直接 exec（无需 spawn） |
| ComplianceClaw | Pro | 1x | `sessions_spawn({ agentId: "pro" })` |
| OptimizerClaw | Pro | 1x | `sessions_spawn({ agentId: "pro" })` |
| AuditorClaw | Pro | 1x | `sessions_spawn({ agentId: "pro" })` |

> ⛔ **DO NOT** 在 sessions_spawn 中指定 `model` 参数。Pro agent 已在 openclaw.json 中配置好模型。
> 只使用 `agentId: "pro"`，不要附加日期后缀或版本号。

---

## ⛔ sessions_spawn 协议（MANDATORY）

1. **MANDATORY STOP 规则**：`sessions_spawn` 返回 `"accepted"` 后，输出状态消息后 **立即结束本轮**，等待 completion event。
2. **超时降级**：子 Claw 超过 120 秒未返回 → 降级为 MasterClaw 自主执行并注明 "⚠️ 超时"。
3. **结果解析**：收到 completion event 后，通过 `sessions_history` 获取子 Claw 完整输出。
4. **增量输出**：每轮只输出新完成步骤，禁止重复已输出内容。
5. **Hash 传递**：每个子 Claw 输出后，记录其 step_hash 供 AuditorClaw 构建 Merkle Tree。
6. **Hash 收集**：在 CM 流程中，维护一个 `all_hashes` 列表，逐步收集每个步骤的 step_hash（CM-1 基线、每天 cm-daily、CM-3 optimizer、CM-4 execute），在 CM-5 时全部传入 auditor。

⛔⛔⛔ **反重复协议（ANTI-REPEAT PROTOCOL — MANDATORY）** ⛔⛔⛔

当你从 stop 状态恢复（收到 completion event 或轮次继续）时：
1. **禁止回顾**：不要重新输出之前已发送过的任何文本（包括 CM-1 基线、之前的 Day 报告）
2. **禁止合并历史**：不要在新内容前面附加之前的 Day 报告
3. **只发增量**：每次恢复后，只输出本次新获得的内容（1 天的 USER_MESSAGE 或 1 个 completion 结果）
4. **已发标记**：内心将之前输出过的内容标记为 `[已发送]`，绝不再次输出
5. **零上下文回顾**：恢复轮次时，不要以「之前我们完成了 XX、YY、ZZ」作为开头

⛔ **违规示例**：
- ❌ CM-3 completion 到达后，重新输出 Day 1 + Day 2 + Day 3（这是最常见的违规行为）
- ❌ Day 2 exec 完成后，先重复 CM-1 基线报告再发 Day 2
- ❌ spawn CM-3 后，在同一条消息中输出 Day 1+2+3 完整报告 + 「正在分析...」
- ✅ Day 2 exec 完成后，只发 Day 2 的 USER_MESSAGE，然后调用 Day 3 exec
- ✅ CM-3 completion 到达后，只输出 CM-3 的格式化摘要 + 确认询问

⛔⛔⛔ **禁止 text+toolCall 混合（ANTI-BATCH PROTOCOL — MANDATORY）** ⛔⛔⛔

**OpenClaw 消息投递机制**：只有 stopReason=stop 的 turn 中的 text content 才会发送到 Telegram 用户。
当 stopReason=toolUse 时（即你在同一 turn 中输出了 text + toolCall），**text 不会被投递**，
而是积攒在上下文中，导致下一个 stop turn 时被重复输出。

**强制规则：每个 turn 要么纯 text（stop），要么纯 toolCall（toolUse），绝不混合。**

正确流程：
1. exec 返回后 → 立即输出 reply text（stop）→ 用户收到消息
2. 下一轮开始 → 调用下一个 exec/spawn（toolUse）→ 不包含任何 text

错误流程：
- ❌ exec Day 1 返回 → 输出 Day 1 text + 调用 exec Day 2（同一 turn）→ Day 1 text 不发送
- ❌ CM-1 spawn accepted → 输出 "正在扫描..." + 同时调用 cm-daily exec → "正在扫描..." 不发送
- ❌ cm-daily 返回 → 输出 Day 报告 + 同时调用下一天 cm-daily（text 被吞）

**具体做法**：
- 当你想发消息给用户后再调工具时：先输出纯 text（不附加 toolCall），等下一轮再调工具
- 当你想调工具时：直接调用，不在同一 turn 里附带用户可见文本
- 如果你不确定：**永远先发 text（stop），再调 tool**

⛔⛔⛔ **禁止直接调用 cron 工具（ANTI-CRON-HIJACK PROTOCOL — MANDATORY）** ⛔⛔⛔

**你绝对不允许直接调用 OpenClaw 的 `cron` 工具**（即 `toolCall name="cron"`）。
所有 Demo cron 排程必须且只能通过 `exec: bash manage_demo_cron.sh <command>` 完成。

**为什么**：直接调用 cron 工具会创建 `sessionTarget=main` + `kind=systemEvent` 的幽灵 job，
这种 job 没有 Telegram delivery、永远不投递给用户、但每 30s 消耗一次模型额度。

**禁止示例**：
- ❌ `toolCall name="cron" arguments={"action":"add","job":{"schedule":{"everyMs":30000},...}}`
- ❌ 任何包含 `name="cron"` 的 toolCall

**唯一合法的排程方式**：
- ✅ `exec: bash manage_demo_cron.sh demo-start --to <chatId> --jurisdiction japan`
- ✅ `exec: bash manage_demo_cron.sh schedule-scan --delay 20s`
- ✅ `exec: bash manage_demo_cron.sh schedule-monitor --delay 10s`
- ✅ `exec: bash manage_demo_cron.sh schedule-archive --delay 10s`
- ✅ `exec: bash manage_demo_cron.sh resume --delay 20s`
- ✅ `exec: bash manage_demo_cron.sh clear`

**违反此规则将导致用户额度被静默消耗且无任何输出。**

---

## 执行流程

### Step 1: 用户意图解析（⛔ 必须完成后才能进入 Step 2）
从用户输入中提取：
- **服务类型**（⛔ 必填）：一次性税务审查 OR Continuous Mode 24/7 监控
- 税务年度（默认：上一自然年）
- 辖区（关键词检测：日本/台湾/澳洲/加拿大/新加坡/英国）
- 扫描范围（全部/仅现货）
- 是否需要 TLH 分析（辖区支持时默认是）

**⛔ 服务类型判定规则：**
- 若用户明确说了 "报税" / "税务分析" / "计算税额" / "合规报告" → 一次性税务审查
- 若用户明确说了 "持续监控" / "Continuous Mode" / "TLH 监控" / "24/7" → Continuous Mode
- 若用户说了 "demo" / "演示" 或其他**未指定具体服务**的表述 → 执行以下操作：

**⛔⛔⛔ Demo 服务选择——三层约束协议（MANDATORY）⛔⛔⛔**

<layer1_tool_first>
**第一层（工具优先）**：先执行 `exec: python3 skills/master-claw/menu.py`，获取菜单文本。
然后将工具输出的文本**原封不动**发送给用户，不添加、不删除、不改写任何内容。
如果 menu.py 执行失败，才使用第二层的 required_output 文本。
</layer1_tool_first>

<layer2_required_output>
**第二层（精确文本）**：仅当 menu.py 不可用时，逐字输出以下文本（含 emoji、换行、编号）：

```
🦞 Demo 数据已就绪。请选择服务类型：

(A) 一次性税务审查（扫描→合规计算→TLH分析→审计证明）
(B) Continuous Mode 持续监控 Demo（模拟多天：每日增量扫描 + 每小时TLH监控 + 闪崩触发）

请回复 A 或 B：
```

要求：上面 ``` 内的文本是你唯一允许输出的内容。逐字复制，不改写、不拆分、不增加选项。
</layer2_required_output>

<layer3_forbidden_output>
**第三层（禁止示例）**：以下是**错误输出**，你绝对不能生成类似内容：

❌ 错误示例（之前的 Flash 错误输出，选项数 ≠ 2）：
"请问你想体验哪种场景？
1. 全流程演示 (Master Pipeline)
2. 日本税务合规 (Japan Compliance)
3. TLH 策略优化 (Optimizer)
4. 持续监控演示 (Continuous Monitoring)"

❌ 为什么错误：选项数量为 4 而非 2，选项名称被改写，不是 (A)/(B) 格式。
✅ 正确行为：只输出 layer2_required_output 中的精确文本。选项永远是 2 个：(A) 和 (B)。
</layer3_forbidden_output>

<enum_constraint>
**枚举约束**：服务类型是一个**封闭枚举**，只有 2 个合法值：
- 值 A = "一次性税务审查"
- 值 B = "Continuous Mode 持续监控"
不存在第 3、第 4 个选项。不允许创建新选项、拆分现有选项、或重命名选项。
</enum_constraint>

**⛔ 绝对禁止**：在未确认服务类型的情况下直接执行 Step 2-5 全流程。

### Step 2: 调用 ScannerClaw（数据采集）
**ACTION**: `exec: python3 skills/scanner-claw/scanner.py --demo=<path> --output=<path>` (Flash 直接执行，无需 spawn)
**WHEN RETURNS "accepted"**: 输出 `🔍 Step 1/4: 正在扫描币安账户数据...` → **MANDATORY STOP**
**ON COMPLETION**: 解析 tax_dataset.json + 记录 scan_hash

### Step 3: 调用 ComplianceClaw（税额计算）
**ACTION**: `sessions_spawn({ agentId: "pro", task: "[VeriTax Step 2] 运行税规引擎：对 <dataset_path> 按{jurisdiction}税法计算{year}年度税额" })`
**WHEN RETURNS "accepted"**: 输出 `🧮 Step 2/4: 正在运行税规引擎...` → **MANDATORY STOP**
**ON COMPLETION**: 解析 compliance_report.json + 记录 compliance_hash

### Step 4: 调用 OptimizerClaw（TLH 优化，条件执行）
**IF 辖区支持 TLH（日本/澳洲/加拿大/英国）**:
**ACTION**: `sessions_spawn({ agentId: "pro", task: "[VeriTax Step 3] 税务优化分析：对 <dataset_path> 按{jurisdiction}辖区识别TLH机会" })`
**WHEN RETURNS "accepted"**: 输出 `📉 Step 3/4: 正在分析税务优化机会...` → **MANDATORY STOP**
**ON COMPLETION**: 解析 tlh_plan.json + 记录 optimizer_hash
**ELSE**: 跳过，optimizer_hash = null

### Step 5: 调用 AuditorClaw（审计链生成）
**ACTION**: `sessions_spawn({ agentId: "pro", task: "[VeriTax Step 4] 生成可验证审计链：scan_hash={scan_hash}, compliance_hash={compliance_hash}, optimizer_hash={optimizer_hash}, scan_dataset={dataset_path}。若 scanner 数据集中存在 source_zktls_proofs，必须通过 --scan-dataset 将其纳入最终 ProofBundle，并在输出中明确 real zkTLS proof 数量。" })`
**WHEN RETURNS "accepted"**: 输出 `🔐 Step 4/4: 正在生成审计证明...` → **MANDATORY STOP**
**ON COMPLETION**: 解析 ProofBundle + 获取 IPFS CID

---

## 最终输出模板

```
🦞 主人，{year}年度税务分析完成！

📊 数据汇总
  交易笔数：{total_trades}
  应税事件：{taxable_events}

🧮 税额计算（{jurisdiction}）
  应纳税额：{tax_amount} {currency}
  有效税率：{effective_rate}%

📉 优化建议
  {tlh_summary}

🔐 可验证审计链
  zkTLS: {zktls_summary}
  TEE: {tee_type}
  IPFS CID: {cid}
  验证链接: https://gateway.pinata.cloud/ipfs/{cid}

⚠️ 免责声明：本工具提供合规参考建议，最终税务申报请咨询持牌税务师。
```

---

## Continuous Mode（v1.5）

用户选择 Continuous Mode 后，执行以下流程。真实模式与 Demo 模式共享同一拓扑：扫描、监控、归档三类 job 分离；差别只在数据来源（OKX ATK CLI vs preset 数据）。

### Demo D1 总原则（MANDATORY）
Demo Continuous Mode 现在采用真实三-job 拓扑压缩版：

1. `scan-tick`：只做当日增量扫描并合并到 tax_dataset，然后排程 `monitor-tick`
2. `monitor-tick`：只做监控 + daily digest；如果触发 TLH，则暂停并等待用户确认；否则排程下一次 `scan-tick`
3. `archive-tick`：当全部天数完成后执行季度归档和 summary

⛔ 不得再使用旧的一体化 `cm-tick` 路径。
⛔ 不得在同一 run 内自循环推进多天。
⛔ 不得依赖 main session 内存保存 Demo Day 进度；必须依赖 `demo_director.py` 的 durable state。

### Demo Durable State 协议（MANDATORY）
所有 Demo Continuous Mode 的状态都落盘到 `/tmp/veritax-demo/agent_state.json` 与 `cm_state.json`：

1. 开始 Demo Continuous Mode 前，执行：`exec: python3 demo_director.py --scene state-start --jurisdiction {jurisdiction}`，或直接使用 `manage_demo_cron.sh demo-start` 由其隐式完成
2. 当收到 cron 驱动的新一轮 Demo 消息时，第一步执行：`exec: python3 demo_director.py --scene state-show`
3. 若 `phase=ready_to_scan`，只允许执行 `scan-tick`
4. 若 `phase=ready_to_monitor`，只允许执行 `monitor-tick`
5. 若 `phase=awaiting_tlh_confirmation`，禁止继续跑监控；此时只能等待用户确认或拒绝 TLH
6. 若 `phase=ready_to_archive`，只允许执行 `archive-tick`
7. 用户确认或拒绝 TLH 后，执行：`exec: python3 demo_director.py --scene state-monitoring --jurisdiction {jurisdiction}`，然后恢复下一次 `scan-tick`

### Step CM-0: 全量扫描（Flash exec）
执行初始全量扫描，生成 tax_dataset.json。
- Demo: `exec: python3 demo_director.py --scene scan0`
- 真实: `exec: python3 skills/scanner-claw/scanner.py --output=<path>`

### Step CM-1: 合规基线 + 监控初始化（spawn Pro）
**ACTION**: `sessions_spawn({ agentId: "pro", task: "[VeriTax CM-1] 你只做一件事：分析初始税务数据集，生成合规基线报告，并验证有效监控参数（资产、阈值、辖区）是否合理，最后返回一句'监控环境已就绪'的确认。\n\n⛔ Demo 约束：Demo 模式下的有效监控配置来自 demo_scenarios/monitor_config.json。不要声称 monitor_config.json 缺失，也不要要求用户补文件。请直接基于该默认 Demo 配置给出监控参数合理性结论。\n\n⛔ 输出约束（必须严格遵守）：\n1) 只输出：①基线要点（数据概况/资产构成/风险预警）②监控参数合理性检查结论③step_hash。\n2) ⛔ 禁止输出任何 Day 1/Day 2/Day 3 的日报内容，也禁止承诺'正在继续推进 Day 3…请稍候'。\n3) ⛔ 禁止重复发送/改写同一段基线报告多次；只输出一次完整结果。\n4) 若你不确定年份，不要编造'2025/2024'；可以省略年份或用'本年度 demo 合成数据'表述。\n5) ⛔ step_hash 必须来自真实工具调用。执行：exec: python3 skills/compliance-claw/compliance.py --dataset /tmp/veritax-demo/tax_dataset.json --jurisdiction japan --mode=daily-digest --json，然后从输出 JSON 中提取 step_hash 字段。禁止自行编造 64 字符哈希。\n\n最后一行必须是：step_hash: <从 compliance.py 输出中提取的真实 64 hex>" })`
Pro 完成后返回：合规基线报告 + 监控参数确认 + step_hash。

⛔ **Demo 调度初始化（MANDATORY）**：若当前是 Demo Continuous Mode，则在发送 CM-1 报告前，单独执行：`exec: bash manage_demo_cron.sh demo-start --to <telegram_chat_id> --jurisdiction {jurisdiction} --delay 20s`。

其中 `<telegram_chat_id>` 不是可选项。必须从当前会话最近一条 Telegram metadata 中读取 `sender_id` 并原样传入，例如当前消息里若 metadata 为 `"sender_id": "6699483903"`，则命令必须写成：`exec: bash manage_demo_cron.sh demo-start --to 6699483903 --jurisdiction {jurisdiction} --delay 20s`。

该命令会同时完成两件事：
1. 初始化 durable state 到 `ready_to_scan`
2. 预排程第一轮 `scan-tick`

记录 compliance_hash（从 Pro 输出中提取 step_hash 字段）。

### Step CM-2: 每日监控循环（Flash exec，逐天报告）
Demo 模式必须按以下 D1 三段式推进，每次 cron run 只做一个原子步骤：

1. `scan-tick`：`exec: python3 demo_director.py --scene scan-tick --jurisdiction {jurisdiction}`
2. `monitor-tick`：`exec: python3 demo_director.py --scene monitor-tick --jurisdiction {jurisdiction}`
3. `archive-tick`：`exec: python3 demo_director.py --scene archive-tick`

#### `scan-tick` 规则
1. 只做当日增量扫描、把 batch 合并进 tax_dataset、更新 state 到 `ready_to_monitor`
2. 由工具内部自动排程下一次 `schedule-monitor`
3. 正常情况下 stdout 为 `NO_REPLY`，你只原样返回 `NO_REPLY`
4. ⛔ 不要在 `scan-tick` 后自行生成日报

#### `monitor-tick` 规则
1. 只做当日 monitor + compliance daily-digest
2. 若未触发 TLH：输出当天日报，并由工具内部自动排程下一次 `schedule-scan`
3. 若触发 TLH：输出当天日报 + TLH 摘要 + 用户确认问题，并将 durable state 切到 `awaiting_tlh_confirmation`
4. 若所有天数已处理完：将 durable state 切到 `ready_to_archive` 并排程 `schedule-archive`

#### `archive-tick` 规则
1. 只做季度归档和 summary
2. 完成后把 durable state 置为 `completed`

⛔ **ONE-AT-A-TIME 规则**：每次 cron run 只允许发送当天一条用户可见消息。禁止把多天日报合并在同一回复中。
⛔ **禁止承诺尚未执行的结果**：在未实际执行 `monitor-tick` 前，不要写“正在继续推进 Day 3”。
⛔ **jurisdiction 参数合法值**：`japan | australia | canada | singapore | taiwan`。

### Step CM-3: TLH 决策（spawn Pro）
当 monitor 检测到阈值触发（triggered 不为空）：
**ACTION**: `sessions_spawn({ agentId: "pro", task: "[VeriTax CM-3] 税务优化分析：对数据集按{jurisdiction}辖区识别TLH机会。\n\n⛔⛔⛔ 以下是唯一合法的操作步骤（MANDATORY）：\n1. 执行命令：exec: python3 demo_director.py --scene cm-analyze\n2. 等待命令返回完整 JSON 输出\n3. 将返回的 JSON 原文（包括 step_hash）原封不动地包含在你的回复中\n4. 最后一行必须是输出中的 step_hash 值，格式：step_hash: <64 hex>\n\n⛔ 禁止事项：\n- 禁止编写自定义 Python 脚本\n- 禁止自行编造 TLH 建议（必须使用工具输出）\n- 禁止省略或改写返回的资产列表、数字、替代标的\n- 如果工具说卖 ETH/SOL/AVAX，你就报告 ETH/SOL/AVAX，不要换成其他资产\n- 禁止添加工具未输出的资产到建议列表中" })`
记录 optimizer_hash（从 Pro 输出中提取 step_hash 字段）。
⛔ **同时从 Pro 返回的 JSON `actions` 数组中提取资产列表**（如 `["ETH","AVAX","SOL"]`），保存为 `cm3_assets`，供 CM-4 execute 使用；如果当前是 D1 Demo monitor-tick，工具通常已经把这些资产写入 durable state，但你仍需按 Pro 输出核对。
⛔ **在向用户提问前持久化确认状态（MANDATORY）**：若当前步骤不是由 `monitor-tick` 自动完成持久化，则执行：`exec: python3 demo_director.py --scene state-awaiting-confirmation --jurisdiction {jurisdiction} --actions '{cm3_assets_json}' --step-hash {optimizer_hash}`。

⛔⛔⛔ **CM-3 Completion 格式化协议（MANDATORY — Flash 层）** ⛔⛔⛔

当 Pro 返回 CM-3 的 completion event 时，Pro 的输出包含 optimizer.py 的 **原始 JSON**。
**你（Flash）禁止将原始 JSON 直接展示给用户**。必须将 JSON 转为用户友好的中文摘要格式：

```
📉 Tax-Loss Harvesting 分析结果

💰 总可收割亏损：{total_harvestable_loss} USD
💵 预估节税：{estimated_tax_savings} USD
🔄 Wash Sale 状态：{wash_sale_status.note}

🧭 排序方案：
  [1] {strategy_plans[0].title}（score={strategy_plans[0].score}｜敞口保持={strategy_plans[0].exposure_retention}｜可执行性={strategy_plans[0].execution_readiness}）
     → {strategy_plans[0].description}
     → 辖区理由：{strategy_plans[0].rationale.jurisdiction}
     → 执行备注：{strategy_plans[0].rationale.execution}
     → ATK 模块：{strategy_plans[0].modules}
  [2] {strategy_plans[1].title} ...

📋 当前可直接执行的 TLH 动作：
  1. 卖出 {actions[0].asset} {actions[0].units} 单位（未实现亏损 {actions[0].unrealized_pnl} / {actions[0].pnl_pct}%）
     → 替代标的：{actions[0].substitutes}
  2. 卖出 {actions[1].asset} ...

{earn_hook}
⚠️ {disclaimer}
```

⛔ 格式化规则：
- 优先从 JSON 的 `strategy_plans` 数组中提取排序后的多方案建议，按 rank 顺序展示
- 从 JSON 的 `actions` 数组中提取每个 SELL 建议，逐条列出
- 数字必须来自 JSON 原文，禁止自行计算或改写
- step_hash 在摘要末尾单独一行输出
- **禁止输出 ```json 代码块给用户** — 用户不需要看原始 JSON

### Step CM-4: TLH 执行确认（⛔ 必须询问用户）
Pro 返回 TLH 方案后，向用户展示优化建议，然后**必须询问**：
> "是否执行以上 TLH 操作？（确认后将模拟卖出亏损资产 + 买入替代标的）"

用户确认后，使用 CM-3 提取的资产列表限制执行范围：
**ACTION**: `exec: python3 demo_director.py --scene execute --actions '["资产1","资产2",...]'`
其中 `--actions` 的值是 CM-3 JSON `actions` 数组中所有 `asset` 字段的列表（如 `'["ETH","AVAX","SOL","MATIC"]'`）。
⛔ **--actions 参数是 MANDATORY 的**：确保 execute 只执行 CM-3 approve 过的资产，禁止遗漏此参数。
在执行前先读取 durable state：`exec: python3 demo_director.py --scene state-show`，并使用其中的 `pending_assets` 作为兜底来源；若当前用户回复是确认/执行/yes 且 `phase=awaiting_tlh_confirmation`，则直接进入 CM-4，不要要求用户重复说明资产列表。
记录执行结果。执行后执行：`exec: python3 demo_director.py --scene state-monitoring --jurisdiction {jurisdiction}`。若当前仍有剩余 demo 天数，再单独执行：`exec: bash manage_demo_cron.sh resume --delay 20s` 以恢复下一轮 `scan-tick`。**用户拒绝则也先执行 `state-monitoring` 清空 pending，再执行 `resume`，然后继续进入后续步骤。**

### Step CM-5: 审计链生成（spawn Pro）
**ACTION**: `sessions_spawn({ agentId: "pro", task: "[VeriTax CM-5] 生成可验证审计链。\n\n以下是所有需要包含在审计链中的 step_hash（按时间顺序）：\n{all_hashes_formatted}\n\n⛔ 必须使用 --json 标志调用 auditor.py：\npython3 skills/auditor-claw/auditor.py --hashes '{json_array_of_all_hashes}' --json\n\n将上述所有 hash 作为 Merkle 叶子传入。禁止使用人类可读模式（会截断哈希）。" })`

其中 `{all_hashes_formatted}` 是 CM 流程中收集的所有 step_hash 列表（CM-1/Day1-N/CM-3/CM-4 execute），`{json_array_of_all_hashes}` 是这些 hash 的 JSON 数组。

⛔ **审计诚实度规则**：
- 输入哈希必须是各步骤输出中的真实 step_hash 字段值，禁止使用占位字符串
- TEE 若为 mock_tdx，必须如实说明 "TEE: mock（当前非 Phala CVM 环境，部署后可获得真实 TDX 证明）"
- 禁止说"验证全部成功"除非所有组件（Merkle + IPFS + TEE）均为真实验证通过

### Step CM-6: 持续运行（TLH 后继续监控）
TLH 执行完成后，继续按 Step CM-2 的规则推进剩余天数。
⛔ 若仍有剩余 demo 天数，则在发出 CM-4 执行结果后重新安排下一次 tick：`exec: bash manage_demo_cron.sh resume --delay 20s`，然后再发送用户可见结果（stop）。
monitor_config 已在 CM-4 执行时更新（已卖出的资产从监控列表移除/替换）。

### Step CM-7: 季度归档（Flash exec，⛔ 必须在 CM-5 之前执行）
当所有监控数据跑完后（数据耗尽或到达季末节点），**必须先执行季度归档，再进入 CM-5 审计链生成**：
**D1 Demo 模式**：优先执行 `exec: python3 demo_director.py --scene archive-tick`，由该命令一次性完成 archive + summary。

**非 D1 / 调试模式**：
**ACTION 1**: `exec: python3 demo_director.py --scene archive`
**ACTION 2**: `exec: python3 demo_director.py --scene summary`

⛔ **强制执行顺序**：数据耗尽 → CM-7 archive → CM-7 summary → CM-5 审计链。
⛔ **禁止跳过 CM-7**：即使数据已耗尽，也必须执行 archive 和 summary 后才能进入 CM-5。
⛔ **违规示例**：数据耗尽后直接 spawn CM-5 审计（❌ 跳过了 CM-7）。

### Cron 映射（真实场景参考）
| Cron Job | 间隔 | 对应 Step |
|----------|------|----------|
| `veritax-daily-scan` | 每日 02:00 UTC | CM-2 扫描部分 |
| `veritax-monitor` | 每小时 | CM-2 监控部分 |
| `veritax-quarterly-archive` | 每季度首日 | CM-7 |

### Compaction 策略
- 监控会话 `session:veritax-monitor` 跨轮次保持上下文
- Compaction model = Flash（无需推理）
- `memoryFlush` 自动将 monitor 状态写入 `memory/YYYY-MM-DD.md`

---

## Demo 模式（preset 数据替代 OKX API）

当用户提到 "Demo"、"演示"、"demo模式" 时，激活 Demo 数据层：

1. 执行 `exec: python3 demo_director.py --scene reset` 清理上一次 demo 状态
2. 执行 `exec: python3 demo_director.py --scene scan0` 加载合成交易数据（替代 OKX 账户扫描）
3. 之后按照正常工作流程操作（税务审查 或 Continuous Mode 监控）
4. 所有 claw 脚本在 `VERITAX_DEMO=1` 环境下会自动使用 `/tmp/veritax-demo` 中的 preset 数据

### 可用 Demo 场景（每个只做数据注入，不改变 agent 行为）

| 场景 | 命令 | 用途 |
|------|------|------|
| 环境重置 | `--scene reset` | 清理 /tmp/veritax-demo |
| 全量扫描 | `--scene scan0` | 加载 demo_dataset.json |
| D1 初始化 | `--scene state-start` | 初始化 durable state 到 `ready_to_scan` |
| D1 扫描 tick | `--scene scan-tick` | 单次增量扫描并排程 monitor job |
| D1 监控 tick | `--scene monitor-tick` | 单次监控 + daily digest，必要时进入 TLH 等待态 |
| D1 归档 tick | `--scene archive-tick` | 单次季度归档 + summary |
| D1 恢复监控态 | `--scene state-monitoring` | TLH 确认后恢复后续扫描 |
| 每日增量 Day 1-5 | `--scene daily1/2/3/4/5` | 注入当日增量交易批次 |
| TLH 监控 Day 1-2 | `--scene monitor1/2` | 注入当日正常价格（应为 all clear） |
| TLH 监控 Day 3 崩盘 | `--scene trigger` | 注入崩盘价格（应触发 TLH） |
| TLH 执行 | `--scene execute` | 模拟卖出 + 买入替代标的 + 更新 monitor_config |
| Post-TLH 监控 Day 4-5 | `--scene monitor4/5` | 注入 TLH 后价格（使用 post-TLH config） |
| 季度归档 | `--scene archive` | 执行 Merkle → IPFS 归档 |
| 总结 | `--scene summary` | 显示 demo 生成的所有文件 |

### Demo 数据耗尽行为

当 preset 数据用完时，claw 脚本会优雅返回：
- scanner.py: `{"ok":true, "new_records":0, "message":"Demo: no more data"}`
- optimizer.py: `{"ok":true, "triggered":[], "message":"Demo: monitoring cycle complete"}`

**收到这些信号时应向用户说明 "Demo 数据已用完，演示结束"。**
