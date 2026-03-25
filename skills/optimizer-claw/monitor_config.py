#!/usr/bin/env python3
"""Monitor config management for TLH continuous monitoring.

Handles read/write of monitor_config.json, which stores:
- positions_watch: assets being monitored with thresholds + cost basis
- executed_tlh: history of executed TLH trades
- last_evaluated: timestamp of last evaluation

Structure follows design.md §7.3.2.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


# Default storage location (VERITAX_DATA_DIR overridable for demo isolation)
DEFAULT_CONFIG_PATH = Path(os.getenv("VERITAX_DATA_DIR",
                           str(Path.home() / ".openclaw" / "workspace" / "veritax-data"))) / "monitor_config.json"


def _default_config(jurisdiction: str = "AU") -> dict:
    """Return a minimal default config structure."""
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "check_interval_ms": 3600000,
        "jurisdiction": jurisdiction,
        "wash_sale_rule_days": _wash_sale_days(jurisdiction),
        "positions_watch": [],
        "executed_tlh": [],
        "last_evaluated": {
            "timestamp": None,
            "results": {},
        },
    }


def _wash_sale_days(jurisdiction: str) -> int:
    """Return wash sale cooldown days for jurisdiction (design.md §7.3.5)."""
    return {
        "CA": 30,   # Superficial Loss Rule, 30 days before + after
        "GB": 30,   # 30-day rule, after only
        "AU": 0,    # Part IVA, no fixed days
        "JP": 0,    # No wash sale rule
    }.get(jurisdiction.upper(), 0)


def load_config(path: Path | None = None) -> dict:
    """Load monitor_config.json. Returns default config if file missing."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return _default_config()
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict, path: Path | None = None) -> Path:
    """Save monitor_config.json. Creates parent directories if needed."""
    config_path = path or DEFAULT_CONFIG_PATH
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return config_path


def find_position(config: dict, asset: str) -> dict | None:
    """Find a position in positions_watch by asset symbol."""
    for pos in config.get("positions_watch", []):
        if pos.get("symbol") == asset:
            return pos
    return None


def upsert_position(config: dict, position: dict) -> None:
    """Insert or update a position in positions_watch."""
    asset = position["symbol"]
    positions = config.setdefault("positions_watch", [])
    for i, existing in enumerate(positions):
        if existing.get("symbol") == asset:
            positions[i] = position
            return
    positions.append(position)


def remove_position(config: dict, asset: str) -> bool:
    """Remove a position from positions_watch. Returns True if found."""
    positions = config.get("positions_watch", [])
    for i, pos in enumerate(positions):
        if pos.get("symbol") == asset:
            positions.pop(i)
            return True
    return False


def add_executed_tlh(config: dict, record: dict) -> None:
    """Append an executed TLH record."""
    config.setdefault("executed_tlh", []).append(record)


def is_in_wash_sale_cooldown(config: dict, asset: str) -> bool:
    """Check if asset is in wash sale cooldown period."""
    now = datetime.now(timezone.utc)
    # Check positions_watch for wash_sale_cooldown_until
    pos = find_position(config, asset)
    if pos and pos.get("wash_sale_cooldown_until"):
        cooldown_end = datetime.fromisoformat(pos["wash_sale_cooldown_until"])
        if now < cooldown_end:
            return True
    # Check executed_tlh for wash_sale_end
    for tlh in config.get("executed_tlh", []):
        if tlh.get("substitute") == asset and tlh.get("wash_sale_end"):
            end = datetime.fromisoformat(tlh["wash_sale_end"])
            if now < end:
                return True
    return False


def make_position_entry(
    symbol: str,
    quantity: float,
    cost_basis_unit: float,
    asset_sector: str = "",
    tlh_threshold_pnl: float = -500.0,
    tlh_threshold_pct: float = -15.0,
    substitute_blacklist: list[str] | None = None,
    last_trade_id: dict | None = None,
) -> dict:
    """Create a position entry for positions_watch (design.md §7.3.2)."""
    return {
        "symbol": symbol,
        "quantity": quantity,
        "cost_basis_unit": cost_basis_unit,
        "asset_sector": asset_sector,
        "tlh_threshold_pnl": tlh_threshold_pnl,
        "tlh_threshold_pct": tlh_threshold_pct,
        "substitute_blacklist": substitute_blacklist or [],
        "wash_sale_cooldown_until": None,
        "last_trade_id": last_trade_id or {},
    }
