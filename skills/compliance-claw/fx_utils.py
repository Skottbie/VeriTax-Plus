#!/usr/bin/env python3
"""Currency conversion utilities for ComplianceClaw (OKX Edition).

Fetches exchange rates from the Frankfurter API (free, no API key required,
based on ECB reference rates). Falls back to hardcoded annual average rates
when the API is unreachable or for unsupported currencies (e.g. TWD).

Architecture:
  - ScannerClaw outputs raw USDT-denominated data (no jurisdiction awareness)
  - ComplianceClaw calls convert_dataset() BEFORE aggregate_metrics()
  - All downstream calculations (ACB, FIFO, CGT, progressive tax) operate
    in the user's local reporting currency
"""

import json
import os
from decimal import Decimal
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

FRANKFURTER_API = "https://api.frankfurter.dev/v1"

# Hardcoded fallback rates: USD → local currency (annual average approximations).
FX_FALLBACK_RATES: dict[int, dict[str, str]] = {
    2024: {
        "JPY": "151.0",
        "AUD": "1.53",
        "CAD": "1.37",
        "SGD": "1.34",
        "TWD": "31.5",
    },
    2025: {
        "JPY": "148.0",
        "AUD": "1.55",
        "CAD": "1.38",
        "SGD": "1.33",
        "TWD": "32.0",
    },
    2026: {
        "JPY": "146.0",
        "AUD": "1.56",
        "CAD": "1.39",
        "SGD": "1.32",
        "TWD": "32.5",
    },
}

_rate_cache: dict[tuple[int, str], Decimal] = {}


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def fetch_fx_rate(year: int, currency: str) -> Decimal:
    """Fetch USD → local currency exchange rate for a given tax year."""
    currency = currency.upper().strip()

    # No conversion needed for USD-pegged stablecoins
    if currency in ("USD", "USDT", "USDC", ""):
        return Decimal("1")

    cache_key = (year, currency)
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    rate = _fetch_from_api(year, currency)
    if rate is not None:
        _rate_cache[cache_key] = rate
        return rate

    rate = _get_fallback_rate(year, currency)
    _rate_cache[cache_key] = rate
    return rate


def _fetch_from_api(year: int, currency: str) -> Decimal | None:
    """Fetch year-end exchange rate from Frankfurter API."""
    if requests is None:
        return None

    ecb_currencies = {
        "JPY", "AUD", "CAD", "SGD", "CHF", "GBP", "EUR",
        "HKD", "KRW", "MYR", "NZD", "CNY", "INR", "BRL",
        "MXN", "THB", "PHP", "IDR", "SEK", "NOK", "DKK",
        "PLN", "HUF", "CZK", "RON", "ISK", "TRY", "ZAR", "ILS",
    }
    if currency not in ecb_currencies:
        return None

    for date_str in [f"{year}-12-31", f"{year}-12-30", f"{year}-12-29",
                     f"{year}-12-15", f"{year}-07-01"]:
        try:
            url = f"{FRANKFURTER_API}/{date_str}"
            params = {"base": "USD", "symbols": currency}
            timeout = int(os.getenv("FX_API_TIMEOUT", "10"))
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                rates = data.get("rates", {})
                if currency in rates:
                    return _to_decimal(rates[currency])
        except Exception:
            continue

    return None


def _get_fallback_rate(year: int, currency: str) -> Decimal:
    """Get hardcoded fallback rate for a year/currency pair."""
    year_rates = FX_FALLBACK_RATES.get(year)
    if year_rates and currency in year_rates:
        return _to_decimal(year_rates[currency])

    available_years = sorted(FX_FALLBACK_RATES.keys())
    if available_years:
        nearest = min(available_years, key=lambda y: abs(y - year))
        nearest_rates = FX_FALLBACK_RATES[nearest]
        if currency in nearest_rates:
            return _to_decimal(nearest_rates[currency])

    return Decimal("1")


def convert_dataset(data: dict, fx_rate: Decimal) -> dict:
    """Convert USDT-denominated dataset amounts to local currency.

    OKX Edition field mapping:
      - trades[].fillPx (price per unit → multiplied by fx_rate)
      - trades[].fee ONLY when feeCcy is a stablecoin
      - earn_records[].amt ONLY when ccy is a stablecoin

    Does NOT convert:
      - trades[].fillSz (base asset quantity, e.g. BTC units)
      - trades[].fee when feeCcy is base asset (e.g. BTC)
    """
    if fx_rate == Decimal("1"):
        return data

    stablecoin_assets = {"USDT", "USDC", "TUSD", "DAI", "USD"}

    converted = dict(data)

    # Convert trades (unified: SPOT + SWAP + MARGIN)
    trades = []
    for trade in data.get("trades", []):
        t = dict(trade)
        # Convert price to local currency (quote amount = fillSz * fillPx)
        t["fillPx"] = str(_to_decimal(trade.get("fillPx")) * fx_rate)
        # Only convert fee if denominated in stablecoin
        fee_ccy = str(trade.get("feeCcy", "")).upper().strip()
        if fee_ccy in stablecoin_assets:
            t["fee"] = str(_to_decimal(trade.get("fee")) * fx_rate)
        # Convert PnL (always in quote currency = USDT for SWAP/FUTURES)
        if _to_decimal(trade.get("pnl")) != Decimal("0"):
            t["pnl"] = str(_to_decimal(trade.get("pnl")) * fx_rate)
        trades.append(t)
    converted["trades"] = trades

    # Convert earn records
    earns = []
    for e in data.get("earn_records", []):
        ee = dict(e)
        ccy = str(e.get("ccy", "")).upper().strip()
        if ccy in stablecoin_assets:
            ee["amt"] = str(_to_decimal(e.get("amt")) * fx_rate)
        earns.append(ee)
    converted["earn_records"] = earns

    return converted
