#!/usr/bin/env python3
"""ATK CLI 统一封装 — 调用 OKX Agent Trade Kit CLI (okx) 命令."""
import json
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Demo 模式下跳过所有 ATK 调用
DEMO_MODE = os.environ.get("VERITAX_DEMO", "") == "1"


def run(
    module: str,
    command: str,
    *,
    args: list[str] | None = None,
    demo: bool = False,
    timeout: int = 30,
) -> dict[str, Any] | list[Any] | None:
    """Execute an ATK CLI command and return parsed JSON.

    Args:
        module:  ATK module name (e.g. "account", "spot", "market", "swap").
        command: Sub-command (e.g. "balance", "fills", "place").
        args:    Extra CLI arguments, e.g. ["--instId", "BTC-USDT"].
        demo:    If True, add --demo flag (OKX simulated trading).
        timeout: Subprocess timeout in seconds.

    Returns:
        Parsed JSON output (dict or list), or None if in VeriTax demo mode.

    Raises:
        ATKError: If the CLI command fails.
    """
    if DEMO_MODE:
        logger.debug("VERITAX_DEMO=1 — skipping ATK call: okx %s %s", module, command)
        return None

    cmd = ["okx", module, command, "--json"]
    if demo:
        cmd.append("--demo")
    if args:
        cmd.extend(args)

    logger.info("ATK CLI: %s", " ".join(cmd))

    # Strip OKX credential env vars so the CLI falls back to ~/.okx/config.toml.
    # OpenClaw's exec may inject env vars that override config.toml; config.toml
    # is the single source of truth for CLI auth + proxy settings.
    cli_env = {k: v for k, v in os.environ.items()
               if k not in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE")}

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=cli_env,
        )
    except FileNotFoundError:
        raise ATKError(
            "okx CLI not found. Install: npm install -g @okx_ai/okx-trade-cli"
        )
    except subprocess.TimeoutExpired:
        raise ATKError(f"ATK CLI timed out after {timeout}s: okx {module} {command}")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise ATKError(
            f"ATK CLI failed (exit {result.returncode}): okx {module} {command}\n{stderr}"
        )

    stdout = result.stdout.strip()
    if not stdout:
        return {}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ATKError(f"ATK CLI returned invalid JSON: {e}\nOutput: {stdout[:500]}")


class ATKError(Exception):
    """Raised when an ATK CLI call fails."""
