#!/usr/bin/env python3
"""Demo Director — Time-compressed Continuous Mode demonstration (OKX Edition).

Orchestrates a 4-day simulated timeline (March 28 → April 1) in ~5 minutes,
showcasing all Continuous Mode features:
  Scene 0:   Initial full scan + compliance baseline (Pro model)
  Scene 1-3: Daily incremental scans (new trades detected)
  Scene 4-5: TLH monitor checks (all clear → threshold triggered)
  Scene 6b:  TLH decision via real optimizer analyze (Pro model)
  Scene 6c:  TLH execution simulation
  Scene 7:   Quarterly archive (Merkle → IPFS)

Usage:
  python demo_director.py              # Run full demo (~5 min)
  python demo_director.py --reset      # Clear demo state, ready for re-run
  python demo_director.py --speed 2    # 2x speed (default 1x)

ENV Setup (auto-configured by this script):
  VERITAX_DEMO=1
  VERITAX_DATA_DIR=/tmp/veritax-demo
  VERITAX_DEMO_BATCH=<path to daily batch>
  VERITAX_DEMO_BALANCES=<JSON>
  VERITAX_DEMO_PRICES=<JSON>
  SCANNER_DEMO_PATH=<path to full dataset>
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# --- Constants ---
DEMO_DATA_DIR = Path("/tmp/veritax-demo")
PROJECT_ROOT = Path(__file__).resolve().parent
SCENARIOS_DIR = PROJECT_ROOT / "demo_scenarios"
SCANNER_PY = PROJECT_ROOT / "skills" / "scanner-claw" / "scanner.py"
OPTIMIZER_PY = PROJECT_ROOT / "skills" / "optimizer-claw" / "optimizer.py"
COMPLIANCE_PY = PROJECT_ROOT / "skills" / "compliance-claw" / "compliance.py"
AUDITOR_PY = PROJECT_ROOT / "skills" / "auditor-claw" / "auditor.py"
DEMO_DATASET = PROJECT_ROOT / "demo_dataset.json"

# Base ENV for all demo subprocesses
DEMO_ENV = {
    **os.environ,
    "VERITAX_DEMO": "1",
    "VERITAX_DATA_DIR": str(DEMO_DATA_DIR),
}

# Load price series
PRICE_SERIES = {}
_ps_file = SCENARIOS_DIR / "price_series.json"
if _ps_file.exists():
    with open(_ps_file, "r", encoding="utf-8") as _f:
        PRICE_SERIES = json.load(_f)

# FX conversion for demo (USD → local currency, 2026 annual averages)
_DEMO_FX = {
    "japan":     (146.0, "JPY"),
    "taiwan":    (32.5,  "TWD"),
    "australia": (1.56,  "AUD"),
    "canada":    (1.39,  "CAD"),
    "singapore": (1.32,  "SGD"),
}

def _get_demo_fx(jurisdiction: str) -> tuple[float, str]:
    return _DEMO_FX.get(jurisdiction, (1.0, "USD"))

def _fmt_local(usd_value: float, fx_rate: float, currency: str) -> str:
    """Format a USD value in local currency (no decimals for JPY/TWD/KRW)."""
    val = usd_value * fx_rate
    if currency in ("JPY", "TWD", "KRW"):
        return f"{val:,.0f}"
    return f"{val:,.2f}"


def _extract_json(output: str) -> dict | None:
    """Extract first JSON object from multiline subprocess output."""
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    first_brace = output.find("{")
    last_brace = output.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(output[first_brace:last_brace + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _extract_json_objects(output: str) -> list[dict]:
    """Extract top-level JSON objects from mixed multiline subprocess output."""
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    index = 0
    while index < len(output):
        next_brace = output.find("{", index)
        if next_brace == -1:
            break
        try:
            obj, consumed = decoder.raw_decode(output[next_brace:])
        except json.JSONDecodeError:
            index = next_brace + 1
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        index = next_brace + consumed
    return objects


def _extract_user_message(output: str) -> str:
    start = output.find("===USER_MESSAGE_START===")
    end = output.find("===USER_MESSAGE_END===")
    if start == -1 or end == -1 or end <= start:
        return ""
    return output[start + len("===USER_MESSAGE_START==="):end].strip()


def _run_demo_cron(*args: str) -> None:
    """Run the demo cron helper without leaking helper output into user-facing messages."""
    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "manage_demo_cron.sh"), *args],
        env=DEMO_ENV,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    if result.returncode != 0 and result.stderr:
        print(f"⚠️ cron helper failed: {result.stderr.strip()}", file=sys.stderr)


def _format_tlh_summary(analyze_json: dict, jurisdiction: str = "japan") -> str:
    fx_rate, currency = _get_demo_fx(jurisdiction)
    total_loss_usd = float(analyze_json.get('total_harvestable_loss', 0))
    savings_usd = float(analyze_json.get('estimated_tax_savings', 0))
    strategy_plans = analyze_json.get("strategy_plans") or []
    lines = [
        "📉 Tax-Loss Harvesting 分析结果",
        "",
        f"💰 总可收割亏损：{_fmt_local(total_loss_usd, fx_rate, currency)} {currency}",
        f"💵 预估节税：{_fmt_local(savings_usd, fx_rate, currency)} {currency}",
        f"🔄 Wash Sale 状态：{analyze_json.get('wash_sale_status', {}).get('note', 'N/A')}",
        "",
        "🧭 排序方案：",
    ]
    for plan in strategy_plans:
        lines.append(
            f"  [{plan.get('rank', '?')}] {plan.get('title', '未命名方案')}"
            f"（score={plan.get('score', '?')}｜敞口保持={plan.get('exposure_retention', 'N/A')}｜"
            f"可执行性={plan.get('execution_readiness', 'N/A')}）"
        )
        lines.append(f"     → {plan.get('description', '')}")
        rationale = plan.get("rationale", {})
        if rationale.get("jurisdiction"):
            lines.append(f"     → 辖区理由：{rationale['jurisdiction']}")
        if rationale.get("execution"):
            lines.append(f"     → 执行备注：{rationale['execution']}")
        modules = plan.get("modules") or []
        if modules:
            lines.append(f"     → ATK 模块：{', '.join(modules)}")
    if strategy_plans:
        lines.append("     → 当前DEX无适合替代标的，Veri Agent将持续通过OnChainOS监控链上持仓情况")
    lines.extend(["", "📋 当前可直接执行的 TLH 动作："])
    for index, action in enumerate(analyze_json.get("actions", []), start=1):
        substitutes = action.get("substitutes") or []
        substitute_text = ", ".join(substitutes) if substitutes else "无"
        pnl_local = _fmt_local(float(action.get('unrealized_pnl', 0)), fx_rate, currency)
        lines.append(
            f"  {index}. 卖出 {action.get('asset', '?')} {action.get('units', '?')} 单位（未实现亏损 {pnl_local} {currency} / {action.get('pnl_pct', '?')}%）"
        )
        lines.append(f"     → 替代标的：{substitute_text}")
        if action.get("onchain_substitute"):
            option = action["onchain_substitute"]
            lines.append(
                f"     → 链上替代：可用 {option.get('funding_asset', '?')} 在 {option.get('chain', '?')} 上通过 OnChainOS 换入 {option.get('asset', '?')}"
            )
    if analyze_json.get("earn_hook"):
        lines.extend(["", analyze_json["earn_hook"]])
    if analyze_json.get("disclaimer"):
        lines.append(f"⚠️ {analyze_json['disclaimer']}")
    if analyze_json.get("step_hash"):
        lines.extend(["", f"🔐 可信证明：step_hash={analyze_json['step_hash']}"])
    return "\n".join(lines)


def banner(text: str, char: str = "═") -> None:
    width = 60
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}\n")


def scene_pause(seconds: float, speed: float, label: str = "") -> None:
    actual = min(seconds / speed, 1.0)
    if label:
        print(f"  ⏳ {label}")
    if actual > 0.01:
        time.sleep(actual)


def run_claw(cmd: list[str], env_overrides: dict | None = None, label: str = "") -> str:
    """Run a claw subprocess and return its stdout."""
    env = {**DEMO_ENV, **(env_overrides or {})}
    if label:
        print(f"  🔧 {label}")
    result = subprocess.run(
        [sys.executable] + cmd,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    output = result.stdout.strip()
    if result.stderr.strip():
        for line in result.stderr.strip().split("\n"):
            if "warning" not in line.lower() and "deprecat" not in line.lower():
                print(f"  ⚠️  {line}")
    if output:
        for line in output.split("\n"):
            print(f"  📤 {line}")
    return output


def reset_demo() -> None:
    """Clear all demo state for a fresh run."""
    if DEMO_DATA_DIR.exists():
        shutil.rmtree(DEMO_DATA_DIR)
    DEMO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✅ Demo state cleared: {DEMO_DATA_DIR}")


# --- CM State Management ---
CM_STATE_FILE = DEMO_DATA_DIR / "cm_state.json"
AGENT_STATE_FILE = DEMO_DATA_DIR / "agent_state.json"

_CM_DAY_SCHEDULE = {
    1: ("daily1", "monitor1"),
    2: ("daily2", "monitor2"),
    3: ("daily3", "trigger"),
    4: ("daily4", "monitor4"),
    5: ("daily5", "monitor5"),
}


def _load_cm_state() -> dict:
    if CM_STATE_FILE.exists():
        with open(CM_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"current_day": 1}


def _save_cm_state(state: dict) -> None:
    CM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CM_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _load_agent_state() -> dict:
    if AGENT_STATE_FILE.exists():
        with open(AGENT_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "mode": None,
        "phase": None,
        "jurisdiction": "japan",
        "pending_assets": [],
        "last_step_hash": None,
    }


def _save_agent_state(state: dict) -> None:
    AGENT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AGENT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _reset_demo_workflow_state(jurisdiction: str = "japan", route_to: str | None = None) -> dict:
    _save_cm_state({"current_day": 1})
    state = {
        "mode": "demo_continuous",
        "phase": "ready_to_scan",
        "jurisdiction": jurisdiction,
        "pending_assets": [],
        "last_step_hash": None,
        "route_to": route_to,
    }
    _save_agent_state(state)
    return state


def _current_demo_day() -> int:
    return int(_load_cm_state().get("current_day", 1))


def _set_current_demo_day(day: int) -> None:
    _save_cm_state({"current_day": day})


def _merge_demo_batch(day: int, dataset_path: Path) -> None:
    """Merge daily incremental batch into the cumulative dataset.

    OKX Edition: uses 'trades' + 'earn_records' (not spot_trades/futures_income).
    """
    batch_file = SCENARIOS_DIR / f"day{day}_batch.json"
    if not dataset_path.exists() or not batch_file.exists():
        return
    with open(dataset_path, "r", encoding="utf-8") as f:
        ds = json.load(f)
    with open(batch_file, "r", encoding="utf-8") as f:
        batch = json.load(f)
    data = ds.get("data", {})
    for key in ("trades", "earn_records", "deposits", "withdrawals"):
        data.setdefault(key, []).extend(batch.get(key, []))
    ds["data"] = data
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(ds, f, ensure_ascii=False)


def _render_daily_message(day: int, jurisdiction: str, monitor_out: str, digest_out: str, scan_out: str) -> str:
    scan_json = _extract_json(scan_out or "")
    monitor_json = _extract_json(monitor_out or "")
    digest_json = _extract_json(digest_out or "")

    new_records = scan_json.get("new_records", "?") if scan_json else "?"
    currency = digest_json.get("currency", "JPY") if digest_json else "JPY"
    triggered = monitor_json.get("triggered", []) if monitor_json else []
    monitor_status = f"⚠️ triggered ({len(triggered)}个标的)" if triggered else "✅ all_clear"

    positions_lines = []
    if digest_json:
        for pos in digest_json.get("top_positions", []):
            positions_lines.append(
                f"  • {pos['asset']}: {pos['units']} (成本 {pos['cost_basis']} {currency})"
            )
    positions_text = "\n".join(positions_lines) if positions_lines else "  • (无数据)"

    realized = digest_json.get("realized_gain", "?") if digest_json else "?"
    futures = digest_json.get("futures_pnl", "0") if digest_json else "0"
    est_tax = digest_json.get("estimated_tax", "?") if digest_json else "?"
    step_hash = digest_json.get("step_hash", "????????") if digest_json else "????????"

    # Build 🧾 line: show futures_pnl only when non-zero
    ledger_parts = [f"累计已实现收益：{realized}"]
    try:
        if futures and float(futures) != 0:
            ledger_parts.append(f"期货损益：{futures}")
    except (ValueError, TypeError):
        pass
    ledger_parts.append(f"预估税额：{est_tax}")
    ledger_line = " | ".join(ledger_parts)

    sim_date = datetime(2026, 3, 28) + timedelta(days=day)
    date_str = f"{sim_date.year}年{sim_date.month}月{sim_date.day}日"
    return (
        f"📅 Day {day} — {date_str}（模拟时间 02:00 UTC）\n"
        f"\n"
        f"📊 增量扫描：新增 {new_records} 笔交易记录\n"
        f"📈 监控状态：{monitor_status}\n"
        f"💰 持仓快照：\n"
        f"{positions_text}\n"
        f"🧾 {ledger_line}\n"
        f"🔐 可信证明：step_hash={step_hash}"
    )


# ═══════════════════════════════════════════════════════
# State management scenes (for D1 cron-based workflow)
# ═══════════════════════════════════════════════════════

def scene_state_show() -> None:
    print(json.dumps(_load_agent_state(), ensure_ascii=False))


def scene_state_start(jurisdiction: str = "japan", route_to: str | None = None) -> None:
    print(json.dumps(_reset_demo_workflow_state(jurisdiction=jurisdiction, route_to=route_to), ensure_ascii=False))


def scene_state_monitoring(jurisdiction: str = "japan") -> None:
    state = _load_agent_state()
    state.update({
        "mode": "demo_continuous",
        "phase": "ready_to_scan",
        "jurisdiction": jurisdiction,
        "pending_assets": [],
    })
    _save_agent_state(state)
    print(json.dumps(state, ensure_ascii=False))


def scene_state_awaiting_confirmation(
    jurisdiction: str = "japan",
    actions_json: str | None = None,
    step_hash: str | None = None,
) -> None:
    pending_assets = []
    if actions_json:
        pending_assets = json.loads(actions_json)
    state = _load_agent_state()
    state.update({
        "mode": "demo_continuous",
        "phase": "awaiting_tlh_confirmation",
        "jurisdiction": jurisdiction,
        "pending_assets": pending_assets,
        "last_step_hash": step_hash,
    })
    _save_agent_state(state)
    print(json.dumps(state, ensure_ascii=False))


def scene_state_clear() -> None:
    if AGENT_STATE_FILE.exists():
        AGENT_STATE_FILE.unlink()
    print(json.dumps(_load_agent_state(), ensure_ascii=False))


# ═══════════════════════════════════════════════════════
# D1 Cron tick scenes
# ═══════════════════════════════════════════════════════

def scene_scan_tick(jurisdiction: str = "japan") -> None:
    state = _load_agent_state()
    if state.get("phase") != "ready_to_scan":
        print("NO_REPLY")
        return

    if not state.get("route_to"):
        print("❌ route_to missing in agent_state — demo-start was not called with --to <chatId>", file=sys.stderr)
        print("NO_REPLY")
        return

    day = _current_demo_day()
    if day > 5:
        state["phase"] = "ready_to_archive"
        _save_agent_state(state)
        _run_demo_cron("schedule-archive", "--delay", "10s")
        print("NO_REPLY")
        return

    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        scene_daily(day)
    dataset_path = DEMO_DATA_DIR / "tax_dataset.json"
    _merge_demo_batch(day, dataset_path)

    state["phase"] = "ready_to_monitor"
    state["jurisdiction"] = jurisdiction
    _save_agent_state(state)
    _run_demo_cron("schedule-monitor", "--delay", "10s")

    print("NO_REPLY")


def scene_monitor_tick(jurisdiction: str = "japan") -> None:
    state = _load_agent_state()
    if state.get("phase") != "ready_to_monitor":
        print("NO_REPLY")
        return

    if not state.get("route_to"):
        print("❌ route_to missing in agent_state — demo-start was not called with --to <chatId>", file=sys.stderr)
        print("NO_REPLY")
        return

    day = _current_demo_day()
    if day > 5:
        state["phase"] = "ready_to_archive"
        _save_agent_state(state)
        _run_demo_cron("schedule-archive", "--delay", "10s")
        print("NO_REPLY")
        return

    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        if day == 3:
            monitor_out = scene_trigger()
        elif day >= 4:
            monitor_out = scene_monitor_post_tlh(day)
        else:
            monitor_out = scene_monitor(day)

        dataset_path = DEMO_DATA_DIR / "tax_dataset.json"
        digest_out = run_claw(
            [str(COMPLIANCE_PY), f"--dataset={dataset_path}",
             f"--jurisdiction={jurisdiction}", "--mode=daily-digest", "--json"],
            label="Compliance --mode=daily-digest",
        )

    scan_out = json.dumps({"new_records": "?"}, ensure_ascii=False)
    batch_file = SCENARIOS_DIR / f"day{day}_batch.json"
    if batch_file.exists():
        with open(batch_file, "r", encoding="utf-8") as f:
            batch = json.load(f)
        # OKX Edition: count from unified 'trades' + 'earn_records'
        total_records = sum(len(batch.get(key, [])) for key in ("trades", "earn_records", "deposits", "withdrawals"))
        scan_out = json.dumps({"new_records": total_records}, ensure_ascii=False)

    user_message = _render_daily_message(day, jurisdiction, monitor_out, digest_out, scan_out)
    monitor_json = _extract_json(monitor_out or "") or {}
    triggered = monitor_json.get("triggered", [])

    if triggered:
        crash_px = PRICE_SERIES.get("day3_crash", {})
        _buf2 = io.StringIO()
        with contextlib.redirect_stdout(_buf2):
            analyze_out = run_claw(
                [str(OPTIMIZER_PY), "--mode=analyze",
                 f"--dataset={dataset_path}",
                 f"--jurisdiction={jurisdiction}",
                 "--config", str(SCENARIOS_DIR / "monitor_config.json"),
                 f"--prices={json.dumps(crash_px.get('prices', {}))}",
                 "--json"],
                label="Optimizer --mode=analyze (demo crash prices)",
            )
        analyze_json = _extract_json(analyze_out or "") or {}
        assets = [item.get("asset") for item in analyze_json.get("actions", []) if item.get("asset")]
        state.update({
            "phase": "awaiting_tlh_confirmation",
            "pending_assets": assets,
            "last_step_hash": analyze_json.get("step_hash"),
            "total_harvestable_loss": analyze_json.get("total_harvestable_loss"),
            "estimated_tax_savings": analyze_json.get("estimated_tax_savings"),
        })
        _set_current_demo_day(day + 1)
        _save_agent_state(state)
        print("\n\n".join([
            user_message,
            _format_tlh_summary(analyze_json, jurisdiction=jurisdiction),
            "是否执行以上 TLH 操作？（确认后将模拟卖出亏损资产 + 买入替代标的）",
        ]))
        return

    next_day = day + 1
    _set_current_demo_day(next_day)
    if next_day > 5:
        state["phase"] = "ready_to_archive"
        _save_agent_state(state)
        _run_demo_cron("schedule-archive", "--delay", "10s")
    else:
        state["phase"] = "ready_to_scan"
        _save_agent_state(state)
        _run_demo_cron("schedule-scan", "--delay", "20s")
    print(user_message)


def scene_archive_tick() -> None:
    state = _load_agent_state()
    if state.get("phase") != "ready_to_archive":
        print("NO_REPLY")
        return
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        archive_raw = scene_archive()
    archive_json = _extract_json(archive_raw or "")
    summary_buf = io.StringIO()
    with contextlib.redirect_stdout(summary_buf):
        scene_summary()
    summary_lines = []
    for line in summary_buf.getvalue().splitlines():
        if line.strip().startswith("📤") or line.strip().startswith("{"):
            continue
        summary_lines.append(line)

    state["phase"] = "completed"
    state["pending_assets"] = []
    _save_agent_state(state)

    parts = ["🗂️ Demo 数据已完成季度归档。"]
    if archive_json:
        parts.append("")
        parts.append("🔗 可信链条（Cryptographic Audit Trail）：")
        mr = archive_json.get("merkle_root", "N/A")
        cid = archive_json.get("ipfs_cid", "N/A")
        total = archive_json.get("total_records", "?")
        parts.append(f"  • Merkle Root: {mr}")
        parts.append(f"  • IPFS CID: {cid}")
        parts.append(f"  • 归档记录数: {total}")
        files = archive_json.get("files", {})
        if files.get("proof"):
            parts.append(f"  • Proof 文件: {files['proof']}")
    parts.append("")
    parts.append("\n".join(summary_lines).strip())
    print("\n".join(parts))


# ═══════════════════════════════════════════════════════
# Atomic scene functions (for agent orchestration)
# ═══════════════════════════════════════════════════════

def scene_reset() -> None:
    reset_demo()


def scene_scan0() -> None:
    dataset_path = DEMO_DATA_DIR / "tax_dataset.json"
    DEMO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    banner("📅 Scene 0: 3月28日 — 初始全量扫描", "─")
    print("  📊 加载 Demo 合成数据（2026年交易记录 → 基线数据集）")
    run_claw(
        [str(SCANNER_PY), f"--demo={DEMO_DATASET}", f"--output={dataset_path}"],
        label="Scanner --demo --output (加载2026年合成数据)",
    )


def scene_daily(day: int) -> str:
    batch_file = SCENARIOS_DIR / f"day{day}_batch.json"
    if not batch_file.exists():
        print(f"  ❌ Batch file not found: {batch_file}")
        return ""
    banner(f"📅 每日增量扫描 — Day {day}", "─")
    print(f"  🔔 Cron veritax-daily-scan 触发 (Day {day})")
    return run_claw(
        [str(SCANNER_PY), "--mode=incremental", "--json"],
        env_overrides={"VERITAX_DEMO_BATCH": str(batch_file)},
        label="Scanner --mode=incremental",
    )


def scene_monitor(day: int) -> str:
    day_key = f"day{day}"
    day_px = PRICE_SERIES.get(day_key, {})
    if not day_px:
        print(f"  ❌ Price data not found for {day_key} in price_series.json")
        return ""
    banner(f"📅 TLH 监控轮询 — Day {day}", "─")
    print(f"  🔔 Cron veritax-monitor 触发 (Day {day})")
    return run_claw(
        [str(OPTIMIZER_PY), "--mode=monitor", "--jurisdiction=japan",
         "--config", str(SCENARIOS_DIR / "monitor_config.json"), "--json"],
        env_overrides={
            "VERITAX_DEMO_BALANCES": json.dumps(day_px.get("balances", {})),
            "VERITAX_DEMO_PRICES": json.dumps(day_px.get("prices", {})),
        },
        label="Optimizer --mode=monitor",
    )


def scene_monitor_post_tlh(day: int) -> str:
    day_key = f"day{day}"
    day_px = PRICE_SERIES.get(day_key, {})
    if not day_px:
        print(f"  ❌ Price data not found for {day_key} in price_series.json")
        return ""
    banner(f"📅 TLH 监控轮询 — Day {day}（Post-TLH）", "─")
    print(f"  🔔 Cron veritax-monitor 触发 (Day {day}, post-TLH config)")
    return run_claw(
        [str(OPTIMIZER_PY), "--mode=monitor", "--jurisdiction=japan",
         "--config", str(SCENARIOS_DIR / "monitor_config_post_tlh.json"), "--json"],
        env_overrides={
            "VERITAX_DEMO_BALANCES": json.dumps(day_px.get("balances", {})),
            "VERITAX_DEMO_PRICES": json.dumps(day_px.get("prices", {})),
        },
        label="Optimizer --mode=monitor (post-TLH config)",
    )


def scene_trigger() -> str:
    crash_px = PRICE_SERIES.get("day3_crash", {})
    if not crash_px:
        print("  ❌ Crash price data not found in price_series.json")
        return ""
    banner("📅 ⚠️ TLH 监控 — 阈值触发！", "─")
    print("  🔔 Cron veritax-monitor 触发")
    print("  💥 ETH 价格暴跌 -22%！从 $2080 → $1620")
    return run_claw(
        [str(OPTIMIZER_PY), "--mode=monitor", "--jurisdiction=japan",
         "--config", str(SCENARIOS_DIR / "monitor_config.json"), "--json"],
        env_overrides={
            "VERITAX_DEMO_BALANCES": json.dumps(crash_px.get("balances", {})),
            "VERITAX_DEMO_PRICES": json.dumps(crash_px.get("prices", {})),
        },
        label="Optimizer --mode=monitor (CRASH PRICES)",
    )


def scene_cm_analyze() -> None:
    crash_px = PRICE_SERIES.get("day3_crash", {})
    crash_prices = crash_px.get("prices", {})
    dataset_path = DEMO_DATA_DIR / "tax_dataset.json"
    banner("📉 TLH 分析（Demo 崩盘价格）", "─")
    print("  📡 使用 demo crash 价格运行 TLH 分析")
    run_claw(
        [str(OPTIMIZER_PY), "--mode=analyze",
         f"--dataset={dataset_path}",
         "--jurisdiction=japan",
         "--config", str(SCENARIOS_DIR / "monitor_config.json"),
         f"--prices={json.dumps(crash_prices)}",
         "--json"],
        label="Optimizer --mode=analyze (demo crash prices)",
    )


def scene_execute(actions_json: str | None = None, jurisdiction: str = "japan") -> None:
    """Scene: TLH execution — simulate sell + substitute buy + config update.

    OKX Edition: writes back OKX-format trades (instId, fillSz, fillPx, side, fee, feeCcy, ts).
    Outputs a formatted user-facing message and transitions state for next scan.
    """
    crash_px = PRICE_SERIES.get("day3_crash", {})
    crash_prices = crash_px.get("prices", {})
    dataset_path = DEMO_DATA_DIR / "tax_dataset.json"
    fx_rate, currency = _get_demo_fx(jurisdiction)
    banner("⚡ TLH 执行", "─")
    print("  📡 执行 TLH 操作（模拟卖出 + 替代标的买入）")
    cmd = [str(OPTIMIZER_PY), "--mode=execute",
         f"--dataset={dataset_path}",
         f"--jurisdiction={jurisdiction}",
         "--config", str(SCENARIOS_DIR / "monitor_config.json"),
         f"--prices={json.dumps(crash_prices)}",
         "--json"]
    if actions_json:
        cmd.append(f"--actions={actions_json}")

    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        exec_out = run_claw(
            cmd,
            label="Optimizer --mode=execute (TLH simulation)",
        )

    # Write TLH sell/buy trades back to tax_dataset.json so compliance sees them
    exec_json = _extract_json(exec_out or "")
    sell_assets = []
    buy_assets = []
    if exec_json and dataset_path.exists():
        with open(dataset_path, "r", encoding="utf-8") as f:
            ds = json.load(f)
        data = ds.get("data", {})
        trades = data.setdefault("trades", [])
        base_ts = 1743382800000
        for i, item in enumerate(exec_json.get("executed", [])):
            ts = base_ts + i * 60000
            asset = item.get("asset", "")
            sell_assets.append(asset)
            inst_id = f"{asset}-USDT"
            trades.append({
                "instId": inst_id, "instType": "SPOT", "side": "sell",
                "fillSz": str(item.get("quantity", 0)),
                "fillPx": str(item.get("price", 0)),
                "fee": "0", "feeCcy": "USDT", "ts": ts,
                "tradeId": f"TLH-SELL-{i}", "ordId": f"TLH-ORD-{i}", "pnl": "0",
            })
            sub = item.get("substitute", {})
            if sub:
                sub_asset = sub.get("asset", "")
                buy_assets.append(sub_asset)
                trades.append({
                    "instId": f"{sub_asset}-USDT", "instType": "SPOT", "side": "buy",
                    "fillSz": str(sub.get("quantity", 0)),
                    "fillPx": str(sub.get("price", 0)),
                    "fee": "0", "feeCcy": "USDT",
                    "ts": ts + 1000,
                    "tradeId": f"TLH-BUY-{i}", "ordId": f"TLH-BUYORD-{i}", "pnl": "0",
                })
        ds["data"] = data
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(ds, f, ensure_ascii=False)

    # --- Build formatted user message ---
    state = _load_agent_state()
    total_loss_usd = float(state.get("total_harvestable_loss", 0))
    savings_usd = float(state.get("estimated_tax_savings", 0))
    total_loss_local = _fmt_local(total_loss_usd, fx_rate, currency)
    savings_local = _fmt_local(savings_usd, fx_rate, currency)
    wash_note = "日本暂无 Wash Sale 限制，操作完全合规。" if jurisdiction == "japan" else exec_json.get("wash_sale_status", "N/A") if exec_json else "N/A"

    step_hash = exec_json.get("step_hash", "") if exec_json else ""
    msg_parts = [
        "⚡ TLH 策略已执行 (Demo 模拟)",
        "",
        "✅ 执行摘要：",
        f"  • 卖出资产：{', '.join(sell_assets) or 'N/A'}",
        f"  • 买入替代标的：{', '.join(buy_assets) or 'N/A'}",
        f"  • 累计实现亏损：{total_loss_local} {currency}",
        "",
        "📊 税务影响：",
        f"  • 预估节税：{savings_local} {currency}",
        f"  • Wash Sale：{wash_note}",
        "",
        "🔄 后续监控：",
        f"  • 已更新监控清单，后续将跟踪新持仓 ({', '.join(buy_assets)}) 的盈亏情况。",
        "  • Demo 恢复：将在 20 秒后继续推进剩余天的增量扫描。",
    ]
    if step_hash:
        msg_parts.extend(["", f"🔐 可信证明：step_hash={step_hash}"])
    print("\n".join(msg_parts))

    # --- Transition state: resume scanning ---
    state.update({
        "phase": "ready_to_scan",
        "pending_assets": [],
        "total_harvestable_loss": None,
        "estimated_tax_savings": None,
    })
    _save_agent_state(state)
    _run_demo_cron("schedule-scan", "--delay", "20s")


def scene_archive() -> str:
    banner("📅 Q1 季度归档", "─")
    print("  🔔 Cron veritax-quarterly-archive 触发")
    return run_claw(
        [str(SCANNER_PY), "--mode=archive", "--json"],
        env_overrides={"SCANNER_DEMO_PATH": str(DEMO_DATASET)},
        label="Scanner --mode=archive (Merkle → IPFS)",
    )


def scene_cm_daily(jurisdiction: str = "japan") -> None:
    """CM-2: Stateful daily cycle — one call = one day.

    OKX Edition: uses 'trades'/'earn_records' for merge.
    """
    state = _load_cm_state()
    day = state.get("current_day", 1)

    if day > 5:
        print(json.dumps({
            "status": "complete",
            "message": "Demo 数据已用完，演示结束",
        }, ensure_ascii=False))
        return

    banner(f"📅 CM-2 Day {day} — 自动循环", "─")

    # Step 1: Daily incremental scan
    scan_out = scene_daily(day)

    # Step 1.5: Merge incremental batch into tax_dataset.json
    dataset_path = DEMO_DATA_DIR / "tax_dataset.json"
    batch_file = SCENARIOS_DIR / f"day{day}_batch.json"
    if dataset_path.exists() and batch_file.exists():
        with open(dataset_path, "r", encoding="utf-8") as f:
            ds = json.load(f)
        with open(batch_file, "r", encoding="utf-8") as f:
            batch = json.load(f)
        data = ds.get("data", {})
        # OKX Edition: unified field names
        for key in ("trades", "earn_records", "deposits", "withdrawals"):
            data.setdefault(key, []).extend(batch.get(key, []))
        ds["data"] = data
        with open(dataset_path, "w", encoding="utf-8") as f:
            json.dump(ds, f, ensure_ascii=False)

    # Step 2: Monitor
    _daily, monitor_scene = _CM_DAY_SCHEDULE[day]
    if monitor_scene == "trigger":
        monitor_out = scene_trigger()
    elif day >= 4:
        monitor_out = scene_monitor_post_tlh(day)
    else:
        monitor_out = scene_monitor(day)

    # Step 3: Daily digest
    digest_out = run_claw(
        [str(COMPLIANCE_PY), f"--dataset={dataset_path}",
         f"--jurisdiction={jurisdiction}", "--mode=daily-digest", "--json"],
        label="Compliance --mode=daily-digest",
    )

    # Advance state
    state["current_day"] = day + 1
    _save_cm_state(state)

    print(f"\n  📊 cm-daily Day {day} 完成，下次执行将运行 Day {day + 1}")

    # --- Build pre-formatted USER_MESSAGE for agent relay ---
    scan_json = _extract_json(scan_out or "")
    monitor_json = _extract_json(monitor_out or "")
    digest_json = _extract_json(digest_out or "")

    new_records = scan_json.get("new_records", "?") if scan_json else "?"
    currency = digest_json.get("currency", "JPY") if digest_json else "JPY"

    triggered = monitor_json.get("triggered", []) if monitor_json else []
    if triggered:
        monitor_status = f"⚠️ triggered ({len(triggered)}个标的)"
    else:
        monitor_status = "✅ all_clear"

    positions_lines = []
    if digest_json:
        for pos in digest_json.get("top_positions", []):
            positions_lines.append(
                f"  • {pos['asset']}: {pos['units']} (成本 {pos['cost_basis']} {currency})"
            )
    positions_text = "\n".join(positions_lines) if positions_lines else "  • (无数据)"

    realized = digest_json.get("realized_gain", "?") if digest_json else "?"
    futures = digest_json.get("futures_pnl", "0") if digest_json else "0"
    est_tax = digest_json.get("estimated_tax", "?") if digest_json else "?"
    step_hash = digest_json.get("step_hash", "????????") if digest_json else "????????"

    ledger_parts = [f"累计已实现收益：{realized}"]
    try:
        if futures and float(futures) != 0:
            ledger_parts.append(f"期货损益：{futures}")
    except (ValueError, TypeError):
        pass
    ledger_parts.append(f"预估税额：{est_tax}")
    ledger_line = " | ".join(ledger_parts)

    sim_date = datetime(2026, 3, 28) + timedelta(days=day)
    date_str = f"{sim_date.year}年{sim_date.month}月{sim_date.day}日"
    msg = (
        f"📅 Day {day} — {date_str}（模拟时间 02:00 UTC）\n"
        f"\n"
        f"📊 增量扫描：新增 {new_records} 笔交易记录\n"
        f"📈 监控状态：{monitor_status}\n"
        f"💰 持仓快照：\n"
        f"{positions_text}\n"
        f"🧾 {ledger_line}\n"
        f"🔐 可信证明：step_hash={step_hash}"
    )

    print("\n===USER_MESSAGE_START===")
    print(msg)
    print("===USER_MESSAGE_END===")


def scene_summary() -> None:
    banner("🦞 Demo 完成！Continuous Mode 全流程展示完毕")
    print("  ✅ Scene 0:     初始全量扫描（Flash exec）")
    print("  ✅ Step 1:      Pro 合规分析 + 监控初始化（sessions_spawn Pro）")
    print("  ✅ Day 1-3:     每日增量扫描 × 3 + 监控轮询 × 2（Flash exec）")
    print("  ✅ Scene 6:     TLH 阈值触发！ETH -22% 闪崩（Flash detect）")
    print("  ✅ Step 6:      Pro TLH 决策 — 亏损确认 + 税务影响（sessions_spawn Pro）")
    print("  ✅ Scene 7:     Q1 季度归档 → Merkle Tree → IPFS（Flash exec）")
    print()
    print(f"  📁 归档数据：{DEMO_DATA_DIR}")
    if DEMO_DATA_DIR.exists():
        print("  📁 生成文件：")
        for p in sorted(DEMO_DATA_DIR.rglob("*")):
            if p.is_file():
                rel = p.relative_to(DEMO_DATA_DIR)
                size = p.stat().st_size
                print(f"      {rel}  ({size:,} bytes)")


# ═══════════════════════════════════════════════════════
# Full auto demo (CLI debugging only)
# ═══════════════════════════════════════════════════════

def run_demo(speed: float = 1.0) -> None:
    """Execute the full time-compressed demo."""
    reset_demo()

    banner("🦞 VeriTax Continuous Mode Demo — 时间压缩演示 (OKX Edition)")
    print("  模拟时间：2026年3月28日 → 4月1日（4天 → ~5分钟）")
    print(f"  速度倍率：{speed}x")
    print(f"  数据目录：{DEMO_DATA_DIR}")
    print(f"  场景目录：{SCENARIOS_DIR}")

    dataset_path = DEMO_DATA_DIR / "tax_dataset.json"

    # ─── Scene 0: March 28 — Initial Full Scan + Compliance Baseline ───
    banner("📅 Scene 0: 3月28日 — 初始全量扫描 + 合规基线", "─")
    print("  📊 加载 Demo 合成数据（2026年交易记录 → 基线数据集）")
    run_claw(
        [str(SCANNER_PY), f"--demo={DEMO_DATASET}", f"--output={dataset_path}"],
        label="Scanner --demo --output (加载2026年合成数据)",
    )

    scene_pause(3, speed, "合规引擎计算中（Pro 模型）...")
    print("  📡 sessions_spawn(Pro) — 日本税法合规计算")
    run_claw(
        [str(COMPLIANCE_PY), f"--dataset={dataset_path}", "--jurisdiction=japan"],
        label="Compliance --jurisdiction=japan (基线合规报告)",
    )

    # ─── Scene 1: March 29 — Incremental Scan (3 new trades) ───
    scene_pause(5, speed, "模拟到 3月29日 02:00 UTC...")
    banner("📅 Scene 1: 3月29日 — 每日增量扫描", "─")
    print("  🔔 Cron veritax-daily-scan 触发")
    run_claw(
        [str(SCANNER_PY), "--mode=incremental", "--json"],
        env_overrides={"VERITAX_DEMO_BATCH": str(SCENARIOS_DIR / "day1_batch.json")},
        label="Scanner --mode=incremental",
    )

    # ─── Scene 2: March 29 — Monitor Check (all clear) ───
    scene_pause(8, speed, "模拟到 3月29日 08:00 UTC...")
    banner("📅 Scene 2: 3月29日 — TLH 监控轮询", "─")
    print("  🔔 Cron veritax-monitor 触发")
    day1_px = PRICE_SERIES.get("day1", {})
    run_claw(
        [str(OPTIMIZER_PY), "--mode=monitor", "--jurisdiction=japan",
         "--config", str(SCENARIOS_DIR / "monitor_config.json"), "--json"],
        env_overrides={
            "VERITAX_DEMO_BALANCES": json.dumps(day1_px.get("balances", {})),
            "VERITAX_DEMO_PRICES": json.dumps(day1_px.get("prices", {})),
        },
        label="Optimizer --mode=monitor",
    )

    # ─── Scene 3: March 30 — Incremental Scan ───
    scene_pause(10, speed, "模拟到 3月30日 02:00 UTC...")
    banner("📅 Scene 3: 3月30日 — 每日增量扫描", "─")
    print("  🔔 Cron veritax-daily-scan 触发")
    run_claw(
        [str(SCANNER_PY), "--mode=incremental", "--json"],
        env_overrides={"VERITAX_DEMO_BATCH": str(SCENARIOS_DIR / "day2_batch.json")},
        label="Scanner --mode=incremental",
    )

    # ─── Scene 4: March 30 — Monitor Check (ETH dips, still OK) ───
    scene_pause(8, speed, "模拟到 3月30日 14:00 UTC...")
    banner("📅 Scene 4: 3月30日 — TLH 监控轮询", "─")
    print("  🔔 Cron veritax-monitor 触发")
    day2_px = PRICE_SERIES.get("day2", {})
    run_claw(
        [str(OPTIMIZER_PY), "--mode=monitor", "--jurisdiction=japan",
         "--config", str(SCENARIOS_DIR / "monitor_config.json"), "--json"],
        env_overrides={
            "VERITAX_DEMO_BALANCES": json.dumps(day2_px.get("balances", {})),
            "VERITAX_DEMO_PRICES": json.dumps(day2_px.get("prices", {})),
        },
        label="Optimizer --mode=monitor",
    )

    # ─── Scene 5: March 31 — Incremental Scan ───
    scene_pause(10, speed, "模拟到 3月31日 02:00 UTC...")
    banner("📅 Scene 5: 3月31日 — 每日增量扫描", "─")
    print("  🔔 Cron veritax-daily-scan 触发")
    run_claw(
        [str(SCANNER_PY), "--mode=incremental", "--json"],
        env_overrides={"VERITAX_DEMO_BATCH": str(SCENARIOS_DIR / "day3_batch.json")},
        label="Scanner --mode=incremental",
    )

    # ─── Scene 6: March 31 — Monitor TRIGGERS! ETH crash ───
    scene_pause(8, speed, "模拟到 3月31日 14:00 UTC — ETH 闪崩！")
    banner("📅 Scene 6: 3月31日 — ⚠️ TLH 阈值触发！", "─")
    print("  🔔 Cron veritax-monitor 触发")
    print("  💥 ETH 价格暴跌 -22%！从 $2080 → $1620")
    crash_px = PRICE_SERIES.get("day3_crash", {})
    run_claw(
        [str(OPTIMIZER_PY), "--mode=monitor", "--jurisdiction=japan",
         "--config", str(SCENARIOS_DIR / "monitor_config.json"), "--json"],
        env_overrides={
            "VERITAX_DEMO_BALANCES": json.dumps(crash_px.get("balances", {})),
            "VERITAX_DEMO_PRICES": json.dumps(crash_px.get("prices", {})),
        },
        label="Optimizer --mode=monitor (CRASH PRICES)",
    )

    # ─── Scene 6b: TLH Decision (Pro model — REAL analyze call) ───
    scene_pause(5, speed, "⚡ Flash 检测到阈值突破 → 升级 Pro 模型决策...")
    banner("🧠 Scene 6b: Pro 模型 TLH 决策", "─")
    print("  📡 sessions_spawn(Pro) — 亏损持续性 + Wash Sale + 替代标的 + 税务影响")
    crash_prices = crash_px.get("prices", {})
    run_claw(
        [str(OPTIMIZER_PY), "--mode=analyze",
         f"--dataset={dataset_path}",
         "--jurisdiction=japan",
         f"--prices={json.dumps(crash_prices)}"],
        label="Optimizer --mode=analyze (Pro 决策 — crash prices)",
    )

    # ─── Scene 6c: TLH Execution (simulated) ───
    scene_pause(3, speed, "模拟 TLH 执行...")
    banner("⚡ Scene 6c: TLH 执行（模拟）", "─")
    print("  📱 → TG 推送：\"🦞 主人！发现 TLH 机会！ETH 未实现亏损 -$3,910 (-22%)\"")
    print("  📱 → TG 推送：\"推荐替代标的：stETH / WETH (同板块 L1)\"")
    print("  📱 → TG 推送：\"预估省税：$782 (日本税率 20.315%)\"")
    print()
    print("  👤 用户回复：确认执行")
    print()
    print("  🏦 [Demo] OKX Spot 模拟执行:")
    print("    Step A: SELL 8.5 ETH @ $1,620 → 实现亏损 -$3,910")
    print("    Step B: BUY equivalent stETH @ $1,620 (替代标的)")
    print("    Step C: execute_tlh() 成本基础更新")
    print("    Step D: monitor_config.json positions 更新")
    print("    Step E: TG 通知 + 执行记录归档")
    print()
    print("  ✅ TLH 模拟执行完成（真实交易需用户在 TG 中逐步确认）")
    print("  📝 Wash sale cooldown: N/A（日本无 wash sale 规则）")

    # ─── Scene 7: April 1 — Quarterly Archive ───
    scene_pause(10, speed, "模拟到 4月1日 03:00 UTC — 季度归档触发！")
    banner("📅 Scene 7: 4月1日 — Q1 季度归档", "─")
    print("  🔔 Cron veritax-quarterly-archive 触发")
    run_claw(
        [str(SCANNER_PY), "--mode=archive", "--json"],
        env_overrides={"SCANNER_DEMO_PATH": str(DEMO_DATASET)},
        label="Scanner --mode=archive (Merkle → IPFS)",
    )

    # ─── Summary ───
    banner("🦞 Demo 完成！Continuous Mode 全流程展示完毕 (OKX Edition)")
    print("  ✅ Scene 0:     初始全量扫描 + 合规基线报告（Pro）")
    print("  ✅ Scene 1-3,5: 每日增量扫描 × 3 次（共检测 9 笔新交易）")
    print("  ✅ Scene 2,4:   TLH 监控轮询 × 2 次（all clear）")
    print("  ✅ Scene 6:     TLH 阈值触发！ETH -22% 闪崩")
    print("  ✅ Scene 6b:    Pro 决策 — 真实 analyze 计算（亏损 + 税务影响）")
    print("  ✅ Scene 6c:    TLH 执行模拟（卖出 + 替代买入 + 状态更新）")
    print("  ✅ Scene 7:     Q1 季度归档 → Merkle Tree → IPFS")
    print()
    print(f"  📁 归档数据：{DEMO_DATA_DIR}")
    print("  📁 查看生成文件：")

    for p in sorted(DEMO_DATA_DIR.rglob("*")):
        if p.is_file():
            rel = p.relative_to(DEMO_DATA_DIR)
            size = p.stat().st_size
            print(f"      {rel}  ({size:,} bytes)")


# ═══════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════

SCENE_MAP = {
    "reset": scene_reset,
    "scan0": scene_scan0,
    "state-start": None,
    "state-show": scene_state_show,
    "state-monitoring": None,
    "state-awaiting-confirmation": None,
    "state-clear": scene_state_clear,
    "scan-tick": None,
    "monitor-tick": None,
    "archive-tick": scene_archive_tick,
    "daily1": lambda: scene_daily(1),
    "daily2": lambda: scene_daily(2),
    "daily3": lambda: scene_daily(3),
    "daily4": lambda: scene_daily(4),
    "daily5": lambda: scene_daily(5),
    "monitor1": lambda: scene_monitor(1),
    "monitor2": lambda: scene_monitor(2),
    "trigger": scene_trigger,
    "cm-analyze": scene_cm_analyze,
    "monitor4": lambda: scene_monitor_post_tlh(4),
    "monitor5": lambda: scene_monitor_post_tlh(5),
    "execute": None,
    "archive": scene_archive,
    "summary": scene_summary,
    "cm-daily": None,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="VeriTax Demo Director (OKX Edition)")
    parser.add_argument("--reset", action="store_true", help="Clear demo state only")
    parser.add_argument("--speed", type=float, default=9999.0, help="Speed multiplier (default: instant)")
    parser.add_argument("--scene", type=str, default=None,
                        help="Run a single scene: reset|scan0|daily1-5|monitor1-5|trigger|execute|archive|summary|cm-daily")
    parser.add_argument("--jurisdiction", type=str, default="japan",
                        choices=["japan", "australia", "canada", "singapore", "taiwan"],
                        help="Jurisdiction for cm-daily scene (default: japan)")
    parser.add_argument("--to", type=str, default=None,
                        help="Optional explicit outbound destination for demo cron delivery")
    parser.add_argument("--actions", type=str, default=None,
                        help='JSON list of asset symbols for execute scene, e.g. \'["ETH","AVAX","SOL"]\'')
    parser.add_argument("--step-hash", type=str, default=None,
                        help="Optional step_hash for durable demo state scenes")
    parser.add_argument("--full-auto", action="store_true",
                        help="Run full demo in auto mode (CLI debugging only, NOT for agent use)")
    args = parser.parse_args()

    if args.reset:
        reset_demo()
        return 0

    if args.scene:
        if args.scene not in SCENE_MAP:
            print(f"❌ Unknown scene: {args.scene}")
            print(f"   Available: {', '.join(SCENE_MAP.keys())}")
            return 1
        if args.scene == "cm-daily":
            scene_cm_daily(jurisdiction=args.jurisdiction)
        elif args.scene == "scan-tick":
            scene_scan_tick(jurisdiction=args.jurisdiction)
        elif args.scene == "monitor-tick":
            scene_monitor_tick(jurisdiction=args.jurisdiction)
        elif args.scene == "state-start":
            scene_state_start(jurisdiction=args.jurisdiction, route_to=args.to)
        elif args.scene == "state-monitoring":
            scene_state_monitoring(jurisdiction=args.jurisdiction)
        elif args.scene == "state-awaiting-confirmation":
            scene_state_awaiting_confirmation(
                jurisdiction=args.jurisdiction,
                actions_json=args.actions,
                step_hash=args.step_hash,
            )
        elif args.scene == "execute":
            scene_execute(actions_json=args.actions, jurisdiction=args.jurisdiction)
        else:
            SCENE_MAP[args.scene]()
        return 0

    if args.full_auto:
        run_demo(speed=args.speed)
        return 0

    print("❌ 请使用 --scene 参数指定场景，或 --reset 清理状态。")
    print(f"   可用场景: {', '.join(SCENE_MAP.keys())}")
    print("   示例: python demo_director.py --scene scan0")
    print("   完整自动模式: python demo_director.py --full-auto (仅限 CLI 调试)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
