#!/usr/bin/env python3
"""OptimizerClaw — TLH (Tax-Loss Harvesting) Strategy Engine — OKX Edition.

Identifies unrealized losses, checks wash sale eligibility,
estimates tax savings, and generates action plans.

OKX adaptations:
  - ATK CLI for balance/order/trade queries
  - okx_onchain_utils for token audit/signal (replaces binance_web3_utils)
  - price_utils uses OKX market ticker (replaces Binance public API)
  - BNB→OKB, BSC→X Layer, Launchpool→Jumpstart/On-chain Earn
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add compliance-claw, scanner-claw, lib to path for reuse
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compliance-claw"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scanner-claw"))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from compliance import load_dataset, load_rule, aggregate_metrics, to_decimal, apply_progressive_tax
from price_utils import fetch_current_prices, fetch_prices_okx
from okx_onchain_utils import (
    query_token_audit,
    query_token_info,
    fetch_trading_signal,
    fetch_market_rank,
    plan_onchain_swap,
    sign_evm_transaction,
    broadcast_transaction,
    track_order,
)
from monitor_config import load_config, save_config, find_position, is_in_wash_sale_cooldown
from lib.atk_client import run as atk_run, ATKError


# Jurisdictions where TLH is applicable
TLH_JURISDICTIONS = {"japan", "australia", "canada"}

# Default chain index for OKX OnchainOS queries (X Layer)
_CHAIN_INDEX = os.getenv("CHAIN_INDEX", "196")
_CHAIN_NAME = os.getenv("CHAIN_NAME", "xlayer")
_ONCHAIN_PREFERRED_FUNDING = ("USDC", "USDT", "OKB", "WETH")
_ONCHAIN_CHAIN_SUBSTITUTES = {"WETH", "stETH", "UNI", "AAVE", "LINK", "JOE", "mSOL", "JitoSOL"}


# ---------------------------------------------------------------------------
# ATK CLI wrappers (replace scanner.fetch_spot_balances / place_spot_order)
# ---------------------------------------------------------------------------

def _fetch_spot_balances(testnet: bool = False, omit_zero: bool = True) -> list[dict]:
    """Fetch spot balances via ATK CLI: okx account balance --json."""
    extra = []
    if testnet:
        extra.append("--demo")
    try:
        data = atk_run("account", "balance", args=extra)
    except ATKError:
        return []
    if data is None:
        return []  # Demo mode

    # ATK returns: {"details": [{"ccy": "BTC", "availBal": "1.5", ...}]}
    details = data.get("details", []) if isinstance(data, dict) else data
    if not isinstance(details, list):
        return []
    results = []
    for d in details:
        ccy = d.get("ccy", "")
        total = to_decimal(d.get("cashBal") or d.get("availBal", "0"))
        if omit_zero and total <= 0:
            continue
        results.append({"asset": ccy, "total": str(total)})
    return results


def _fetch_recent_trades(inst_id: str, start_ms: int, testnet: bool = False) -> list[dict]:
    """Fetch recent fills via ATK CLI: okx trade get-fills --instId ... --json."""
    extra = ["--instId", inst_id]
    if testnet:
        extra.append("--demo")
    try:
        data = atk_run("trade", "get-fills", args=extra)
    except ATKError:
        return []
    if data is None:
        return []
    items = data if isinstance(data, list) else data.get("data", [])
    if not isinstance(items, list):
        return []
    # Filter by timestamp
    result = []
    for item in items:
        ts = int(item.get("ts", 0))
        if ts >= start_ms:
            result.append(item)
    return result


def _place_spot_order(
    inst_id: str,
    side: str,
    quantity: float,
    testnet: bool = False,
) -> dict:
    """Place a spot order via ATK CLI: okx spot place-order --json."""
    extra = [
        "--instId", inst_id,
        "--side", side.lower(),
        "--ordType", "market",
        "--sz", str(quantity),
    ]
    if testnet:
        extra.append("--demo")
    data = atk_run("spot", "place-order", args=extra)
    return data or {}


# ---------------------------------------------------------------------------
# TLH Core Functions
# ---------------------------------------------------------------------------

def scan_unrealized_losses(
    acb_positions: list[dict],
    prices: dict[str, Decimal],
    threshold: float = 100,
) -> list[dict]:
    """Identify positions with unrealized losses exceeding threshold.

    Args:
        acb_positions: From aggregate_metrics() — [{asset, units, cost, acb_per_unit}].
        prices: Current market prices in USD — {asset: Decimal}.
        threshold: Minimum absolute loss in USD to include.

    Returns:
        List of loss candidates sorted by loss (largest first).
    """
    candidates = []
    for pos in acb_positions:
        asset = pos["asset"]
        units = to_decimal(pos["units"])
        cost = to_decimal(pos["cost"])
        if units <= 0:
            continue
        current_price = prices.get(asset, Decimal("0"))
        if current_price <= 0:
            continue
        market_value = units * current_price
        pnl = market_value - cost
        if pnl >= 0:
            continue  # Not a loss
        if abs(pnl) < Decimal(str(threshold)):
            continue  # Below threshold
        candidates.append({
            "asset": asset,
            "units": str(units),
            "cost_basis": str(cost),
            "acb_per_unit": pos.get("acb_per_unit", "0"),
            "current_price": str(current_price),
            "market_value": str(market_value),
            "unrealized_pnl": str(pnl),
            "pnl_pct": str((pnl / cost * Decimal("100")).quantize(Decimal("0.01"))) if cost > 0 else "0",
        })
    candidates.sort(key=lambda x: to_decimal(x["unrealized_pnl"]))
    return candidates


def check_wash_sale(jurisdiction: str, rule: dict) -> dict:
    """Check wash sale / anti-avoidance rules for a jurisdiction."""
    if jurisdiction == "japan":
        return {
            "eligible": True,
            "restriction": "none",
            "cooldown_days": 0,
            "warning": None,
            "note": "日本には wash sale rule なし。即時回購可能。",
        }
    if jurisdiction == "australia":
        anti = rule.get("anti_avoidance", {})
        return {
            "eligible": True,
            "restriction": "substance_over_form",
            "cooldown_days": 0,
            "warning": anti.get("note", "ATO Part IVA anti-avoidance may apply to wash sales."),
            "note": "ATO does not have a formal wash sale rule, but Part IVA general anti-avoidance provisions apply. Use substitute assets recommended.",
        }
    if jurisdiction == "canada":
        days = rule.get("rules", {}).get("superficial_loss_days", 30)
        return {
            "eligible": False,
            "restriction": "superficial_loss",
            "cooldown_days": days,
            "warning": f"ITA s.54: loss denied if same property reacquired within {days} days. Use substitute asset or wait {days} days.",
            "note": f"Superficial loss rule: {days}-day cooldown or use non-identical substitute asset.",
        }
    return {"eligible": False, "restriction": "unknown", "cooldown_days": 0, "warning": "Unknown jurisdiction"}


def check_pre_sale_window(jurisdiction: str, asset: str, days: int = 30) -> dict:
    """Check Canada superficial loss pre-sale window.

    For Canada: checks if the same asset was bought within the last 30 days.
    If so, selling now would trigger superficial loss rule.
    """
    if jurisdiction.lower() not in ("canada", "ca"):
        return {"has_recent_buy": False, "trades_found": 0, "warning": None}

    import time

    inst_id = f"{asset}-USDT"
    now_ms = int(time.time() * 1000)
    window_start_ms = now_ms - (days * 24 * 60 * 60 * 1000)

    try:
        recent_trades = _fetch_recent_trades(inst_id, window_start_ms, testnet=False)
        recent_buys = [t for t in recent_trades if str(t.get("side", "")).lower() == "buy"]
    except Exception:
        return {"has_recent_buy": False, "trades_found": 0, "warning": "Failed to check pre-sale window"}

    if recent_buys:
        return {
            "has_recent_buy": True,
            "trades_found": len(recent_buys),
            "warning": f"⚠ Superficial loss: {len(recent_buys)} buy(s) of {asset} in last {days} days. "
                       f"Selling now may trigger ITA §54 denial. Consider waiting or using substitute.",
        }
    return {"has_recent_buy": False, "trades_found": 0, "warning": None}


def estimate_tax_savings(
    total_harvestable_loss: Decimal,
    jurisdiction: str,
    rule: dict,
) -> dict:
    """Estimate tax savings from harvesting losses."""
    if total_harvestable_loss >= 0:
        return {"estimated_tax_reduction": "0", "marginal_rate": "0", "note": "No losses to harvest."}

    loss = abs(total_harvestable_loss)

    if jurisdiction == "japan":
        surcharges = rule.get("surcharges", {})
        resident_rate = to_decimal(surcharges.get("resident_tax_rate", "0.10"))
        reconstruction_rate = to_decimal(surcharges.get("reconstruction_surcharge_rate", "0.021"))
        brackets = rule.get("tax_brackets", [])
        top_rate = to_decimal(brackets[-1].get("rate", "0.45")) if brackets else Decimal("0.45")
        effective = top_rate * (Decimal("1") + reconstruction_rate) + resident_rate
        reduction = loss * effective
        return {
            "estimated_tax_reduction": str(reduction.quantize(Decimal("0.01"))),
            "marginal_rate": str(effective),
            "note": f"Marginal: income_tax {top_rate} × (1+{reconstruction_rate}) + resident {resident_rate} = {effective}. Actual savings depend on your total income bracket.",
        }

    if jurisdiction == "australia":
        medicare = to_decimal(rule.get("rates", {}).get("medicare_levy", "0.02"))
        marginal = Decimal("0.30")
        effective = marginal + medicare
        reduction = loss * effective
        return {
            "estimated_tax_reduction": str(reduction.quantize(Decimal("0.01"))),
            "marginal_rate": str(effective),
            "note": f"Estimated at {marginal} marginal rate + {medicare} Medicare levy. Actual depends on total income.",
        }

    if jurisdiction == "canada":
        inclusion = to_decimal(rule.get("rates", {}).get("inclusion_rate", "0.5"))
        marginal = Decimal("0.205")
        taxable_loss = loss * inclusion
        reduction = taxable_loss * marginal
        return {
            "estimated_tax_reduction": str(reduction.quantize(Decimal("0.01"))),
            "marginal_rate": str(marginal),
            "inclusion_rate": str(inclusion),
            "taxable_loss_after_inclusion": str(taxable_loss),
            "note": f"Loss × {inclusion} inclusion × {marginal} federal marginal. Provincial tax savings additional.",
        }

    return {"estimated_tax_reduction": "0", "marginal_rate": "0", "note": "Unknown jurisdiction"}


# Substitute asset mapping for same-sector exposure without triggering wash sale
_SUBSTITUTES = {
    "BTC": ["WBTC", "BTCB"],
    "ETH": ["stETH", "WETH"],
    "SOL": ["JitoSOL", "mSOL"],
    "OKB": ["UNI", "AAVE"],
    "AVAX": ["JOE", "GMX"],
    "MATIC": ["AAVE", "LINK"],
}


_PLAN_BLUEPRINTS = {
    "spot_substitute": {
        "title": "现货替代保持敞口",
        "description": "卖出亏损现货，换入同赛道非同质替代资产，尽量保持市场敞口。",
        "modules": ["account", "market", "spot"],
        "complexity": "low",
        "execution_readiness": "ready_now",
    },
    "derivatives_hedge": {
        "title": "衍生品对冲保持敞口",
        "description": "卖出现货完成 TLH 后，用期权或永续合约维持方向性暴露。",
        "modules": ["account", "market", "swap", "futures", "option"],
        "complexity": "medium",
        "execution_readiness": "proposal_only",
    },
    "yield_deployment": {
        "title": "税后资金收益部署",
        "description": "TLH 完成后将部分资金部署到 Earn / DCD，提高空闲资金效率。",
        "modules": ["account", "market", "earn", "bot.grid"],
        "complexity": "medium",
        "execution_readiness": "proposal_only",
    },
}


def suggest_substitutes(asset: str) -> list[str]:
    """Suggest substitute assets to maintain sector exposure after selling.

    Attempts OKX OnchainOS Skills (okx-security token-scan, okx-dex-token) for
    real-time safety screening. Falls back to static mapping when unavailable.
    """
    candidates = _SUBSTITUTES.get(asset.upper(), [])
    if not candidates:
        return []

    # Try to filter via OKX OnchainOS audit (graceful fallback)
    safe = []
    for sub in candidates:
        audit = query_token_audit(_CHAIN_INDEX, sub)
        if audit.get("source") == "okx-onchainos":
            if audit.get("is_safe") is True:
                safe.append(sub)
        else:
            # API unavailable — include all static candidates
            safe.append(sub)
    return safe if safe else candidates


def _extract_onchain_context(loaded: dict, args=None) -> dict:
    """Collect minimal wallet and holdings context required for OnChainOS execution."""
    root_onchain = loaded.get("onchain", {}) if isinstance(loaded, dict) else {}
    data = loaded.get("data", {}) if isinstance(loaded, dict) else {}
    wallet_address = (
        getattr(args, "onchain_wallet_address", None)
        or os.getenv("VERITAX_ONCHAIN_WALLET_ADDRESS")
        or root_onchain.get("address")
    )
    chain_index = (
        getattr(args, "onchain_chain_index", None)
        or os.getenv("CHAIN_INDEX")
        or root_onchain.get("chainId")
        or _CHAIN_INDEX
    )
    chain_name = (
        getattr(args, "onchain_chain", None)
        or os.getenv("CHAIN_NAME")
        or _CHAIN_NAME
    )
    rpc_url = getattr(args, "onchain_rpc_url", None) or os.getenv("VERITAX_ONCHAIN_RPC_URL")
    holdings = data.get("onchain_holdings", []) if isinstance(data, dict) else []
    return {
        "wallet_address": wallet_address,
        "chain_index": str(chain_index),
        "chain": chain_name,
        "rpc_url": rpc_url,
        "holdings": holdings if isinstance(holdings, list) else [],
    }


def _pick_onchain_funding_asset(onchain_context: dict, target_value_usd: Decimal) -> dict | None:
    """Pick a funded on-chain asset that can finance the substitute purchase."""
    best = None
    for symbol in _ONCHAIN_PREFERRED_FUNDING:
        for holding in onchain_context.get("holdings", []):
            holding_symbol = str(holding.get("symbol") or holding.get("asset") or "").upper()
            if holding_symbol != symbol:
                continue
            raw_amount = holding.get("amount") or holding.get("balance") or holding.get("quantity") or "0"
            amount = to_decimal(raw_amount)
            if amount <= 0:
                continue
            price = to_decimal(holding.get("price") or holding.get("priceUsd") or "1")
            usd_value = amount * price
            if usd_value <= 0:
                continue
            candidate = {
                "symbol": holding_symbol,
                "amount": str(amount),
                "price": str(price),
                "usd_value": str(usd_value),
                "token_address": holding.get("tokenAddress") or holding.get("contractAddress"),
            }
            if usd_value >= target_value_usd:
                return candidate
            if best is None or usd_value > to_decimal(best["usd_value"]):
                best = candidate
    return best


def _build_onchain_substitute_option(substitutes: list[str], onchain_context: dict, gross_proceeds: Decimal) -> dict | None:
    """Create an optional on-chain substitute recommendation when wallet funding exists."""
    if not onchain_context.get("wallet_address"):
        return None

    funded_asset = _pick_onchain_funding_asset(onchain_context, gross_proceeds)
    if not funded_asset:
        return None

    for substitute in substitutes:
        if substitute not in _ONCHAIN_CHAIN_SUBSTITUTES:
            continue
        return {
            "asset": substitute,
            "chain": onchain_context.get("chain", _CHAIN_NAME),
            "chain_index": onchain_context.get("chain_index", _CHAIN_INDEX),
            "wallet_address": onchain_context.get("wallet_address"),
            "funding_asset": funded_asset["symbol"],
            "funding_available": funded_asset["amount"],
            "estimated_budget_usd": str(min(gross_proceeds, to_decimal(funded_asset["usd_value"]))),
            "execution_mode": "okx_onchainos",
            "note": f"若链上钱包已有 {funded_asset['symbol']} 流动性，可在 {_CHAIN_NAME} 上用 OnChainOS 直接换入 {substitute}。",
        }
    return None


def _rank_label(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 70:
        return "medium"
    return "low"


def _build_strategy_plans(
    losses: list[dict],
    jurisdiction: str,
    wash_sale: dict,
    config: dict | None = None,
) -> list[dict]:
    """Build ranked TLH strategy plans without affecting execute-mode compatibility."""
    if not losses:
        return []

    asset_rows = []
    for loss in losses:
        asset = loss["asset"]
        substitutes = suggest_substitutes(asset)
        if config:
            pos = find_position(config, asset)
            blacklist = pos.get("substitute_blacklist", []) if pos else []
            substitutes = [s for s in substitutes if s not in blacklist]
        asset_rows.append({
            "asset": asset,
            "unrealized_pnl": loss["unrealized_pnl"],
            "pnl_pct": loss["pnl_pct"],
            "substitutes": substitutes[:2],
        })

    plans = []

    spot_score = 88
    if jurisdiction == "canada":
        spot_score = 82
    if wash_sale.get("restriction") == "substance_over_form":
        spot_score = 84
    plans.append({
        "plan_id": "spot_substitute",
        **_PLAN_BLUEPRINTS["spot_substitute"],
        "score": spot_score,
        "jurisdiction_fit": _rank_label(spot_score),
        "exposure_retention": "high",
        "rationale": {
            "jurisdiction": "优先满足当前辖区的 TLH 合规边界，并通过非同质替代资产维持主要市场暴露。",
            "execution": "完全兼容当前 VeriTax execute 路径，可直接落到现货卖出加替代买入。",
        },
        "candidate_assets": asset_rows,
    })

    hedge_score = 74 if jurisdiction in {"australia", "canada"} else 79
    hedge_title = "期权对冲保持敞口" if jurisdiction == "japan" else _PLAN_BLUEPRINTS["derivatives_hedge"]["title"]
    hedge_desc = "卖出现货后用 call 或低杠杆永续维持上行参与度。" if jurisdiction == "japan" else _PLAN_BLUEPRINTS["derivatives_hedge"]["description"]
    plans.append({
        "plan_id": "derivatives_hedge",
        **_PLAN_BLUEPRINTS["derivatives_hedge"],
        "title": hedge_title,
        "description": hedge_desc,
        "score": hedge_score,
        "jurisdiction_fit": _rank_label(hedge_score),
        "exposure_retention": "very_high",
        "rationale": {
            "jurisdiction": "适合需要更强敞口连续性的用户，但必须先通过辖区规则校验后再执行。",
            "execution": "当前阶段作为 Pro 推荐方案输出，不进入默认自动执行路径。",
        },
        "candidate_assets": asset_rows,
    })

    yield_score = 68 if jurisdiction == "canada" else 72
    plans.append({
        "plan_id": "yield_deployment",
        **_PLAN_BLUEPRINTS["yield_deployment"],
        "score": yield_score,
        "jurisdiction_fit": _rank_label(yield_score),
        "exposure_retention": "medium",
        "rationale": {
            "jurisdiction": "更适合 TLH 完成后的资金管理，而不是替代主策略。",
            "execution": "当前阶段仅作推荐，不替代核心 TLH 动作。",
        },
        "candidate_assets": asset_rows,
    })

    plans.sort(key=lambda item: item["score"], reverse=True)
    for index, plan in enumerate(plans, start=1):
        plan["rank"] = index
    return plans


def build_tlh_plan(
    losses: list[dict],
    wash_sale: dict,
    savings: dict,
    jurisdiction: str,
    config: dict | None = None,
    onchain_context: dict | None = None,
) -> dict:
    """Build a complete TLH action plan with per-asset actions."""
    actions = []
    for loss in losses:
        asset = loss["asset"]
        subs = suggest_substitutes(asset)
        if config:
            pos = find_position(config, asset)
            blacklist = pos.get("substitute_blacklist", []) if pos else []
            subs = [s for s in subs if s not in blacklist]
        action = {
            "action": "SELL",
            "asset": asset,
            "units": loss["units"],
            "unrealized_pnl": loss["unrealized_pnl"],
            "pnl_pct": loss["pnl_pct"],
            "substitutes": subs,
        }
        gross_proceeds = to_decimal(loss["units"]) * to_decimal(loss.get("current_price", "0"))
        onchain_option = _build_onchain_substitute_option(subs, onchain_context or {}, gross_proceeds)
        if onchain_option:
            action["onchain_substitute"] = onchain_option
        if wash_sale.get("restriction") == "superficial_loss":
            action["warning"] = f"Wait {wash_sale['cooldown_days']} days before repurchasing {asset}, or use substitute: {', '.join(subs) if subs else 'N/A'}"
        elif wash_sale.get("restriction") == "substance_over_form":
            action["warning"] = "Ensure economic substance — use substitute asset to avoid Part IVA challenge."
        actions.append(action)

    # Jumpstart / On-chain Earn Hook (replaces Binance Launchpool)
    earn_hook = (
        "💡 Earn Tip: After selling loss positions, consider deploying proceeds "
        "into OKX Jumpstart or On-chain Earn for yield while maintaining market exposure. "
        "Use ATK CLI `okx earn` to check active earn products."
    )
    if onchain_context and onchain_context.get("wallet_address"):
        earn_hook += (
            f" If the preferred substitute is on-chain, you can keep demo output unchanged and "
            f"use OKX OnChainOS on {onchain_context.get('chain', _CHAIN_NAME)} for execution."
        )

    # Trading signal check (OKX OnchainOS integration)
    timing_note = None
    if losses:
        top_asset = losses[0]["asset"]
        signal = fetch_trading_signal(top_asset)
        if signal.get("source") == "okx-onchainos" and signal.get("signals"):
            timing_note = f"Trading signal data available for {top_asset}. Review before executing."
        elif signal.get("note"):
            timing_note = signal["note"]

    strategy_plans = _build_strategy_plans(losses, jurisdiction, wash_sale, config=config)

    plan = {
        "jurisdiction": jurisdiction,
        "total_harvestable_loss": str(sum(to_decimal(l["unrealized_pnl"]) for l in losses)),
        "estimated_tax_savings": savings.get("estimated_tax_reduction", "0"),
        "wash_sale_status": wash_sale,
        "strategy_plans": strategy_plans,
        "actions": actions,
        "earn_hook": earn_hook,
        "timing_note": timing_note,
        "disclaimer": "This is an estimate only. Consult a qualified tax advisor before executing trades.",
    }
    return plan


def tlh_decision(triggered: list[dict], jurisdiction: str, config: dict) -> dict:
    """TLH decision logic — step3.

    Called by OpenClaw sessions_spawn(Pro) when monitor_check triggers.
    Validates loss persistence, checks wash sale, audits substitutes.
    """
    decisions = []
    rule_dir = Path(__file__).resolve().parent.parent.parent / "rules"
    rule = load_rule(rule_dir, jurisdiction)

    for candidate in triggered:
        symbol = candidate["symbol"]
        pnl = candidate["unrealized_pnl"]
        in_cooldown = candidate.get("wash_sale_cooldown", False)

        if in_cooldown:
            decisions.append({
                "symbol": symbol,
                "action": "skip",
                "reason": f"wash_sale_cooldown active for {symbol}",
            })
            continue

        if jurisdiction.lower() in ("canada", "ca"):
            pre_check = check_pre_sale_window(jurisdiction, symbol)
            if pre_check.get("has_recent_buy"):
                decisions.append({
                    "symbol": symbol,
                    "action": "skip",
                    "reason": pre_check["warning"],
                })
                continue

        pos = find_position(config, symbol)
        sector = pos.get("asset_sector", "") if pos else ""
        blacklist = pos.get("substitute_blacklist", []) if pos else []
        substitutes = suggest_substitutes(symbol)
        substitutes = [s for s in substitutes if s not in blacklist]

        total_loss = Decimal(str(pnl))
        savings = estimate_tax_savings(total_loss, jurisdiction, rule)

        decisions.append({
            "symbol": symbol,
            "action": "recommend_sell",
            "unrealized_pnl": pnl,
            "pnl_pct": candidate.get("pnl_pct"),
            "substitutes": substitutes[:3],
            "estimated_tax_savings": savings.get("estimated_tax_reduction", "0"),
            "sector": sector,
        })

    return {
        "ok": True,
        "step": "step3_decision",
        "jurisdiction": jurisdiction,
        "decisions": decisions,
        "total_candidates": len(triggered),
        "actionable": len([d for d in decisions if d["action"] == "recommend_sell"]),
        "skipped": len([d for d in decisions if d["action"] == "skip"]),
    }


def update_tlh_state(
    sell_asset: str,
    buy_asset: str,
    sell_qty: float,
    sell_price: float,
    buy_price: float,
    loss_amount: float,
    jurisdiction: str,
    config: dict,
    config_path=None,
) -> dict:
    """Atomic TLH execution state update (Steps C-E).

    Called AFTER OKX Spot order completes Steps A (sell) and B (buy).
    This function handles Steps C (cost basis), D (config), E (notify).
    """
    from monitor_config import (
        remove_position, upsert_position, add_executed_tlh,
        save_config, make_position_entry,
    )

    now = datetime.now(timezone.utc)
    wash_days = {"ca": 30, "gb": 30}.get(jurisdiction.lower(), 0)
    wash_sale_end = None
    if wash_days > 0:
        from datetime import timedelta
        wash_sale_end = (now + timedelta(days=wash_days)).isoformat()

    try:
        remove_position(config, sell_asset)

        buy_qty = (sell_qty * sell_price) / buy_price if buy_price > 0 else 0

        new_pos = make_position_entry(
            symbol=buy_asset,
            quantity=buy_qty,
            cost_basis_unit=buy_price,
            asset_sector=_get_sector_for_asset(sell_asset, config),
        )
        if wash_sale_end:
            new_pos["wash_sale_cooldown_until"] = wash_sale_end

        upsert_position(config, new_pos)

        add_executed_tlh(config, {
            "symbol": sell_asset,
            "executed_at": now.isoformat(),
            "loss_harvested": loss_amount,
            "substitute": buy_asset,
            "sell_qty": sell_qty,
            "sell_price": sell_price,
            "buy_qty": buy_qty,
            "buy_price": buy_price,
            "wash_sale_end": wash_sale_end,
        })

        save_config(config, config_path)

        msg = (
            f"✅ TLH 执行完成\n"
            f"  卖出: {sell_qty} {sell_asset} @ {sell_price}\n"
            f"  买入: {buy_qty:.6f} {buy_asset} @ {buy_price}\n"
            f"  实现亏损: {loss_amount} USD\n"
        )
        if wash_sale_end:
            msg += f"  Wash sale 冷却至: {wash_sale_end[:10]}\n"
        print(msg)

        return {
            "ok": True,
            "step": "step3.1_executed",
            "sell": {"asset": sell_asset, "qty": sell_qty, "price": sell_price},
            "buy": {"asset": buy_asset, "qty": buy_qty, "price": buy_price},
            "loss_harvested": loss_amount,
            "wash_sale_end": wash_sale_end,
        }

    except Exception as exc:
        config.setdefault("_state_dirty", True)
        try:
            save_config(config, config_path)
        except Exception:
            pass
        print(f"⚠ TLH 状态更新失败: {exc}")
        return {"ok": False, "error": str(exc), "status": "partial_executed"}


def _get_sector_for_asset(asset: str, config: dict) -> str:
    """Get asset sector from config or return empty string."""
    from monitor_config import find_position
    pos = find_position(config, asset)
    return pos.get("asset_sector", "") if pos else ""


# ---------------------------------------------------------------------------
# Monitor Mode
# ---------------------------------------------------------------------------

def monitor_check(args) -> int:
    """Single TLH monitor check cycle.

    Reads monitor_config.json → fetches current spot balances + prices →
    calculates unrealized PnL → compares against thresholds →
    returns triggered candidates (if any).
    """
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    positions = config.get("positions_watch", [])
    if not positions:
        if args.as_json:
            print(json.dumps({"ok": True, "triggered": [], "message": "No positions to monitor."}))
        else:
            print("[Optimizer-Monitor] No positions to monitor.")
        return 0

    # Fetch current spot balances (or load demo overrides)
    demo_balances_env = os.getenv("VERITAX_DEMO_BALANCES", "")
    demo_prices_env = os.getenv("VERITAX_DEMO_PRICES", "")
    demo_mode = os.getenv("VERITAX_DEMO", "") == "1"

    if demo_mode and demo_balances_env:
        try:
            demo_bal = json.loads(demo_balances_env)
            balances = [{"asset": k, "total": str(v)} for k, v in demo_bal.items()]
            print("[Optimizer-Monitor] DEMO balances loaded", flush=True)
        except json.JSONDecodeError:
            print("[Optimizer-Monitor] DEMO balances JSON invalid, falling back to API")
            balances = _fetch_spot_balances(testnet=False, omit_zero=True)
    elif demo_mode:
        print("[Optimizer-Monitor] DEMO: no more price data available. Demo monitoring cycle complete.", flush=True)
        result = {
            "ok": True,
            "mode": "monitor",
            "checked": 0,
            "triggered": [],
            "message": "Demo: no more price data available. Demo monitoring cycle complete.",
        }
        if args.as_json:
            print(json.dumps(result))
        return 0
    else:
        try:
            balances = _fetch_spot_balances(testnet=False, omit_zero=True)
        except Exception as exc:
            print(f"[Optimizer-Monitor] Failed to fetch balances: {exc}")
            return 1

    balance_map = {b["asset"]: float(b["total"]) for b in balances}

    # Fetch current prices for all watched assets (or load demo overrides)
    watched_assets = [p["symbol"] for p in positions]
    if demo_mode and demo_prices_env:
        try:
            demo_px = json.loads(demo_prices_env)
            prices = {k: Decimal(str(v)) for k, v in demo_px.items()}
            print("[Optimizer-Monitor] DEMO prices loaded", flush=True)
        except json.JSONDecodeError:
            print("[Optimizer-Monitor] DEMO prices JSON invalid, falling back to API")
            prices = fetch_prices_okx(watched_assets)
    else:
        prices = fetch_prices_okx(watched_assets)

    # Calculate unrealized PnL and compare thresholds
    triggered = []
    all_clear = []

    for pos in positions:
        symbol = pos["symbol"]
        stored_qty = float(pos.get("quantity", 0))
        cost_unit = Decimal(str(pos.get("cost_basis_unit", 0)))
        threshold_pnl = float(pos.get("tlh_threshold_pnl", -500))
        threshold_pct = float(pos.get("tlh_threshold_pct", -15))

        current_qty = balance_map.get(symbol, 0.0)
        current_price = prices.get(symbol, Decimal("0"))

        if current_price <= 0 or current_qty <= 0:
            all_clear.append({"symbol": symbol, "reason": "no_balance_or_price"})
            continue

        qty_changed = abs(current_qty - stored_qty) > 1e-8

        market_value = current_price * Decimal(str(current_qty))
        cost_total = cost_unit * Decimal(str(current_qty))
        unrealized_pnl = float(market_value - cost_total)
        pnl_pct = (unrealized_pnl / float(cost_total) * 100) if float(cost_total) > 0 else 0.0

        pnl_triggered = unrealized_pnl <= threshold_pnl
        pct_triggered = pnl_pct <= threshold_pct

        if pnl_triggered or pct_triggered:
            in_cooldown = is_in_wash_sale_cooldown(config, symbol)
            triggered.append({
                "symbol": symbol,
                "current_qty": current_qty,
                "current_price": str(current_price),
                "cost_basis_unit": str(cost_unit),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "threshold_pnl": threshold_pnl,
                "threshold_pct": threshold_pct,
                "pnl_triggered": pnl_triggered,
                "pct_triggered": pct_triggered,
                "qty_changed": qty_changed,
                "wash_sale_cooldown": in_cooldown,
            })
        else:
            all_clear.append({"symbol": symbol, "unrealized_pnl": round(unrealized_pnl, 2)})

    # Update last_evaluated
    config["last_evaluated"] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": {
            "checked": len(positions),
            "triggered": len(triggered),
            "all_clear": len(all_clear),
        },
    }
    save_config(config, config_path)

    result = {
        "ok": True,
        "mode": "monitor",
        "checked": len(positions),
        "triggered": triggered,
        "all_clear": all_clear,
    }

    import hashlib as _hl
    result["step_hash"] = _hl.sha256(
        json.dumps(result, sort_keys=True).encode()
    ).hexdigest()

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if triggered:
            print(f"[Optimizer-Monitor] ⚠ {len(triggered)} TLH candidate(s) triggered:")
            for t in triggered:
                cooldown_note = " (WASH SALE COOLDOWN)" if t["wash_sale_cooldown"] else ""
                print(f"  • {t['symbol']}: PnL={t['unrealized_pnl']} USD ({t['pnl_pct']}%){cooldown_note}")
        else:
            print(f"[Optimizer-Monitor] All clear. {len(positions)} positions checked.")

    return 0


# ---------------------------------------------------------------------------
# Execute Mode
# ---------------------------------------------------------------------------

def execute_tlh(args) -> int:
    """Simulate or execute TLH: sell loss assets + buy substitutes."""
    if not args.dataset:
        print("[Optimizer-Execute] error: --dataset is required for execute mode")
        return 1

    price_overrides = None
    if args.prices:
        try:
            price_overrides = json.loads(args.prices)
        except json.JSONDecodeError:
            print("[Optimizer-Execute] error: invalid --prices JSON")
            return 1

    allowed_assets = None
    if args.actions:
        try:
            allowed_assets = set(a.upper() for a in json.loads(args.actions))
        except (json.JSONDecodeError, TypeError):
            print("[Optimizer-Execute] error: invalid --actions JSON (expected list of asset symbols)")
            return 1

    loaded = load_dataset(Path(args.dataset))
    onchain_context = _extract_onchain_context(loaded, args=args)
    rule_dir = Path(__file__).resolve().parent.parent.parent / "rules"
    rule = load_rule(rule_dir, args.jurisdiction)
    cost_method = rule.get("cost_basis_method", "fifo")
    metrics = aggregate_metrics(loaded["data"], cost_basis_method=cost_method)
    acb_positions = metrics.get("acb_positions", [])

    assets = [p["asset"] for p in acb_positions]
    for a in list(assets):
        assets.extend(suggest_substitutes(a))
    assets = list(set(assets))
    prices = fetch_current_prices(assets, overrides=price_overrides)

    losses = scan_unrealized_losses(acb_positions, prices, threshold=args.threshold)

    if allowed_assets is not None:
        losses = [l for l in losses if l["asset"].upper() in allowed_assets]

    if not losses:
        result = {"ok": True, "mode": "execute", "executed": [], "message": "No losses to execute."}
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print("[Optimizer-Execute] No losses to execute.")
        return 0

    config = None
    try:
        config_path = Path(args.config) if args.config else None
        config = load_config(config_path)
    except Exception:
        pass

    sell_assets = {l["asset"].upper() for l in losses}

    executed = []
    for loss in losses:
        asset = loss["asset"]
        qty = float(loss["units"])
        sell_price = float(loss["current_price"])
        realized_loss = float(loss["unrealized_pnl"])

        subs = suggest_substitutes(asset)
        if config:
            pos = find_position(config, asset)
            blacklist = pos.get("substitute_blacklist", []) if pos else []
            subs = [s for s in subs if s not in blacklist]
        subs = [s for s in subs if s.upper() not in sell_assets]
        substitute = subs[0] if subs else "USDT"
        sub_price = float(prices.get(substitute.upper(), Decimal("1"))) if substitute != "USDT" else 1.0
        sub_qty = round((qty * sell_price) / sub_price, 2) if sub_price > 0 else 0
        onchain_option = _build_onchain_substitute_option(
            subs,
            onchain_context,
            Decimal(str(qty)) * Decimal(str(sell_price)),
        )

        entry = {
            "action": "SELL",
            "asset": asset,
            "quantity": qty,
            "price": sell_price,
            "proceeds": round(qty * sell_price, 2),
            "realized_loss": round(realized_loss, 2),
            "substitute": {
                "action": "BUY",
                "asset": substitute,
                "quantity": sub_qty,
                "price": sub_price,
                "cost": round(sub_qty * sub_price, 2),
            },
        }
        if onchain_option:
            entry["onchain_substitute"] = onchain_option

        # Real order placement via OKX ATK CLI
        if getattr(args, "confirm", False):
            testnet = getattr(args, "testnet", False)
            try:
                sell_order = _place_spot_order(
                    inst_id=f"{asset}-USDT", side="sell",
                    quantity=qty, testnet=testnet,
                )
                entry["sell_order"] = sell_order
                actual_sell_price = float(sell_order.get("fillPx", sell_price))
                print(f"[Optimizer-Execute] ✅ SELL {qty} {asset} filled @ {actual_sell_price}", flush=True)
            except Exception as exc:
                entry["sell_order"] = {"error": str(exc)}
                print(f"[Optimizer-Execute] ❌ SELL {asset} failed: {exc}", flush=True)
                executed.append(entry)
                continue

            if substitute != "USDT":
                try:
                    use_onchain = bool(
                        getattr(args, "prefer_onchain_substitute", False)
                        and onchain_option
                        and onchain_context.get("wallet_address")
                        and getattr(args, "onchain_private_key", None)
                    )
                    if use_onchain:
                        budget = min(
                            Decimal(str(entry["proceeds"])),
                            to_decimal(onchain_option["estimated_budget_usd"]),
                        )
                        swap_plan = plan_onchain_swap(
                            funding_token_symbol=onchain_option["funding_asset"],
                            target_symbol=onchain_option["asset"],
                            amount=str(budget),
                            wallet_address=onchain_context["wallet_address"],
                            chain=onchain_context["chain"],
                            chain_index=onchain_context["chain_index"],
                            slippage=getattr(args, "onchain_slippage", None),
                        )
                        entry["onchain_execution"] = swap_plan
                        tx_scan = swap_plan.get("tx_scan", {}) if isinstance(swap_plan, dict) else {}
                        if not swap_plan.get("ok"):
                            raise RuntimeError(swap_plan.get("note", "On-chain swap plan unavailable"))
                        if tx_scan.get("action") == "block":
                            raise RuntimeError("OnChainOS tx-scan blocked the swap transaction")
                        tx_payload = swap_plan.get("swap", {}).get("tx", {})
                        signed = sign_evm_transaction(
                            tx_payload,
                            getattr(args, "onchain_private_key"),
                            wallet_address=onchain_context["wallet_address"],
                            chain_id=int(onchain_context["chain_index"]),
                            rpc_url=onchain_context.get("rpc_url"),
                        )
                        broadcast = broadcast_transaction(
                            signed["raw_transaction"],
                            onchain_context["wallet_address"],
                            chain=onchain_context["chain"],
                        )
                        entry["substitute"]["execution_channel"] = "onchainos"
                        entry["substitute"]["buy_order"] = {
                            "signed_tx_hash": signed["hash"],
                            "broadcast": broadcast,
                        }
                        if broadcast.get("orderId"):
                            entry["substitute"]["order_status"] = track_order(
                                onchain_context["wallet_address"],
                                chain=onchain_context["chain"],
                                order_id=broadcast.get("orderId"),
                            )
                        print(
                            f"[Optimizer-Execute] ✅ ONCHAIN BUY {onchain_option['asset']} broadcast via OnChainOS "
                            f"(tx={broadcast.get('txHash', signed['hash'])})",
                            flush=True,
                        )
                    else:
                        buy_order = _place_spot_order(
                            inst_id=f"{substitute}-USDT", side="buy",
                            quantity=sub_qty, testnet=testnet,
                        )
                        entry["substitute"]["buy_order"] = buy_order
                        actual_buy_price = float(buy_order.get("fillPx", sub_price))
                        print(f"[Optimizer-Execute] ✅ BUY {sub_qty} {substitute} filled @ {actual_buy_price}", flush=True)
                except Exception as exc:
                    entry["substitute"]["buy_order"] = {"error": str(exc)}
                    print(f"[Optimizer-Execute] ⚠ BUY {substitute} failed: {exc}", flush=True)

            # Post-trade state update
            if config is not None:
                actual_sell = float(entry.get("sell_order", {}).get("fillPx", sell_price))
                actual_buy = float(entry.get("substitute", {}).get("buy_order", {}).get("fillPx", sub_price)) if substitute != "USDT" else 1.0
                update_tlh_state(
                    sell_asset=asset, buy_asset=substitute,
                    sell_qty=qty, sell_price=actual_sell,
                    buy_price=actual_buy, loss_amount=realized_loss,
                    jurisdiction=args.jurisdiction, config=config,
                    config_path=Path(args.config) if args.config else None,
                )

        executed.append(entry)

    import hashlib as _hl
    result = {
        "ok": True,
        "mode": "execute",
        "live": getattr(args, "confirm", False),
        "jurisdiction": args.jurisdiction,
        "executed": executed,
        "total_realized_loss": round(sum(e["realized_loss"] for e in executed), 2),
        "wash_sale_status": "N/A (Japan: no wash sale rule)",
    }
    if not getattr(args, "confirm", False):
        result["note"] = "Dry run. Use --confirm to place real orders via OKX Spot API."
    result["step_hash"] = _hl.sha256(
        json.dumps(result, sort_keys=True, default=str).encode()
    ).hexdigest()

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        mode_label = "LIVE" if getattr(args, "confirm", False) else "DRY RUN"
        print(f"\n[Optimizer-Execute] TLH Execution Report ({mode_label}) — {args.jurisdiction.upper()}")
        for e in executed:
            print(f"  SELL {e['quantity']} {e['asset']} @ ${e['price']} → loss ${e['realized_loss']}")
            s = e["substitute"]
            print(f"  BUY  {s['quantity']} {s['asset']} @ ${s['price']} (substitute)")
            if e.get("onchain_substitute"):
                option = e["onchain_substitute"]
                print(
                    f"    ↳ On-chain option: {option['funding_asset']} -> {option['asset']} "
                    f"on {option['chain']} via OnChainOS"
                )
            if "sell_order" in e:
                status = "✅" if "error" not in e["sell_order"] else "❌"
                print(f"    {status} Sell order: {e['sell_order'].get('ordId', e['sell_order'].get('error', 'N/A'))}")
        print(f"\n  Total realized loss: ${result['total_realized_loss']}")
        print(f"  Wash sale: {result['wash_sale_status']}")

    return 0


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="OptimizerClaw TLH engine (OKX Edition)")
    parser.add_argument("--mode", choices=["analyze", "monitor", "execute"], default="analyze",
                        help="analyze: one-shot TLH scan (default). monitor: continuous check from config. execute: simulate TLH execution.")
    parser.add_argument("--dataset", required=False, default=None, help="Path to scanner dataset JSON (required for analyze/execute mode)")
    parser.add_argument("--jurisdiction", required=True, help="Tax jurisdiction")
    parser.add_argument("--prices", default=None, help="JSON price overrides, e.g. '{\"BTC\":62000}'")
    parser.add_argument("--actions", default=None, help="JSON list of asset symbols to execute (from analyze output), e.g. '[\"ETH\",\"AVAX\"]'.")
    parser.add_argument("--threshold", type=float, default=100, help="Min loss threshold in USD (default: 100)")
    parser.add_argument("--config", default=None, help="Path to monitor_config.json (monitor mode)")
    parser.add_argument("--confirm", action="store_true", help="Execute real orders via OKX Spot API (execute mode). Without this flag, execute mode is dry-run only.")
    parser.add_argument("--testnet", action="store_true", help="Use OKX demo trading mode for order placement")
    parser.add_argument("--prefer-onchain-substitute", action="store_true", help="When available, execute TLH substitute buy through OKX OnChainOS instead of OKX spot.")
    parser.add_argument("--onchain-wallet-address", default=None, help="Wallet address used for OnChainOS substitute execution. Falls back to VERITAX_ONCHAIN_WALLET_ADDRESS or dataset onchain.address.")
    parser.add_argument("--onchain-private-key", default=os.getenv("VERITAX_ONCHAIN_PRIVATE_KEY"), help="Private key for local OnChainOS EVM signing. Required only when --confirm and --prefer-onchain-substitute are both set.")
    parser.add_argument("--onchain-chain", default=None, help="On-chain execution network name, e.g. xlayer.")
    parser.add_argument("--onchain-chain-index", default=None, help="On-chain execution chain id, e.g. 196.")
    parser.add_argument("--onchain-rpc-url", default=os.getenv("VERITAX_ONCHAIN_RPC_URL"), help="RPC endpoint used to fetch nonce for local OnChainOS signing.")
    parser.add_argument("--onchain-slippage", default=None, help="Optional OnChainOS swap slippage percentage.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.jurisdiction not in TLH_JURISDICTIONS:
        msg = f"TLH not applicable for {args.jurisdiction}. Supported: {', '.join(sorted(TLH_JURISDICTIONS))}"
        if args.as_json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"[Optimizer] {msg}")
        return 1

    if args.mode == "monitor":
        return monitor_check(args)

    if args.mode == "execute":
        return execute_tlh(args)

    # --- Analyze mode ---
    if not args.dataset:
        print("[Optimizer] error: --dataset is required for analyze mode")
        return 1

    price_overrides = None
    if args.prices:
        try:
            price_overrides = json.loads(args.prices)
        except json.JSONDecodeError:
            print("[Optimizer] error: invalid --prices JSON")
            return 1

    loaded = load_dataset(Path(args.dataset))
    rule_dir = Path(__file__).resolve().parent.parent.parent / "rules"
    rule = load_rule(rule_dir, args.jurisdiction)
    cost_method = rule.get("cost_basis_method", "fifo")
    metrics = aggregate_metrics(loaded["data"], cost_basis_method=cost_method)
    acb_positions = metrics.get("acb_positions", [])
    onchain_context = _extract_onchain_context(loaded, args=args)

    if not acb_positions:
        print("[Optimizer] No positions found in dataset.")
        return 0

    assets = [p["asset"] for p in acb_positions]
    prices = fetch_current_prices(assets, overrides=price_overrides)

    losses = scan_unrealized_losses(acb_positions, prices, threshold=args.threshold)

    if not losses:
        msg = "No unrealized losses above threshold found."
        if args.as_json:
            print(json.dumps({"ok": True, "losses": [], "message": msg}))
        else:
            print(f"[Optimizer] {msg}")
        return 0

    wash_sale = check_wash_sale(args.jurisdiction, rule)

    total_loss = sum(to_decimal(l["unrealized_pnl"]) for l in losses)
    savings = estimate_tax_savings(total_loss, args.jurisdiction, rule)

    analyze_config = None
    if args.config:
        analyze_config = load_config(Path(args.config))
    plan = build_tlh_plan(
        losses,
        wash_sale,
        savings,
        args.jurisdiction,
        config=analyze_config,
        onchain_context=onchain_context,
    )
    plan["ok"] = True

    import hashlib as _hl
    plan["step_hash"] = _hl.sha256(
        json.dumps(plan, sort_keys=True).encode()
    ).hexdigest()

    if args.as_json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    else:
        print(f"\n[Optimizer] TLH Analysis — {args.jurisdiction.upper()}")
        print(f"  Positions scanned: {len(acb_positions)}")
        print(f"  Loss candidates: {len(losses)}")
        print(f"  Total harvestable loss: {plan['total_harvestable_loss']} USD")
        print(f"  Estimated tax savings: {plan['estimated_tax_savings']} USD")
        if wash_sale.get("warning"):
            print(f"  ⚠ Wash sale: {wash_sale['warning']}")
        if plan.get("strategy_plans"):
            print(f"\n  Ranked plans:")
            for candidate in plan["strategy_plans"]:
                print(
                    f"    [{candidate['rank']}] {candidate['title']} "
                    f"score={candidate['score']} modules={', '.join(candidate['modules'])}"
                )
        print(f"\n  Actions:")
        for a in plan["actions"]:
            print(f"    • SELL {a['units']} {a['asset']} (PnL: {a['unrealized_pnl']} USD, {a['pnl_pct']}%)")
            if a.get("substitutes"):
                print(f"      → Substitute: {', '.join(a['substitutes'])}")
            if a.get("onchain_substitute"):
                option = a["onchain_substitute"]
                print(
                    f"      → On-chain option: {option['funding_asset']} -> {option['asset']} "
                    f"on {option['chain']} via OnChainOS"
                )
            if a.get("warning"):
                print(f"      ⚠ {a['warning']}")
        print(f"\n  {plan['earn_hook']}")
        print(f"\n  ⚖ {plan['disclaimer']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
