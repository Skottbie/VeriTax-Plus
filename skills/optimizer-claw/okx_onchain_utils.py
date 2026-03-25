#!/usr/bin/env python3
"""OKX OnchainOS Skills integration for OptimizerClaw.

Replaces binance_web3_utils.py — wraps VeriTask OnchainOS CLI for:
  - token safety scan (okx-security + okx-dex-token)
  - token info (okx-dex-token)
  - smart money signals (okx-dex-signal)
  - market rankings (okx-dex-token trending)

All functions include graceful fallback when CLI is unavailable.
"""

import json
import logging
import os
import subprocess
from decimal import Decimal
from typing import Any

import requests
from eth_account import Account
from eth_utils import to_checksum_address

logger = logging.getLogger(__name__)

# Demo mode: skip all real CLI calls
_DEMO = os.getenv("VERITAX_DEMO", "") == "1"

# Default chain for OKX OnchainOS queries (X Layer = 196)
_DEFAULT_CHAIN_INDEX = os.getenv("CHAIN_INDEX", "196")
_DEFAULT_CHAIN_NAME = os.getenv("CHAIN_NAME", "xlayer")
_NATIVE_TOKEN_ADDRESS = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
_CHAIN_RPC_URLS = {
    "196": os.getenv("VERITAX_ONCHAIN_RPC_URL", "https://rpc.xlayer.tech"),
    "1": "https://eth.llamarpc.com",
    "8453": "https://mainnet.base.org",
}


