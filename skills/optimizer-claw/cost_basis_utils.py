#!/usr/bin/env python3
"""Cost basis utilities for TLH monitor — OKX Edition.

Extracts per-asset cost basis from scanner datasets (via compliance ACB),
and supports incremental updates from new trades.

OKX adaptation:
  - trade fields: instId (dash-sep), fillSz, fillPx, side, fee, feeCcy, ts
  - split_symbol() from compliance-claw for OKX instId parsing
"""

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Reuse compliance ACB calculation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "compliance-claw"))
from compliance import load_dataset, load_rule, aggregate_metrics, to_decimal


def generate_from_dataset(
    dataset_path: Path,
    jurisdiction: str,
    rules_dir: Path | None = None,
) -> dict[str, dict]:
    """Extract per-asset cost basis from a scanner dataset.

    Uses compliance aggregate_metrics() to calculate ACB/FIFO positions,
    then converts to a flat dict suitable for monitor_config.

    Args:
        dataset_path: Path to scanner output JSON.
        jurisdiction: Tax jurisdiction (determines cost_basis_method).
        rules_dir: Path to rules/ directory. Auto-detected if None.

    Returns:
        Dict of {asset: {units, total_cost, unit_cost}} with string values.
    """
    if rules_dir is None:
        rules_dir = Path(__file__).resolve().parent.parent.parent / "rules"

    loaded = load_dataset(dataset_path)
    rule = load_rule(rules_dir, jurisdiction)
    cost_method = rule.get("cost_basis_method", "fifo")
    metrics = aggregate_metrics(loaded["data"], cost_basis_method=cost_method)
    acb_positions = metrics.get("acb_positions", [])

    result: dict[str, dict] = {}
    for pos in acb_positions:
        asset = pos["asset"]
        units = to_decimal(pos["units"])
        cost = to_decimal(pos["cost"])
        if units <= 0:
            continue
        result[asset] = {
            "units": str(units),
            "total_cost": str(cost),
            "unit_cost": str(cost / units) if units > 0 else "0",
        }
    return result


def _split_symbol(inst_id: str) -> tuple[str, str]:
    """Split OKX instId into (base, quote).

    OKX format examples:
      'BTC-USDT' → ('BTC', 'USDT')
      'ETH-USDC' → ('ETH', 'USDC')
      'BTC-USDT-SWAP' → ('BTC', 'USDT')
    """
    parts = inst_id.split("-")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return inst_id, ""


def update_from_trades(
    current: dict[str, dict],
    new_trades: list[dict],
) -> dict[str, dict]:
    """Incrementally update cost basis from new OKX trades.

    Processes buy trades to update weighted average cost.
    Sell trades reduce units and proportionally reduce total cost.

    Args:
        current: Existing cost basis {asset: {units, total_cost, unit_cost}}.
        new_trades: New trades from OKX ATK.
            Each trade has: instId, fillPx, fillSz, side, fee, feeCcy, ts.

    Returns:
        Updated cost basis dict.
    """
    updated = {k: dict(v) for k, v in current.items()}

    for trade in sorted(new_trades, key=lambda t: int(t.get("ts", 0))):
        inst_id = trade.get("instId", "")
        base_asset, _ = _split_symbol(inst_id)
        if not base_asset:
            continue

        qty = to_decimal(trade.get("fillSz", "0"))
        price = to_decimal(trade.get("fillPx", "0"))
        side = str(trade.get("side", "")).lower()

        if base_asset not in updated:
            updated[base_asset] = {
                "units": "0",
                "total_cost": "0",
                "unit_cost": "0",
            }

        pos = updated[base_asset]
        old_units = to_decimal(pos["units"])
        old_cost = to_decimal(pos["total_cost"])

        if side == "buy":
            # Buy: add to position, update weighted average cost
            trade_cost = qty * price
            new_units = old_units + qty
            new_cost = old_cost + trade_cost
            pos["units"] = str(new_units)
            pos["total_cost"] = str(new_cost)
            pos["unit_cost"] = str(new_cost / new_units) if new_units > 0 else "0"
        elif side == "sell":
            # Sell: reduce position proportionally
            new_units = old_units - qty
            if new_units <= 0:
                pos["units"] = "0"
                pos["total_cost"] = "0"
                pos["unit_cost"] = "0"
            else:
                # Proportional cost reduction (weighted average method)
                cost_removed = (old_cost / old_units) * qty if old_units > 0 else Decimal("0")
                new_cost = old_cost - cost_removed
                pos["units"] = str(new_units)
                pos["total_cost"] = str(new_cost)
                pos["unit_cost"] = str(new_cost / new_units)

    return updated
