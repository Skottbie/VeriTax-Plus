#!/usr/bin/env python3
"""Price fetching utility for OptimizerClaw — OKX Edition.

Three-layer price retrieval:
  Layer 1: OKX ATK CLI (market ticker, requires ATK installed)
  Layer 2: CLI --prices override (offline testing)
  Layer 3: CoinGecko free API (fallback)
"""

import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Ensure lib/ is importable
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lib.atk_client import run as atk_run  # noqa: E402

COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

# CoinGecko ID mapping for common crypto assets
_COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "OKB": "okb",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "AAVE": "aave",
    "LTC": "litecoin",
    "ATOM": "cosmos",
}


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fetch_prices_okx(assets: list[str]) -> dict[str, Decimal]:
    """Fetch current USDT prices from OKX via ATK CLI.

    Uses: okx market ticker --instId BTC-USDT --json
    """
    prices: dict[str, Decimal] = {}
    for asset in assets:
        upper = asset.upper()
        if upper in ("USDT", "USDC"):
            prices[upper] = Decimal("1")
            continue
        inst_id = f"{upper}-USDT"
        try:
            data = atk_run("market", "ticker", args=["--instId", inst_id])
        except Exception:
            continue
        if data is None:
            continue
        # ATK returns: {"instId": "BTC-USDT", "last": "62000.5", ...}
        # or list of dicts
        items = data if isinstance(data, list) else [data]
        for item in items:
            last = _to_decimal(item.get("last") or item.get("lastPx"))
            if last > 0:
                prices[upper] = last
                break
    return prices


def fetch_prices_coingecko(assets: list[str]) -> dict[str, Decimal]:
    """Fetch USD prices from CoinGecko free API (fallback)."""
    try:
        import requests
    except ImportError:
        return {}

    ids = []
    id_to_asset: dict[str, str] = {}
    for a in assets:
        cg_id = _COINGECKO_IDS.get(a.upper())
        if cg_id:
            ids.append(cg_id)
            id_to_asset[cg_id] = a.upper()

    if not ids:
        return {}

    try:
        resp = requests.get(
            COINGECKO_PRICE_URL,
            params={"ids": ",".join(ids), "vs_currencies": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    prices: dict[str, Decimal] = {}
    for cg_id, asset in id_to_asset.items():
        usd_price = data.get(cg_id, {}).get("usd")
        if usd_price is not None:
            prices[asset] = _to_decimal(usd_price)
    return prices


def fetch_current_prices(
    assets: list[str],
    overrides: dict[str, float | str] | None = None,
) -> dict[str, Decimal]:
    """Fetch current prices with three-layer fallback.

    Args:
        assets: List of asset symbols (e.g. ["BTC", "ETH"]).
        overrides: Optional CLI-provided price overrides.

    Returns:
        Dict mapping asset symbol to USD price as Decimal.
    """
    result: dict[str, Decimal] = {}

    # Layer 1: OKX ATK CLI
    okx_prices = fetch_prices_okx(assets)
    result.update(okx_prices)

    # Check for missing assets
    missing = [a for a in assets if a.upper() not in result]

    # Layer 3: CoinGecko fallback for missing
    if missing:
        cg_prices = fetch_prices_coingecko(missing)
        for k, v in cg_prices.items():
            if k not in result:
                result[k] = v

    # Layer 2: CLI overrides (highest priority, applied last)
    if overrides:
        for k, v in overrides.items():
            result[k.upper()] = _to_decimal(v)

    return result