def _run_onchainos(skill: str, args: list[str], timeout: int = 20) -> dict | None:
    """Execute an onchainos CLI command and return parsed JSON."""
    if _DEMO:
        logger.debug("DEMO — skipping onchainos: %s %s", skill, args)
        return None

    cmd = ["onchainos", "run", skill, "--json", *args]
    logger.info("OnchainOS CLI: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        logger.warning("onchainos %s failed (exit %d)", skill, result.returncode)
        return None

    stdout = result.stdout.strip()
    if not stdout:
        return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def _run_onchainos_cli(args: list[str], timeout: int = 30) -> Any:
    """Execute direct onchainos CLI command and parse JSON output."""
    if _DEMO:
        logger.debug("DEMO - skipping onchainos cli: %s", args)
        return None

    cmd = ["onchainos", *args]
    logger.info("OnchainOS CLI: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        logger.warning("onchainos cli failed (exit %d): %s", result.returncode, " ".join(cmd))
        return None

    stdout = result.stdout.strip()
    if not stdout:
        return None

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def _normalize_rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            return [row for row in data["data"] if isinstance(row, dict)]
        return [data]
    return []


def _pick_first_row(data: Any) -> dict | None:
    rows = _normalize_rows(data)
    return rows[0] if rows else None


def _to_minimal_units(amount: str | float | Decimal, decimals: str | int | None) -> str:
    scale = int(decimals or 18)
    value = Decimal(str(amount))
    return str(int(value * (Decimal(10) ** scale)))


def _get_evm_nonce(rpc_url: str, wallet_address: str) -> int:
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionCount",
        "params": [wallet_address, "latest"],
        "id": 1,
    }
    response = requests.post(rpc_url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return int(data["result"], 16)


def search_token(query: str, chains: str | None = None) -> list[dict]:
    """Search tokens by symbol/name/address using direct OnChainOS CLI."""
    args = ["token", "search", "--query", query]
    if chains:
        args.extend(["--chains", chains])
    data = _run_onchainos_cli(args)
    return _normalize_rows(data)


def resolve_token(query: str, chain: str | None = None, chain_index: str | None = None) -> dict:
    """Resolve a symbol/name to a concrete token on the target chain."""
    requested_chain = chain_index or chain or _DEFAULT_CHAIN_INDEX
    rows = search_token(query, chains=requested_chain)
    target = str(chain_index or "")
    target_name = str(chain or _DEFAULT_CHAIN_NAME).lower()

    exact_symbol = []
    partial_symbol = []
    for row in rows:
        row_chain = str(row.get("chainIndex", ""))
        symbol = str(row.get("tokenSymbol", ""))
        if target and row_chain != target:
            continue
        if symbol.upper() == query.upper():
            exact_symbol.append(row)
        elif query.upper() in symbol.upper():
            partial_symbol.append(row)

    candidates = exact_symbol or partial_symbol or rows
    for row in candidates:
        row_chain_name = str(row.get("chainName", "")).lower()
        if row_chain_name == target_name:
            return row
    return candidates[0] if candidates else {}


def quote_swap(from_token: str, to_token: str, amount: str, chain: str | None = None, swap_mode: str = "exactIn") -> dict:
    args = [
        "swap", "quote",
        "--from", from_token,
        "--to", to_token,
        "--amount", amount,
        "--chain", chain or _DEFAULT_CHAIN_NAME,
        "--swap-mode", swap_mode,
    ]
    return _pick_first_row(_run_onchainos_cli(args)) or {}


def build_approve_tx(token_address: str, amount: str, chain: str | None = None) -> dict:
    args = [
        "swap", "approve",
        "--token", token_address,
        "--amount", amount,
        "--chain", chain or _DEFAULT_CHAIN_NAME,
    ]
    return _pick_first_row(_run_onchainos_cli(args)) or {}


def build_swap_tx(
    from_token: str,
    to_token: str,
    amount: str,
    wallet_address: str,
    chain: str | None = None,
    slippage: str | None = None,
    gas_level: str = "average",
    swap_mode: str = "exactIn",
) -> dict:
    args = [
        "swap", "swap",
        "--from", from_token,
        "--to", to_token,
        "--amount", amount,
        "--chain", chain or _DEFAULT_CHAIN_NAME,
        "--wallet", wallet_address,
        "--gas-level", gas_level,
        "--swap-mode", swap_mode,
    ]
    if slippage:
        args.extend(["--slippage", slippage])
    return _pick_first_row(_run_onchainos_cli(args)) or {}


def simulate_transaction(wallet_address: str, to_address: str, data: str, chain: str | None = None, amount: str = "0") -> dict:
    args = [
        "gateway", "simulate",
        "--from", wallet_address,
        "--to", to_address,
        "--data", data,
        "--chain", chain or _DEFAULT_CHAIN_NAME,
        "--amount", amount,
    ]
    return _pick_first_row(_run_onchainos_cli(args)) or {}


def scan_transaction(wallet_address: str, to_address: str, data: str, chain: str | None = None, amount: str = "0", gas: str | None = None, gas_price: str | None = None) -> dict:
    args = [
        "security", "tx-scan",
        "--chain", chain or _DEFAULT_CHAIN_NAME,
        "--from", wallet_address,
        "--to", to_address,
        "--data", data,
        "--value", amount,
    ]
    if gas:
        args.extend(["--gas", gas])
    if gas_price:
        args.extend(["--gas-price", gas_price])
    return _pick_first_row(_run_onchainos_cli(args)) or {}


def broadcast_transaction(signed_tx: str, wallet_address: str, chain: str | None = None) -> dict:
    args = [
        "gateway", "broadcast",
        "--signed-tx", signed_tx,
        "--address", wallet_address,
        "--chain", chain or _DEFAULT_CHAIN_NAME,
    ]
    return _pick_first_row(_run_onchainos_cli(args)) or {}


def track_order(wallet_address: str, chain: str | None = None, order_id: str | None = None) -> dict:
    args = [
        "gateway", "orders",
        "--address", wallet_address,
        "--chain", chain or _DEFAULT_CHAIN_NAME,
    ]
    if order_id:
        args.extend(["--order-id", order_id])
    return _pick_first_row(_run_onchainos_cli(args)) or {}


def sign_evm_transaction(
    tx: dict,
    private_key: str,
    wallet_address: str,
    chain_id: int | None = None,
    rpc_url: str | None = None,
) -> dict:
    """Sign an EVM transaction locally for subsequent gateway broadcast."""
    nonce = tx.get("nonce")
    if nonce is None:
        if not rpc_url:
            raise ValueError("RPC URL is required to fetch nonce for on-chain signing")
        nonce = _get_evm_nonce(rpc_url, wallet_address)
    tx_payload = {
        "to": to_checksum_address(tx.get("to")),
        "data": tx.get("data", "0x"),
        "value": int(str(tx.get("value") or "0"), 0),
        "gas": int(str(tx.get("gas") or tx.get("gasLimit") or "0"), 0),
        "nonce": int(str(nonce), 0),
    }
    if tx.get("gasPrice"):
        tx_payload["gasPrice"] = int(str(tx["gasPrice"]), 0)
    if tx.get("maxFeePerGas"):
        tx_payload["maxFeePerGas"] = int(str(tx["maxFeePerGas"]), 0)
    if tx.get("maxPriorityFeePerGas"):
        tx_payload["maxPriorityFeePerGas"] = int(str(tx["maxPriorityFeePerGas"]), 0)
    if chain_id is not None:
        tx_payload["chainId"] = chain_id

    signed = Account.sign_transaction(tx_payload, private_key)
    return {
        "raw_transaction": signed.raw_transaction.hex(),
        "hash": signed.hash.hex(),
    }


def plan_onchain_swap(
    funding_token_symbol: str,
    target_symbol: str,
    amount: str | float | Decimal,
    wallet_address: str,
    chain: str | None = None,
    chain_index: str | None = None,
    slippage: str | None = None,
) -> dict:
    """Build a full on-chain swap plan for TLH substitute execution."""
    active_chain = chain or _DEFAULT_CHAIN_NAME
    active_chain_index = chain_index or _DEFAULT_CHAIN_INDEX
    source = resolve_token(funding_token_symbol, chain=active_chain, chain_index=active_chain_index)
    target = resolve_token(target_symbol, chain=active_chain, chain_index=active_chain_index)
    if not source or not target:
        return {
            "ok": False,
            "reason": "token_resolution_failed",
            "note": "OnChainOS could not resolve source or target token on the requested chain.",
        }

    source_decimals = source.get("decimal") or "18"
    amount_minimal = _to_minimal_units(amount, source_decimals)
    source_address = source.get("tokenContractAddress") or _NATIVE_TOKEN_ADDRESS
    target_address = target.get("tokenContractAddress") or _NATIVE_TOKEN_ADDRESS
    quote = quote_swap(source_address, target_address, amount_minimal, chain=active_chain)
    if not quote:
        return {
            "ok": False,
            "reason": "quote_unavailable",
            "note": "OnChainOS quote API unavailable.",
        }

    approval = {}
    if source_address.lower() != _NATIVE_TOKEN_ADDRESS:
        approval = build_approve_tx(source_address, amount_minimal, chain=active_chain)

    swap_tx = build_swap_tx(
        source_address,
        target_address,
        amount_minimal,
        wallet_address,
        chain=active_chain,
        slippage=slippage,
    )
    tx_payload = swap_tx.get("tx", {}) if isinstance(swap_tx, dict) else {}
    simulation = {}
    tx_scan = {}
    if tx_payload.get("to") and tx_payload.get("data"):
        simulation = simulate_transaction(
            wallet_address,
            tx_payload["to"],
            tx_payload["data"],
            chain=active_chain,
            amount=str(tx_payload.get("value") or "0"),
        )
        tx_scan = scan_transaction(
            wallet_address,
            tx_payload["to"],
            tx_payload["data"],
            chain=active_chain,
            amount=str(tx_payload.get("value") or "0"),
            gas=str(tx_payload.get("gas") or ""),
            gas_price=str(tx_payload.get("gasPrice") or ""),
        )

    return {
        "ok": True,
        "chain": active_chain,
        "chain_index": active_chain_index,
        "wallet_address": wallet_address,
        "source_token": source,
        "target_token": target,
        "sell_amount": str(amount),
        "sell_amount_minimal": amount_minimal,
        "quote": quote,
        "approval": approval,
        "swap": swap_tx,
        "simulation": simulation,
        "tx_scan": tx_scan,
    }


# ---------------------------------------------------------------------------
# Public API — drop-in replacement for binance_web3_utils functions
# ---------------------------------------------------------------------------

def query_token_audit(chain_index: str, token_address: str) -> dict:
    """Check token contract security (honeypot, rug pull, ownership).

    Uses okx-security token-scan + okx-dex-token holder analysis.
    Falls back gracefully when CLI unavailable.
    """
    data = _run_onchainos("okx-security", [
        "--action", "token-scan",
        "--chainIndex", chain_index or _DEFAULT_CHAIN_INDEX,
        "--tokenAddress", token_address,
    ])
    if data and isinstance(data, dict):
        return {
            "source": "okx-onchainos",
            "is_safe": data.get("is_safe", data.get("riskLevel", "unknown") == "safe"),
            "has_proxy": data.get("has_proxy", False),
            "can_mint": data.get("can_mint", False),
            "risk_level": data.get("riskLevel", "unknown"),
            "raw": data,
        }
    return {
        "source": "fallback",
        "is_safe": None,
        "note": "Token audit API unavailable. Manual verification recommended.",
    }


def query_token_info(chain_index: str, token_address: str) -> dict:
    """Get token metadata: market cap, liquidity, holder distribution.

    Uses okx-dex-token detail query.
    """
    data = _run_onchainos("okx-dex-token", [
        "--action", "detail",
        "--chainIndex", chain_index or _DEFAULT_CHAIN_INDEX,
        "--tokenAddress", token_address,
    ])
    if data and isinstance(data, dict):
        return {
            "source": "okx-onchainos",
            "name": data.get("name", ""),
            "symbol": data.get("symbol", ""),
            "market_cap": data.get("marketCap"),
            "liquidity": data.get("liquidity"),
            "holder_count": data.get("holderCount"),
            "raw": data,
        }
    return {
        "source": "fallback",
        "note": "Token info API unavailable.",
    }


def fetch_trading_signal(token_symbol: str) -> dict:
    """Get smart money / whale buy signals for execution timing.

    Uses okx-dex-signal aggregated alerts.
    """
    data = _run_onchainos("okx-dex-signal", [
        "--action", "alerts",
        "--symbol", token_symbol,
    ])
    if data and isinstance(data, (dict, list)):
        signals = data if isinstance(data, list) else data.get("signals", [])
        return {
            "source": "okx-onchainos",
            "signals": signals,
        }
    return {
        "source": "fallback",
        "signals": [],
        "note": "Trading signal API unavailable. Proceed with caution.",
    }


def fetch_market_rank(limit: int = 50) -> dict:
    """Get top tokens by market cap for substitute filtering.

    Uses okx-dex-token trending/ranking.
    """
    data = _run_onchainos("okx-dex-token", [
        "--action", "trending",
        "--limit", str(limit),
    ])
    if data and isinstance(data, (dict, list)):
        rankings = data if isinstance(data, list) else data.get("rankings", [])
        return {
            "source": "okx-onchainos",
            "rankings": rankings,
        }
    return {
        "source": "fallback",
        "rankings": [],
        "note": "Market rank API unavailable.",
    }
