#!/usr/bin/env python3
"""ComplianceClaw — VeriTax rules engine (OKX Edition).

Reads scanner output (unified OKX V5 format), applies jurisdiction-specific
tax rules, and outputs structured tax calculation + human-readable report.

Adapted from VeriTax v1 (Binance) — field names follow OKX V5 convention:
  instId, side, fillSz, fillPx, fee (negative), feeCcy, ts, pnl, instType
"""

import argparse
import json
import sys
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path

from fx_utils import fetch_fx_rate, convert_dataset

# ──────────────────── Utility helpers ────────────────────

def to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def to_millis(value: object) -> int:
    try:
        v = int(value)
        return v if v > 1_000_000_000_000 else v * 1000
    except Exception:
        return 0


def millis_to_iso(ms: int) -> str:
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(ms)


def load_dataset(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    if "data" not in loaded:
        raise ValueError(f"Dataset missing 'data' key: {path}")
    return loaded


def load_rule(rule_dir: Path, jurisdiction: str) -> dict:
    rule_file = rule_dir / f"{jurisdiction}.json"
    if not rule_file.exists():
        raise FileNotFoundError(f"Rule file not found: {rule_file}")
    with open(rule_file, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────── Quote asset parsing ────────────────────

# OKX instId format: "BTC-USDT", "ETH-USDT-SWAP", "BTC-USDT-240628"
# Quote assets for cost-basis calculation purposes
QUOTE_ASSETS = [
    "USDT", "USDC", "TUSD", "DAI",
    "BTC", "ETH", "OKB",
    "EUR", "USD", "JPY", "AUD", "CAD", "SGD",
]


def split_symbol(inst_id: str) -> tuple[str, str]:
    """Parse OKX instId to (base, quote).

    Examples:
      "BTC-USDT"         → ("BTC", "USDT")
      "ETH-BTC"          → ("ETH", "BTC")
      "BTC-USDT-SWAP"    → ("BTC", "USDT")
      "BTC-USDT-240628"  → ("BTC", "USDT")
    """
    parts = inst_id.upper().split("-")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "", ""


# ──────────────────── Holding period ────────────────────

def holding_days(buy_ms: int, sell_ms: int) -> Decimal:
    diff = to_millis(sell_ms) - to_millis(buy_ms)
    if diff <= 0:
        return Decimal("0")
    return Decimal(str(diff)) / Decimal("86400000")


# ──────────────────── Progressive tax ────────────────────

def apply_progressive_tax(taxable: Decimal, brackets: list[dict]) -> Decimal:
    """Apply progressive tax brackets.

    Supports two modes determined by bracket structure:
      - Quick-calc (Japanese NTA style): each bracket has "deduction"
        → tax = taxable * rate - deduction
      - Marginal: standard bracket-by-bracket layered calculation
    """
    if taxable <= 0:
        return Decimal("0")

    # Quick-calc mode: bracket has "deduction" key
    if brackets and "deduction" in brackets[0]:
        for bracket in brackets:
            b_min = Decimal(str(bracket["min"]))
            b_max = Decimal(str(bracket["max"])) if bracket.get("max") is not None else Decimal("999999999999")
            rate = Decimal(str(bracket["rate"]))
            deduction = Decimal(str(bracket.get("deduction", 0)))
            if taxable <= b_max:
                return taxable * rate - deduction
        last = brackets[-1]
        return taxable * Decimal(str(last["rate"])) - Decimal(str(last.get("deduction", 0)))

    # Marginal mode
    total_tax = Decimal("0")
    remaining = taxable
    for bracket in brackets:
        b_min = Decimal(str(bracket["min"]))
        b_max = Decimal(str(bracket["max"])) if bracket.get("max") is not None else Decimal("999999999999")
        rate = Decimal(str(bracket["rate"]))
        width = b_max - b_min
        taxable_in_bracket = min(remaining, width + 1) if b_max < Decimal("999999999999") else remaining
        if taxable_in_bracket <= 0:
            break
        total_tax += taxable_in_bracket * rate
        remaining -= taxable_in_bracket
        if remaining <= 0:
            break
    return total_tax


# ──────────────────── Reward classification ────────────────────

def classify_reward(item: dict) -> str:
    """Classify an earn_record into reward categories.

    OKX earn product names (from scanner):
      "Simple Earn Interest", "On-chain Earn Staking Reward",
      "Jumpstart Mining Reward", "OKX Earn Staking Reward",
      "DCD Yield", "Shark Fin Yield", etc.
    """
    product = str(item.get("product", "")).lower()
    item_type = str(item.get("type", "")).lower()

    # Staking (on-chain earn, OKX staking)
    if "stak" in product or "staking" in product:
        return "staking"
    # Jumpstart (OKX launchpad equivalent)
    if "jumpstart" in product or "launch" in product:
        return "jumpstart"
    # Lending / Simple Earn interest
    if "lend" in product or "interest" in product or "simple earn" in product:
        return "lending_interest"
    # DCD / structured products
    if "dcd" in product or "shark" in product or "dual" in product:
        return "lending_interest"

    return "other_reward"


# ──────────────────── Evidence evaluation ────────────────────

def evaluate_evidence(rule: dict) -> dict:
    rules_evidence = rule.get("rules_evidence", [])
    total = len(rules_evidence)
    verified = sum(1 for e in rules_evidence if e.get("verified", False))
    return {
        "total": total,
        "verified": verified,
        "all_verified": total > 0 and verified == total,
    }


# ──────────────────── Core: aggregate metrics ────────────────────

def aggregate_metrics(data: dict, cost_basis_method: str = "fifo") -> dict:
    """Aggregate trade/earn metrics and compute realized gains.

    Args:
        data: Scanner dataset containing unified trades[], earn_records[],
              deposits[], withdrawals[] (OKX V5 format).
        cost_basis_method: 'fifo' (default) or 'total_average' (Japan: 總平均法).
    """
    all_trades = data.get("trades", []) or []
    earn_records = data.get("earn_records", []) or []
    deposits = data.get("deposits", []) or []
    withdrawals = data.get("withdrawals", []) or []

    # Split trades by instType
    spot_trades = [t for t in all_trades if t.get("instType", "SPOT") in ("SPOT", "MARGIN")]
    swap_trades = [t for t in all_trades if t.get("instType") in ("SWAP", "FUTURES")]
    # Funding fees: SWAP entries with billSubType == "FUNDING_FEE"
    funding_fees = [t for t in swap_trades if t.get("billSubType") == "FUNDING_FEE"]
    # Actual swap/futures fills (not funding fees)
    swap_fills = [t for t in swap_trades if t.get("billSubType") != "FUNDING_FEE"]

    # --- Spot/margin trade aggregation ---
    total_trade_quote = Decimal("0")
    total_trade_fee = Decimal("0")
    trade_details: list[dict] = []
    for item in spot_trades:
        fill_sz = to_decimal(item.get("fillSz"))
        fill_px = to_decimal(item.get("fillPx"))
        fee = abs(to_decimal(item.get("fee")))
        quote_amount = fill_sz * fill_px
        total_trade_quote += quote_amount
        total_trade_fee += fee
        trade_details.append({
            "instId": item.get("instId", ""),
            "side": item.get("side", ""),
            "fillSz": str(fill_sz.quantize(Decimal("0.00000001"))) if fill_sz else "0",
            "fillPx": str(fill_px.quantize(Decimal("0.01"))) if fill_px else "0",
            "quoteAmt": str(quote_amount.quantize(Decimal("0.01"))) if quote_amount else "0",
            "fee": str(fee.quantize(Decimal("0.00000001"))) if fee else "0",
            "feeCcy": item.get("feeCcy", ""),
            "ts": item.get("ts", ""),
        })

    # --- Earn records aggregation ---
    total_dividend_income = sum(to_decimal(item.get("amt")) for item in earn_records)

    lots: dict[str, list[dict]] = {}
    acb_state: dict[str, dict] = {}
    realized_fifo_gain = Decimal("0")
    long_term_gain = Decimal("0")
    short_term_gain = Decimal("0")
    inventory_warnings: list[str] = []
    buy_events: dict[str, list[int]] = {}
    loss_sales: list[dict] = []

    trades_sorted = sorted(spot_trades, key=lambda item: to_millis(item.get("ts", 0)))

    for item in trades_sorted:
        inst_id = str(item.get("instId", "")).upper()
        base, quote = split_symbol(inst_id)
        if not base or not quote:
            inventory_warnings.append(f"unrecognized_instId={inst_id} skipped")
            continue

        fill_sz = to_decimal(item.get("fillSz"))
        fill_px = to_decimal(item.get("fillPx"))
        quote_qty = fill_sz * fill_px
        fee = abs(to_decimal(item.get("fee")))  # OKX fee is negative; take abs
        fee_ccy = str(item.get("feeCcy", "")).upper().strip()
        is_buy = str(item.get("side", "")).lower() == "buy"
        event_ms = to_millis(item.get("ts", 0))

        if base not in lots:
            lots[base] = []
        if base not in acb_state:
            acb_state[base] = {"units": Decimal("0"), "cost": Decimal("0")}

        if is_buy:
            acquired_qty = fill_sz - fee if fee_ccy == base else fill_sz
            if acquired_qty < 0:
                acquired_qty = Decimal("0")
            cost = quote_qty + fee if fee_ccy == quote else quote_qty
            if fee > 0 and fee_ccy not in (base, quote):
                inventory_warnings.append(
                    f"third_party_fee_not_converted asset={fee_ccy} qty={str(fee)} at={millis_to_iso(event_ms)}"
                )
            if acquired_qty > 0:
                lots[base].append({"qty": acquired_qty, "cost": cost, "time": event_ms})
                acb_state[base]["units"] += acquired_qty
                acb_state[base]["cost"] += cost
                buy_events.setdefault(base, []).append(event_ms)
            continue

        # Sell
        sold_qty = fill_sz + fee if fee_ccy == base else fill_sz
        if sold_qty <= 0:
            continue
        proceeds = quote_qty - fee if fee_ccy == quote else quote_qty
        if fee > 0 and fee_ccy not in (base, quote):
            inventory_warnings.append(
                f"third_party_fee_not_converted asset={fee_ccy} qty={str(fee)} at={millis_to_iso(event_ms)}"
            )
        proceeds_per_unit = proceeds / sold_qty if sold_qty > 0 else Decimal("0")

        remaining = sold_qty
        consumed_qty = Decimal("0")
        cost_basis = Decimal("0")
        sale_long = Decimal("0")
        sale_short = Decimal("0")

        if cost_basis_method == "total_average":
            # ACB / 総平均法 (Total Average / Weighted Average Method)
            acb = acb_state[base]
            if acb["units"] > 0:
                avg_cost_unit = acb["cost"] / acb["units"]
                consumed_qty = min(sold_qty, acb["units"])
                cost_basis = avg_cost_unit * consumed_qty
                remaining = sold_qty - consumed_qty
                sale_short = proceeds_per_unit * consumed_qty - cost_basis
                acb["units"] -= consumed_qty
                acb["cost"] -= cost_basis
            else:
                consumed_qty = Decimal("0")
        else:
            # FIFO method (default for AU/CA/SG/TW)
            while remaining > 0 and lots[base]:
                lot = lots[base][0]
                lot_qty = lot["qty"]
                take = lot_qty if lot_qty <= remaining else remaining
                if take <= 0:
                    break
                ratio = take / lot_qty
                lot_cost_take = lot["cost"] * ratio

                gain_part = proceeds_per_unit * take - lot_cost_take
                if holding_days(lot.get("time", 0), event_ms) > Decimal("365"):
                    sale_long += gain_part
                else:
                    sale_short += gain_part

                lot["qty"] = lot_qty - take
                lot["cost"] = lot["cost"] - lot_cost_take
                if lot["qty"] <= Decimal("0"):
                    lots[base].pop(0)

                remaining -= take
                consumed_qty += take
                cost_basis += lot_cost_take

        if remaining > 0:
            inventory_warnings.append(
                f"sell_without_inventory asset={base} missing_qty={str(remaining)} at={millis_to_iso(event_ms)}"
            )

        consumed_proceeds = proceeds_per_unit * consumed_qty
        sale_gain = consumed_proceeds - cost_basis
        realized_fifo_gain += sale_gain
        long_term_gain += sale_long
        short_term_gain += sale_short

        # Update ACB state (only for FIFO; total_average already updated above)
        if cost_basis_method != "total_average":
            acb = acb_state[base]
            if acb["units"] > 0 and consumed_qty > 0:
                acb_unit = acb["cost"] / acb["units"]
                remove_cost = acb_unit * consumed_qty
                acb["units"] = acb["units"] - consumed_qty
                acb["cost"] = acb["cost"] - remove_cost
        if sale_gain < 0:
            loss_sales.append({"asset": base, "time": event_ms, "loss": str(abs(sale_gain))})

    # ── Superficial loss detection (Canada ITA s.54) ──
    superficial_hits: list[dict] = []
    thirty_days_ms = 30 * 24 * 60 * 60 * 1000
    for event in loss_sales:
        asset = event["asset"]
        sale_time = event["time"]
        reacquired_after = False
        for buy_time in buy_events.get(asset, []):
            if abs(buy_time - sale_time) <= thirty_days_ms:
                if buy_time >= sale_time:
                    reacquired_after = True
                    superficial_hits.append(
                        {
                            "asset": asset,
                            "sale_time": millis_to_iso(sale_time),
                            "buy_time": millis_to_iso(buy_time),
                            "condition": "ITA s.54: reacquired within 30 days and likely still held at period end",
                        }
                    )
                    break
        if not reacquired_after:
            for buy_time in buy_events.get(asset, []):
                if sale_time - thirty_days_ms <= buy_time < sale_time:
                    superficial_hits.append(
                        {
                            "asset": asset,
                            "sale_time": millis_to_iso(sale_time),
                            "buy_time": millis_to_iso(buy_time),
                            "condition": "ITA s.54 candidate: acquired within 30 days before sale. Verify if still held at period end.",
                        }
                    )
                    break

    # ── Reward breakdown (from earn_records) ──
    reward_breakdown = {
        "staking": 0,
        "jumpstart": 0,
        "lending_interest": 0,
        "other_reward": 0,
    }
    reward_amounts = {
        "staking": Decimal("0"),
        "jumpstart": Decimal("0"),
        "lending_interest": Decimal("0"),
        "other_reward": Decimal("0"),
    }
    for item in earn_records:
        category = classify_reward(item)
        reward_breakdown[category] = reward_breakdown.get(category, 0) + 1
        reward_amounts[category] = reward_amounts.get(category, Decimal("0")) + to_decimal(item.get("amt"))

    # ── ACB positions ──
    acb_positions = []
    for asset, state in acb_state.items():
        units = state["units"]
        cost = state["cost"]
        if units <= 0 and cost <= 0:
            continue
        acb_positions.append(
            {
                "asset": asset,
                "units": str(units),
                "cost": str(cost),
                "acb_per_unit": str(cost / units) if units > 0 else "0",
            }
        )

    # ── Futures/Swap PnL aggregation ──
    total_futures_pnl = sum(to_decimal(t.get("pnl")) for t in swap_fills)
    total_futures_commission = sum(abs(to_decimal(t.get("fee"))) for t in swap_fills) * Decimal("-1")
    total_futures_funding = sum(to_decimal(t.get("pnl")) for t in funding_fees)

    return {
        "trade_count": len(spot_trades),
        "deposit_count": len(deposits),
        "withdrawal_count": len(withdrawals),
        "dividend_count": len(earn_records),
        "total_trade_quote": str(total_trade_quote),
        "total_trade_fee": str(total_trade_fee),
        "total_dividend_income": str(total_dividend_income),
        "realized_fifo_gain": str(realized_fifo_gain),
        "long_term_gain": str(long_term_gain),
        "short_term_gain": str(short_term_gain),
        "inventory_warnings": inventory_warnings,
        "superficial_loss_candidates": superficial_hits,
        "reward_event_breakdown": reward_breakdown,
        "reward_amount_breakdown": {key: str(value) for key, value in reward_amounts.items()},
        "acb_positions": acb_positions,
        "trade_details": trade_details,
        # --- Futures/Swap income ---
        "futures_income_count": len(swap_trades),
        "total_futures_pnl": str(total_futures_pnl),
        "total_futures_commission": str(total_futures_commission),
        "total_futures_funding": str(total_futures_funding),
    }


# ──────────────────── Tax calculation ────────────────────

def calculate_tax(rule: dict, metrics: dict) -> dict:
    jurisdiction = rule.get("jurisdiction")
    rates = rule.get("rates", {})

    realized_gain = to_decimal(metrics.get("realized_fifo_gain"))
    long_term_gain = to_decimal(metrics.get("long_term_gain"))
    short_term_gain = to_decimal(metrics.get("short_term_gain"))
    dividends = to_decimal(metrics.get("total_dividend_income"))
    futures_pnl = to_decimal(metrics.get("total_futures_pnl"))
    futures_commission = to_decimal(metrics.get("total_futures_commission"))
    futures_funding = to_decimal(metrics.get("total_futures_funding"))
    net_futures = futures_pnl + futures_commission + futures_funding

    if jurisdiction == "japan":
        brackets = rule.get("tax_brackets", [])
        surcharges = rule.get("surcharges", {})
        resident_tax_rate = to_decimal(surcharges.get("resident_tax_rate", "0.10"))
        reconstruction_rate = to_decimal(surcharges.get("reconstruction_surcharge_rate", "0.021"))

        taxable = max(realized_gain + net_futures + dividends, Decimal("0"))
        income_tax = apply_progressive_tax(taxable, brackets)
        reconstruction_tax = income_tax * reconstruction_rate
        resident_tax = taxable * resident_tax_rate
        total_tax = income_tax + reconstruction_tax + resident_tax
        carry_loss_years = int(rule.get("carry_loss_years", 0))

        # Reform dual-track simulation
        reform = rule.get("proposed_reform", {})
        reform_status = reform.get("status", "")
        reform_note = None
        reform_comparison = None

        if "enacted" in reform_status or "pending" in reform_status or "approved" in reform_status:
            reform_rates = reform.get("rates", {})
            specified_rate = to_decimal(reform_rates.get("specified_crypto", "0.20315"))
            reward_amounts = metrics.get("reward_amount_breakdown", {})
            excluded_income = (
                to_decimal(reward_amounts.get("staking", 0))
                + to_decimal(reward_amounts.get("lending_interest", 0))
            )
            green_zone_income = max(taxable - excluded_income, Decimal("0"))
            excluded_taxable = max(excluded_income, Decimal("0"))

            reform_green_tax = green_zone_income * specified_rate
            reform_excluded_tax = apply_progressive_tax(excluded_taxable, brackets)
            reform_excluded_reconstruction = reform_excluded_tax * reconstruction_rate
            reform_excluded_resident = excluded_taxable * resident_tax_rate
            reform_total = (
                reform_green_tax
                + reform_excluded_tax
                + reform_excluded_reconstruction
                + reform_excluded_resident
            )

            reform_comparison = {
                "green_zone_income": str(green_zone_income),
                "green_zone_tax_rate": str(specified_rate),
                "green_zone_tax": str(reform_green_tax),
                "excluded_income": str(excluded_taxable),
                "excluded_tax_progressive": str(
                    reform_excluded_tax + reform_excluded_reconstruction + reform_excluded_resident
                ),
                "reform_total_tax": str(reform_total),
                "current_law_total_tax": str(total_tax),
                "savings": str(total_tax - reform_total),
            }

            if "enacted" in reform_status:
                reform_note = (
                    f"申告分離課税（立法済み）: グリーンゾーン所得 {green_zone_income} → "
                    f"20.315%分離課税 = {reform_green_tax}。"
                )
            else:
                reform_note = (
                    "令和8年度税制改正大綱（2025.12.19）: グリーンゾーン20%分離課税+3年損失繰越を提言。"
                    "国会審議待ち。現行法では雑所得・総合課税を適用。"
                    f" 【参考シミュレーション】現行法 {total_tax} vs 改革後 {reform_total}"
                    f"（差額 {total_tax - reform_total}）"
                )

        result = {
            "mode": "progressive_miscellaneous",
            "taxable_base": str(taxable),
            "income_tax": str(income_tax),
            "reconstruction_tax": str(reconstruction_tax),
            "resident_tax": str(resident_tax),
            "estimated_tax": str(total_tax),
            "carry_loss_years": carry_loss_years,
            "cost_basis_method": rule.get("cost_basis_method", "total_average"),
            "note": "雑所得・総合課税。所得税(累進)+住民税10%+復興特別所得税2.1%。損失繰越不可。",
        }
        if reform_note:
            result["reform_note"] = reform_note
        if reform_comparison:
            result["reform_comparison"] = reform_comparison
        return result

    if jurisdiction == "taiwan":
        brackets = rule.get("tax_brackets", [])
        rewards = metrics.get("reward_amount_breakdown", {})

        potential_taxable = (
            to_decimal(rewards.get("staking", 0))
            + to_decimal(rewards.get("jumpstart", 0))
            + to_decimal(rewards.get("lending_interest", 0))
        )
        potential_tax = apply_progressive_tax(potential_taxable, brackets) if potential_taxable > 0 else Decimal("0")

        return {
            "mode": "self_check",
            "estimated_tax": "0",
            "potential_other_income_tax": str(potential_tax),
            "potential_taxable_other_income": str(potential_taxable),
            "futures_pnl_reference": str(net_futures),
            "futures_income_count": metrics.get("futures_income_count", 0),
            "check_items": {
                "trade_events": metrics.get("trade_count", 0),
                "dividend_events": metrics.get("dividend_count", 0),
                "futures_events": metrics.get("futures_income_count", 0),
                "requires_income_review": str(dividends > Decimal("0")).lower(),
                "staking_events": metrics.get("reward_event_breakdown", {}).get("staking", 0),
                "jumpstart_events": metrics.get("reward_event_breakdown", {}).get("jumpstart", 0),
                "lending_interest_events": metrics.get("reward_event_breakdown", {}).get("lending_interest", 0),
            },
            "note": "交易所得暫無課稅規定。質押/挖礦收入可能為「其他所得」，供自查參考。合約搭配盈虧已列入參考欄位。注意：potential_tax 為未扣除免稅額(97,000 TWD/人)及標準扣除額(131,000 TWD)之保守估算，實際應納稅額將低於此值。",
        }

    if jurisdiction == "australia":
        brackets = rule.get("tax_brackets", [])
        medicare_levy = to_decimal(rates.get("medicare_levy", "0.02"))
        discount = to_decimal(rates.get("long_term_discount", "0.5"))

        pos_short = max(short_term_gain, Decimal("0"))
        pos_long = max(long_term_gain, Decimal("0"))
        total_loss = max(-short_term_gain, Decimal("0")) + max(-long_term_gain, Decimal("0"))
        short_after = max(pos_short - total_loss, Decimal("0"))
        remaining_loss = max(total_loss - pos_short, Decimal("0"))
        long_after = max(pos_long - remaining_loss, Decimal("0"))
        discounted_base = long_after * (Decimal("1") - discount)
        futures_taxable = max(net_futures, Decimal("0"))
        taxable = short_after + discounted_base + futures_taxable

        income_tax = apply_progressive_tax(taxable, brackets)
        medicare_tax = taxable * medicare_levy
        total_tax = income_tax + medicare_tax

        return {
            "mode": "cgt",
            "taxable_base_before_discount": str(short_after + long_after),
            "short_term_taxable": str(short_after),
            "long_term_before_discount": str(long_after),
            "discounted_base": str(discounted_base),
            "net_capital_gain": str(taxable),
            "income_tax": str(income_tax),
            "medicare_levy": str(medicare_tax),
            "estimated_tax": str(total_tax),
        }

    if jurisdiction == "canada":
        brackets = rule.get("tax_brackets", [])
        inclusion = to_decimal(rates.get("inclusion_rate", "0.5"))
        total_gain = max(realized_gain + net_futures, Decimal("0"))
        taxable = total_gain * inclusion
        superficial_days = rule.get("rules", {}).get("superficial_loss_days", 30)

        federal_tax = apply_progressive_tax(taxable, brackets)

        return {
            "mode": "acb",
            "taxable_base_after_inclusion": str(taxable),
            "inclusion_rate": str(inclusion),
            "federal_tax": str(federal_tax),
            "estimated_tax": str(federal_tax),
            "superficial_loss_days": superficial_days,
            "superficial_loss_hits": metrics.get("superficial_loss_candidates", []),
            "acb_positions": metrics.get("acb_positions", []),
            "note": "Federal tax only. Provincial tax varies by province and is additional.",
        }

    if jurisdiction == "singapore":
        brackets = rule.get("tax_brackets", [])
        rewards = metrics.get("reward_amount_breakdown", {})
        taxable_income = (
            to_decimal(rewards.get("staking", 0))
            + to_decimal(rewards.get("jumpstart", 0))
            + to_decimal(rewards.get("lending_interest", 0))
        )

        income_tax = apply_progressive_tax(taxable_income, brackets)
        trader_assessment = rule.get("trader_assessment", {})

        return {
            "mode": "income_classification",
            "capital_gain_tax": "0",
            "taxable_income_from_rewards": str(taxable_income),
            "income_tax_on_rewards": str(income_tax),
            "estimated_tax": str(income_tax),
            "reward_amount_breakdown": rewards,
            "trader_assessment_badges": trader_assessment.get("badges_of_trade", []),
            "classification_note": trader_assessment.get("classification_note", ""),
            "note": "Capital gains not taxable. Tax applies only to income-classified rewards (staking/lending). Trader vs investor per IRAS badges of trade.",
        }

    raise ValueError(f"Unsupported jurisdiction: {jurisdiction}")


# ──────────────────── Report builder ────────────────────

def _fmt_dec(val) -> str:
    """Format a decimal-like value to a clean string (up to 2 decimal places)."""
    try:
        d = Decimal(str(val))
        return str(d.quantize(Decimal("0.01")))
    except Exception:
        return str(val)


def build_report(year: int | None, rule: dict, metrics: dict, tax: dict) -> str:
    jurisdiction = rule.get("jurisdiction", "unknown")
    currency = rule.get("currency", "")
    header = f"[Compliance] {jurisdiction} {year if year else ''}".strip()
    lines = [
        header,
        f"- trades={metrics.get('trade_count', 0)} earn_records={metrics.get('dividend_count', 0)} futures={metrics.get('futures_income_count', 0)}",
        f"- total_trade_volume={_fmt_dec(metrics.get('total_trade_quote', '0'))} {currency or 'USD'}  total_fee={_fmt_dec(metrics.get('total_trade_fee', '0'))} {currency or 'USD'}",
        f"- realized_gain={metrics.get('realized_fifo_gain', '0')} futures_pnl={metrics.get('total_futures_pnl', '0')}",
        f"- mode={tax.get('mode', '')}",
    ]

    # Per-trade breakdown
    trade_details = metrics.get('trade_details', [])
    if trade_details:
        lines.append("- trade_breakdown:")
        for td in trade_details:
            ts_str = td.get('ts', '')
            if ts_str:
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    ts_str = _dt.fromtimestamp(int(ts_str) / 1000, tz=_tz.utc).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    pass
            lines.append(f"    {td.get('instId')} {td.get('side')} sz={td.get('fillSz')} px={td.get('fillPx')} amt={td.get('quoteAmt')} {currency or 'USD'} fee={td.get('fee')} {td.get('feeCcy')} @ {ts_str}")

    evidence = evaluate_evidence(rule)
    lines.append(f"- evidence_verified={evidence.get('verified', 0)}/{evidence.get('total', 0)}")

    if "estimated_tax" in tax:
        lines.append(f"- estimated_tax={tax.get('estimated_tax')} {currency}")
    if "income_tax" in tax and "resident_tax" in tax:
        lines.append(f"- income_tax={tax.get('income_tax')} + resident_tax={tax.get('resident_tax')} + reconstruction={tax.get('reconstruction_tax')}")
    if "income_tax" in tax and "medicare_levy" in tax and jurisdiction == "australia":
        lines.append(f"- income_tax={tax.get('income_tax')} + medicare_levy={tax.get('medicare_levy')}")
        anti_avoidance = rule.get("anti_avoidance", {})
        if anti_avoidance.get("wash_sale_warning"):
            lines.append(f"- ⚠ ATO wash sale warning: {anti_avoidance.get('note', 'Part IVA anti-avoidance may apply')}")
    if "federal_tax" in tax:
        lines.append(f"- federal_tax={tax.get('federal_tax')} (provincial additional)")
    if tax.get("reform_note"):
        lines.append(f"- reform_note={tax.get('reform_note')}")
    if tax.get("reform_comparison"):
        comp = tax["reform_comparison"]
        lines.append(f"- reform_simulation: current_law={comp.get('current_law_total_tax')} vs reform={comp.get('reform_total_tax')} (savings={comp.get('savings')})")
    if "potential_other_income_tax" in tax:
        lines.append(f"- potential_other_income_tax={tax.get('potential_other_income_tax')} {currency} (staking/mining)")
    if "income_tax_on_rewards" in tax:
        lines.append(f"- income_tax_on_rewards={tax.get('income_tax_on_rewards')} {currency}")

    if tax.get("note"):
        lines.append(f"- note={tax.get('note')}")

    if tax.get("fx_conversion") and tax.get("fx_conversion") != "none":
        lines.append(f"- fx_rate={tax.get('fx_rate')} ({tax.get('fx_conversion')})")
        lines.append("- ⚠ 本工具使用年末/年均汇率近似，精确申报请使用逐笔交易日汇率。")

    if metrics.get("inventory_warnings"):
        lines.append(f"- inventory_warnings={len(metrics.get('inventory_warnings', []))}")
    if not evidence.get("all_verified", False):
        lines.append("- disclaimer=法规证据未全部在线核验，当前结果仅可用于合规预审，不可直接用于申报。")
    else:
        lines.append("- disclaimer=本工具提供合规参考建议，最终税务申报请咨询持牌税务师。")
    return "\n".join(lines)


# ──────────────────── Daily digest (Continuous Mode) ────────────────────

def run_daily_digest(args) -> int:
    _ZERO_DP = {"JPY", "TWD", "KRW"}

    def _fmt(val, cur: str) -> str:
        d = to_decimal(val) if not isinstance(val, Decimal) else val
        if cur in _ZERO_DP:
            return str(d.quantize(Decimal("1")))
        return str(d.quantize(Decimal("0.01")))

    def _fmt_units(val) -> str:
        d = to_decimal(val) if not isinstance(val, Decimal) else val
        q = d.quantize(Decimal("0.00000001"))
        s = format(q, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s

    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]
    rule_dir = project_root / "rules"

    try:
        loaded = load_dataset(Path(args.dataset))
        rule = load_rule(rule_dir, args.jurisdiction)
        cost_method = rule.get("cost_basis_method", "fifo")

        currency = rule.get("currency", "USD")
        tax_year = loaded.get("year") or 2024
        fx_rate = fetch_fx_rate(tax_year, currency)
        data_local = convert_dataset(loaded["data"], fx_rate)

        metrics = aggregate_metrics(data_local, cost_basis_method=cost_method)
        tax_result = calculate_tax(rule, metrics)

        digest = {
            "ok": True,
            "mode": "daily-digest",
            "jurisdiction": args.jurisdiction,
            "year": tax_year,
            "currency": currency,
            "total_trades": metrics.get("trade_count", 0),
            "realized_gain": _fmt(metrics.get("realized_fifo_gain", 0), currency),
            "futures_pnl": _fmt(
                to_decimal(metrics.get("total_futures_pnl", 0))
                + to_decimal(metrics.get("total_futures_commission", 0))
                + to_decimal(metrics.get("total_futures_funding", 0)),
                currency),
            "estimated_tax": _fmt(tax_result.get("estimated_tax", 0), currency),
            "effective_rate": str(to_decimal(tax_result.get("effective_rate_pct", 0)).quantize(Decimal("0.01"))),
            "positions_count": len(metrics.get("acb_positions", [])),
            "top_positions": [
                {"asset": p["asset"], "units": _fmt_units(p["units"]), "cost_basis": _fmt(p.get("cost", p.get("cost_basis", 0)), currency)}
                for p in sorted(
                    metrics.get("acb_positions", []),
                    key=lambda x: float(x.get("cost", x.get("cost_basis", 0))),
                    reverse=True,
                )[:5]
            ],
        }

        import hashlib as _hl
        digest["step_hash"] = _hl.sha256(
            json.dumps(digest, sort_keys=True).encode()
        ).hexdigest()

        if args.as_json:
            print(json.dumps(digest, ensure_ascii=False))
        else:
            print(f"\n📊 VeriTax 每日简报 ({args.jurisdiction.upper()})")
            print(f"  税务年度：{tax_year}")
            print(f"  总交易笔数：{digest['total_trades']}")
            print(f"  累计已实现收益：{digest['realized_gain']} {currency}")
            print(f"  预估应纳税额：{digest['estimated_tax']} {currency}")
            print(f"  有效税率：{digest['effective_rate']}%")
            print(f"  持仓数量：{digest['positions_count']}")
            if digest["top_positions"]:
                print(f"  前 5 持仓：")
                for p in digest["top_positions"]:
                    print(f"    • {p['asset']}: {p['units']} (成本 {p['cost_basis']} {currency})")
        return 0
    except Exception as exc:
        if args.as_json:
            print(json.dumps({"ok": False, "mode": "daily-digest", "error": str(exc)}))
        else:
            print(f"[Compliance-DailyDigest] error: {exc}")
        return 1


# ──────────────────── Main entry ────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="ComplianceClaw rules engine")
    parser.add_argument("--dataset", required=True, help="Path to scanner dataset json")
    parser.add_argument("--jurisdiction", required=True, choices=["japan", "taiwan", "australia", "canada", "singapore"])
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--mode", choices=["full", "daily-digest"], default="full",
                        help="full: complete analysis (default). daily-digest: concise status summary.")
    args = parser.parse_args()

    if args.mode == "daily-digest":
        return run_daily_digest(args)

    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]
    rule_dir = project_root / "rules"

    try:
        loaded = load_dataset(Path(args.dataset))
        rule = load_rule(rule_dir, args.jurisdiction)
        cost_method = rule.get("cost_basis_method", "fifo")

        currency = rule.get("currency", "USD")
        tax_year = loaded.get("year") or 2024
        fx_rate = fetch_fx_rate(tax_year, currency)
        data_local = convert_dataset(loaded["data"], fx_rate)

        metrics = aggregate_metrics(data_local, cost_basis_method=cost_method)
        tax_result = calculate_tax(rule, metrics)

        tax_result["fx_rate"] = str(fx_rate)
        tax_result["fx_conversion"] = f"USD→{currency}" if fx_rate != Decimal("1") else "none"

        report = build_report(loaded.get("year"), rule, metrics, tax_result)

        payload = {
            "ok": True,
            "source": "compliance-claw",
            "jurisdiction": args.jurisdiction,
            "year": loaded.get("year"),
            "rule": rule,
            "evidence": evaluate_evidence(rule),
            "metrics": metrics,
            "tax": tax_result,
            "report": report,
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "source": "compliance-claw",
            "jurisdiction": args.jurisdiction,
            "error": str(exc),
        }

    if payload.get("ok"):
        import hashlib as _hl
        payload["step_hash"] = _hl.sha256(
            json.dumps(payload.get("tax", payload), sort_keys=True).encode()
        ).hexdigest()

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        if payload.get("ok"):
            print(payload["report"])
        else:
            print(f"[Compliance] error: {payload['error']}")

    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
